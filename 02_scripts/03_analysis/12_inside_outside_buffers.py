#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
12_inside_outside_buffers.py
Counterfactual analysis: Compare EII inside vs outside Protected Areas.

This script:
1. Buffers each PA polygon (default 10km; optional 5km and 20km)
2. Creates outside ring = buffer minus PA
3. Computes zonal statistics for EII and components inside and outside
4. Calculates delta (difference) columns

Outputs:
- 01_data/03_tables/pa_inside_outside_stats.csv
- 03_results/tables/table4_inside_vs_outside.csv

Version History:
    1.0.0 - Initial implementation
"""

__version__ = "1.0.0"

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ee
import geopandas as gpd
import pandas as pd
import numpy as np

from _shared.config import CONFIG, get_path, validate_paths
from _shared.gee_utils import authenticate_gee, geometry_to_ee
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import (
    load_pa_geodataframe, load_bhutan_boundary, ensure_dir,
    save_dataframe, write_success_marker
)
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report,
    retry_with_backoff
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "12_inside_outside_buffers"

# EII asset and bands
EII_ASSET = CONFIG["gee_eii_asset"]
EII_BANDS = CONFIG["eii_bands"]
SCALE = CONFIG["analysis_scale"]
PERCENTILES = CONFIG["percentiles"]

# Buffer configuration
DEFAULT_BUFFER_M = CONFIG["default_buffer_m"]
BUFFER_DISTANCES = CONFIG["buffer_distances_m"]
EE_GEOMETRY_ERROR_MARGIN_M = 10


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Counterfactual analysis: Inside vs outside PA comparison"
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Override base project directory"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files"
    )
    parser.add_argument(
        "--allow-pa-count-mismatch",
        action="store_true",
        help="Allow PA count different from expected 19"
    )
    parser.add_argument(
        "--buffer-km",
        type=float,
        default=DEFAULT_BUFFER_M / 1000,
        help=f"Buffer distance in km (default: {DEFAULT_BUFFER_M/1000})"
    )
    parser.add_argument(
        "--multi-buffer",
        action="store_true",
        help="Run analysis for 5km, 10km, and 20km buffers"
    )
    parser.add_argument(
        "--enable-exports",
        action="store_true",
        help="Not used in this script"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Not used in this script"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Allow geometry simplification for large polygons"
    )
    return parser.parse_args()


def create_buffer_ring(pa_geom, buffer_distance_m, bhutan_geom, logger):
    """
    Create outside buffer ring for a PA.

    Args:
        pa_geom: ee.Geometry of the PA
        buffer_distance_m: Buffer distance in meters
        bhutan_geom: ee.Geometry of Bhutan boundary
        logger: Logger instance

    Returns:
        ee.Geometry of the outside ring (buffer minus PA)
    """
    # Buffer the PA
    buffered = pa_geom.buffer(buffer_distance_m, EE_GEOMETRY_ERROR_MARGIN_M)

    # Create ring by removing the PA from buffer
    ring = buffered.difference(pa_geom, EE_GEOMETRY_ERROR_MARGIN_M)

    # Clip to Bhutan boundary to avoid areas outside country
    ring_clipped = ring.intersection(bhutan_geom, EE_GEOMETRY_ERROR_MARGIN_M)

    return ring_clipped


def gdf_to_ee_geometry(gdf):
    """Convert GeoDataFrame to single ee.Geometry."""
    union_geom = gdf.unary_union
    return geometry_to_ee(union_geom)


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def compute_zonal_stats(image, region, region_name, location, logger):
    """
    Compute zonal statistics for a region.

    Args:
        image: ee.Image with bands to analyze
        region: ee.Geometry
        region_name: Name of the region (PA name)
        location: 'inside' or 'outside'
        logger: Logger instance

    Returns:
        Dictionary with statistics
    """
    # Define reducers
    reducers = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
        .combine(ee.Reducer.percentile(PERCENTILES), sharedInputs=True)
    )

    # Compute stats
    stats = image.reduceRegion(
        reducer=reducers,
        geometry=region,
        scale=SCALE,
        maxPixels=1e9,
        bestEffort=True
    )

    stats_dict = stats.getInfo()

    # Parse results for each band
    results = {
        "PA_name": region_name,
        "location": location,
    }

    for band in EII_BANDS:
        results[f"{band}_mean"] = stats_dict.get(f"{band}_mean")
        results[f"{band}_stdDev"] = stats_dict.get(f"{band}_stdDev")
        results[f"{band}_count"] = stats_dict.get(f"{band}_count")
        for p in PERCENTILES:
            results[f"{band}_p{p}"] = stats_dict.get(f"{band}_p{p}")

    return results


def compute_deltas(inside_df, outside_df, logger):
    """
    Compute delta (inside - outside) for each metric.

    Args:
        inside_df: DataFrame with inside stats
        outside_df: DataFrame with outside stats
        logger: Logger instance

    Returns:
        DataFrame with delta columns
    """
    logger.info("Computing delta (inside - outside) values...")

    # Merge inside and outside
    # Include 'park' in merge keys to preserve it (same for inside/outside)
    merge_keys = ["PA_name"]
    if "park" in inside_df.columns and "park" in outside_df.columns:
        merge_keys.append("park")

    merged = inside_df.merge(
        outside_df,
        on=merge_keys,
        suffixes=("_inside", "_outside")
    )

    # Compute deltas for mean values
    delta_cols = {}
    for band in EII_BANDS:
        col_inside = f"{band}_mean_inside"
        col_outside = f"{band}_mean_outside"

        if col_inside in merged.columns and col_outside in merged.columns:
            delta_cols[f"delta_{band}"] = merged[col_inside] - merged[col_outside]

    # Add delta columns
    for col_name, values in delta_cols.items():
        merged[col_name] = values

    return merged


def create_publication_table(stats_df, buffer_km, logger):
    """
    Create publication-ready Table 4.

    Args:
        stats_df: DataFrame with all stats and deltas
        buffer_km: Buffer distance in km
        logger: Logger instance

    Returns:
        Formatted DataFrame
    """
    logger.info("Creating publication Table 4...")

    # Select key columns
    cols_to_keep = [
        "PA_name",
        "eii_mean_inside", "eii_stdDev_inside",
        "eii_mean_outside", "eii_stdDev_outside",
        "delta_eii",
        "functional_integrity_mean_inside", "functional_integrity_mean_outside",
        "delta_functional_integrity",
        "structural_integrity_mean_inside", "structural_integrity_mean_outside",
        "delta_structural_integrity",
        "compositional_integrity_mean_inside", "compositional_integrity_mean_outside",
        "delta_compositional_integrity",
    ]

    # Filter to existing columns
    existing_cols = [c for c in cols_to_keep if c in stats_df.columns]
    table4 = stats_df[existing_cols].copy()

    # Rename for publication
    rename_map = {
        "PA_name": "PA Code",
        "eii_mean_inside": "EII Inside",
        "eii_stdDev_inside": "EII Inside SD",
        "eii_mean_outside": "EII Outside",
        "eii_stdDev_outside": "EII Outside SD",
        "delta_eii": "Delta EII",
        "functional_integrity_mean_inside": "Func. Inside",
        "functional_integrity_mean_outside": "Func. Outside",
        "delta_functional_integrity": "Delta Func.",
        "structural_integrity_mean_inside": "Struct. Inside",
        "structural_integrity_mean_outside": "Struct. Outside",
        "delta_structural_integrity": "Delta Struct.",
        "compositional_integrity_mean_inside": "Comp. Inside",
        "compositional_integrity_mean_outside": "Comp. Outside",
        "delta_compositional_integrity": "Delta Comp.",
    }

    table4 = table4.rename(columns=rename_map)

    # Round numeric columns
    numeric_cols = [c for c in table4.columns if c != "PA Code"]
    for col in numeric_cols:
        if col in table4.columns:
            table4[col] = table4[col].round(4)

    # Sort by Delta EII descending
    if "Delta EII" in table4.columns:
        table4 = table4.sort_values("Delta EII", ascending=False)

    # Add buffer distance as metadata
    table4["Buffer (km)"] = buffer_km

    # Reorder columns
    cols_order = ["PA Code", "Buffer (km)"] + [c for c in table4.columns if c not in ["PA Code", "Buffer (km)"]]
    table4 = table4[cols_order].reset_index(drop=True)

    return table4


def main():
    args = parse_args()
    base_dir = args.base_dir

    # Set up logging
    log_dir = get_path("logs", base_dir)
    ensure_dir(log_dir)
    log_file = log_dir / f"{SCRIPT_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = setup_logger(SCRIPT_NAME, log_file)

    log_session_info(logger, SCRIPT_NAME, __version__, args)

    error_bundle = ErrorBundle(SCRIPT_NAME, __version__)
    error_bundle.add_context("base_dir", str(base_dir or get_path("base")))

    try:
        # Validate required inputs
        logger.info("Validating required input files...")
        validation = validate_paths(base_dir, ["protected_areas", "bhutan_boundary", "gee_key"])
        if not validation["valid"]:
            raise FileNotFoundError(
                f"Missing required files:\n" + "\n".join(validation["missing"])
            )

        # Authenticate to GEE
        authenticate_gee(base_dir, logger)

        # Load EII image
        logger.info(f"Loading EII asset: {EII_ASSET}")
        eii_image = ee.Image(EII_ASSET).select(EII_BANDS)

        # Load Protected Areas
        logger.info("Loading Protected Areas...")
        pa_gdf = load_pa_geodataframe(
            base_dir=base_dir,
            validate_count=True,
            allow_mismatch=args.allow_pa_count_mismatch
        )
        if pa_gdf.crs.to_epsg() != 4326:
            pa_gdf = pa_gdf.to_crs("EPSG:4326")
        logger.info(f"Loaded {len(pa_gdf)} Protected Areas")

        # Validate PA count
        if len(pa_gdf) != CONFIG["expected_pa_count"] and not args.allow_pa_count_mismatch:
            raise ValueError(
                f"PA count mismatch: expected {CONFIG['expected_pa_count']}, "
                f"found {len(pa_gdf)}"
            )

        # Load Bhutan boundary
        logger.info("Loading Bhutan boundary...")
        bhutan_gdf = load_bhutan_boundary(base_dir)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")
        bhutan_geom = gdf_to_ee_geometry(bhutan_gdf)

        # Determine buffer distances
        if args.multi_buffer:
            buffer_distances_km = [5, 10, 20]
        else:
            buffer_distances_km = [args.buffer_km]

        logger.info(f"Buffer distances: {buffer_distances_km} km")

        # Process each buffer distance
        all_results = []

        for buffer_km in buffer_distances_km:
            buffer_m = buffer_km * 1000

            logger.info("\n" + "=" * 60)
            logger.info(f"PROCESSING {buffer_km}km BUFFER")
            logger.info("=" * 60)

            inside_stats = []
            outside_stats = []

            # Process each PA
            for idx, row in pa_gdf.iterrows():
                pa_name = row[CONFIG["pa_name_field"]]
                pa_category = row[CONFIG["pa_category_field"]]

                logger.info(f"\nProcessing: {pa_name} ({pa_category})")

                # Create PA geometry
                pa_geom = geometry_to_ee(row.geometry)

                # Compute inside stats
                logger.info(f"  Computing inside stats...")
                inside_result = compute_zonal_stats(
                    eii_image, pa_geom, pa_name, "inside", logger
                )
                inside_result["park"] = pa_category
                inside_result["Area_km2"] = row.get(CONFIG["pa_area_field"], np.nan)
                inside_result["buffer_km"] = buffer_km
                inside_stats.append(inside_result)

                # Create outside ring
                logger.info(f"  Creating {buffer_km}km buffer ring...")
                ring_geom = create_buffer_ring(pa_geom, buffer_m, bhutan_geom, logger)

                # Compute outside stats
                logger.info(f"  Computing outside stats...")
                outside_result = compute_zonal_stats(
                    eii_image, ring_geom, pa_name, "outside", logger
                )
                outside_result["park"] = pa_category
                outside_result["buffer_km"] = buffer_km
                outside_stats.append(outside_result)

            # Create DataFrames
            inside_df = pd.DataFrame(inside_stats)
            outside_df = pd.DataFrame(outside_stats)

            # Compute deltas
            combined_df = compute_deltas(inside_df, outside_df, logger)
            combined_df["buffer_km"] = buffer_km

            all_results.append(combined_df)

            # Log summary for this buffer
            if "delta_eii" in combined_df.columns:
                mean_delta = combined_df["delta_eii"].mean()
                positive_delta = (combined_df["delta_eii"] > 0).sum()
                logger.info(f"\n{buffer_km}km Buffer Summary:")
                logger.info(f"  Mean Delta EII: {mean_delta:.4f}")
                logger.info(f"  PAs with positive delta: {positive_delta}/{len(combined_df)}")

        # Combine all results
        final_df = pd.concat(all_results, ignore_index=True)

        # Output paths
        tables_dir = get_path("tables", base_dir)
        ensure_dir(tables_dir)

        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        # Save raw stats
        raw_path = tables_dir / "pa_inside_outside_stats.csv"
        save_dataframe(final_df, raw_path, overwrite=args.overwrite)
        logger.info(f"Saved raw stats: {raw_path}")

        # Create and save publication table (using default buffer)
        default_df = final_df[final_df["buffer_km"] == args.buffer_km].copy()
        table4 = create_publication_table(default_df, args.buffer_km, logger)

        table4_path = results_tables / "table4_inside_vs_outside.csv"
        save_dataframe(table4, table4_path, overwrite=args.overwrite)
        logger.info(f"Saved Table 4: {table4_path}")

        # Ensure 'park' column exists for inside/outside stats (fallback if missing)
        if "park" not in final_df.columns:
            if "park_inside" in final_df.columns:
                final_df["park"] = final_df["park_inside"]
                logger.warning("'park' column missing; recovered from 'park_inside'")
            elif "PA_name" in final_df.columns:
                final_df["park"] = final_df["PA_name"]
                logger.warning("'park' column missing; using 'PA_name' as fallback")
            else:
                final_df["park"] = final_df.index.astype(str)
                logger.warning("'park' column missing; using index as fallback")

        # Save separate inside/outside stats for modeling
        inside_only = final_df[["PA_name", "park", "buffer_km"] +
                               [c for c in final_df.columns if "_inside" in c or c == "Area_km2"]]
        inside_path = tables_dir / "pa_inside_stats.csv"
        save_dataframe(inside_only, inside_path, overwrite=args.overwrite)

        outside_only = final_df[["PA_name", "park", "buffer_km"] +
                                [c for c in final_df.columns if "_outside" in c]]
        outside_path = tables_dir / "pa_outside_stats.csv"
        save_dataframe(outside_only, outside_path, overwrite=args.overwrite)

        # Append to GEE assets log
        repro_dir = get_path("reproducibility", base_dir)
        ensure_dir(repro_dir)

        assets_log_path = repro_dir / "gee_assets_used.txt"
        with open(assets_log_path, 'a') as f:
            f.write(f"\n# Inside/Outside Analysis (added {datetime.now().isoformat()})\n")
            f.write(f"EII Asset: {EII_ASSET}\n")
            f.write(f"Buffer distances (km): {buffer_distances_km}\n")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "GEE authentication successful": True,
            "EII image loaded": True,
            f"PA count validated ({len(pa_gdf)})": len(pa_gdf) == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
            "Inside stats computed": len(inside_stats) == len(pa_gdf),
            "Outside stats computed": len(outside_stats) == len(pa_gdf),
            "Deltas computed": "delta_eii" in final_df.columns,
            "Raw stats file created": raw_path.exists(),
            "Table 4 created": table4_path.exists(),
            "Output non-empty": len(final_df) > 0,
        }

        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("INSIDE/OUTSIDE ANALYSIS COMPLETE")
        logger.info("=" * 60)
        logger.info(f"PAs processed: {len(pa_gdf)}")
        logger.info(f"Buffer distances: {buffer_distances_km} km")
        logger.info(f"Total rows: {len(final_df)}")

        if "delta_eii" in final_df.columns:
            overall_mean = final_df["delta_eii"].mean()
            logger.info(f"Overall mean Delta EII: {overall_mean:.4f}")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
