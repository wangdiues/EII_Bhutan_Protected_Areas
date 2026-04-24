#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
06_pa_zonal_stats.py
Process and format PA-level EII zonal statistics for analysis and publication.

This script takes the raw zonal statistics from GEE and creates
publication-ready summary tables.

Version History:
    1.0.0 - Initial implementation
"""

__version__ = "1.0.0"

import argparse
import sys
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

SCRIPT_NAME = "06_pa_zonal_stats"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Process PA-level EII zonal statistics"
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
        help="Include sensitivity analysis columns"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Not used in this script"
    )
    return parser.parse_args()


def load_eii_stats(base_dir, logger):
    """
    Load EII statistics from downloaded CSV.

    Args:
        base_dir: Base directory
        logger: Logger instance

    Returns:
        pandas DataFrame
    """
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_eii_stats.csv"

    if not stats_path.exists():
        raise FileNotFoundError(
            f"EII stats file not found: {stats_path}\n"
            f"Run 03_download_eii.py first."
        )

    logger.info(f"Loading EII stats from: {stats_path}")
    df = pd.read_csv(stats_path)
    logger.info(f"Loaded {len(df)} rows")

    return df


def load_component_stats(base_dir, logger):
    """
    Load component statistics from downloaded CSV.

    Args:
        base_dir: Base directory
        logger: Logger instance

    Returns:
        pandas DataFrame
    """
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_component_stats.csv"

    if not stats_path.exists():
        raise FileNotFoundError(
            f"Component stats file not found: {stats_path}\n"
            f"Run 03_download_eii.py first."
        )

    logger.info(f"Loading component stats from: {stats_path}")
    df = pd.read_csv(stats_path)
    logger.info(f"Loaded {len(df)} rows")

    return df


def create_table1_pa_summary(eii_df, logger):
    """
    Create Table 1: PA-level EII summary.

    Args:
        eii_df: DataFrame with EII statistics
        logger: Logger instance

    Returns:
        pandas DataFrame formatted for publication
    """
    logger.info("Creating Table 1: PA EII Summary")

    # Select and rename columns
    table1 = eii_df[[
        'PA_name', 'park', 'Area_km2',
        'eii_mean', 'eii_stdDev', 'eii_p5', 'eii_p25',
        'eii_p50', 'eii_p75', 'eii_p95', 'pixel_count'
    ]].copy()

    # Rename columns for publication
    table1.columns = [
        'PA Code', 'Category', 'Area (km²)',
        'EII Mean', 'EII SD', 'EII P5', 'EII P25',
        'EII P50', 'EII P75', 'EII P95', 'Pixel Count'
    ]

    # Round numeric columns
    numeric_cols = ['EII Mean', 'EII SD', 'EII P5', 'EII P25',
                    'EII P50', 'EII P75', 'EII P95']
    for col in numeric_cols:
        table1[col] = table1[col].round(4)

    table1['Area (km²)'] = table1['Area (km²)'].round(2)

    # Sort by EII mean descending
    table1 = table1.sort_values('EII Mean', ascending=False).reset_index(drop=True)

    # Add rank
    table1.insert(0, 'Rank', range(1, len(table1) + 1))

    logger.info(f"Table 1 created with {len(table1)} rows")
    return table1


def create_table2_components(component_df, logger):
    """
    Create Table 2: Component integrity values by PA.

    Args:
        component_df: DataFrame with component statistics
        logger: Logger instance

    Returns:
        pandas DataFrame formatted for publication
    """
    logger.info("Creating Table 2: Components by PA")

    # Pivot from long to wide format
    component_pivot = component_df.pivot_table(
        index=['PA_name', 'park', 'Area_km2'],
        columns='band',
        values=['mean', 'stdDev'],
        aggfunc='first'
    ).reset_index()

    # Flatten column names
    component_pivot.columns = [
        '_'.join(col).strip('_') if isinstance(col, tuple) else col
        for col in component_pivot.columns
    ]

    # Rename columns
    rename_map = {
        'PA_name': 'PA Code',
        'park': 'Category',
        'Area_km2': 'Area (km²)',
    }

    for band in CONFIG["eii_component_bands"]:
        short_name = band.replace('_integrity', '')
        rename_map[f'mean_{band}'] = f'{short_name.title()} Mean'
        rename_map[f'stdDev_{band}'] = f'{short_name.title()} SD'

    table2 = component_pivot.rename(columns=rename_map)

    # Round numeric columns
    numeric_cols = [c for c in table2.columns if 'Mean' in c or 'SD' in c]
    for col in numeric_cols:
        if col in table2.columns:
            table2[col] = table2[col].round(4)

    table2['Area (km²)'] = table2['Area (km²)'].round(2)

    # Sort by PA Code
    table2 = table2.sort_values('PA Code').reset_index(drop=True)

    logger.info(f"Table 2 created with {len(table2)} rows")
    return table2


def validate_pa_count(df, allow_mismatch, logger):
    """
    Validate PA count.

    Args:
        df: DataFrame to validate
        allow_mismatch: Whether to allow count mismatch
        logger: Logger instance

    Returns:
        bool: True if valid
    """
    expected = CONFIG["expected_pa_count"]
    actual = len(df)

    if actual != expected:
        msg = f"PA count mismatch: expected {expected}, found {actual}"
        if allow_mismatch:
            logger.warning(msg)
            return True
        else:
            raise ValueError(f"{msg}. Use --allow-pa-count-mismatch to override.")

    logger.info(f"PA count validated: {actual}")
    return True


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
        validate_pa_count(eii_df, args.allow_pa_count_mismatch, logger)

        # Create publication tables
        table1 = create_table1_pa_summary(eii_df, logger)
        table2 = create_table2_components(component_df, logger)

        # Output paths
        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        # Save tables
        table1_path = results_tables / "table1_pa_eii_summary.csv"
        save_dataframe(table1, table1_path, overwrite=args.overwrite)
        logger.info(f"Saved Table 1: {table1_path}")

        table2_path = results_tables / "table2_components_by_pa.csv"
        save_dataframe(table2, table2_path, overwrite=args.overwrite)
        logger.info(f"Saved Table 2: {table2_path}")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("PA EII SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total PAs: {len(table1)}")
        logger.info(f"EII Mean range: {table1['EII Mean'].min():.4f} - {table1['EII Mean'].max():.4f}")
        logger.info(f"Network mean EII: {table1['EII Mean'].mean():.4f}")

        # Top 5 PAs
        logger.info("\nTop 5 PAs by EII Mean:")
        for _, row in table1.head().iterrows():
            logger.info(f"  {row['Rank']}. {row['PA Code']} ({row['Category']}): {row['EII Mean']:.4f}")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "EII stats loaded": len(eii_df) > 0,
            "Component stats loaded": len(component_df) > 0,
            "Table 1 created": table1_path.exists(),
            "Table 2 created": table2_path.exists(),
            "PA count validated": len(table1) == CONFIG["expected_pa_count"] or args.allow_pa_count_mismatch,
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
        logger.info("PA ZONAL STATS PROCESSING COMPLETE")
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
