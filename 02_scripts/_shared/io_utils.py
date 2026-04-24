#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
io_utils.py
I/O utilities for EII Bhutan Protected Areas analysis.
"""

__version__ = "1.0.0"

import os
from pathlib import Path
from datetime import datetime

import geopandas as gpd
import pandas as pd

from .config import CONFIG, get_path


def ensure_dir(path):
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path: Path to directory

    Returns:
        Path object
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dissolve_pa_network(gdf):
    """
    Normalize raw PA/BC features into one record per network unit.

    The raw PA_BC shapefile contains multipart and duplicated entries for
    some protected areas. The analysis should operate on the dissolved
    19-feature network.
    """
    name_field = CONFIG["pa_name_field"]
    category_field = CONFIG["pa_category_field"]
    excluded_names = set(CONFIG.get("excluded_raw_pa_names", []))

    if excluded_names:
        gdf = gdf[~gdf[name_field].isin(excluded_names)].copy()

    dissolved = gdf.dissolve(
        by=[category_field, name_field],
        as_index=False,
        aggfunc="first"
    )
    dissolved["geometry"] = dissolved.geometry.make_valid()

    area_series = dissolved.to_crs(CONFIG["source_crs"]).geometry.area / 1_000_000
    dissolved[CONFIG["pa_area_field"]] = area_series.round(6)

    ordered_columns = [
        category_field,
        name_field,
        CONFIG["pa_area_field"],
        "geometry",
    ]
    return dissolved[ordered_columns]


def load_raw_pa_geodataframe(base_dir=None, normalize_network=True):
    """
    Load the raw PA/BC shapefile and optionally dissolve to the network units.
    """
    pa_path = get_path("raw_protected_areas", base_dir)

    if not pa_path.exists():
        raise FileNotFoundError(f"Raw Protected Areas file not found: {pa_path}")

    gdf = gpd.read_file(pa_path)

    required_fields = [CONFIG["pa_name_field"], CONFIG["pa_category_field"]]
    missing_fields = [f for f in required_fields if f not in gdf.columns]
    if missing_fields:
        raise ValueError(f"Missing required fields in raw PA layer: {missing_fields}")

    if normalize_network:
        gdf = _dissolve_pa_network(gdf)

    return gdf


def load_raw_bhutan_boundary(base_dir=None):
    """Load the raw Bhutan boundary shapefile."""
    boundary_path = get_path("raw_bhutan_boundary", base_dir)

    if not boundary_path.exists():
        raise FileNotFoundError(f"Raw Bhutan boundary file not found: {boundary_path}")

    return gpd.read_file(boundary_path)


def load_pa_geodataframe(base_dir=None, validate_count=True, allow_mismatch=False):
    """
    Load the Protected Areas GeoDataFrame with validation.

    Args:
        base_dir: Optional base directory override
        validate_count: Whether to validate PA count
        allow_mismatch: If True, warn but don't fail on count mismatch

    Returns:
        geopandas.GeoDataFrame

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If PA count validation fails and allow_mismatch=False
    """
    pa_path = get_path("protected_areas", base_dir)
    layer = CONFIG["protected_areas_layer"]

    if not pa_path.exists():
        raise FileNotFoundError(f"Protected Areas file not found: {pa_path}")

    gdf = gpd.read_file(pa_path, layer=layer)

    # Validate required fields
    required_fields = [CONFIG["pa_name_field"], CONFIG["pa_category_field"]]
    missing_fields = [f for f in required_fields if f not in gdf.columns]
    if missing_fields:
        raise ValueError(f"Missing required fields in PA layer: {missing_fields}")

    # Validate PA count
    if validate_count:
        expected = CONFIG["expected_pa_count"]
        actual = len(gdf)
        if actual != expected:
            msg = f"PA count mismatch: expected {expected}, found {actual}"
            if allow_mismatch:
                import warnings
                warnings.warn(msg)
            else:
                raise ValueError(
                    f"{msg}. Use --allow-pa-count-mismatch to override."
                )

    return gdf


def load_bhutan_boundary(base_dir=None):
    """
    Load the Bhutan boundary GeoDataFrame.

    Args:
        base_dir: Optional base directory override

    Returns:
        geopandas.GeoDataFrame

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    boundary_path = get_path("bhutan_boundary", base_dir)
    layer = CONFIG["bhutan_boundary_layer"]

    if not boundary_path.exists():
        raise FileNotFoundError(f"Bhutan boundary file not found: {boundary_path}")

    return gpd.read_file(boundary_path, layer=layer)


def save_dataframe(df, filepath, overwrite=False):
    """
    Save a DataFrame to CSV with safety checks.

    Args:
        df: pandas DataFrame
        filepath: Output path
        overwrite: Whether to overwrite existing file

    Returns:
        Path to saved file

    Raises:
        FileExistsError: If file exists and overwrite=False
    """
    filepath = Path(filepath)

    if filepath.exists() and not overwrite:
        raise FileExistsError(
            f"Output file exists: {filepath}. Use --overwrite to replace."
        )

    filepath.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(filepath, index=False)

    return filepath


def save_geodataframe(gdf, filepath, layer=None, overwrite=False):
    """
    Save a GeoDataFrame with safety checks.

    Args:
        gdf: geopandas GeoDataFrame
        filepath: Output path (supports .gpkg, .shp, .geojson)
        layer: Layer name (for GeoPackage)
        overwrite: Whether to overwrite existing file

    Returns:
        Path to saved file

    Raises:
        FileExistsError: If file exists and overwrite=False
    """
    filepath = Path(filepath)

    if filepath.exists() and not overwrite:
        raise FileExistsError(
            f"Output file exists: {filepath}. Use --overwrite to replace."
        )

    filepath.parent.mkdir(parents=True, exist_ok=True)

    if filepath.suffix.lower() == '.gpkg' and layer:
        gdf.to_file(filepath, layer=layer, driver='GPKG')
    else:
        gdf.to_file(filepath)

    return filepath


def write_success_marker(script_dir, script_name):
    """
    Write a success marker file.

    Args:
        script_dir: Directory to write marker
        script_name: Name of the script

    Returns:
        Path to success file
    """
    script_dir = Path(script_dir)
    success_file = script_dir / f"_SUCCESS_{script_name}.txt"

    with open(success_file, 'w') as f:
        f.write(f"Completed: {datetime.now().isoformat()}\n")
        f.write(f"Script: {script_name}\n")

    return success_file


def write_gee_assets_log(filepath, assets_used):
    """
    Write a log of GEE assets used in the analysis.

    Args:
        filepath: Output path
        assets_used: List of asset IDs or dict with asset info

    Returns:
        Path to log file
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w') as f:
        f.write("Google Earth Engine Assets Used\n")
        f.write("=" * 60 + "\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")

        if isinstance(assets_used, dict):
            for name, asset_id in assets_used.items():
                f.write(f"{name}:\n  {asset_id}\n\n")
        else:
            for asset_id in assets_used:
                f.write(f"{asset_id}\n")

    return filepath
