#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
14_sample_points_for_models.py
Generate stratified random sample points for inferential modeling.

This script:
1. Generates stratified random points inside PAs and outside rings
2. Extracts EII, components, all covariates, and elevation
3. Creates dataset ready for regression modeling

Sampling strategy:
- Stratified by PA and inside/outside
- Target ~50k points (configurable)
- Minimum 100 points per stratum

Output:
- 01_data/03_tables/model_points_eii_covariates.csv

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

SCRIPT_NAME = "14_sample_points_for_models"

# EII configuration
EII_ASSET = CONFIG["gee_eii_asset"]
EII_BANDS = CONFIG["eii_bands"]

# Covariate configuration
COVARIATES = CONFIG["gee_covariates"]

# Sampling configuration
SAMPLING_CONFIG = CONFIG["model_sampling"]
RANDOM_SEED = SAMPLING_CONFIG["random_seed"]
TARGET_POINTS = SAMPLING_CONFIG["target_points"]
MIN_POINTS_PER_STRATUM = SAMPLING_CONFIG["min_points_per_stratum"]

# Buffer for outside ring
DEFAULT_BUFFER_M = CONFIG["default_buffer_m"]
EE_GEOMETRY_ERROR_MARGIN_M = 10

# Analysis scale
SCALE = CONFIG["analysis_scale"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate stratified sample points for modeling"
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
        "--target-points",
        type=int,
        default=TARGET_POINTS,
        help=f"Target total points (default: {TARGET_POINTS})"
    )
    parser.add_argument(
        "--buffer-km",
        type=float,
        default=DEFAULT_BUFFER_M / 1000,
        help=f"Buffer distance in km (default: {DEFAULT_BUFFER_M/1000})"
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
        help="Not used in this script"
    )
    return parser.parse_args()


def prepare_combined_image(bhutan_geom, logger):
    """
    Prepare combined image with EII and all covariates.

    Args:
        bhutan_geom: ee.Geometry for Bhutan
        logger: Logger instance

    Returns:
        tuple: (ee.Image, list of band names)
    """
    logger.info("Preparing combined EII + covariate image...")

    # EII image
    eii_image = ee.Image(EII_ASSET).select(EII_BANDS)

    # Covariates
    # Human Modification Index
    # CSP/HM/GlobalHumanModification is an ImageCollection, not an Image
    hm_config = COVARIATES["human_modification"]
    hmi = ee.ImageCollection(hm_config["asset"]).mosaic().select(hm_config["band"]).rename("hmi")

    # Hansen Forest Change
    hansen_config = COVARIATES["hansen_forest"]
    hansen = ee.Image(hansen_config["asset"])
    treecover2000 = hansen.select("treecover2000").rename("treecover2000")
    forest_loss = hansen.select("loss").rename("forest_loss")

    # NDVI mean (simplified for point extraction)
    ndvi_config = COVARIATES["ndvi_modis"]
    date_range = ndvi_config["date_range"]
    ndvi_collection = (
        ee.ImageCollection(ndvi_config["asset"])
        .filterDate(date_range[0], date_range[1])
        .filterBounds(bhutan_geom)
        .select(ndvi_config["band"])
    )
    scale_factor = ndvi_config.get("scale_factor", 0.0001)
    ndvi_mean = ndvi_collection.mean().multiply(scale_factor).rename("ndvi_mean")

    # NDVI trend
    def add_time(img):
        date = ee.Date(img.get("system:time_start"))
        years = date.difference(ee.Date(date_range[0]), "year")
        return img.multiply(scale_factor).addBands(ee.Image(years).rename("t").float())

    ndvi_with_time = ndvi_collection.map(add_time)
    trend = ndvi_with_time.select(["t", "NDVI"]).reduce(ee.Reducer.linearFit())
    ndvi_trend = trend.select("scale").rename("ndvi_trend")

    # Burned area frequency
    ba_config = COVARIATES["burned_area"]
    ba_collection = (
        ee.ImageCollection(ba_config["asset"])
        .filterDate(ba_config["date_range"][0], ba_config["date_range"][1])
        .filterBounds(bhutan_geom)
        .select(ba_config["band"])
    )
    fire_frequency = ba_collection.map(lambda img: img.gt(0).unmask(0)).sum().rename("fire_frequency")

    # WorldCover
    wc_config = COVARIATES["worldcover"]
    worldcover = (
        ee.ImageCollection(wc_config["asset"])
        .filterBounds(bhutan_geom)
        .first()
        .select(wc_config["band"])
    )
    classes = wc_config["classes"]
    cropland = worldcover.eq(classes["cropland"]).rename("cropland")
    built_up = worldcover.eq(classes["built_up"]).rename("built_up")

    # Elevation
    elev_config = COVARIATES["elevation"]
    elevation = ee.Image(elev_config["asset"]).select(elev_config["band"]).rename("elevation")

    # Combine all
    combined = (
        eii_image
        .addBands(hmi)
        .addBands(treecover2000)
        .addBands(forest_loss)
        .addBands(ndvi_mean)
        .addBands(ndvi_trend)
        .addBands(fire_frequency)
        .addBands(cropland)
        .addBands(built_up)
        .addBands(elevation)
    ).clip(bhutan_geom)

    band_names = combined.bandNames().getInfo()
    logger.info(f"Combined image has {len(band_names)} bands: {band_names}")

    return combined, band_names


def create_buffer_ring(pa_geom, buffer_distance_m, bhutan_geom):
    """Create outside buffer ring for a PA."""
    buffered = pa_geom.buffer(buffer_distance_m, EE_GEOMETRY_ERROR_MARGIN_M)
    ring = buffered.difference(pa_geom, EE_GEOMETRY_ERROR_MARGIN_M)
    ring_clipped = ring.intersection(bhutan_geom, EE_GEOMETRY_ERROR_MARGIN_M)
    return ring_clipped


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def sample_points_from_region(image, region, n_points, pa_name, pa_type, location, seed, logger):
    """
    Sample random points from a region and extract values.

    Args:
        image: ee.Image to sample from
        region: ee.Geometry to sample within
        n_points: Number of points to sample
        pa_name: Name of the PA
        pa_type: Type/category of the PA
        location: 'inside' or 'outside'
        seed: Random seed
        logger: Logger instance

    Returns:
        List of dictionaries with sampled values
    """
    logger.info(f"  Sampling {n_points} points from {pa_name} ({location})...")

    # Generate random points
    points = ee.FeatureCollection.randomPoints(
        region=region,
        points=n_points,
        seed=seed,
        maxError=50  # meters
    )

    # Sample image at points
    sampled = image.sampleRegions(
        collection=points,
        scale=SCALE,
        geometries=True
    )

    # Get results
    sampled_info = sampled.getInfo()

    results = []
    for feature in sampled_info['features']:
        props = feature['properties']
        geom = feature['geometry']

        # Extract coordinates
        coords = geom['coordinates']
        if isinstance(coords[0], list):
            # Handle potential nested coordinates
            coords = coords[0]

        result = {
            'PA_name': pa_name,
            'PA_type': pa_type,
            'location': location,
            'inside_outside': 1 if location == 'inside' else 0,
            'longitude': coords[0],
            'latitude': coords[1],
        }

        # Add all band values
        for key, value in props.items():
            if key not in ['system:index']:
                result[key] = value

        results.append(result)

    logger.info(f"    Retrieved {len(results)} points")
    return results


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

        # Load Protected Areas
        logger.info("Loading Protected Areas...")
        pa_gdf = load_pa_geodataframe(
            base_dir=base_dir,
            validate_count=True,
            allow_mismatch=args.allow_pa_count_mismatch
        )
        if pa_gdf.crs.to_epsg() != 4326:
            pa_gdf = pa_gdf.to_crs("EPSG:4326")

        n_pas = len(pa_gdf)
        logger.info(f"Loaded {n_pas} Protected Areas")

        # Load Bhutan boundary
        logger.info("Loading Bhutan boundary...")
        bhutan_gdf = load_bhutan_boundary(base_dir)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")
        bhutan_geom = geometry_to_ee(bhutan_gdf.unary_union)

        # Prepare combined image
        combined_image, band_names = prepare_combined_image(bhutan_geom, logger)

        # Calculate points per stratum
        # Total strata = n_pas * 2 (inside + outside)
        n_strata = n_pas * 2
        target_points = args.target_points
        points_per_stratum = max(MIN_POINTS_PER_STRATUM, target_points // n_strata)

        logger.info("\n" + "=" * 60)
        logger.info("SAMPLING CONFIGURATION")
        logger.info("=" * 60)
        logger.info(f"Target total points: {target_points}")
        logger.info(f"Number of strata: {n_strata}")
        logger.info(f"Points per stratum: {points_per_stratum}")
        logger.info(f"Buffer distance: {args.buffer_km} km")
        logger.info(f"Random seed: {RANDOM_SEED}")

        # Sample points from each PA
        logger.info("\n" + "=" * 60)
        logger.info("SAMPLING POINTS")
        logger.info("=" * 60)

        all_points = []
        buffer_m = args.buffer_km * 1000

        for idx, row in pa_gdf.iterrows():
            pa_name = row[CONFIG["pa_name_field"]]
            pa_type = row[CONFIG["pa_category_field"]]

            logger.info(f"\nProcessing: {pa_name} ({pa_type})")

            # Create PA geometry
            pa_geom = geometry_to_ee(row.geometry)

            # Sample inside points
            seed_inside = RANDOM_SEED + idx * 2
            inside_points = sample_points_from_region(
                combined_image, pa_geom, points_per_stratum,
                pa_name, pa_type, 'inside', seed_inside, logger
            )
            all_points.extend(inside_points)

            # Create outside ring
            ring_geom = create_buffer_ring(pa_geom, buffer_m, bhutan_geom)

            # Sample outside points
            seed_outside = RANDOM_SEED + idx * 2 + 1
            outside_points = sample_points_from_region(
                combined_image, ring_geom, points_per_stratum,
                pa_name, pa_type, 'outside', seed_outside, logger
            )
            all_points.extend(outside_points)

        # Create DataFrame
        logger.info("\n" + "=" * 60)
        logger.info("CREATING OUTPUT DATASET")
        logger.info("=" * 60)

        points_df = pd.DataFrame(all_points)
        logger.info(f"Total points sampled: {len(points_df)}")

        # Summary statistics
        logger.info("\nSampling summary:")
        logger.info(f"  Inside points: {(points_df['location'] == 'inside').sum()}")
        logger.info(f"  Outside points: {(points_df['location'] == 'outside').sum()}")

        for pa_type in points_df['PA_type'].unique():
            type_count = len(points_df[points_df['PA_type'] == pa_type])
            logger.info(f"  {pa_type}: {type_count} points")

        # Check for missing values
        missing_summary = points_df.isnull().sum()
        missing_cols = missing_summary[missing_summary > 0]
        if len(missing_cols) > 0:
            logger.warning("\nColumns with missing values:")
            for col, count in missing_cols.items():
                logger.warning(f"  {col}: {count} missing ({100*count/len(points_df):.1f}%)")

        # Save output
        tables_dir = get_path("tables", base_dir)
        ensure_dir(tables_dir)

        output_path = tables_dir / "model_points_eii_covariates.csv"
        save_dataframe(points_df, output_path, overwrite=args.overwrite)
        logger.info(f"\nSaved model points: {output_path}")

        # Save sampling manifest
        repro_dir = get_path("reproducibility", base_dir)
        ensure_dir(repro_dir)

        manifest = {
            "script": SCRIPT_NAME,
            "version": __version__,
            "timestamp": datetime.now().isoformat(),
            "sampling_config": {
                "target_points": target_points,
                "points_per_stratum": points_per_stratum,
                "n_strata": n_strata,
                "buffer_km": args.buffer_km,
                "random_seed": RANDOM_SEED,
            },
            "results": {
                "total_points": len(points_df),
                "inside_points": int((points_df['location'] == 'inside').sum()),
                "outside_points": int((points_df['location'] == 'outside').sum()),
                "pas_sampled": n_pas,
            },
            "bands_extracted": band_names,
        }

        manifest_path = repro_dir / "sampling_manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"Saved sampling manifest: {manifest_path}")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "GEE authentication successful": True,
            f"PA count validated ({n_pas})": n_pas == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
            "Combined image prepared": len(band_names) > 0,
            f"Points sampled ({len(points_df)})": len(points_df) > 0,
            "Inside points sampled": (points_df['location'] == 'inside').sum() > 0,
            "Outside points sampled": (points_df['location'] == 'outside').sum() > 0,
            "Output file created": output_path.exists(),
            "Output non-empty": len(points_df) > 0,
        }

        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        logger.info("\n" + "=" * 60)
        logger.info("POINT SAMPLING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total points: {len(points_df)}")
        logger.info(f"Ready for 15_models_drivers.py")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
