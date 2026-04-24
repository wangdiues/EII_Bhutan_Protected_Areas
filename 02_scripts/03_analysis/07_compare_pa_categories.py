#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
07_compare_pa_categories.py
Compare EII values across different PA categories (park types).

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

SCRIPT_NAME = "07_compare_pa_categories"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compare EII across PA categories"
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
        help="Include sensitivity indices comparison"
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
        raise FileNotFoundError(
            f"EII stats file not found: {stats_path}\n"
            f"Run 03_download_eii.py first."
        )

    logger.info(f"Loading EII stats from: {stats_path}")
    return pd.read_csv(stats_path)


def derive_pa_type(park_name):
    """
    Derive PA management-type category from a full PA name.

    The upstream `park` column stores individual PA full names (e.g.
    "Biological Corridor 1").  For category-level aggregation we need
    the management type (e.g. "Biological Corridor") so that each group
    contains multiple PAs and statistics (min, max, median, SD) are
    meaningful.

    Returns one of: Biological Corridor | National Park |
                    Wildlife Sanctuary | Strict Nature Reserve |
                    Botanical Park
    """
    if 'Biological Corridor' in park_name:
        return 'Biological Corridor'
    elif 'National Park' in park_name:
        return 'National Park'
    elif 'Wildlife Sanctuary' in park_name:
        return 'Wildlife Sanctuary'
    elif 'Nature Reserve' in park_name:
        return 'Strict Nature Reserve'
    elif 'Botanical Park' in park_name:
        return 'Botanical Park'
    else:
        return park_name  # fallback: keep original if no rule matches


def compute_category_stats(df, logger):
    """
    Compute summary statistics by PA management-type category.

    Groups PAs by type (Biological Corridor, National Park, etc.) so that
    each group contains multiple PAs and statistics are statistically valid.
    Median EII is computed as the median of PA-level EII means within the
    type group, which is the only defensible median for this aggregation.

    Args:
        df: DataFrame with PA-level EII stats
        logger: Logger instance

    Returns:
        DataFrame with category-level statistics
    """
    logger.info("Computing category-level statistics...")

    # Derive PA type from full park name
    df = df.copy()
    df['pa_type'] = df['park'].apply(derive_pa_type)
    category_col = 'pa_type'

    # Group by PA type category
    # Median EII = median of PA-level eii_mean values within the type group
    category_stats = df.groupby(category_col).agg({
        'PA_name': 'count',
        'Area_km2': ['sum', 'mean'],
        'eii_mean': ['mean', 'std', 'min', 'max', 'median'],
        'pixel_count': 'sum'
    }).reset_index()

    # Flatten column names
    category_stats.columns = [
        '_'.join(col).strip('_') if isinstance(col, tuple) and col[1] else col[0]
        for col in category_stats.columns
    ]

    # Rename columns
    category_stats.columns = [
        'Category', 'PA Count', 'Total Area (km²)', 'Mean Area (km²)',
        'Mean EII', 'EII SD', 'Min EII', 'Max EII',
        'Median EII', 'Total Pixels'
    ]

    # Round values
    round_cols = ['Total Area (km²)', 'Mean Area (km²)', 'Mean EII',
                  'EII SD', 'Min EII', 'Max EII', 'Median EII']
    for col in round_cols:
        if col in category_stats.columns:
            decimals = 2 if 'Area' in col else 4
            category_stats[col] = category_stats[col].round(decimals)

    # Sort by Mean EII descending
    category_stats = category_stats.sort_values('Mean EII', ascending=False)
    category_stats = category_stats.reset_index(drop=True)

    logger.info(f"Computed stats for {len(category_stats)} categories")
    return category_stats


def compute_pairwise_differences(df, logger):
    """
    Compute pairwise mean-EII differences between PA management-type categories.

    Args:
        df: DataFrame with PA-level EII stats
        logger: Logger instance

    Returns:
        DataFrame with pairwise comparison matrix (PA types × PA types)
    """
    logger.info("Computing pairwise category differences...")

    df = df.copy()
    df['pa_type'] = df['park'].apply(derive_pa_type)
    category_col = 'pa_type'
    categories = sorted(df[category_col].unique())

    # Calculate mean EII per PA type category
    category_means = df.groupby(category_col)['eii_mean'].mean()

    # Create difference matrix
    n_cats = len(categories)
    diff_matrix = np.zeros((n_cats, n_cats))

    for i, cat1 in enumerate(categories):
        for j, cat2 in enumerate(categories):
            diff_matrix[i, j] = category_means[cat1] - category_means[cat2]

    diff_df = pd.DataFrame(
        diff_matrix,
        index=categories,
        columns=categories
    ).round(4)

    logger.info(f"Created {n_cats}x{n_cats} difference matrix")
    return diff_df


def compute_component_by_category(base_dir, logger):
    """
    Compute component statistics by category.

    Args:
        base_dir: Base directory
        logger: Logger instance

    Returns:
        DataFrame with component stats by category
    """
    tables_dir = get_path("tables", base_dir)
    component_path = tables_dir / "pa_component_stats.csv"

    if not component_path.exists():
        logger.warning("Component stats not found, skipping component analysis")
        return None

    component_df = pd.read_csv(component_path)

    # Derive PA type so statistics are aggregated across multiple PAs per group
    component_df['pa_type'] = component_df['park'].apply(derive_pa_type)

    # Aggregate by PA type category (not individual PA name)
    results = []

    for pa_type in sorted(component_df['pa_type'].unique()):
        cat_data = component_df[component_df['pa_type'] == pa_type]

        for band in CONFIG["eii_component_bands"]:
            band_data = cat_data[cat_data['band'] == band]
            if len(band_data) == 0:
                continue

            results.append({
                'Category': pa_type,
                'Component': band.replace('_integrity', '').title(),
                'Mean': band_data['mean'].mean(),
                'SD': band_data['mean'].std(),
                'Min': band_data['mean'].min(),
                'Max': band_data['mean'].max(),
            })

    if not results:
        return None

    comp_cat_df = pd.DataFrame(results)

    # Round values
    for col in ['Mean', 'SD', 'Min', 'Max']:
        comp_cat_df[col] = comp_cat_df[col].round(4)

    logger.info(f"Computed component stats for {len(comp_cat_df)} category-component combinations")
    return comp_cat_df


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
        logger.info(f"Loaded {len(eii_df)} PAs")

        # Validate PA count
        expected = CONFIG["expected_pa_count"]
        actual = len(eii_df)
        if actual != expected and not args.allow_pa_count_mismatch:
            raise ValueError(
                f"PA count mismatch: expected {expected}, found {actual}. "
                f"Use --allow-pa-count-mismatch to override."
            )

        # Compute category statistics
        category_stats = compute_category_stats(eii_df, logger)

        # Compute pairwise differences
        diff_matrix = compute_pairwise_differences(eii_df, logger)

        # Compute component by category
        comp_cat_stats = compute_component_by_category(base_dir, logger)

        # Output paths
        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        # Save outputs
        cat_stats_path = results_tables / "category_eii_summary.csv"
        save_dataframe(category_stats, cat_stats_path, overwrite=args.overwrite)
        logger.info(f"Saved category stats: {cat_stats_path}")

        diff_path = results_tables / "category_pairwise_differences.csv"
        diff_matrix.to_csv(diff_path)
        logger.info(f"Saved pairwise differences: {diff_path}")

        if comp_cat_stats is not None:
            comp_path = results_tables / "category_component_summary.csv"
            save_dataframe(comp_cat_stats, comp_path, overwrite=args.overwrite)
            logger.info(f"Saved component by category: {comp_path}")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("CATEGORY COMPARISON SUMMARY")
        logger.info("=" * 60)

        logger.info("\nCategory Rankings (by Mean EII):")
        for idx, row in category_stats.iterrows():
            logger.info(
                f"  {idx+1}. {row['Category']}: "
                f"Mean={row['Mean EII']:.4f}, "
                f"N={row['PA Count']}, "
                f"Area={row['Total Area (km²)']:.0f} km²"
            )

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "EII stats loaded": len(eii_df) > 0,
            "Category stats computed": len(category_stats) > 0,
            "Pairwise differences computed": diff_matrix is not None,
            "Category stats saved": cat_stats_path.exists(),
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
        logger.info("CATEGORY COMPARISON COMPLETE")
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
