#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
16_validation.py
Empirical validation of EII against independent datasets.

Validation approaches:
1. Preferred: GEDI canopy height vs structural integrity
2. Fallback: NDVI trend + forest loss vs functional integrity

This script validates EII components against independent remote sensing
products to assess ecological validity.

Outputs:
- 03_results/tables/table7_validation.csv
- 03_results/figures/fig7_validation_scatter.png

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
import matplotlib.pyplot as plt
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

SCRIPT_NAME = "16_validation"

# EII asset
EII_ASSET = CONFIG["gee_eii_asset"]

# Validation datasets
GEDI_CONFIG = CONFIG["gee_validation"]["gedi_canopy"]
COVARIATES = CONFIG["gee_covariates"]

# Analysis parameters
SCALE = CONFIG["analysis_scale"]
FIGURE_DPI = CONFIG["figure_dpi"]
EE_TRANSFER_SIMPLIFY_TOLERANCE_M = 90
EE_BATCH_SIZE = 4


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate EII against independent datasets"
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
        "--force-fallback",
        action="store_true",
        help="Use fallback validation (NDVI/forest loss) even if GEDI available"
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


def check_gedi_availability(bhutan_geom, logger):
    """
    Check if GEDI data is available for Bhutan.

    Args:
        bhutan_geom: ee.Geometry for Bhutan
        logger: Logger instance

    Returns:
        bool: True if GEDI data available
    """
    logger.info("Checking GEDI data availability...")

    try:
        gedi = (
            ee.ImageCollection(GEDI_CONFIG["asset"])
            .filterBounds(bhutan_geom)
            .filterDate(GEDI_CONFIG["date_range"][0], GEDI_CONFIG["date_range"][1])
            .select(GEDI_CONFIG["band"])
        )

        count = gedi.size().getInfo()
        logger.info(f"GEDI images available: {count}")

        if count > 0:
            # Check if there's actual data in Bhutan
            sample = gedi.first().reduceRegion(
                reducer=ee.Reducer.count(),
                geometry=bhutan_geom,
                scale=1000,
                maxPixels=1e7
            ).getInfo()

            pixel_count = sample.get(GEDI_CONFIG["band"], 0)
            logger.info(f"GEDI pixels in Bhutan: {pixel_count}")

            return pixel_count > 100  # Require minimum data
        return False

    except Exception as e:
        logger.warning(f"Error checking GEDI: {e}")
        return False


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
def compute_gedi_validation(eii_image, bhutan_geom, pa_gdf_ee, logger):
    """
    Compute GEDI canopy height vs structural integrity.

    Args:
        eii_image: ee.Image with EII bands
        bhutan_geom: ee.Geometry for Bhutan
        pa_gdf_ee: Simplified WGS84 PA GeoDataFrame
        logger: Logger instance

    Returns:
        DataFrame with validation metrics per PA
    """
    logger.info("\n" + "=" * 60)
    logger.info("GEDI VALIDATION: Canopy Height vs Structural Integrity")
    logger.info("=" * 60)

    # Load GEDI data
    gedi = (
        ee.ImageCollection(GEDI_CONFIG["asset"])
        .filterBounds(bhutan_geom)
        .filterDate(GEDI_CONFIG["date_range"][0], GEDI_CONFIG["date_range"][1])
        .select(GEDI_CONFIG["band"])
    )

    # Compute mean canopy height
    canopy_height = gedi.mean().rename("canopy_height")

    # Combine with EII structural integrity
    structural = eii_image.select("structural_integrity")
    combined = canopy_height.addBands(structural)

    # Compute zonal stats per PA
    reducers = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True)

    stats_list = []
    batches = list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE))
    for batch_idx, batch_gdf in enumerate(batches, start=1):
        logger.info(f"GEDI batch {batch_idx}/{len(batches)} ({len(batch_gdf)} PAs)...")
        pa_fc = gdf_to_ee_featurecollection(
            batch_gdf,
            CONFIG["pa_name_field"],
            CONFIG["pa_category_field"],
            CONFIG["pa_area_field"]
        )
        results = combined.reduceRegions(
            collection=pa_fc,
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
                'validation_type': 'GEDI',
                'validation_metric': 'canopy_height',
                'eii_component': 'structural_integrity',
                'validation_value': props.get('canopy_height_mean'),
                'validation_stddev': props.get('canopy_height_stdDev'),
                'eii_value': props.get('structural_integrity_mean'),
                'eii_stddev': props.get('structural_integrity_stdDev'),
            }
            stats_list.append(stats)

    logger.info(f"GEDI validation computed for {len(stats_list)} PAs")
    return pd.DataFrame(stats_list)


@retry_with_backoff(max_retries=CONFIG["max_retries"], delay=CONFIG["retry_delay_seconds"])
def compute_fallback_validation(eii_image, bhutan_geom, pa_gdf_ee, logger):
    """
    Compute fallback validation using NDVI trend and forest loss.

    Args:
        eii_image: ee.Image with EII bands
        bhutan_geom: ee.Geometry for Bhutan
        pa_gdf_ee: Simplified WGS84 PA GeoDataFrame
        logger: Logger instance

    Returns:
        DataFrame with validation metrics per PA
    """
    logger.info("\n" + "=" * 60)
    logger.info("FALLBACK VALIDATION: NDVI Trend & Forest Loss vs Functional")
    logger.info("=" * 60)

    # NDVI trend
    ndvi_config = COVARIATES["ndvi_modis"]
    date_range = ndvi_config["date_range"]

    ndvi_collection = (
        ee.ImageCollection(ndvi_config["asset"])
        .filterDate(date_range[0], date_range[1])
        .filterBounds(bhutan_geom)
        .select(ndvi_config["band"])
    )

    scale_factor = ndvi_config.get("scale_factor", 0.0001)

    def add_time(img):
        date = ee.Date(img.get("system:time_start"))
        years = date.difference(ee.Date(date_range[0]), "year")
        return img.multiply(scale_factor).addBands(ee.Image(years).rename("t").float())

    ndvi_with_time = ndvi_collection.map(add_time)
    trend = ndvi_with_time.select(["t", "NDVI"]).reduce(ee.Reducer.linearFit())
    ndvi_trend = trend.select("scale").rename("ndvi_trend")

    # Forest loss
    hansen_config = COVARIATES["hansen_forest"]
    hansen = ee.Image(hansen_config["asset"])
    forest_loss = hansen.select("loss").rename("forest_loss")

    # Functional integrity
    functional = eii_image.select("functional_integrity")

    # Combine
    combined = (
        ndvi_trend
        .addBands(forest_loss)
        .addBands(functional)
    ).clip(bhutan_geom)

    # Compute zonal stats
    reducers = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True)

    stats_list = []
    batches = list(iter_gdf_batches(pa_gdf_ee, EE_BATCH_SIZE))
    for batch_idx, batch_gdf in enumerate(batches, start=1):
        logger.info(f"Fallback validation batch {batch_idx}/{len(batches)} ({len(batch_gdf)} PAs)...")
        pa_fc = gdf_to_ee_featurecollection(
            batch_gdf,
            CONFIG["pa_name_field"],
            CONFIG["pa_category_field"],
            CONFIG["pa_area_field"]
        )
        results = combined.reduceRegions(
            collection=pa_fc,
            reducer=reducers,
            scale=SCALE,
            crs='EPSG:4326'
        )
        result_info = results.getInfo()

        for feature in result_info['features']:
            props = feature['properties']
            stats_list.append({
                'PA_name': props.get(CONFIG["pa_name_field"]),
                'park': props.get(CONFIG["pa_category_field"]),
                'validation_type': 'fallback',
                'validation_metric': 'ndvi_trend',
                'eii_component': 'functional_integrity',
                'validation_value': props.get('ndvi_trend_mean'),
                'validation_stddev': props.get('ndvi_trend_stdDev'),
                'eii_value': props.get('functional_integrity_mean'),
                'eii_stddev': props.get('functional_integrity_stdDev'),
            })

            stats_list.append({
                'PA_name': props.get(CONFIG["pa_name_field"]),
                'park': props.get(CONFIG["pa_category_field"]),
                'validation_type': 'fallback',
                'validation_metric': 'forest_loss_inverse',
                'eii_component': 'functional_integrity',
                'validation_value': 1.0 - (props.get('forest_loss_mean') or 0),
                'validation_stddev': props.get('forest_loss_stdDev'),
                'eii_value': props.get('functional_integrity_mean'),
                'eii_stddev': props.get('functional_integrity_stdDev'),
            })

    logger.info(f"Fallback validation computed for {len(stats_list)//2} PAs")
    return pd.DataFrame(stats_list)


def compute_validation_statistics(validation_df, logger):
    """
    Compute validation statistics (correlations, etc.).

    Args:
        validation_df: DataFrame with validation data
        logger: Logger instance

    Returns:
        DataFrame with validation statistics
    """
    logger.info("Computing validation statistics...")

    results = []

    for metric in validation_df['validation_metric'].unique():
        subset = validation_df[validation_df['validation_metric'] == metric].copy()
        subset = subset.dropna(subset=['validation_value', 'eii_value'])

        if len(subset) < 3:
            logger.warning(f"Insufficient data for {metric} validation")
            continue

        val_values = subset['validation_value'].values
        eii_values = subset['eii_value'].values

        # Pearson correlation
        pearson_r, pearson_p = scipy_stats.pearsonr(val_values, eii_values)

        # Spearman correlation
        spearman_rho, spearman_p = scipy_stats.spearmanr(val_values, eii_values)

        # R-squared
        r_squared = pearson_r ** 2

        # RMSE (normalized by EII range)
        eii_range = eii_values.max() - eii_values.min()
        if eii_range > 0:
            # Normalize validation to same scale as EII for comparison
            val_norm = (val_values - val_values.min()) / (val_values.max() - val_values.min())
            val_scaled = val_norm * eii_range + eii_values.min()
            rmse = np.sqrt(np.mean((val_scaled - eii_values) ** 2))
            nrmse = rmse / eii_range
        else:
            rmse = np.nan
            nrmse = np.nan

        results.append({
            'validation_metric': metric,
            'eii_component': subset['eii_component'].iloc[0],
            'n_observations': len(subset),
            'pearson_r': pearson_r,
            'pearson_p': pearson_p,
            'spearman_rho': spearman_rho,
            'spearman_p': spearman_p,
            'r_squared': r_squared,
            'rmse': rmse,
            'nrmse': nrmse,
            'pearson_sig': pearson_p < 0.05,
            'spearman_sig': spearman_p < 0.05,
        })

    return pd.DataFrame(results)


def create_validation_figure(validation_df, stats_df, output_path, logger):
    """
    Create validation scatter plot.

    Args:
        validation_df: Raw validation data
        stats_df: Validation statistics
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating validation scatter plot...")

    metrics = validation_df['validation_metric'].unique()
    n_metrics = len(metrics)

    if n_metrics == 0:
        logger.warning("No validation metrics to plot")
        return

    # Create subplots
    fig, axes = plt.subplots(1, min(n_metrics, 3), figsize=(5 * min(n_metrics, 3), 5))
    if n_metrics == 1:
        axes = [axes]

    for i, (ax, metric) in enumerate(zip(axes, metrics[:3])):
        subset = validation_df[validation_df['validation_metric'] == metric].dropna(
            subset=['validation_value', 'eii_value']
        )

        if len(subset) == 0:
            continue

        # Get stats for this metric
        metric_stats = stats_df[stats_df['validation_metric'] == metric]
        if len(metric_stats) > 0:
            r_val = metric_stats.iloc[0]['pearson_r']
            p_val = metric_stats.iloc[0]['pearson_p']
        else:
            r_val = np.nan
            p_val = np.nan

        # Color by PA category
        categories = subset['park'].unique()
        colors = plt.cm.Set2(np.linspace(0, 1, len(categories)))
        color_map = dict(zip(categories, colors))

        # Scatter plot
        for cat in categories:
            cat_data = subset[subset['park'] == cat]
            ax.scatter(
                cat_data['validation_value'],
                cat_data['eii_value'],
                c=[color_map[cat]],
                label=cat,
                s=80,
                alpha=0.7,
                edgecolors='black',
                linewidth=0.5
            )

        # Add trend line
        x = subset['validation_value'].values
        y = subset['eii_value'].values
        z = np.polyfit(x, y, 1)
        p = np.poly1d(z)
        x_line = np.linspace(x.min(), x.max(), 100)
        ax.plot(x_line, p(x_line), 'r--', linewidth=1.5, alpha=0.7)

        # Labels
        ax.set_xlabel(metric.replace('_', ' ').title(), fontsize=10)
        ax.set_ylabel('EII Component', fontsize=10)

        sig_marker = "*" if p_val < 0.05 else ""
        ax.set_title(f'r = {r_val:.3f}{sig_marker}', fontsize=11)

        ax.grid(alpha=0.3)

    # Overall title
    fig.suptitle(
        'EII Validation: EII Components vs Independent Metrics',
        fontsize=12,
        fontweight='bold',
        y=1.02
    )

    # Legend
    if n_metrics > 0:
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(
            handles, labels,
            loc='lower center',
            ncol=min(len(categories), 5),
            bbox_to_anchor=(0.5, -0.1),
            fontsize=8
        )

    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def create_publication_table(validation_df, stats_df, logger):
    """
    Create publication-ready Table 7.

    Args:
        validation_df: Raw validation data
        stats_df: Validation statistics
        logger: Logger instance

    Returns:
        Formatted DataFrame
    """
    logger.info("Creating publication Table 7...")

    # Combine raw stats summary with validation metrics
    table7 = stats_df.copy()

    # Rename columns
    rename_map = {
        'validation_metric': 'Validation Metric',
        'eii_component': 'EII Component',
        'n_observations': 'N',
        'pearson_r': 'Pearson r',
        'pearson_p': 'Pearson p',
        'spearman_rho': 'Spearman rho',
        'spearman_p': 'Spearman p',
        'r_squared': 'R-squared',
        'nrmse': 'NRMSE',
        'pearson_sig': 'Sig.',
    }

    # Select and rename columns
    cols_to_keep = [c for c in rename_map.keys() if c in table7.columns]
    table7 = table7[cols_to_keep].rename(columns=rename_map)

    # Round numeric columns
    for col in ['Pearson r', 'Pearson p', 'Spearman rho', 'Spearman p', 'R-squared', 'NRMSE']:
        if col in table7.columns:
            table7[col] = table7[col].round(4)

    return table7


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
        logger.info(f"Loaded {len(pa_gdf)} Protected Areas")

        # Load Bhutan boundary
        bhutan_gdf = load_bhutan_boundary(base_dir)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs("EPSG:4326")
        bhutan_geom = geometry_to_ee(bhutan_gdf.unary_union)

        # Load EII image
        logger.info(f"Loading EII asset: {EII_ASSET}")
        eii_image = ee.Image(EII_ASSET)

        pa_gdf_ee = prepare_gdf_for_ee(pa_gdf, tolerance_m=EE_TRANSFER_SIMPLIFY_TOLERANCE_M)

        # Check GEDI availability
        use_gedi = False
        if not args.force_fallback:
            use_gedi = check_gedi_availability(bhutan_geom, logger)

        # Run appropriate validation
        if use_gedi:
            logger.info("Using GEDI validation (preferred)")
            validation_df = compute_gedi_validation(eii_image, bhutan_geom, pa_gdf_ee, logger)
        else:
            logger.info("Using fallback validation (NDVI trend + forest loss)")
            validation_df = compute_fallback_validation(eii_image, bhutan_geom, pa_gdf_ee, logger)

        # Compute validation statistics
        stats_df = compute_validation_statistics(validation_df, logger)

        # Output paths
        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        figures_dir = get_path("figures", base_dir)
        ensure_dir(figures_dir)

        # Save raw validation data
        tables_dir = get_path("tables", base_dir)
        ensure_dir(tables_dir)

        raw_path = tables_dir / "validation_raw_data.csv"
        save_dataframe(validation_df, raw_path, overwrite=args.overwrite)
        logger.info(f"Saved raw validation data: {raw_path}")

        # Create and save publication table
        table7 = create_publication_table(validation_df, stats_df, logger)
        table7_path = results_tables / "table7_validation.csv"
        save_dataframe(table7, table7_path, overwrite=args.overwrite)
        logger.info(f"Saved Table 7: {table7_path}")

        # Create validation figure
        fig7_path = figures_dir / "fig7_validation_scatter.png"
        create_validation_figure(validation_df, stats_df, fig7_path, logger)

        # Log validation summary
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 60)

        for _, row in stats_df.iterrows():
            sig = "*" if row.get('pearson_sig', False) else ""
            logger.info(
                f"  {row['validation_metric']}: "
                f"r={row['pearson_r']:.3f}{sig}, "
                f"R²={row['r_squared']:.3f}"
            )

        # Append to GEE assets log
        repro_dir = get_path("reproducibility", base_dir)
        ensure_dir(repro_dir)

        assets_log_path = repro_dir / "gee_assets_used.txt"
        with open(assets_log_path, 'a') as f:
            f.write(f"\n# Validation (added {datetime.now().isoformat()})\n")
            if use_gedi:
                f.write(f"GEDI: {GEDI_CONFIG['asset']}\n")
            else:
                f.write(f"NDVI: {COVARIATES['ndvi_modis']['asset']}\n")
                f.write(f"Hansen: {COVARIATES['hansen_forest']['asset']}\n")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "GEE authentication successful": True,
            f"PA count validated ({len(pa_gdf)})": len(pa_gdf) == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
            "Validation data computed": len(validation_df) > 0,
            "Validation statistics computed": len(stats_df) > 0,
            "Table 7 created": table7_path.exists(),
            "Figure 7 created": fig7_path.exists(),
            "At least one significant correlation": stats_df['pearson_sig'].any() if 'pearson_sig' in stats_df.columns else False,
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
        logger.info("VALIDATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Validation type: {'GEDI' if use_gedi else 'Fallback'}")
        logger.info(f"PAs validated: {validation_df['PA_name'].nunique()}")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
