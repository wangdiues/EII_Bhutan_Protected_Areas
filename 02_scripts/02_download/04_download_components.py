#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
04_download_components.py
Download EII component rasters (clipped to Bhutan) from Google Earth Engine.
This script exports rasters for visualization purposes.

Version History:
    1.0.0 - Initial implementation
"""

__version__ = "1.0.0"

import argparse
import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ee
import geopandas as gpd
import numpy as np

from _shared.config import CONFIG, get_path, validate_paths
from _shared.gee_utils import authenticate_gee, geometry_to_ee
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import (
    load_bhutan_boundary, ensure_dir, write_success_marker
)
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report,
    retry_with_backoff
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "04_download_components"
EII_ASSET = CONFIG["gee_eii_asset"]
EII_BANDS = CONFIG["eii_bands"]
SCALE = CONFIG["analysis_scale"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download EII component rasters from Google Earth Engine"
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
        "--enable-exports",
        action="store_true",
        help="Enable GEE exports (required for this script)"
    )
    parser.add_argument(
        "--allow-pa-count-mismatch",
        action="store_true",
        help="Allow PA count different from expected 19"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Enable sensitivity analysis"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Allow geometry simplification"
    )
    return parser.parse_args()


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def download_raster_via_url(image, region, scale, band_name, output_path, logger):
    """
    Download a raster using getDownloadURL.

    Args:
        image: ee.Image
        region: ee.Geometry
        scale: Scale in meters
        band_name: Name of the band
        output_path: Path to save the GeoTIFF
        logger: Logger instance

    Returns:
        Path to downloaded file
    """
    logger.info(f"Requesting download URL for band: {band_name}")

    # Get download URL
    url = image.select(band_name).getDownloadURL({
        'scale': scale,
        'region': region,
        'format': 'GEO_TIFF',
        'crs': 'EPSG:4326'
    })

    logger.info(f"Download URL obtained, fetching data...")

    # Download the file
    response = requests.get(url, timeout=300)
    response.raise_for_status()

    # Save to file
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

    # Error handling
    error_bundle = ErrorBundle(SCRIPT_NAME, __version__)
    error_bundle.add_context("base_dir", str(base_dir or get_path("base")))

    try:
        # Validate inputs
        logger.info("Validating required input files...")
        validation = validate_paths(base_dir, ["bhutan_boundary", "gee_key"])
        if not validation["valid"]:
            raise FileNotFoundError(
                f"Missing required files:\n" + "\n".join(validation["missing"])
            )

        # Authenticate
        authenticate_gee(base_dir, logger)

        # Load Bhutan boundary
        logger.info("Loading Bhutan boundary...")
        bhutan_gdf = load_bhutan_boundary(base_dir)

        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")

        # Convert to EE geometry
        ee_region = geometry_to_ee(bhutan_gdf.unary_union)

        # Load EII image
        logger.info(f"Loading EII asset: {EII_ASSET}")
        eii_image = ee.Image(EII_ASSET)

        # Verify bands
        band_names = eii_image.bandNames().getInfo()
        logger.info(f"Available bands: {band_names}")

        # Output directory
        output_dir = get_path("gee_eii", base_dir)
        ensure_dir(output_dir)

        # Download each band
        downloaded_files = []

        for band in EII_BANDS:
            if band not in band_names:
                logger.warning(f"Band {band} not found in asset, skipping")
                continue

            output_file = output_dir / f"{band}_bhutan.tif"

            if output_file.exists() and not args.overwrite:
                logger.info(f"Output exists, skipping: {output_file}")
                downloaded_files.append(str(output_file))
                continue

            logger.info(f"\n{'='*50}")
            logger.info(f"Downloading band: {band}")
            logger.info(f"{'='*50}")

            try:
                downloaded_path = download_raster_via_url(
                    eii_image, ee_region, SCALE, band, output_file, logger
                )
                downloaded_files.append(str(downloaded_path))
            except Exception as e:
                logger.error(f"Failed to download {band}: {e}")
                logger.error("Try using --enable-exports for batch export as fallback")
                raise

        # Validation
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "GEE authentication successful": True,
            "Bhutan boundary loaded": True,
            f"Downloaded {len(downloaded_files)} rasters": len(downloaded_files) == len(EII_BANDS),
        }

        for band in EII_BANDS:
            check_path = output_dir / f"{band}_bhutan.tif"
            checks[f"Raster exists: {band}"] = check_path.exists()

        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        logger.info("\n" + "=" * 60)
        logger.info("COMPONENT DOWNLOAD COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Downloaded files: {len(downloaded_files)}")
        for f in downloaded_files:
            logger.info(f"  - {f}")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
