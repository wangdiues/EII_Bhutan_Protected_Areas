#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
03_download_eii.py
Download EII zonal statistics for Bhutan Protected Areas from Google Earth Engine.

IMPORTANT SCIENTIFIC RULE:
- The EII value is taken DIRECTLY from the precomputed 'eii' band.
- We DO NOT re-implement or recalculate EII using min(), product(), or any other reducer.
- The 'eii' band from the GEE asset is the AUTHORITATIVE source.

Version History:
    1.0.0 - Initial implementation
"""

__version__ = "1.0.0"

import argparse
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ee
import geopandas as gpd
import pandas as pd

from _shared.config import CONFIG, get_path, validate_paths
from _shared.gee_utils import (
    authenticate_gee,
    geometry_to_ee,
    iter_gdf_batches,
    prepare_gdf_for_ee,
)
from _shared.logging_utils import setup_logger, log_session_info, write_session_info
from _shared.io_utils import (
    load_pa_geodataframe, ensure_dir, save_dataframe,
    write_success_marker, write_gee_assets_log
)
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report,
    retry_with_backoff
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "03_download_eii"

# GEE Asset (AUTHORITATIVE - DO NOT MODIFY)
EII_ASSET = CONFIG["gee_eii_asset"]
EII_BANDS = CONFIG["eii_bands"]
EII_MAIN_BAND = CONFIG["eii_main_band"]

# Analysis parameters
SCALE = CONFIG["analysis_scale"]
PERCENTILES = CONFIG["percentiles"]
EE_TRANSFER_SIMPLIFY_TOLERANCE_M = 90
EE_BATCH_SIZE = 4


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download EII zonal statistics from Google Earth Engine"
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
        "--enable-exports",
        action="store_true",
        help="Enable batch exports to Google Drive as fallback"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Enable sensitivity analysis with alternative aggregation methods"
    )
    return parser.parse_args()


def _count_geometry_vertices(geometry):
    """Count coordinate vertices in a shapely Polygon or MultiPolygon."""
    geom = geometry.__geo_interface__

    def walk(coords):
        if not coords:
            return 0
        first = coords[0]
        if isinstance(first, (float, int)):
            return 1
        return sum(walk(part) for part in coords)

    return walk(geom.get("coordinates", []))


def prepare_pa_geometries_for_ee(gdf, logger):
    """
    Simplify PA geometries for Earth Engine transfer only.

    The canonical processed GeoPackage remains unchanged. This reduces inline
    request payload size while staying well below the 300 m analysis scale.
    """
    before_vertices = int(gdf.geometry.apply(_count_geometry_vertices).sum())
    gdf_ee = prepare_gdf_for_ee(gdf, tolerance_m=EE_TRANSFER_SIMPLIFY_TOLERANCE_M)
    after_vertices = int(gdf_ee.geometry.apply(_count_geometry_vertices).sum())

    logger.info(
        "Prepared PA geometries for Earth Engine transfer "
        f"(tolerance={EE_TRANSFER_SIMPLIFY_TOLERANCE_M} m, "
        f"vertices {before_vertices} -> {after_vertices})"
    )

    if not gdf_ee.is_valid.all():
        raise ValueError("Simplified PA geometries are invalid")

    return gdf_ee


def gdf_to_ee_featurecollection(gdf, id_field):
    """
    Convert GeoDataFrame to Earth Engine FeatureCollection.

    Args:
        gdf: GeoDataFrame in WGS84
        id_field: Field to use as feature ID

    Returns:
        ee.FeatureCollection
    """
    features = []
    for idx, row in gdf.iterrows():
        props = {
            id_field: row[id_field],
            CONFIG["pa_category_field"]: row[CONFIG["pa_category_field"]],
            CONFIG["pa_area_field"]: row[CONFIG["pa_area_field"]]
        }
        try:
            ee_geom = geometry_to_ee(row.geometry)
        except Exception as exc:
            raise ValueError(
                f"Failed to convert geometry for {id_field}={row[id_field]} "
                f"({row.geometry.geom_type})"
            ) from exc
        feature = ee.Feature(ee_geom, props)
        features.append(feature)

    return ee.FeatureCollection(features)


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def compute_zonal_stats_for_band(image, band_name, pa_gdf_ee, scale, logger):
    """
    Compute zonal statistics for a single band.

    Args:
        image: ee.Image
        band_name: Name of the band to analyze
        pa_gdf_ee: Simplified WGS84 PA GeoDataFrame
        scale: Analysis scale in meters
        logger: Logger instance

    Returns:
        List of dictionaries with statistics per region
    """
    logger.info(f"Computing zonal statistics for band: {band_name}")

    # Select the specific band
    band_image = image.select(band_name)

    # Define reducers
    reducers = (
        ee.Reducer.mean()
        .combine(ee.Reducer.percentile(PERCENTILES), sharedInputs=True)
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )

    stats_list = []
    batches = list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE))
    for batch_idx, batch_gdf in enumerate(batches, start=1):
        logger.info(f"Fetching batch {batch_idx}/{len(batches)} ({len(batch_gdf)} PAs)...")
        regions = gdf_to_ee_featurecollection(batch_gdf, CONFIG["pa_name_field"])
        results = band_image.reduceRegions(
            collection=regions,
            reducer=reducers,
            scale=scale,
            crs='EPSG:4326'
        )
        result_info = results.getInfo()

        for feature in result_info['features']:
            props = feature['properties']
            stats = {
                'PA_name': props.get(CONFIG["pa_name_field"]),
                'park': props.get(CONFIG["pa_category_field"]),
                'Area_km2': props.get(CONFIG["pa_area_field"]),
                'band': band_name,
                'mean': props.get('mean'),
                'stdDev': props.get('stdDev'),
                'count': props.get('count'),
                'p5': props.get('p5'),
                'p25': props.get('p25'),
                'p50': props.get('p50'),
                'p75': props.get('p75'),
                'p95': props.get('p95'),
            }
            stats_list.append(stats)

    logger.info(f"Retrieved stats for {len(stats_list)} regions")
    return stats_list


def compute_sensitivity_indices(image, pa_gdf_ee, scale, logger):
    """
    Compute sensitivity analysis indices using alternative aggregation methods.
    These are NOT EII - they are for methodological comparison only.

    Args:
        image: ee.Image with component bands
        pa_gdf_ee: Simplified WGS84 PA GeoDataFrame
        scale: Analysis scale
        logger: Logger instance

    Returns:
        DataFrame with sensitivity indices
    """
    logger.info("Computing sensitivity analysis indices (NOT EII)...")
    logger.info("WARNING: These indices are for sensitivity analysis only, not EII values")

    component_bands = CONFIG["eii_component_bands"]
    components = image.select(component_bands)

    # Minimum across components
    min_index = components.reduce(ee.Reducer.min()).rename('sensitivity_min')

    # Product of components
    product_index = components.reduce(ee.Reducer.product()).rename('sensitivity_product')

    # Geometric mean (cube root of product for 3 components)
    geom_mean_index = product_index.pow(1.0 / len(component_bands)).rename('sensitivity_geom_mean')

    # Combine indices
    sensitivity_image = min_index.addBands(product_index).addBands(geom_mean_index)

    # Compute zonal stats
    reducers = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True)

    stats_list = []
    batches = list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE))
    for batch_idx, batch_gdf in enumerate(batches, start=1):
        logger.info(f"Sensitivity batch {batch_idx}/{len(batches)} ({len(batch_gdf)} PAs)...")
        regions = gdf_to_ee_featurecollection(batch_gdf, CONFIG["pa_name_field"])
        results = sensitivity_image.reduceRegions(
            collection=regions,
            reducer=reducers,
            scale=scale,
            crs='EPSG:4326'
        )
        result_info = results.getInfo()

        for feature in result_info['features']:
            props = feature['properties']
            stats = {
                'PA_name': props.get(CONFIG["pa_name_field"]),
                'park': props.get(CONFIG["pa_category_field"]),
                'Area_km2': props.get(CONFIG["pa_area_field"]),
                'sensitivity_min_mean': props.get('sensitivity_min_mean'),
                'sensitivity_min_stdDev': props.get('sensitivity_min_stdDev'),
                'sensitivity_product_mean': props.get('sensitivity_product_mean'),
                'sensitivity_product_stdDev': props.get('sensitivity_product_stdDev'),
                'sensitivity_geom_mean_mean': props.get('sensitivity_geom_mean_mean'),
                'sensitivity_geom_mean_stdDev': props.get('sensitivity_geom_mean_stdDev'),
            }
            stats_list.append(stats)

    return pd.DataFrame(stats_list)


def main():
    args = parse_args()
    base_dir = args.base_dir

    # Set up logging
    log_dir = get_path("reproducibility", base_dir)
    ensure_dir(log_dir)
    log_file = log_dir / f"{SCRIPT_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = setup_logger(SCRIPT_NAME, log_file)

    log_session_info(logger, SCRIPT_NAME, __version__, args)

    # Error handling setup
    error_bundle = ErrorBundle(SCRIPT_NAME, __version__)
    error_bundle.add_context("base_dir", str(base_dir or get_path("base")))
    error_bundle.add_context("gee_asset", EII_ASSET)

    try:
        # Validate required inputs
        logger.info("Validating required input files...")
        validation = validate_paths(base_dir, ["protected_areas", "gee_key"])
        if not validation["valid"]:
            raise FileNotFoundError(
                f"Missing required files:\n" + "\n".join(validation["missing"])
            )
        logger.info("All required input files found")

        # Authenticate to GEE
        authenticate_gee(base_dir, logger)

        # Load EII image
        logger.info(f"Loading EII asset: {EII_ASSET}")
        eii_image = ee.Image(EII_ASSET)

        # Verify bands exist
        band_names = eii_image.bandNames().getInfo()
        logger.info(f"Available bands: {band_names}")

        missing_bands = [b for b in EII_BANDS if b not in band_names]
        if missing_bands:
            raise ValueError(f"Missing required bands in EII asset: {missing_bands}")

        if EII_MAIN_BAND not in band_names:
            raise ValueError(
                f"CRITICAL: The precomputed 'eii' band is missing from the asset. "
                f"Cannot proceed without authoritative EII values. "
                f"Available bands: {band_names}"
            )

        logger.info(f"Confirmed: Precomputed '{EII_MAIN_BAND}' band is available")

        # Load Protected Areas
        logger.info("Loading Protected Areas...")
        pa_gdf = load_pa_geodataframe(
            base_dir=base_dir,
            validate_count=True,
            allow_mismatch=args.allow_pa_count_mismatch
        )
        logger.info(f"Loaded {len(pa_gdf)} Protected Areas")

        # Convert to WGS84 if needed
        if pa_gdf.crs.to_epsg() != 4326:
            logger.info("Converting PA geometries to WGS84...")
            pa_gdf = pa_gdf.to_crs("EPSG:4326")

        # Simplify only for EE request payload size
        pa_gdf_ee = prepare_pa_geometries_for_ee(pa_gdf, logger)

        batch_count = len(list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE)))
        logger.info(
            f"Prepared Earth Engine transfer in {batch_count} batches "
            f"(batch size {EE_BATCH_SIZE})"
        )

        # Compute zonal statistics for each band
        all_stats = []

        for band in EII_BANDS:
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing band: {band}")
            logger.info(f"{'='*50}")

            band_stats = compute_zonal_stats_for_band(
                eii_image, band, pa_gdf_ee, SCALE, logger
            )
            all_stats.extend(band_stats)

        # Create DataFrames
        stats_df = pd.DataFrame(all_stats)

        # Pivot to wide format for EII stats
        eii_stats = stats_df[stats_df['band'] == EII_MAIN_BAND].copy()
        eii_stats = eii_stats.drop(columns=['band'])
        eii_stats = eii_stats.rename(columns={
            'mean': 'eii_mean',
            'stdDev': 'eii_stdDev',
            'count': 'pixel_count',
            'p5': 'eii_p5',
            'p25': 'eii_p25',
            'p50': 'eii_p50',
            'p75': 'eii_p75',
            'p95': 'eii_p95',
        })

        # Component stats (wide format)
        component_stats = stats_df[stats_df['band'].isin(CONFIG["eii_component_bands"])].copy()

        # Output paths
        tables_dir = get_path("tables", base_dir)
        ensure_dir(tables_dir)

        # Save EII stats
        eii_path = tables_dir / "pa_eii_stats.csv"
        save_dataframe(eii_stats, eii_path, overwrite=args.overwrite)
        logger.info(f"Saved EII stats: {eii_path}")

        # Save all stats (long format)
        all_stats_path = tables_dir / "pa_all_bands_stats.csv"
        save_dataframe(stats_df, all_stats_path, overwrite=args.overwrite)
        logger.info(f"Saved all band stats: {all_stats_path}")

        # Save component stats
        component_path = tables_dir / "pa_component_stats.csv"
        save_dataframe(component_stats, component_path, overwrite=args.overwrite)
        logger.info(f"Saved component stats: {component_path}")

        # Sensitivity analysis (optional)
        if args.enable_method_compare:
            logger.info("\n" + "=" * 50)
            logger.info("SENSITIVITY ANALYSIS (NOT EII)")
            logger.info("=" * 50)

            sensitivity_df = compute_sensitivity_indices(
                eii_image, pa_gdf_ee, SCALE, logger
            )

            sensitivity_path = tables_dir / "pa_sensitivity_indices.csv"
            save_dataframe(sensitivity_df, sensitivity_path, overwrite=args.overwrite)
            logger.info(f"Saved sensitivity indices: {sensitivity_path}")

        # Write GEE assets log
        repro_dir = get_path("reproducibility", base_dir)
        ensure_dir(repro_dir)

        assets_used = {
            "EII Global v1": EII_ASSET,
            "Analysis Scale (m)": str(SCALE),
            "Analysis CRS": "EPSG:4326",
            "Percentiles": str(PERCENTILES),
        }
        assets_path = repro_dir / "gee_assets_used.txt"
        write_gee_assets_log(assets_path, assets_used)
        logger.info(f"Wrote GEE assets log: {assets_path}")

        # Create run manifest
        manifest = {
            "script": SCRIPT_NAME,
            "version": __version__,
            "timestamp": datetime.now().isoformat(),
            "gee_asset": EII_ASSET,
            "scale": SCALE,
            "pa_count": len(pa_gdf),
            "bands_processed": EII_BANDS,
            "method_compare_enabled": args.enable_method_compare,
            "outputs": {
                "eii_stats": str(eii_path),
                "all_band_stats": str(all_stats_path),
                "component_stats": str(component_path),
            }
        }

        if args.enable_method_compare:
            manifest["outputs"]["sensitivity_indices"] = str(sensitivity_path)

        manifest_path = repro_dir / "run_manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"Wrote run manifest: {manifest_path}")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "GEE authentication successful": True,
            "EII asset loaded": True,
            f"Precomputed '{EII_MAIN_BAND}' band used": True,
            f"PA count validated ({len(pa_gdf)})": len(pa_gdf) == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
            "All EII bands processed": len([s for s in stats_df['band'].unique()]) == len(EII_BANDS),
            "EII stats file created": eii_path.exists(),
            "Component stats file created": component_path.exists(),
        }
        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Write session info
        session_path = repro_dir / "session_info.txt"
        write_session_info(session_path, SCRIPT_NAME, __version__, args)

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("EII DOWNLOAD COMPLETE")
        logger.info("=" * 60)
        logger.info(f"PAs processed: {len(pa_gdf)}")
        logger.info(f"Bands processed: {EII_BANDS}")
        logger.info(f"Scale: {SCALE}m")
        logger.info(f"EII stats saved to: {eii_path}")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        logger.error("Paste the error file contents to Claude Code for diagnosis.")
        sys.exit(1)


if __name__ == "__main__":
    main()
