#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10_maps_components.py
Generate component integrity maps (Functional, Structural, Compositional).

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

SCRIPT_NAME = "10_maps_components"
FIGURE_DPI = CONFIG["figure_dpi"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate component integrity maps"
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


def load_component_stats(base_dir, logger):
    """Load component statistics."""
    tables_dir = get_path("tables", base_dir)
    stats_path = tables_dir / "pa_component_stats.csv"

    if not stats_path.exists():
        raise FileNotFoundError(f"Component stats not found: {stats_path}")

    logger.info(f"Loading component stats from: {stats_path}")
    return pd.read_csv(stats_path)


def create_component_maps(pa_gdf, bhutan_gdf, component_df, output_path, logger):
    """
    Create multi-panel component integrity maps.

    Args:
        pa_gdf: Protected Areas GeoDataFrame
        bhutan_gdf: Bhutan boundary GeoDataFrame
        component_df: Component statistics DataFrame
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating component integrity maps...")

    components = CONFIG["eii_component_bands"]
    n_components = len(components)

    # Create figure with subplots
    fig, axes = plt.subplots(1, n_components, figsize=(5 * n_components, 6))

    # Pivot component data to wide format
    component_wide = component_df.pivot(
        index='PA_name',
        columns='band',
        values='mean'
    ).reset_index()

    # Merge with geometries
    pa_merged = pa_gdf.merge(
        component_wide,
        left_on=CONFIG["pa_name_field"],
        right_on='PA_name',
        how='left'
    )

    # Component display names
    display_names = {
        'functional_integrity': 'Functional Integrity',
        'structural_integrity': 'Structural Integrity',
        'compositional_integrity': 'Compositional Integrity'
    }

    # Colormaps for each component
    cmaps = {
        'functional_integrity': 'YlGn',
        'structural_integrity': 'YlOrBr',
        'compositional_integrity': 'PuBu'
    }

    for idx, (ax, component) in enumerate(zip(axes, components)):
        # Plot Bhutan boundary
        bhutan_gdf.plot(
            ax=ax,
            color='#f5f5f5',
            edgecolor='#666666',
            linewidth=0.3
        )

        if component not in pa_merged.columns:
            logger.warning(f"Component {component} not in data")
            ax.set_title(display_names.get(component, component))
            continue

        # Get value range
        vmin = pa_merged[component].min()
        vmax = pa_merged[component].max()

        # Plot PAs
        pa_merged.plot(
            column=component,
            ax=ax,
            cmap=cmaps.get(component, 'viridis'),
            edgecolor='black',
            linewidth=0.5,
            legend=False,
            vmin=vmin,
            vmax=vmax
        )

        # Add colorbar
        sm = plt.cm.ScalarMappable(
            cmap=cmaps.get(component, 'viridis'),
            norm=plt.Normalize(vmin=vmin, vmax=vmax)
        )
        sm._A = []
        cbar = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02, shrink=0.8)
        cbar.ax.tick_params(labelsize=8)

        # Title
        ax.set_title(display_names.get(component, component), fontsize=11, fontweight='bold')

        # Remove axis labels for cleaner look
        ax.set_xlabel('')
        ax.set_ylabel('')
        ax.tick_params(labelsize=7)

    # Overall title
    fig.suptitle(
        "EII Component Integrity Across Bhutan's Protected Areas",
        fontsize=14,
        fontweight='bold',
        y=1.02
    )

    plt.tight_layout()

    # Save
    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved component maps: {output_path}")


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
        component_df = load_component_stats(base_dir, logger)

        # Ensure same CRS
        target_crs = "EPSG:4326"
        if pa_gdf.crs.to_epsg() != 4326:
            pa_gdf = pa_gdf.to_crs(target_crs)
        if bhutan_gdf.crs.to_epsg() != 4326:
            bhutan_gdf = bhutan_gdf.to_crs(target_crs)

        # Output path
        figures_dir = get_path("figures", base_dir)
        ensure_dir(figures_dir)

        output_path = figures_dir / "fig3_components.png"
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"Output exists: {output_path}. Use --overwrite to replace."
            )

        # Create maps
        create_component_maps(pa_gdf, bhutan_gdf, component_df, output_path, logger)

        # Validation
        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        checks = {
            "PA data loaded": len(pa_gdf) > 0,
            "Component stats loaded": len(component_df) > 0,
            "Component maps created": output_path.exists(),
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
        logger.info("COMPONENT MAPS GENERATION COMPLETE")
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
