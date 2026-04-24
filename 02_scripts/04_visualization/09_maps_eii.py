#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
09_maps_eii.py
Generate EII choropleth map of Bhutan Protected Areas.

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

import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as path_effects  # FIX: import patheffects correctly
from matplotlib.patches import Patch
import numpy as np

from _shared.config import CONFIG, get_path
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import (
    load_pa_geodataframe, load_bhutan_boundary, ensure_dir,
    write_success_marker
)
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report
)


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "09_maps_eii"
FIGURE_DPI = CONFIG["figure_dpi"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate EII map of Protected Areas"
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
        help="Not used"
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
        raise FileNotFoundError(f"EII stats not found: {stats_path}")

    logger.info(f"Loading EII stats from: {stats_path}")
    return pd.read_csv(stats_path)


def create_eii_map(pa_gdf, bhutan_gdf, eii_df, output_path, logger):
    """
    Create EII choropleth map.

    Args:
        pa_gdf: Protected Areas GeoDataFrame
        bhutan_gdf: Bhutan boundary GeoDataFrame
        eii_df: EII statistics DataFrame
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating EII choropleth map...")

    # Merge EII stats with geometries
    pa_merged = pa_gdf.merge(
        eii_df[['PA_name', 'eii_mean', 'eii_p50']],
        left_on=CONFIG["pa_name_field"],
        right_on='PA_name',
        how='left'
    )

    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))

    # Plot Bhutan boundary
    bhutan_gdf.plot(
        ax=ax,
        color='#f0f0f0',
        edgecolor='#333333',
        linewidth=0.5
    )

    # Define colormap (green for high EII, red for low)
    cmap = plt.cm.RdYlGn

    # Get value range
    vmin = pa_merged['eii_mean'].min()
    vmax = pa_merged['eii_mean'].max()

    # Plot PAs with EII coloring
    pa_merged.plot(
        column='eii_mean',
        ax=ax,
        cmap=cmap,
        edgecolor='black',
        linewidth=0.8,
        legend=False,
        vmin=vmin,
        vmax=vmax
    )

    # Add colorbar
    sm = plt.cm.ScalarMappable(
        cmap=cmap,
        norm=plt.Normalize(vmin=vmin, vmax=vmax)
    )
    sm._A = []
    cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label('Ecosystem Integrity Index (EII)', fontsize=11)

    # Add PA labels
    for _, row in pa_merged.iterrows():
        centroid = row.geometry.centroid
        label = row[CONFIG["pa_name_field"]]
        # Shorten long labels
        if isinstance(label, str) and len(label) > 10:
            label = label[:8] + '..'

        ax.annotate(
            label,
            xy=(centroid.x, centroid.y),
            fontsize=6,
            ha='center',
            va='center',
            color='black',
            weight='bold',
            path_effects=[  # FIX: use imported path_effects (NOT plt.matplotlib...)
                path_effects.withStroke(linewidth=2, foreground='white')
            ]
        )

    # Styling
    ax.set_title(
        "Ecosystem Integrity Index (EII) of Bhutan's Protected Areas",
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax.set_xlabel('Longitude', fontsize=10)
    ax.set_ylabel('Latitude', fontsize=10)

    # Add north arrow (simplified)
    ax.annotate(
        'N',
        xy=(0.95, 0.95),
        xycoords='axes fraction',
        fontsize=14,
        fontweight='bold',
        ha='center'
    )
    ax.annotate(
        '',
        xy=(0.95, 0.93),
        xytext=(0.95, 0.88),
        xycoords='axes fraction',
        arrowprops=dict(arrowstyle='->', color='black', lw=1.5)
    )

    # Add data source note
    ax.annotate(
        f'Data: EII Global v1 (Landler Open Data) | Scale: {CONFIG["analysis_scale"]}m',
        xy=(0.02, 0.02),
        xycoords='axes fraction',
        fontsize=8,
        color='gray'
    )

    plt.tight_layout()

    # Save
    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved EII map: {output_path}")


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
        logger.info("Loading spatial data...")
        pa_gdf = load_pa_geodataframe(
            base_dir=base_dir,
            validate_count=True,
            allow_mismatch=args.allow_pa_count_mismatch
        )
        bhutan_gdf = load_bhutan_boundary(base_dir)
        eii_df = load_eii_stats(base_dir, logger)

        # Ensure same CRS
        target_crs = "EPSG:4326"
        if pa_gdf.crs is not None and pa_gdf.crs.to_epsg() != 4326:
            pa_gdf = pa_gdf.to_crs(target_crs)
        if bhutan_gdf.crs is not None and bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs(target_crs)

        # Output path
        figures_dir = get_path("figures", base_dir)
        ensure_dir(figures_dir)

        output_path = figures_dir / "fig1_eii_map.png"
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"Output exists: {output_path}. Use --overwrite to replace."
            )

        # Create map
        create_eii_map(pa_gdf, bhutan_gdf, eii_df, output_path, logger)

        # Validation
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "PA data loaded": len(pa_gdf) > 0,
            "Bhutan boundary loaded": len(bhutan_gdf) > 0,
            "EII stats loaded": len(eii_df) > 0,
            "Map figure created": output_path.exists(),
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
        logger.info("EII MAP GENERATION COMPLETE")
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
