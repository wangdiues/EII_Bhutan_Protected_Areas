#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
12_figures_counterfactual_and_covariates.py
Generate publication figures for counterfactual and covariate analyses.

Figures generated:
- Boxplots: Inside vs outside EII by PA type
- Scatter: EII vs Human Modification Index
- Scatter: EII vs Forest Loss

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
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy import stats as scipy_stats

from _shared.config import CONFIG, get_path
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import ensure_dir, write_success_marker
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "12_figures_counterfactual_covariates"
FIGURE_DPI = CONFIG["figure_dpi"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate counterfactual and covariate figures"
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


def load_inside_outside_stats(base_dir, logger):
    """Load inside/outside statistics."""
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_inside_outside_stats.csv"

    if not stats_path.exists():
        raise FileNotFoundError(
            f"Inside/outside stats not found: {stats_path}\n"
            f"Run 12_inside_outside_buffers.py first."
        )

    logger.info(f"Loading inside/outside stats from: {stats_path}")
    return pd.read_csv(stats_path)


def load_covariate_stats(base_dir, logger):
    """Load covariate statistics."""
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_covariates_stats.csv"

    if not stats_path.exists():
        logger.warning(f"Covariate stats not found: {stats_path}")
        return None

    logger.info(f"Loading covariate stats from: {stats_path}")
    return pd.read_csv(stats_path)


def load_eii_stats(base_dir, logger):
    """Load EII statistics."""
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_eii_stats.csv"

    if not stats_path.exists():
        raise FileNotFoundError(f"EII stats not found: {stats_path}")

    return pd.read_csv(stats_path)


def create_inside_outside_boxplot(io_stats, output_path, logger):
    """
    Create boxplot comparing inside vs outside EII by PA type.

    Args:
        io_stats: DataFrame with inside/outside statistics
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating inside/outside boxplot...")

    # Get unique PA types
    pa_types = io_stats['park'].unique()
    n_types = len(pa_types)

    # Prepare data for boxplot
    inside_data = []
    outside_data = []

    for pa_type in pa_types:
        type_data = io_stats[io_stats['park'] == pa_type]

        # Get inside values (use mean as representative)
        inside_col = 'eii_mean_inside' if 'eii_mean_inside' in type_data.columns else None
        outside_col = 'eii_mean_outside' if 'eii_mean_outside' in type_data.columns else None

        if inside_col and outside_col:
            inside_data.append(type_data[inside_col].dropna().values)
            outside_data.append(type_data[outside_col].dropna().values)
        else:
            # Fallback: separate by location column
            inside_vals = type_data[type_data.get('location', 'inside') == 'inside']
            outside_vals = type_data[type_data.get('location', 'outside') == 'outside']
            if 'eii_mean' in type_data.columns:
                inside_data.append(inside_vals['eii_mean'].dropna().values)
                outside_data.append(outside_vals['eii_mean'].dropna().values)

    # Create figure
    fig, ax = plt.subplots(figsize=(12, 7))

    # Position settings
    positions_inside = np.arange(n_types) * 3
    positions_outside = positions_inside + 1
    width = 0.8

    # Colors
    color_inside = '#2ecc71'  # Green
    color_outside = '#e74c3c'  # Red

    # Create boxplots
    bp_inside = ax.boxplot(
        inside_data,
        positions=positions_inside,
        widths=width,
        patch_artist=True,
        boxprops=dict(facecolor=color_inside, alpha=0.7),
        medianprops=dict(color='black', linewidth=1.5),
        whiskerprops=dict(color='black'),
        capprops=dict(color='black'),
        flierprops=dict(marker='o', markerfacecolor=color_inside, markersize=4, alpha=0.5)
    )

    bp_outside = ax.boxplot(
        outside_data,
        positions=positions_outside,
        widths=width,
        patch_artist=True,
        boxprops=dict(facecolor=color_outside, alpha=0.7),
        medianprops=dict(color='black', linewidth=1.5),
        whiskerprops=dict(color='black'),
        capprops=dict(color='black'),
        flierprops=dict(marker='o', markerfacecolor=color_outside, markersize=4, alpha=0.5)
    )

    # Labels
    ax.set_xticks(positions_inside + 0.5)
    ax.set_xticklabels(pa_types, rotation=30, ha='right', fontsize=10)
    ax.set_ylabel('Ecosystem Integrity Index (EII)', fontsize=12)
    ax.set_xlabel('Protected Area Type', fontsize=12)
    ax.set_title(
        'EII Inside vs Outside Protected Areas by Type\n'
        '(10km buffer comparison)',
        fontsize=13,
        fontweight='bold',
        pad=15
    )

    # Legend
    legend_patches = [
        mpatches.Patch(color=color_inside, alpha=0.7, label='Inside PA'),
        mpatches.Patch(color=color_outside, alpha=0.7, label='Outside PA (buffer)')
    ]
    ax.legend(handles=legend_patches, loc='upper right', fontsize=10)

    # Add significance annotations
    for i, pa_type in enumerate(pa_types):
        if len(inside_data[i]) > 0 and len(outside_data[i]) > 0:
            # T-test
            try:
                t_stat, p_val = scipy_stats.ttest_ind(inside_data[i], outside_data[i])
                if p_val < 0.001:
                    sig_text = '***'
                elif p_val < 0.01:
                    sig_text = '**'
                elif p_val < 0.05:
                    sig_text = '*'
                else:
                    sig_text = 'ns'

                # Add annotation above the pair
                max_val = max(
                    np.max(inside_data[i]) if len(inside_data[i]) > 0 else 0,
                    np.max(outside_data[i]) if len(outside_data[i]) > 0 else 0
                )
                ax.annotate(
                    sig_text,
                    xy=(positions_inside[i] + 0.5, max_val + 0.02),
                    ha='center',
                    fontsize=10,
                    fontweight='bold'
                )
            except Exception:
                pass

    ax.grid(axis='y', alpha=0.3)
    ax.set_ylim(0, min(1.0, ax.get_ylim()[1] + 0.1))

    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def create_eii_hmi_scatter(eii_df, cov_df, output_path, logger):
    """
    Create scatter plot of EII vs Human Modification Index.

    Args:
        eii_df: EII statistics DataFrame
        cov_df: Covariate statistics DataFrame
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating EII vs HMI scatter plot...")

    # Merge data
    if 'hmi_mean' not in cov_df.columns:
        logger.warning("HMI data not available, skipping scatter plot")
        return

    merged = eii_df[['PA_name', 'park', 'eii_mean']].merge(
        cov_df[['PA_name', 'hmi_mean']],
        on='PA_name'
    )

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Color by PA type
    categories = merged['park'].unique()
    colors = plt.cm.Set2(np.linspace(0, 1, len(categories)))
    color_map = dict(zip(categories, colors))

    # Scatter points
    for cat in categories:
        cat_data = merged[merged['park'] == cat]
        ax.scatter(
            cat_data['hmi_mean'],
            cat_data['eii_mean'],
            c=[color_map[cat]],
            label=cat,
            s=100,
            alpha=0.7,
            edgecolors='black',
            linewidth=0.5
        )

    # Add PA labels
    for _, row in merged.iterrows():
        ax.annotate(
            row['PA_name'],
            (row['hmi_mean'], row['eii_mean']),
            xytext=(5, 5),
            textcoords='offset points',
            fontsize=7,
            alpha=0.7
        )

    # Trend line
    x = merged['hmi_mean'].values
    y = merged['eii_mean'].values
    mask = ~np.isnan(x) & ~np.isnan(y)
    if mask.sum() > 2:
        z = np.polyfit(x[mask], y[mask], 1)
        p = np.poly1d(z)
        x_line = np.linspace(x[mask].min(), x[mask].max(), 100)
        ax.plot(x_line, p(x_line), 'r--', linewidth=1.5, alpha=0.7, label='Trend line')

        # Correlation
        r, p_val = scipy_stats.pearsonr(x[mask], y[mask])
        sig = '*' if p_val < 0.05 else ''
        ax.annotate(
            f'r = {r:.3f}{sig}\np = {p_val:.3f}',
            xy=(0.05, 0.95),
            xycoords='axes fraction',
            fontsize=10,
            verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
        )

    ax.set_xlabel('Human Modification Index (HMI)', fontsize=12)
    ax.set_ylabel('Ecosystem Integrity Index (EII)', fontsize=12)
    ax.set_title(
        'EII vs Human Modification Index\n'
        'Across Bhutan Protected Areas',
        fontsize=13,
        fontweight='bold',
        pad=15
    )

    ax.legend(title='PA Type', loc='lower left', fontsize=9)
    ax.grid(alpha=0.3)

    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def create_eii_forest_loss_scatter(eii_df, cov_df, output_path, logger):
    """
    Create scatter plot of EII vs Forest Loss.

    Args:
        eii_df: EII statistics DataFrame
        cov_df: Covariate statistics DataFrame
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating EII vs Forest Loss scatter plot...")

    # Merge data
    if 'forest_loss_mean' not in cov_df.columns:
        logger.warning("Forest loss data not available, skipping scatter plot")
        return

    merged = eii_df[['PA_name', 'park', 'eii_mean']].merge(
        cov_df[['PA_name', 'forest_loss_mean']],
        on='PA_name'
    )

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Color by PA type
    categories = merged['park'].unique()
    colors = plt.cm.Set2(np.linspace(0, 1, len(categories)))
    color_map = dict(zip(categories, colors))

    # Scatter points
    for cat in categories:
        cat_data = merged[merged['park'] == cat]
        ax.scatter(
            cat_data['forest_loss_mean'] * 100,  # Convert to percentage
            cat_data['eii_mean'],
            c=[color_map[cat]],
            label=cat,
            s=100,
            alpha=0.7,
            edgecolors='black',
            linewidth=0.5
        )

    # Add PA labels
    for _, row in merged.iterrows():
        ax.annotate(
            row['PA_name'],
            (row['forest_loss_mean'] * 100, row['eii_mean']),
            xytext=(5, 5),
            textcoords='offset points',
            fontsize=7,
            alpha=0.7
        )

    # Trend line
    x = merged['forest_loss_mean'].values * 100
    y = merged['eii_mean'].values
    mask = ~np.isnan(x) & ~np.isnan(y)
    if mask.sum() > 2:
        z = np.polyfit(x[mask], y[mask], 1)
        p = np.poly1d(z)
        x_line = np.linspace(x[mask].min(), x[mask].max(), 100)
        ax.plot(x_line, p(x_line), 'r--', linewidth=1.5, alpha=0.7, label='Trend line')

        # Correlation
        r, p_val = scipy_stats.pearsonr(x[mask], y[mask])
        sig = '*' if p_val < 0.05 else ''
        ax.annotate(
            f'r = {r:.3f}{sig}\np = {p_val:.3f}',
            xy=(0.95, 0.95),
            xycoords='axes fraction',
            fontsize=10,
            verticalalignment='top',
            horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
        )

    ax.set_xlabel('Forest Loss (%)', fontsize=12)
    ax.set_ylabel('Ecosystem Integrity Index (EII)', fontsize=12)
    ax.set_title(
        'EII vs Forest Loss (2001-2023)\n'
        'Across Bhutan Protected Areas',
        fontsize=13,
        fontweight='bold',
        pad=15
    )

    ax.legend(title='PA Type', loc='upper right', fontsize=9)
    ax.grid(alpha=0.3)

    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def create_delta_summary_figure(io_stats, output_path, logger):
    """
    Create summary figure showing delta EII (inside - outside) by PA.

    Args:
        io_stats: DataFrame with inside/outside statistics
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating delta EII summary figure...")

    # Check for delta column
    if 'delta_eii' not in io_stats.columns:
        logger.warning("delta_eii not in data, skipping delta figure")
        return

    # Sort by delta
    df_sorted = io_stats.sort_values('delta_eii', ascending=True).copy()

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Colors based on positive/negative delta
    colors = ['green' if d > 0 else 'red' for d in df_sorted['delta_eii']]

    # Bar chart
    y_pos = range(len(df_sorted))
    bars = ax.barh(
        y_pos,
        df_sorted['delta_eii'],
        color=colors,
        alpha=0.7,
        edgecolor='black',
        linewidth=0.5
    )

    # Labels
    ax.set_yticks(y_pos)
    ax.set_yticklabels(df_sorted['PA_name'], fontsize=9)
    ax.axvline(0, color='black', linestyle='-', linewidth=1)

    ax.set_xlabel('Delta EII (Inside - Outside)', fontsize=12)
    ax.set_ylabel('Protected Area', fontsize=12)
    ax.set_title(
        'Protection Effect: EII Difference Inside vs Outside PA\n'
        '(Positive = Higher EII inside PA)',
        fontsize=13,
        fontweight='bold',
        pad=15
    )

    # Add mean line
    mean_delta = df_sorted['delta_eii'].mean()
    ax.axvline(mean_delta, color='blue', linestyle='--', linewidth=1.5, alpha=0.7)
    ax.annotate(
        f'Mean: {mean_delta:.3f}',
        xy=(mean_delta, len(df_sorted) - 1),
        xytext=(mean_delta + 0.01, len(df_sorted) - 2),
        fontsize=9,
        color='blue'
    )

    # Summary stats
    positive = (df_sorted['delta_eii'] > 0).sum()
    total = len(df_sorted)
    ax.annotate(
        f'{positive}/{total} PAs with positive delta',
        xy=(0.95, 0.05),
        xycoords='axes fraction',
        fontsize=10,
        horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
    )

    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


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
        # Load data
        logger.info("Loading data...")

        # Required: Inside/outside stats
        io_stats = load_inside_outside_stats(base_dir, logger)

        # Required: EII stats
        eii_df = load_eii_stats(base_dir, logger)

        # Optional: Covariate stats
        cov_df = load_covariate_stats(base_dir, logger)

        # Validate PA count
        n_pas = io_stats['PA_name'].nunique()
        if n_pas != CONFIG["expected_pa_count"] and not args.allow_pa_count_mismatch:
            logger.warning(
                f"PA count ({n_pas}) differs from expected ({CONFIG['expected_pa_count']})"
            )

        # Output directory
        figures_dir = get_path("figures", base_dir)
        ensure_dir(figures_dir)

        figures_created = []

        # Figure 1: Inside/Outside Boxplot by PA Type
        logger.info("\n" + "=" * 60)
        logger.info("CREATING FIGURES")
        logger.info("=" * 60)

        fig_boxplot_path = figures_dir / "fig8_inside_outside_boxplot.png"
        if fig_boxplot_path.exists() and not args.overwrite:
            logger.info(f"Boxplot exists, skipping: {fig_boxplot_path}")
        else:
            create_inside_outside_boxplot(io_stats, fig_boxplot_path, logger)
            figures_created.append(str(fig_boxplot_path))

        # Figure 2: Delta EII Summary
        fig_delta_path = figures_dir / "fig9_delta_eii_summary.png"
        if fig_delta_path.exists() and not args.overwrite:
            logger.info(f"Delta figure exists, skipping: {fig_delta_path}")
        else:
            create_delta_summary_figure(io_stats, fig_delta_path, logger)
            if fig_delta_path.exists():
                figures_created.append(str(fig_delta_path))

        # Covariate figures (if data available)
        if cov_df is not None:
            # Figure 3: EII vs HMI
            fig_hmi_path = figures_dir / "fig10_eii_vs_hmi.png"
            if fig_hmi_path.exists() and not args.overwrite:
                logger.info(f"HMI figure exists, skipping: {fig_hmi_path}")
            else:
                create_eii_hmi_scatter(eii_df, cov_df, fig_hmi_path, logger)
                if fig_hmi_path.exists():
                    figures_created.append(str(fig_hmi_path))

            # Figure 4: EII vs Forest Loss
            fig_loss_path = figures_dir / "fig11_eii_vs_forest_loss.png"
            if fig_loss_path.exists() and not args.overwrite:
                logger.info(f"Forest loss figure exists, skipping: {fig_loss_path}")
            else:
                create_eii_forest_loss_scatter(eii_df, cov_df, fig_loss_path, logger)
                if fig_loss_path.exists():
                    figures_created.append(str(fig_loss_path))
        else:
            logger.warning("Covariate data not available, skipping covariate figures")

        # Validation report
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "Inside/outside data loaded": len(io_stats) > 0,
            "EII data loaded": len(eii_df) > 0,
            "Boxplot created": fig_boxplot_path.exists(),
            "Delta figure created": fig_delta_path.exists() if 'delta_eii' in io_stats.columns else True,
            "At least one figure created": len(figures_created) > 0,
        }

        if cov_df is not None:
            checks["Covariate data loaded"] = len(cov_df) > 0
            checks["HMI scatter created"] = (figures_dir / "fig10_eii_vs_hmi.png").exists()
            checks["Forest loss scatter created"] = (figures_dir / "fig11_eii_vs_forest_loss.png").exists()

        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        logger.info("\n" + "=" * 60)
        logger.info("FIGURE GENERATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Figures created: {len(figures_created)}")
        for f in figures_created:
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
