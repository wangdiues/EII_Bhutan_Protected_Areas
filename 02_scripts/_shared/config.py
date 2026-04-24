#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py
Central configuration for EII Bhutan Protected Areas analysis.
"""

__version__ = "1.2.0"

import os
from pathlib import Path

# =============================================================================
# BASE PATHS
# =============================================================================

DEFAULT_BASE_DIR = Path(__file__).resolve().parents[2]

CONFIG = {
    # Project info
    "project_name": "EII_Bhutan_Protected_Areas",
    "project_title": "Ecosystem Integrity of Bhutan's Protected Area Network",

    # GEE Service Account
    # Prefer EII_GEE_SERVICE_ACCOUNT and EII_GEE_KEY_PATH in the environment.
    # If EII_GEE_KEY_PATH is not set, the pipeline uses the only non-example
    # JSON key file found in 06_Google_application_credentials/.
    "gee_service_account": None,
    "gee_key_filename": None,

    # GEE Assets (AUTHORITATIVE - DO NOT MODIFY)
    "gee_eii_asset": "projects/landler-open-data/assets/eii/global/eii_global_v1",
    "gee_npp_asset": "projects/landler-open-data/assets/eii/predictions/npp",

    # EII Bands
    "eii_bands": ["eii", "functional_integrity", "structural_integrity", "compositional_integrity"],
    "eii_main_band": "eii",
    "eii_component_bands": ["functional_integrity", "structural_integrity", "compositional_integrity"],

    # Analysis Parameters
    "analysis_scale": 300,  # meters
    "analysis_crs": "EPSG:4326",
    "source_crs": "EPSG:5266",  # DRUKREF03 TM
    "percentiles": [5, 25, 50, 75, 95],

    # Validation
    "expected_pa_count": 20,

    # Input layers
    "bhutan_boundary_layer": "bhutan_boundary",
    "protected_areas_layer": "protected_areas_btn",

    # PA attribute fields
    "pa_name_field": "PA_name",
    "pa_category_field": "park",
    "pa_area_field": "Area_km2",
    "excluded_raw_pa_names": [],

    # Network retry settings
    "max_retries": 3,
    "retry_delay_seconds": 5,

    # Output figure settings
    "figure_dpi": 300,
    "figure_format": "png",

    # =============================================================================
    # EXTENSION: Counterfactual & Triangulation Analysis (Scripts 12-16)
    # =============================================================================

    # Buffer distances for counterfactual analysis (in meters)
    "buffer_distances_m": [10000],  # Default 10km; can add 5000, 20000
    "default_buffer_m": 10000,

    # GEE Covariates for triangulation
    "gee_covariates": {
        "human_modification": {
            "asset": "CSP/HM/GlobalHumanModification",
            "band": "gHM",
            "description": "Global Human Modification Index (0-1)",
            "date_range": None,  # Static dataset
        },
        "hansen_forest": {
            "asset": "UMD/hansen/global_forest_change_2024_v1_12",
            "bands": {
                "treecover2000": "treecover2000",
                "loss": "loss",
                "lossyear": "lossyear",
            },
            "description": "Hansen Global Forest Change v1.12",
            "date_range": ["2001-01-01", "2024-12-31"],
        },
        "ndvi_modis": {
            "asset": "MODIS/061/MOD13Q1",
            "band": "NDVI",
            "description": "MODIS Terra NDVI 16-day 250m",
            "date_range": ["2001-01-01", "2024-12-31"],
            "scale_factor": 0.0001,
        },
        "burned_area": {
            "asset": "MODIS/061/MCD64A1",
            "band": "BurnDate",
            "description": "MODIS Burned Area Monthly 500m",
            "date_range": ["2001-01-01", "2024-12-31"],
        },
        "worldcover": {
            "asset": "ESA/WorldCover/v200",
            "band": "Map",
            "description": "ESA WorldCover 10m v200",
            "date_range": ["2021-01-01", "2021-12-31"],
            "classes": {
                "cropland": 40,
                "built_up": 50,
            },
        },
        "elevation": {
            "asset": "USGS/SRTMGL1_003",
            "band": "elevation",
            "description": "SRTM Digital Elevation 30m",
            "date_range": None,  # Static dataset
        },
    },

    # GEDI canopy height for validation
    "gee_validation": {
        "gedi_canopy": {
            "asset": "LARSE/GEDI/GEDI02_A_002_MONTHLY",
            "band": "rh98",
            "description": "GEDI L2A Monthly Canopy Height (rh98)",
            "date_range": ["2019-04-01", "2024-12-31"],
        },
    },

    # Model sampling parameters
    "model_sampling": {
        "target_points": 50000,
        "min_points_per_stratum": 100,
        "random_seed": 42,
    },

    # Concordance analysis parameters
    "concordance_metrics": ["pearson_r", "spearman_rho", "rank_diff"],
}


def get_base_dir(override=None):
    """Get base directory, with optional override."""
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_BASE_DIR


def _is_real_gee_key_candidate(path):
    """Return True for local credential JSON files, excluding public examples."""
    return path.suffix == ".json" and not path.name.endswith(".example.json")


def get_path(key, base_dir=None):
    """
    Get path for a known location.

    Keys:
        - base: Base project directory
        - admin: 00_admin
        - raw: 01_data/01_raw
        - raw_boundaries: 01_data/01_raw/boundaries
        - gee_exports: 01_data/01_raw/gee_exports
        - gee_eii: 01_data/01_raw/gee_exports/eii_global
        - gee_components: 01_data/01_raw/gee_exports/components
        - gee_npp: 01_data/01_raw/gee_exports/npp_predictions
        - processed: 01_data/02_processed
        - processed_rasters: 01_data/02_processed/rasters
        - processed_vectors: 01_data/02_processed/vectors
        - tables: 01_data/03_tables
        - scripts: 02_scripts
        - results: 03_results
        - figures: 03_results/figures
        - results_tables: 03_results/tables
        - manuscript: 04_manuscript
        - reproducibility: 05_reproducibility
        - errors: 05_reproducibility/errors
        - validation: 05_reproducibility/validation
        - credentials: 06_Google_application_credentials
        - bhutan_boundary: GeoPackage path
        - protected_areas: GeoPackage path
        - gee_key: Service account key path
    """
    base = get_base_dir(base_dir)

    if key == "gee_key":
        env_path = os.getenv("EII_GEE_KEY_PATH")
        if env_path:
            return Path(env_path).expanduser().resolve()

    paths = {
        "base": base,
        "admin": base / "00_admin",
        "raw": base / "01_data" / "01_raw",
        "raw_boundaries": base / "01_data" / "01_raw" / "boundaries",
        "raw_bhutan_boundary": base / "01_data" / "01_raw" / "boundaries" / "Bhutan.shp",
        "raw_protected_areas": base / "01_data" / "01_raw" / "boundaries" / "PA_BC.shp",
        "gee_exports": base / "01_data" / "01_raw" / "gee_exports",
        "gee_eii": base / "01_data" / "01_raw" / "gee_exports" / "eii_global",
        "gee_components": base / "01_data" / "01_raw" / "gee_exports" / "components",
        "gee_npp": base / "01_data" / "01_raw" / "gee_exports" / "npp_predictions",
        "processed": base / "01_data" / "02_processed",
        "processed_rasters": base / "01_data" / "02_processed" / "rasters",
        "processed_vectors": base / "01_data" / "02_processed" / "vectors",
        "tables": base / "01_data" / "03_tables",
        "scripts": base / "02_scripts",
        "results": base / "03_results",
        "figures": base / "03_results" / "figures",
        "results_tables": base / "03_results" / "tables",
        "manuscript": base / "04_manuscript",
        "reproducibility": base / "05_reproducibility",
        "logs": base / "05_reproducibility" / "logs",
        "errors": base / "05_reproducibility" / "errors",
        "validation": base / "05_reproducibility" / "validation",
        "credentials": base / "06_Google_application_credentials",
        # Specific files
        "bhutan_boundary": base / "01_data" / "02_processed" / "vectors" / "bhutan_boundary.gpkg",
        "protected_areas": base / "01_data" / "02_processed" / "vectors" / "protected_areas_btn.gpkg",
        "gee_key": base / "06_Google_application_credentials" / "service-account-key.json",
    }

    if key == "gee_key":
        credentials_dir = paths["credentials"]
        configured_filename = CONFIG.get("gee_key_filename")
        if configured_filename:
            return credentials_dir / configured_filename

        key_candidates = sorted(
            path for path in credentials_dir.glob("*.json") if _is_real_gee_key_candidate(path)
        )
        if len(key_candidates) == 1:
            return key_candidates[0]

    if key not in paths:
        raise KeyError(f"Unknown path key: {key}. Valid keys: {list(paths.keys())}")

    return paths[key]


def validate_paths(base_dir=None, required_keys=None):
    """
    Validate that required paths exist.

    Args:
        base_dir: Optional base directory override
        required_keys: List of path keys to validate (default: critical inputs)

    Returns:
        dict: {"valid": bool, "missing": list of missing paths}
    """
    if required_keys is None:
        required_keys = ["raw_bhutan_boundary", "raw_protected_areas", "gee_key"]

    missing = []
    for key in required_keys:
        path = get_path(key, base_dir)
        if not path.exists():
            missing.append(str(path))

    return {
        "valid": len(missing) == 0,
        "missing": missing
    }


if __name__ == "__main__":
    # Test configuration
    print("EII Bhutan Protected Areas - Configuration Test")
    print("=" * 60)
    print(f"Base directory: {get_path('base')}")
    print(f"Protected Areas: {get_path('protected_areas')}")
    print(f"GEE Key: {get_path('gee_key')}")
    print()

    result = validate_paths()
    if result["valid"]:
        print("All required paths exist.")
    else:
        print("Missing paths:")
        for p in result["missing"]:
            print(f"  - {p}")
