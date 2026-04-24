#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
02_define_aoi.py
Define Area of Interest (AOI) from Bhutan boundary and Protected Areas.
Validates data and prepares geometries for GEE analysis.

Version History:
    1.0.0 - Initial implementation
"""

__version__ = "1.1.0"

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geopandas as gpd
import pandas as pd

from _shared.config import CONFIG, get_path, validate_paths
from _shared.logging_utils import setup_logger, log_session_info, write_session_info
from _shared.io_utils import (
    load_raw_pa_geodataframe, load_raw_bhutan_boundary, ensure_dir,
    save_dataframe, save_geodataframe, write_success_marker
)
from _shared.error_utils import ErrorBundle, write_error_bundle, create_validation_report


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "02_define_aoi"
OUTPUT_GEOJSON = "bhutan_pas_wgs84.geojson"
OUTPUT_PA_TABLE = "pa_attributes.csv"
OUTPUT_PA_GPKG = "protected_areas_btn.gpkg"
OUTPUT_BHUTAN_GPKG = "bhutan_boundary.gpkg"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Define AOI from Bhutan boundary and Protected Areas"
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
        "--allow-geometry-simplification",
        action="store_true",
        help="Allow geometry simplification (logs tolerance and area change)"
    )
    parser.add_argument(
        "--simplify-tolerance",
        type=float,
        default=None,
        help="Simplification tolerance in degrees (only if --allow-geometry-simplification)"
    )
    return parser.parse_args()


def convert_to_wgs84(gdf, logger):
    """
    Convert GeoDataFrame to WGS84 (EPSG:4326).

    Args:
        gdf: Input GeoDataFrame
        logger: Logger instance

    Returns:
        GeoDataFrame in WGS84
    """
    source_crs = gdf.crs
    logger.info(f"Source CRS: {source_crs}")

    if source_crs is None:
        raise ValueError("Input GeoDataFrame has no CRS defined")

    if source_crs.to_epsg() == 4326:
        logger.info("Data already in WGS84, no conversion needed")
        return gdf

    logger.info(f"Converting from {source_crs} to EPSG:4326 (WGS84)")
    gdf_wgs84 = gdf.to_crs("EPSG:4326")
    logger.info("CRS conversion complete")

    return gdf_wgs84


def simplify_geometry_if_allowed(gdf, args, logger):
    """
    Optionally simplify geometry with full logging.

    Args:
        gdf: Input GeoDataFrame
        args: Parsed arguments
        logger: Logger instance

    Returns:
        GeoDataFrame (simplified or original)
    """
    if not args.allow_geometry_simplification:
        logger.info("Geometry simplification: DISABLED")
        return gdf

    if args.simplify_tolerance is None:
        logger.warning("--allow-geometry-simplification set but no --simplify-tolerance provided")
        logger.warning("Skipping simplification")
        return gdf

    tolerance = args.simplify_tolerance
    logger.info(f"Geometry simplification: ENABLED (tolerance={tolerance} degrees)")

    # Calculate area before simplification
    gdf_projected = gdf.to_crs("EPSG:5266")  # DRUKREF03 for area calculation
    area_before = gdf_projected.geometry.area.sum()

    # Simplify
    gdf_simplified = gdf.copy()
    gdf_simplified['geometry'] = gdf_simplified.geometry.simplify(
        tolerance, preserve_topology=True
    )

    # Calculate area after
    gdf_simplified_projected = gdf_simplified.to_crs("EPSG:5266")
    area_after = gdf_simplified_projected.geometry.area.sum()

    # Report area change
    area_change_pct = ((area_after - area_before) / area_before) * 100
    logger.info(f"Area before simplification: {area_before / 1e6:.2f} km2")
    logger.info(f"Area after simplification: {area_after / 1e6:.2f} km2")
    logger.info(f"Area change: {area_change_pct:.4f}%")

    return gdf_simplified


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

    try:
        # Validate required raw inputs
        logger.info("Validating required input files...")
        validation = validate_paths(base_dir, ["raw_bhutan_boundary", "raw_protected_areas"])
        if not validation["valid"]:
            raise FileNotFoundError(
                f"Missing required files:\n" + "\n".join(validation["missing"])
            )
        logger.info("All required input files found")

        # Load normalized Protected Areas / Biological Corridors network
        logger.info("Loading raw PA/BC boundary source...")
        pa_gdf = load_raw_pa_geodataframe(base_dir=base_dir, normalize_network=True)
        logger.info(f"Loaded {len(pa_gdf)} dissolved PA network features")
        logger.info(f"PA CRS: {pa_gdf.crs}")

        if len(pa_gdf) != CONFIG["expected_pa_count"]:
            msg = (
                f"PA network count mismatch after normalization: expected "
                f"{CONFIG['expected_pa_count']}, found {len(pa_gdf)}"
            )
            if args.allow_pa_count_mismatch:
                logger.warning(msg)
            else:
                raise ValueError(f"{msg}. Use --allow-pa-count-mismatch to override.")

        # Load raw Bhutan boundary
        logger.info("Loading raw Bhutan boundary...")
        bhutan_gdf = load_raw_bhutan_boundary(base_dir)
        logger.info(f"Bhutan boundary CRS: {bhutan_gdf.crs}")

        # Convert to WGS84
        logger.info("Converting to WGS84...")
        pa_wgs84 = convert_to_wgs84(pa_gdf, logger)
        bhutan_wgs84 = convert_to_wgs84(bhutan_gdf, logger)

        # Optional simplification
        pa_wgs84 = simplify_geometry_if_allowed(pa_wgs84, args, logger)

        # Validate geometries
        logger.info("Validating geometries...")
        invalid_count = (~pa_wgs84.is_valid).sum()
        if invalid_count > 0:
            logger.warning(f"Found {invalid_count} invalid geometries, attempting repair...")
            pa_wgs84['geometry'] = pa_wgs84.geometry.make_valid()
            invalid_after = (~pa_wgs84.is_valid).sum()
            if invalid_after > 0:
                raise ValueError(f"Could not repair {invalid_after} invalid geometries")
            logger.info("All geometries repaired")
        else:
            logger.info("All geometries valid")

        # Output paths
        processed_dir = get_path("processed_vectors", base_dir)
        tables_dir = get_path("tables", base_dir)
        ensure_dir(processed_dir)
        ensure_dir(tables_dir)

        pa_gpkg_path = processed_dir / OUTPUT_PA_GPKG
        bhutan_gpkg_path = processed_dir / OUTPUT_BHUTAN_GPKG
        logger.info(f"Saving Protected Areas GeoPackage: {pa_gpkg_path}")
        save_geodataframe(
            pa_wgs84,
            pa_gpkg_path,
            layer=CONFIG["protected_areas_layer"],
            overwrite=args.overwrite
        )
        logger.info(f"Saving Bhutan boundary GeoPackage: {bhutan_gpkg_path}")
        save_geodataframe(
            bhutan_wgs84,
            bhutan_gpkg_path,
            layer=CONFIG["bhutan_boundary_layer"],
            overwrite=args.overwrite
        )

        # Save GeoJSON for GEE
        geojson_path = processed_dir / OUTPUT_GEOJSON
        if geojson_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"Output exists: {geojson_path}. Use --overwrite to replace."
            )

        logger.info(f"Saving GeoJSON: {geojson_path}")
        pa_wgs84.to_file(geojson_path, driver='GeoJSON')

        # Save PA attributes table
        pa_attrs = pa_wgs84[[
            CONFIG["pa_name_field"],
            CONFIG["pa_category_field"],
            CONFIG["pa_area_field"]
        ]].copy()

        csv_path = tables_dir / OUTPUT_PA_TABLE
        save_dataframe(pa_attrs, csv_path, overwrite=args.overwrite)
        logger.info(f"Saved PA attributes: {csv_path}")

        # Summary statistics
        logger.info("-" * 50)
        logger.info("PA Summary:")
        logger.info(f"  Total PAs: {len(pa_wgs84)}")
        logger.info(f"  Total Area: {pa_wgs84[CONFIG['pa_area_field']].sum():.2f} km2")
        logger.info(f"  Categories: {pa_wgs84[CONFIG['pa_category_field']].unique().tolist()}")

        # Bounding box
        bounds = pa_wgs84.total_bounds
        logger.info(f"  Bounding Box: [{bounds[0]:.4f}, {bounds[1]:.4f}, {bounds[2]:.4f}, {bounds[3]:.4f}]")

        # Create validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)
        checks = {
            "PA count validated": len(pa_wgs84) == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
            "All geometries valid": pa_wgs84.is_valid.all(),
            "CRS is WGS84": pa_wgs84.crs.to_epsg() == 4326,
            "Protected Areas GeoPackage created": pa_gpkg_path.exists(),
            "Bhutan boundary GeoPackage created": bhutan_gpkg_path.exists(),
            "GeoJSON output created": geojson_path.exists(),
            "CSV output created": csv_path.exists(),
        }
        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Write session info
        session_path = get_path("reproducibility", base_dir) / "session_info.txt"
        write_session_info(session_path, SCRIPT_NAME, __version__, args)

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        logger.info("=" * 50)
        logger.info("AOI DEFINITION COMPLETE")
        logger.info("=" * 50)

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
