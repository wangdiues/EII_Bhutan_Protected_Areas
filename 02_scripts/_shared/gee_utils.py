#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gee_utils.py
Shared Google Earth Engine credential and initialization helpers.
"""

import json
import math
import os
from pathlib import Path

import ee
import pandas as pd

from .config import CONFIG, get_path


def get_gee_service_account():
    """Return the configured GEE service account, allowing env override."""
    return os.getenv("EII_GEE_SERVICE_ACCOUNT", CONFIG["gee_service_account"])


def get_gee_key_path(base_dir=None):
    """Return the service-account key path, allowing env override."""
    env_path = os.getenv("EII_GEE_KEY_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return get_path("gee_key", base_dir)


def authenticate_gee(base_dir=None, logger=None):
    """
    Authenticate to Earth Engine using the configured service account.

    Args:
        base_dir: Optional project base directory
        logger: Optional logger instance

    Returns:
        Path to the key file used for authentication
    """
    key_path = get_gee_key_path(base_dir)

    if not key_path.exists():
        raise FileNotFoundError(
            f"GEE service account key not found: {key_path}. "
            "Set EII_GEE_KEY_PATH to a valid JSON key file."
        )

    service_account = get_gee_service_account()
    if not service_account:
        with open(key_path, "r", encoding="utf-8") as f:
            service_account = json.load(f).get("client_email")

    if not service_account:
        raise ValueError(
            "GEE service account email is not configured. Set "
            "EII_GEE_SERVICE_ACCOUNT or use a JSON key with client_email."
        )

    if logger:
        logger.info(f"Authenticating with service account: {service_account}")
        logger.info(f"Key file: {key_path}")

    credentials = ee.ServiceAccountCredentials(service_account, str(key_path))
    ee.Initialize(credentials=credentials)

    if logger:
        logger.info("GEE authentication successful")

    return key_path


def geometry_to_ee(geometry):
    """
    Convert a shapely geometry into an Earth Engine geometry using
    JSON-safe coordinates and explicit Polygon/MultiPolygon constructors.
    """
    geojson = json.loads(json.dumps(geometry.__geo_interface__))

    def strip_to_2d(coords):
        if isinstance(coords, (list, tuple)):
            if coords and isinstance(coords[0], (int, float)):
                if len(coords) < 2:
                    raise ValueError("Coordinate has fewer than two numbers")
                x = float(coords[0])
                y = float(coords[1])
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise ValueError(f"Non-finite coordinate encountered: {coords}")
                return [x, y]
            return [strip_to_2d(part) for part in coords]
        return coords

    geojson["coordinates"] = strip_to_2d(geojson.get("coordinates", []))
    geom_type = geojson.get("type")
    coords = geojson.get("coordinates")

    return ee.Geometry(geojson, proj="EPSG:4326", geodesic=False)


def prepare_gdf_for_ee(gdf, tolerance_m=90):
    """
    Simplify geometries for Earth Engine transfer only.

    Returns a WGS84 GeoDataFrame suitable for inline upload while leaving
    canonical stored geometries unchanged.
    """
    if gdf.crs is None:
        raise ValueError("GeoDataFrame has no CRS")

    gdf_metric = gdf.to_crs(CONFIG["source_crs"])
    gdf_metric = gdf_metric.copy()
    gdf_metric["geometry"] = gdf_metric.geometry.simplify(
        tolerance_m,
        preserve_topology=True
    ).make_valid()

    gdf_ee = gdf_metric.to_crs("EPSG:4326")
    if not gdf_ee.is_valid.all():
        raise ValueError("Simplified GeoDataFrame contains invalid geometries")

    return gdf_ee


def iter_gdf_batches(gdf, batch_size):
    """Yield GeoDataFrame batches with reset index."""
    for start in range(0, len(gdf), batch_size):
        yield gdf.iloc[start:start + batch_size].reset_index(drop=True)
