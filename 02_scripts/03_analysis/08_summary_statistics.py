#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
08_summary_statistics.py
Compute network-wide summary statistics for Bhutan's PA network.

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

import pandas as pd
import numpy as np

from _shared.config import CONFIG, get_path
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import ensure_dir, save_dataframe, write_success_marker
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "08_summary_statistics"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compute network-wide summary statistics"
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
        help="Not used"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Include sensitivity analysis in summary"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Not used"
    )
    return parser.parse_args()


def load_eii_stats(base_dir, logger):
    """Load EII statistics."""
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_eii_stats.csv"

    if not stats_path.exists():
        raise FileNotFoundError(f"EII stats file not found: {stats_path}")

    logger.info(f"Loading EII stats from: {stats_path}")
    return pd.read_csv(stats_path)


def load_component_stats(base_dir, logger):
    """Load component statistics."""
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_component_stats.csv"

    if not stats_path.exists():
        logger.warning("Component stats not found")
        return None

    return pd.read_csv(stats_path)


def compute_network_summary(eii_df, logger):
    """
    Compute network-wide EII summary statistics.

    Args:
        eii_df: DataFrame with PA-level EII stats
        logger: Logger instance

    Returns:
        Dictionary of summary statistics
    """
    logger.info("Computing network-wide summary statistics...")

    # Basic counts
    n_pas = len(eii_df)
    total_area = eii_df['Area_km2'].sum()
    total_pixels = eii_df['pixel_count'].sum()

    # EII statistics (simple average across PAs)
    eii_mean = eii_df['eii_mean'].mean()
    eii_std = eii_df['eii_mean'].std()
    eii_min = eii_df['eii_mean'].min()
    eii_max = eii_df['eii_mean'].max()
    eii_median = eii_df['eii_mean'].median()

    # Area-weighted EII mean
    eii_weighted = np.average(eii_df['eii_mean'], weights=eii_df['Area_km2'])

    # Pixel-weighted EII mean (more accurate for heterogeneous PA sizes)
    eii_pixel_weighted = np.average(eii_df['eii_mean'], weights=eii_df['pixel_count'])

    # Percentile stats
    eii_p5 = eii_df['eii_mean'].quantile(0.05)
    eii_p25 = eii_df['eii_mean'].quantile(0.25)
    eii_p75 = eii_df['eii_mean'].quantile(0.75)
    eii_p95 = eii_df['eii_mean'].quantile(0.95)

    # Top and bottom PAs
    top_pa = eii_df.loc[eii_df['eii_mean'].idxmax()]
    bottom_pa = eii_df.loc[eii_df['eii_mean'].idxmin()]

    summary = {
        'Network Statistics': {
            'Number of Protected Areas': n_pas,
            'Total Network Area (km²)': round(total_area, 2),
            'Total Analyzed Pixels': int(total_pixels),
            'Analysis Scale (m)': CONFIG['analysis_scale'],
        },
        'EII Summary (PA-level means)': {
            'Simple Mean': round(eii_mean, 4),
            'Area-Weighted Mean': round(eii_weighted, 4),
            'Pixel-Weighted Mean': round(eii_pixel_weighted, 4),
            'Standard Deviation': round(eii_std, 4),
            'Minimum': round(eii_min, 4),
            'Maximum': round(eii_max, 4),
            'Median': round(eii_median, 4),
            'P5': round(eii_p5, 4),
            'P25': round(eii_p25, 4),
            'P75': round(eii_p75, 4),
            'P95': round(eii_p95, 4),
            'Range': round(eii_max - eii_min, 4),
            'IQR': round(eii_p75 - eii_p25, 4),
        },
        'Top Performing PA': {
            'PA Code': top_pa['PA_name'],
            'Category': top_pa['park'],
            'EII Mean': round(top_pa['eii_mean'], 4),
            'Area (km²)': round(top_pa['Area_km2'], 2),
        },
        'Lowest Performing PA': {
            'PA Code': bottom_pa['PA_name'],
            'Category': bottom_pa['park'],
            'EII Mean': round(bottom_pa['eii_mean'], 4),
            'Area (km²)': round(bottom_pa['Area_km2'], 2),
        },
    }

    logger.info(f"Network EII Mean: {eii_mean:.4f}")
    logger.info(f"Area-Weighted Mean: {eii_weighted:.4f}")

    return summary


def compute_component_summary(component_df, logger):
    """
    Compute network-wide component summary.

    Args:
        component_df: DataFrame with component stats
        logger: Logger instance

    Returns:
        Dictionary of component summaries
    """
    if component_df is None:
        return None

    logger.info("Computing component summary statistics...")

    summary = {}

    for band in CONFIG["eii_component_bands"]:
        band_data = component_df[component_df['band'] == band]
        if len(band_data) == 0:
            continue

        short_name = band.replace('_integrity', '').title()

        summary[short_name] = {
            'Mean': round(band_data['mean'].mean(), 4),
            'SD': round(band_data['mean'].std(), 4),
            'Min': round(band_data['mean'].min(), 4),
            'Max': round(band_data['mean'].max(), 4),
            'Median': round(band_data['mean'].median(), 4),
        }

    return summary


def create_summary_table(summary_dict, logger):
    """
    Convert summary dictionary to a flat table.

    Handles up to two levels of nesting:
      section -> metric -> scalar          (normal case)
      section -> component -> stat -> scalar  (Component Summary case)

    Args:
        summary_dict: Nested dictionary of summary stats
        logger: Logger instance

    Returns:
        DataFrame suitable for CSV export
    """
    rows = []

    for section, values in summary_dict.items():
        if isinstance(values, dict):
            for metric, value in values.items():
                if isinstance(value, dict):
                    # Doubly-nested: e.g. Component Summary -> Functional -> Mean/SD/...
                    for sub_metric, sub_value in value.items():
                        rows.append({
                            'Section': section,
                            'Metric': f'{metric} {sub_metric}',
                            'Value': float(sub_value),
                        })
                else:
                    rows.append({
                        'Section': section,
                        'Metric': metric,
                        'Value': value,
                    })
        else:
            rows.append({
                'Section': 'General',
                'Metric': section,
                'Value': values,
            })

    return pd.DataFrame(rows)


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

    try:
        # Load data
        eii_df = load_eii_stats(base_dir, logger)
        component_df = load_component_stats(base_dir, logger)

        # Validate PA count
        expected = CONFIG["expected_pa_count"]
        actual = len(eii_df)
        if actual != expected and not args.allow_pa_count_mismatch:
            raise ValueError(
                f"PA count mismatch: expected {expected}, found {actual}. "
                f"Use --allow-pa-count-mismatch to override."
            )

        # Compute summaries
        network_summary = compute_network_summary(eii_df, logger)

        if component_df is not None:
            component_summary = compute_component_summary(component_df, logger)
            if component_summary:
                network_summary['Component Summary'] = component_summary

        # Output paths
        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        # Save as CSV (flat table)
        summary_table = create_summary_table(network_summary, logger)
        csv_path = results_tables / "bhutan_network_summary.csv"
        save_dataframe(summary_table, csv_path, overwrite=args.overwrite)
        logger.info(f"Saved summary table: {csv_path}")

        # Save as JSON (structured)
        json_path = results_tables / "bhutan_network_summary.json"
        with open(json_path, 'w') as f:
            json.dump(network_summary, f, indent=2)
        logger.info(f"Saved JSON summary: {json_path}")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("BHUTAN PA NETWORK SUMMARY")
        logger.info("=" * 60)

        for section, values in network_summary.items():
            logger.info(f"\n{section}:")
            if isinstance(values, dict):
                for metric, value in values.items():
                    if isinstance(value, dict):
                        logger.info(f"  {metric}:")
                        for k, v in value.items():
                            logger.info(f"    {k}: {v}")
                    else:
                        logger.info(f"  {metric}: {value}")
            else:
                logger.info(f"  {values}")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "EII stats loaded": len(eii_df) > 0,
            "Network summary computed": len(network_summary) > 0,
            "CSV output created": csv_path.exists(),
            "JSON output created": json_path.exists(),
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
        logger.info("SUMMARY STATISTICS COMPLETE")
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
