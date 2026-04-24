#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
05_download_npp.py
Download NPP predictions for Bhutan from Google Earth Engine (optional).

Version History:
    1.0.0 - Initial implementation
"""

__version__ = "1.0.0"

import argparse
import sys
import requests
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
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import (
    load_bhutan_boundary, load_pa_geodataframe, ensure_dir,
    save_dataframe, write_success_marker
)
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report,
    retry_with_backoff
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "05_download_npp"
NPP_ASSET = CONFIG["gee_npp_asset"]
SCALE = CONFIG["analysis_scale"]
EE_TRANSFER_SIMPLIFY_TOLERANCE_M = 90
EE_BATCH_SIZE = 4


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download NPP predictions from Google Earth Engine"
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
        help="Enable batch exports"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Enable method comparison"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Allow geometry simplification"
    )
    return parser.parse_args()


def gdf_to_ee_featurecollection(gdf, id_field):
    """Convert GeoDataFrame to Earth Engine FeatureCollection."""
    features = []
    for idx, row in gdf.iterrows():
        props = {
            id_field: row[id_field],
            CONFIG["pa_category_field"]: row[CONFIG["pa_category_field"]],
            CONFIG["pa_area_field"]: row[CONFIG["pa_area_field"]]
        }
        ee_geom = geometry_to_ee(row.geometry)
        feature = ee.Feature(ee_geom, props)
        features.append(feature)

    return ee.FeatureCollection(features)


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def compute_npp_zonal_stats(image, pa_gdf_ee, scale, logger):
    """
    Compute zonal statistics for NPP.

    Args:
        image: ee.Image (NPP predictions)
        pa_gdf_ee: Simplified WGS84 PA GeoDataFrame
        scale: Analysis scale
        logger: Logger instance

    Returns:
        List of dictionaries with NPP stats per region
    """
    logger.info("Computing NPP zonal statistics...")

    # NPP typically has a single band, get band names first
    band_names = image.bandNames().getInfo()
    logger.info(f"NPP bands: {band_names}")

    if not band_names:
        raise ValueError("NPP image has no bands")

    # Use the first band
    npp_band = band_names[0]
    npp_image = image.select(npp_band)

    reducers = (
        ee.Reducer.mean()
        .combine(ee.Reducer.percentile([5, 25, 50, 75, 95]), sharedInputs=True)
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
    )

    stats_list = []
    batches = list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE))
    for batch_idx, batch_gdf in enumerate(batches, start=1):
        logger.info(f"NPP batch {batch_idx}/{len(batches)} ({len(batch_gdf)} PAs)...")
        regions = gdf_to_ee_featurecollection(batch_gdf, CONFIG["pa_name_field"])
        results = npp_image.reduceRegions(
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
                'npp_mean': props.get('mean'),
                'npp_stdDev': props.get('stdDev'),
                'npp_p5': props.get('p5'),
                'npp_p25': props.get('p25'),
                'npp_p50': props.get('p50'),
                'npp_p75': props.get('p75'),
                'npp_p95': props.get('p95'),
            }
            stats_list.append(stats)

    logger.info(f"Retrieved NPP stats for {len(stats_list)} regions")
    return stats_list


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def download_npp_raster(image, region, scale, output_path, logger):
    """Download NPP raster via URL."""
    logger.info("Requesting NPP download URL...")

    band_names = image.bandNames().getInfo()
    if not band_names:
        raise ValueError("NPP image has no bands")

    url = image.getDownloadURL({
        'scale': scale,
        'region': region,
        'format': 'GEO_TIFF',
        'crs': 'EPSG:4326'
    })

    logger.info("Downloading NPP raster...")
    response = requests.get(url, timeout=300)
    response.raise_for_status()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'wb') as f:
        f.write(response.content)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Downloaded: {output_path} ({file_size_mb:.2f} MB)")

    return output_path


def main():
    args = parse_args()
    base_dir = args.base_dir

    # Set up logging
    log_dir = get_path("reproducibility", base_dir)
    ensure_dir(log_dir)
    log_file = log_dir / f"{SCRIPT_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = setup_logger(SCRIPT_NAME, log_file)

    log_session_info(logger, SCRIPT_NAME, __version__, args)

    error_bundle = ErrorBundle(SCRIPT_NAME, __version__)
    error_bundle.add_context("base_dir", str(base_dir or get_path("base")))
    error_bundle.add_context("npp_asset", NPP_ASSET)

    try:
        # Validate inputs
        logger.info("Validating required input files...")
        validation = validate_paths(base_dir, ["protected_areas", "bhutan_boundary", "gee_key"])
        if not validation["valid"]:
            raise FileNotFoundError(
                f"Missing required files:\n" + "\n".join(validation["missing"])
            )

        # Authenticate
        authenticate_gee(base_dir, logger)

        # Try to load NPP asset
        logger.info(f"Loading NPP asset: {NPP_ASSET}")
        try:
            npp_image = ee.Image(NPP_ASSET)
            # Test that the asset exists by getting info
            npp_info = npp_image.getInfo()
            logger.info("NPP asset loaded successfully")
        except Exception as e:
            logger.warning(f"Could not load NPP asset: {e}")
            logger.warning("NPP is optional - proceeding without NPP analysis")

            # Write skip marker
            script_dir = Path(__file__).parent
            skip_file = script_dir / f"_SKIPPED_{SCRIPT_NAME}.txt"
            with open(skip_file, 'w') as f:
                f.write(f"Skipped at: {datetime.now().isoformat()}\n")
                f.write(f"Reason: NPP asset not accessible\n")
                f.write(f"Asset: {NPP_ASSET}\n")
            logger.info(f"Wrote skip marker: {skip_file}")
            return

        # Load boundaries
        logger.info("Loading Protected Areas...")
        pa_gdf = load_pa_geodataframe(
            base_dir=base_dir,
            validate_count=True,
            allow_mismatch=args.allow_pa_count_mismatch
        )

        if pa_gdf.crs.to_epsg() != 4326:
            pa_gdf = pa_gdf.to_crs("EPSG:4326")

        logger.info("Loading Bhutan boundary...")
        bhutan_gdf = load_bhutan_boundary(base_dir)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")

        pa_gdf_ee = prepare_gdf_for_ee(pa_gdf, tolerance_m=EE_TRANSFER_SIMPLIFY_TOLERANCE_M)
        bhutan_geom = geometry_to_ee(bhutan_gdf.unary_union)

        # Compute zonal stats
        logger.info("\n" + "=" * 50)
        logger.info("Computing NPP zonal statistics")
        logger.info("=" * 50)

        npp_stats = compute_npp_zonal_stats(npp_image, pa_gdf_ee, SCALE, logger)
        npp_df = pd.DataFrame(npp_stats)

        # Save stats
        tables_dir = get_path("tables", base_dir)
        ensure_dir(tables_dir)

        stats_path = tables_dir / "pa_npp_stats.csv"
        save_dataframe(npp_df, stats_path, overwrite=args.overwrite)
        logger.info(f"Saved NPP stats: {stats_path}")

        # Download raster
        raster_dir = get_path("gee_npp", base_dir)
        ensure_dir(raster_dir)

        raster_path = raster_dir / "npp_bhutan.tif"
        if raster_path.exists() and not args.overwrite:
            logger.info(f"Raster exists, skipping: {raster_path}")
        else:
            download_npp_raster(npp_image, bhutan_geom, SCALE, raster_path, logger)

        # Validation
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "NPP asset loaded": True,
            "Zonal stats computed": len(npp_df) > 0,
            "Stats file created": stats_path.exists(),
            "Raster downloaded": raster_path.exists(),
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
        logger.info("NPP DOWNLOAD COMPLETE")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
