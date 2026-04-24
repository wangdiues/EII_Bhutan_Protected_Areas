#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
13_covariates_zonal_stats.py
Compute per-PA zonal statistics for covariates and EII-covariate concordance.

This script:
1. Computes zonal statistics for all covariates per PA
2. Creates concordance table comparing EII with each covariate
3. Includes Pearson r, Spearman rho, and rank differences

Outputs:
- 01_data/03_tables/pa_covariates_stats.csv
- 03_results/tables/table5_covariates_summary.csv
- 03_results/tables/table5b_eii_covariate_concordance.csv

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
from scipy import stats as scipy_stats

from _shared.config import CONFIG, get_path, validate_paths
from _shared.gee_utils import authenticate_gee, geometry_to_ee, iter_gdf_batches, prepare_gdf_for_ee
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

SCRIPT_NAME = "13_covariates_zonal_stats"
COVARIATES = CONFIG["gee_covariates"]
SCALE = CONFIG["analysis_scale"]
EE_TRANSFER_SIMPLIFY_TOLERANCE_M = 90
EE_BATCH_SIZE = 4


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compute covariate zonal statistics and EII concordance"
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


def prepare_covariate_image(bhutan_geom, logger):
    """
    Prepare combined covariate image.

    Args:
        bhutan_geom: ee.Geometry for Bhutan
        logger: Logger instance

    Returns:
        ee.Image with all covariate bands
    """
    logger.info("Preparing covariate image...")

    bands_created = []

    # Human Modification Index
    # CSP/HM/GlobalHumanModification is an ImageCollection, not an Image
    hm_config = COVARIATES["human_modification"]
    hmi = ee.ImageCollection(hm_config["asset"]).mosaic().select(hm_config["band"]).rename("hmi")
    bands_created.append("hmi")

    # Hansen Forest Change
    hansen_config = COVARIATES["hansen_forest"]
    hansen = ee.Image(hansen_config["asset"])
    treecover2000 = hansen.select("treecover2000").rename("treecover2000")
    forest_loss = hansen.select("loss").rename("forest_loss")
    bands_created.extend(["treecover2000", "forest_loss"])

    # NDVI trend (compute from collection)
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

    # Compute NDVI trend
    def add_time(img):
        date = ee.Date(img.get("system:time_start"))
        years = date.difference(ee.Date(date_range[0]), "year")
        return img.addBands(ee.Image(years).rename("t").float())

    ndvi_with_time = ndvi_scaled.map(add_time)
    trend = ndvi_with_time.select(["t", "NDVI"]).reduce(ee.Reducer.linearFit())
    ndvi_trend = trend.select("scale").rename("ndvi_trend")
    bands_created.extend(["ndvi_mean", "ndvi_trend"])

    # Burned area frequency
    ba_config = COVARIATES["burned_area"]
    ba_date_range = ba_config["date_range"]

    ba_collection = (
        ee.ImageCollection(ba_config["asset"])
        .filterDate(ba_date_range[0], ba_date_range[1])
        .filterBounds(bhutan_geom)
        .select(ba_config["band"])
    )

    def has_burn(img):
        return img.gt(0).unmask(0)

    fire_frequency = ba_collection.map(has_burn).sum().rename("fire_frequency")
    bands_created.append("fire_frequency")

    # WorldCover fractions
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
    bands_created.extend(["cropland", "built_up"])

    # Elevation
    elev_config = COVARIATES["elevation"]
    elevation = ee.Image(elev_config["asset"]).select(elev_config["band"]).rename("elevation")
    bands_created.append("elevation")

    # Combine all bands
    combined = (
        hmi
        .addBands(treecover2000)
        .addBands(forest_loss)
        .addBands(ndvi_mean)
        .addBands(ndvi_trend)
        .addBands(fire_frequency)
        .addBands(cropland)
        .addBands(built_up)
        .addBands(elevation)
    ).clip(bhutan_geom)

    logger.info(f"Covariate image prepared with bands: {bands_created}")
    return combined, bands_created


def gdf_to_ee_featurecollection(gdf, id_field, category_field, area_field):
    """Convert GeoDataFrame to Earth Engine FeatureCollection."""
    features = []
    for idx, row in gdf.iterrows():
        props = {
            id_field: row[id_field],
            category_field: row[category_field],
            area_field: row.get(area_field, 0)
        }
        ee_geom = geometry_to_ee(row.geometry)
        feature = ee.Feature(ee_geom, props)
        features.append(feature)

    return ee.FeatureCollection(features)


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def compute_covariate_zonal_stats(covariate_image, bands, pa_gdf_ee, logger):
    """
    Compute zonal statistics for covariates.

    Args:
        covariate_image: ee.Image with covariate bands
        bands: List of band names
        pa_gdf_ee: Simplified WGS84 PA GeoDataFrame
        logger: Logger instance

    Returns:
        List of dictionaries with statistics
    """
    logger.info("Computing covariate zonal statistics...")

    # Define reducers (mean, stdDev, count)
    reducers = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )

    stats_list = []
    batches = list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE))
    for batch_idx, batch_gdf in enumerate(batches, start=1):
        logger.info(f"Covariate batch {batch_idx}/{len(batches)} ({len(batch_gdf)} PAs)...")
        regions = gdf_to_ee_featurecollection(
            batch_gdf,
            CONFIG["pa_name_field"],
            CONFIG["pa_category_field"],
            CONFIG["pa_area_field"]
        )
        results = covariate_image.reduceRegions(
            collection=regions,
            reducer=reducers,
            scale=SCALE,
            crs='EPSG:4326'
        )
        result_info = results.getInfo()

        for feature in result_info['features']:
            props = feature['properties']
            stats = {
                'PA_name': props.get(CONFIG["pa_name_field"]),
                'park': props.get(CONFIG["pa_category_field"]),
                'Area_km2': props.get(CONFIG["pa_area_field"]),
            }

            for band in bands:
                stats[f"{band}_mean"] = props.get(f"{band}_mean")
                stats[f"{band}_stdDev"] = props.get(f"{band}_stdDev")
                stats[f"{band}_count"] = props.get(f"{band}_count")

            stats_list.append(stats)

    logger.info(f"Computed stats for {len(stats_list)} regions")
    return stats_list


def compute_concordance(eii_df, covariate_df, logger):
    """
    Compute concordance between EII and covariates.

    Args:
        eii_df: DataFrame with EII stats
        covariate_df: DataFrame with covariate stats
        logger: Logger instance

    Returns:
        DataFrame with concordance metrics
    """
    logger.info("Computing EII-covariate concordance...")

    # Merge on PA_name
    merged = eii_df[['PA_name', 'eii_mean']].merge(
        covariate_df,
        on='PA_name'
    )

    concordance_results = []

    # Covariate columns to analyze
    covariate_cols = [c for c in covariate_df.columns if c.endswith('_mean') and c != 'PA_name']

    for cov_col in covariate_cols:
        cov_name = cov_col.replace('_mean', '')

        # Get valid pairs
        valid_mask = merged['eii_mean'].notna() & merged[cov_col].notna()
        eii_values = merged.loc[valid_mask, 'eii_mean'].values
        cov_values = merged.loc[valid_mask, cov_col].values

        if len(eii_values) < 3:
            logger.warning(f"Insufficient data for {cov_name} concordance")
            continue

        # Pearson correlation
        pearson_r, pearson_p = scipy_stats.pearsonr(eii_values, cov_values)

        # Spearman correlation
        spearman_rho, spearman_p = scipy_stats.spearmanr(eii_values, cov_values)

        # Rank difference
        eii_ranks = scipy_stats.rankdata(eii_values)
        cov_ranks = scipy_stats.rankdata(cov_values)
        mean_rank_diff = np.mean(np.abs(eii_ranks - cov_ranks))
        max_rank_diff = np.max(np.abs(eii_ranks - cov_ranks))

        concordance_results.append({
            'covariate': cov_name,
            'n_valid': len(eii_values),
            'pearson_r': pearson_r,
            'pearson_p': pearson_p,
            'spearman_rho': spearman_rho,
            'spearman_p': spearman_p,
            'mean_rank_diff': mean_rank_diff,
            'max_rank_diff': max_rank_diff,
        })

    concordance_df = pd.DataFrame(concordance_results)

    # Add significance flags
    concordance_df['pearson_sig'] = concordance_df['pearson_p'] < 0.05
    concordance_df['spearman_sig'] = concordance_df['spearman_p'] < 0.05

    logger.info(f"Concordance computed for {len(concordance_df)} covariates")
    return concordance_df


def create_publication_tables(covariate_df, concordance_df, logger):
    """
    Create publication-ready tables.

    Args:
        covariate_df: Raw covariate stats
        concordance_df: Concordance metrics
        logger: Logger instance

    Returns:
        tuple: (table5, table5b)
    """
    logger.info("Creating publication tables...")

    # Table 5: Covariate summary by PA
    mean_cols = [c for c in covariate_df.columns if c.endswith('_mean')]
    table5 = covariate_df[['PA_name', 'park'] + mean_cols].copy()

    # Rename columns
    rename_map = {'PA_name': 'PA Code', 'park': 'Category'}
    for col in mean_cols:
        clean_name = col.replace('_mean', '').replace('_', ' ').title()
        rename_map[col] = clean_name

    table5 = table5.rename(columns=rename_map)

    # Round numeric columns
    numeric_cols = [c for c in table5.columns if c not in ['PA Code', 'Category']]
    for col in numeric_cols:
        table5[col] = table5[col].round(4)

    # Table 5b: Concordance summary
    table5b = concordance_df.copy()

    # Rename columns for publication
    table5b_rename = {
        'covariate': 'Covariate',
        'n_valid': 'N',
        'pearson_r': 'Pearson r',
        'pearson_p': 'Pearson p',
        'spearman_rho': 'Spearman rho',
        'spearman_p': 'Spearman p',
        'mean_rank_diff': 'Mean Rank Diff',
        'max_rank_diff': 'Max Rank Diff',
        'pearson_sig': 'Pearson Sig.',
        'spearman_sig': 'Spearman Sig.',
    }
    table5b = table5b.rename(columns=table5b_rename)

    # Round numeric columns
    for col in ['Pearson r', 'Pearson p', 'Spearman rho', 'Spearman p', 'Mean Rank Diff']:
        if col in table5b.columns:
            table5b[col] = table5b[col].round(4)

    # Sort by absolute Pearson r
    if 'Pearson r' in table5b.columns:
        table5b = table5b.sort_values('Pearson r', key=abs, ascending=False)

    return table5, table5b


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

        # Check for EII stats
        tables_dir = get_path("tables", base_dir)
        eii_stats_path = tables_dir / "pa_eii_stats.csv"
        if not eii_stats_path.exists():
            raise FileNotFoundError(
                f"EII stats not found: {eii_stats_path}\n"
                f"Run 03_download_eii.py first."
            )

        eii_df = pd.read_csv(eii_stats_path)
        logger.info(f"Loaded EII stats: {len(eii_df)} PAs")

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
        logger.info(f"Loaded {len(pa_gdf)} Protected Areas")

        # Load Bhutan boundary
        bhutan_gdf = load_bhutan_boundary(base_dir)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")
        bhutan_geom = geometry_to_ee(bhutan_gdf.unary_union)

        # Prepare covariate image
        covariate_image, bands = prepare_covariate_image(bhutan_geom, logger)

        pa_gdf_ee = prepare_gdf_for_ee(pa_gdf, tolerance_m=EE_TRANSFER_SIMPLIFY_TOLERANCE_M)

        # Compute zonal stats
        logger.info("\n" + "=" * 60)
        logger.info("COMPUTING COVARIATE ZONAL STATISTICS")
        logger.info("=" * 60)

        covariate_stats = compute_covariate_zonal_stats(
            covariate_image, bands, pa_gdf_ee, logger
        )
        covariate_df = pd.DataFrame(covariate_stats)

        # Save raw covariate stats
        ensure_dir(tables_dir)
        cov_path = tables_dir / "pa_covariates_stats.csv"
        save_dataframe(covariate_df, cov_path, overwrite=args.overwrite)
        logger.info(f"Saved covariate stats: {cov_path}")

        # Compute concordance
        logger.info("\n" + "=" * 60)
        logger.info("COMPUTING EII-COVARIATE CONCORDANCE")
        logger.info("=" * 60)

        concordance_df = compute_concordance(eii_df, covariate_df, logger)

        # Create publication tables
        table5, table5b = create_publication_tables(covariate_df, concordance_df, logger)

        # Save publication tables
        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        table5_path = results_tables / "table5_covariates_summary.csv"
        save_dataframe(table5, table5_path, overwrite=args.overwrite)
        logger.info(f"Saved Table 5: {table5_path}")

        table5b_path = results_tables / "table5b_eii_covariate_concordance.csv"
        save_dataframe(table5b, table5b_path, overwrite=args.overwrite)
        logger.info(f"Saved Table 5b: {table5b_path}")

        # Log concordance summary
        logger.info("\n" + "=" * 60)
        logger.info("CONCORDANCE SUMMARY")
        logger.info("=" * 60)

        for _, row in concordance_df.iterrows():
            sig_marker = "*" if row['pearson_sig'] else ""
            logger.info(
                f"  {row['covariate']}: r={row['pearson_r']:.3f}{sig_marker}, "
                f"rho={row['spearman_rho']:.3f}"
            )

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "GEE authentication successful": True,
            "EII stats loaded": len(eii_df) > 0,
            f"PA count validated ({len(pa_gdf)})": len(pa_gdf) == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
            "Covariate image prepared": len(bands) > 0,
            "Zonal stats computed": len(covariate_df) > 0,
            "Concordance computed": len(concordance_df) > 0,
            "Table 5 created": table5_path.exists(),
            "Table 5b created": table5b_path.exists(),
            "Output non-empty": len(covariate_df) > 0,
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
        logger.info("COVARIATE ZONAL STATS COMPLETE")
        logger.info("=" * 60)
        logger.info(f"PAs processed: {len(covariate_df)}")
        logger.info(f"Covariates analyzed: {len(bands)}")
        logger.info(f"Concordance metrics: {len(concordance_df)}")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
