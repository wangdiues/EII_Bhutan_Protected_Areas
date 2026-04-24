#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
12_prepare_covariates.py
Prepare covariate datasets from Google Earth Engine for triangulation analysis.

This script prepares and validates access to GEE covariate datasets used for:
- Multi-metric triangulation (EII vs independent pressure/condition datasets)
- Inferential drivers modeling

Datasets prepared:
- CSP/HM Global Human Modification Index (gHM)
- Hansen Global Forest Change (loss rate)
- MODIS NDVI trend (2001-latest)
- MODIS MCD64A1 burned area frequency
- ESA WorldCover v200 (cropland + built-up fractions)
- SRTM Elevation

Version History:
    1.0.0 - Initial implementation
    1.0.1 - Fix: load CSP/HM/GlobalHumanModification as ImageCollection (mosaic -> Image)
    1.0.2 - Fix: consistent key naming for NDVI (use ndvi_modis key everywhere)
"""

__version__ = "1.0.2"

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ee
import pandas as pd

from _shared.config import CONFIG, get_path, validate_paths
from _shared.gee_utils import authenticate_gee, geometry_to_ee
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import (
    load_bhutan_boundary, ensure_dir,
    save_dataframe, write_success_marker
)
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report,
    retry_with_backoff
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "12_prepare_covariates"
COVARIATES = CONFIG["gee_covariates"]
SCALE = CONFIG["analysis_scale"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Prepare covariate datasets from GEE for triangulation analysis"
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
        help="Enable GEE batch exports (not used in this script)"
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


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def validate_gee_asset(asset_id, logger):
    """
    Validate that a GEE asset exists and is accessible.

    Args:
        asset_id: GEE asset path
        logger: Logger instance

    Returns:
        dict with asset info
    """
    logger.info(f"Validating asset: {asset_id}")

    try:
        # Try as Image first
        image = ee.Image(asset_id)
        info = image.getInfo()
        asset_type = "Image"
    except Exception:
        try:
            # Try as ImageCollection
            collection = ee.ImageCollection(asset_id)
            info = collection.first().getInfo()
            asset_type = "ImageCollection"
        except Exception as e:
            raise ValueError(f"Cannot access asset {asset_id}: {e}")

    bands = info.get("bands", [])
    band_names = [b["id"] for b in bands if "id" in b]

    return {
        "asset_id": asset_id,
        "type": asset_type,
        "bands": band_names,
        "accessible": True
    }


def prepare_human_modification(bhutan_geom, logger):
    """
    Prepare Global Human Modification Index.

    NOTE:
    CSP/HM/GlobalHumanModification is an ImageCollection, not an Image.
    Convert to a single Image with mosaic() before selecting band.
    """
    logger.info("Preparing Human Modification Index...")

    hm_config = COVARIATES["human_modification"]
    asset_id = hm_config["asset"]
    band = hm_config["band"]

    hm_image = (
        ee.ImageCollection(asset_id)
        .mosaic()
        .select(band)
    )

    hm_clipped = hm_image.clip(bhutan_geom)

    logger.info(f"Human Modification prepared: {asset_id} (ImageCollection -> mosaic -> Image)")
    return hm_clipped


def prepare_hansen_forest_change(bhutan_geom, logger):
    """
    Prepare Hansen Global Forest Change metrics.
    """
    logger.info("Preparing Hansen Forest Change...")

    hansen_config = COVARIATES["hansen_forest"]
    hansen = ee.Image(hansen_config["asset"])

    treecover2000 = hansen.select("treecover2000")
    loss = hansen.select("loss")
    lossyear = hansen.select("lossyear")

    # Only consider areas that had >25% tree cover in 2000
    forest_mask = treecover2000.gt(25)

    # Proportional loss relative to 2000 cover
    loss_rate = loss.updateMask(forest_mask).divide(treecover2000.divide(100))

    hansen_metrics = (
        treecover2000.rename("treecover2000")
        .addBands(loss.rename("forest_loss"))
        .addBands(loss_rate.rename("forest_loss_rate"))
        .addBands(lossyear.rename("lossyear"))
    ).clip(bhutan_geom)

    logger.info(f"Hansen Forest Change prepared: {hansen_config['asset']}")
    return hansen_metrics


def prepare_ndvi_trend(bhutan_geom, logger):
    """
    Prepare NDVI trend from MODIS time series.
    """
    logger.info("Preparing NDVI trend from MODIS...")

    ndvi_config = COVARIATES["ndvi_modis"]
    date_range = ndvi_config["date_range"]

    ndvi_collection = (
        ee.ImageCollection(ndvi_config["asset"])
        .filterDate(date_range[0], date_range[1])
        .filterBounds(bhutan_geom)
        .select(ndvi_config["band"])
    )

    scale_factor = ndvi_config.get("scale_factor", 0.0001)

    def scale_ndvi(img):
        return img.multiply(scale_factor).copyProperties(img, ["system:time_start"])

    ndvi_scaled = ndvi_collection.map(scale_ndvi)

    ndvi_mean = ndvi_scaled.mean().rename("ndvi_mean")
    ndvi_std = ndvi_scaled.reduce(ee.Reducer.stdDev()).rename("ndvi_std")

    def add_time(img):
        date = ee.Date(img.get("system:time_start"))
        years = date.difference(ee.Date(date_range[0]), "year")
        return img.addBands(ee.Image(years).rename("t").float())

    ndvi_with_time = ndvi_scaled.map(add_time)

    trend = ndvi_with_time.select(["t", "NDVI"]).reduce(ee.Reducer.linearFit())
    ndvi_slope = trend.select("scale").rename("ndvi_trend")

    ndvi_metrics = ndvi_mean.addBands(ndvi_std).addBands(ndvi_slope).clip(bhutan_geom)

    logger.info(f"NDVI trend prepared from {ndvi_collection.size().getInfo()} images")
    return ndvi_metrics


def prepare_burned_area(bhutan_geom, logger):
    """
    Prepare burned area frequency from MODIS.
    """
    logger.info("Preparing burned area frequency...")

    ba_config = COVARIATES["burned_area"]
    date_range = ba_config["date_range"]

    ba_collection = (
        ee.ImageCollection(ba_config["asset"])
        .filterDate(date_range[0], date_range[1])
        .filterBounds(bhutan_geom)
        .select(ba_config["band"])
    )

    def has_burn(img):
        return img.gt(0).unmask(0)

    burn_binary = ba_collection.map(has_burn)
    fire_frequency = burn_binary.sum().rename("fire_frequency")

    n_years = ee.Date(date_range[1]).difference(ee.Date(date_range[0]), "year")
    fire_density = fire_frequency.divide(n_years).rename("fire_density")

    fire_metrics = fire_frequency.addBands(fire_density).clip(bhutan_geom)

    logger.info(f"Burned area prepared from {ba_collection.size().getInfo()} months")
    return fire_metrics


def prepare_worldcover(bhutan_geom, logger):
    """
    Prepare land cover fractions from ESA WorldCover.
    """
    logger.info("Preparing ESA WorldCover fractions...")

    wc_config = COVARIATES["worldcover"]

    worldcover = (
        ee.ImageCollection(wc_config["asset"])
        .filterBounds(bhutan_geom)
        .first()
        .select(wc_config["band"])
    )

    classes = wc_config["classes"]

    cropland_mask = worldcover.eq(classes["cropland"]).rename("cropland")
    builtup_mask = worldcover.eq(classes["built_up"]).rename("built_up")

    lc_metrics = cropland_mask.addBands(builtup_mask).clip(bhutan_geom)

    logger.info(f"WorldCover prepared: {wc_config['asset']}")
    return lc_metrics


def prepare_elevation(bhutan_geom, logger):
    """
    Prepare elevation from SRTM.
    """
    logger.info("Preparing SRTM elevation...")

    elev_config = COVARIATES["elevation"]
    elevation = ee.Image(elev_config["asset"]).select(elev_config["band"])
    elevation_clipped = elevation.clip(bhutan_geom).rename("elevation")

    logger.info(f"Elevation prepared: {elev_config['asset']}")
    return elevation_clipped


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
        validation = validate_paths(base_dir, ["bhutan_boundary", "gee_key"])
        if not validation["valid"]:
            raise FileNotFoundError(
                "Missing required files:\n" + "\n".join(validation["missing"])
            )

        # Authenticate to GEE
        authenticate_gee(base_dir, logger)

        # Load Bhutan boundary
        logger.info("Loading Bhutan boundary...")
        bhutan_gdf = load_bhutan_boundary(base_dir)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")

        # DeprecationWarning is from geopandas; safe to ignore
        bhutan_geom = geometry_to_ee(bhutan_gdf.unary_union)

        # Validate all covariate assets
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATING GEE COVARIATE ASSETS")
        logger.info("=" * 60)

        assets_validated = {}
        assets_info = []

        for cov_name, cov_config in COVARIATES.items():
            asset_id = cov_config["asset"]
            try:
                info = validate_gee_asset(asset_id, logger)
                assets_validated[cov_name] = True
                assets_info.append({
                    "covariate": cov_name,
                    "asset": asset_id,
                    "type": info["type"],
                    "bands": ", ".join(info["bands"][:5]),
                    "accessible": True
                })
                logger.info(f"  [OK] {cov_name}: {asset_id}")
            except Exception as e:
                assets_validated[cov_name] = False
                assets_info.append({
                    "covariate": cov_name,
                    "asset": asset_id,
                    "type": "Unknown",
                    "bands": "",
                    "accessible": False
                })
                logger.warning(f"  [FAIL] {cov_name}: {e}")

        # Save asset validation results
        tables_dir = get_path("tables", base_dir)
        ensure_dir(tables_dir)

        assets_df = pd.DataFrame(assets_info)
        assets_path = tables_dir / "covariate_assets_validation.csv"
        save_dataframe(assets_df, assets_path, overwrite=args.overwrite)
        logger.info(f"Saved asset validation: {assets_path}")

        # Prepare all covariates
        logger.info("\n" + "=" * 60)
        logger.info("PREPARING COVARIATE DATASETS")
        logger.info("=" * 60)

        covariates_prepared = {}

        if assets_validated.get("human_modification"):
            covariates_prepared["human_modification"] = prepare_human_modification(bhutan_geom, logger)

        if assets_validated.get("hansen_forest"):
            covariates_prepared["hansen_forest"] = prepare_hansen_forest_change(bhutan_geom, logger)

        # IMPORTANT: keep key name consistent with CONFIG (ndvi_modis)
        if assets_validated.get("ndvi_modis"):
            covariates_prepared["ndvi_modis"] = prepare_ndvi_trend(bhutan_geom, logger)

        if assets_validated.get("burned_area"):
            covariates_prepared["burned_area"] = prepare_burned_area(bhutan_geom, logger)

        if assets_validated.get("worldcover"):
            covariates_prepared["worldcover"] = prepare_worldcover(bhutan_geom, logger)

        if assets_validated.get("elevation"):
            covariates_prepared["elevation"] = prepare_elevation(bhutan_geom, logger)

        # Create combined covariate image
        logger.info("\n" + "=" * 60)
        logger.info("CREATING COMBINED COVARIATE IMAGE")
        logger.info("=" * 60)

        covariate_names = list(covariates_prepared.keys())
        if len(covariate_names) == 0:
            raise ValueError("No covariates could be prepared")

        combined = covariates_prepared[covariate_names[0]]
        for name in covariate_names[1:]:
            combined = combined.addBands(covariates_prepared[name])

        combined_bands = combined.bandNames().getInfo()
        logger.info(f"Combined covariate image has {len(combined_bands)} bands:")
        for band in combined_bands:
            logger.info(f"  - {band}")

        # Save covariate manifest
        manifest = {
            "script": SCRIPT_NAME,
            "version": __version__,
            "timestamp": datetime.now().isoformat(),
            "covariates_prepared": covariate_names,
            "combined_bands": combined_bands,
            "assets_used": {
                name: COVARIATES[name]["asset"]
                for name in covariate_names
            }
        }

        repro_dir = get_path("reproducibility", base_dir)
        ensure_dir(repro_dir)

        manifest_path = repro_dir / "covariate_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"Saved covariate manifest: {manifest_path}")

        # Append to GEE assets log
        assets_log_path = repro_dir / "gee_assets_used.txt"
        with open(assets_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n# Covariates (added {datetime.now().isoformat()})\n")
            for name, config in COVARIATES.items():
                f.write(f"{name}: {config['asset']}\n")
        logger.info(f"Appended to GEE assets log: {assets_log_path}")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        n_validated = sum(1 for v in assets_validated.values() if v)
        checks = {
            "GEE authentication successful": True,
            f"Assets validated ({n_validated}/{len(COVARIATES)})": n_validated >= 5,
            "Human Modification accessible": assets_validated.get("human_modification", False),
            "Hansen Forest Change accessible": assets_validated.get("hansen_forest", False),
            "NDVI MODIS accessible": assets_validated.get("ndvi_modis", False),
            "Burned Area accessible": assets_validated.get("burned_area", False),
            "WorldCover accessible": assets_validated.get("worldcover", False),
            "Elevation accessible": assets_validated.get("elevation", False),
            "Combined image created": len(combined_bands) > 0,
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
        logger.info("COVARIATE PREPARATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Covariates prepared: {len(covariate_names)}")
        logger.info(f"Combined bands: {len(combined_bands)}")
        logger.info("Ready for 13_covariates_zonal_stats.py")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
