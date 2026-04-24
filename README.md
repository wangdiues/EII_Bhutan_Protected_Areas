# Ecosystem Integrity Index (EII) Analysis for Bhutan's Protected Area Network

## Implementation Guide

A production-grade geospatial analysis pipeline for assessing Ecosystem Integrity across Bhutan's 20 protected-area network units using Google Earth Engine.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites](#2-prerequisites)
3. [Installation](#3-installation)
4. [Project Structure](#4-project-structure)
5. [Configuration](#5-configuration)
6. [Step-by-Step Execution Guide](#6-step-by-step-execution-guide)
7. [Output Files](#7-output-files)
8. [Troubleshooting](#8-troubleshooting)
9. [Scientific Notes](#9-scientific-notes)
10. [Version History](#10-version-history)
11. [Research Operations](#11-research-operations)

---

## 1. Project Overview

### Purpose

This pipeline computes and analyzes the **Ecosystem Integrity Index (EII)** for Bhutan's Protected Area Network. It downloads precomputed EII data from Google Earth Engine public assets, performs zonal statistics for each Protected Area, and generates publication-ready figures and tables.

### Key Features

- Automated data download from Google Earth Engine
- Zonal statistics computation (mean, standard deviation, percentiles)
- PA category comparison analysis
- Network-wide summary statistics
- **Counterfactual analysis** (inside vs outside PA comparison)
- **Multi-metric triangulation** (EII vs independent pressure/condition datasets)
- **Inferential drivers modeling** (OLS regression + RandomForest importance)
- **Empirical validation** (GEDI canopy height, NDVI, forest loss)
- Publication-quality maps and figures (300 DPI)
- Complete reproducibility documentation

### Data Sources

| Dataset | Source | Asset Path |
|---------|--------|------------|
| EII Global | Landler Open Data | `projects/landler-open-data/assets/eii/global/eii_global_v1` |
| NPP Predictions | Landler Open Data | `projects/landler-open-data/assets/eii/predictions/npp` |
| Human Modification Index | CSP | `CSP/HM/GlobalHumanModification` |
| Hansen Forest Change | UMD | `UMD/hansen/global_forest_change_2024_v1_12` |
| MODIS NDVI | NASA | `MODIS/061/MOD13Q1` |
| MODIS Burned Area | NASA | `MODIS/061/MCD64A1` |
| ESA WorldCover | ESA | `ESA/WorldCover/v200` |
| SRTM Elevation | USGS | `USGS/SRTMGL1_003` |
| GEDI Canopy Height | LARSE | `LARSE/GEDI/GEDI02_A_002_MONTHLY` |
| Protected Areas | Local | `01_data/02_processed/vectors/protected_areas_btn.gpkg` |
| Bhutan Boundary | Local | `01_data/02_processed/vectors/bhutan_boundary.gpkg` |

---

## 2. Prerequisites

### System Requirements

- **Operating System**: Windows 10/11, Linux, or macOS
- **Python**: Version 3.10 or higher
- **Internet Connection**: Required for Google Earth Engine access
- **Disk Space**: Minimum 500 MB for outputs

### Google Earth Engine Account

You need a valid Google Earth Engine service account with credentials. Configure it with environment variables:
- **Service Account**: `EII_GEE_SERVICE_ACCOUNT`
- **Credentials File**: `EII_GEE_KEY_PATH`

If `EII_GEE_KEY_PATH` is not set, the pipeline will use the only non-example `.json` key found in `06_Google_application_credentials/`. Do not commit real credential files. The repository includes `fake_service_account.example.json.template` only as a template.

### Required Input Data

Ensure the following files exist before starting:

| File | Location | Description |
|------|----------|-------------|
| Protected Areas | `01_data/02_processed/vectors/protected_areas_btn.gpkg` | 20 protected-area network units |
| Bhutan Boundary | `01_data/02_processed/vectors/bhutan_boundary.gpkg` | Country boundary |
| GEE Credentials | `06_Google_application_credentials/*.json` | Local service account key; only the fake example is tracked |

---

## 3. Installation

### Step 3.1: Clone or Download the Project

```bash
# If using git:
git clone <repository_url> EII_Bhutan_Protected_Areas
cd EII_Bhutan_Protected_Areas
# Or download and extract the zip file, then cd into the project root
```

### Step 3.2: Create a Virtual Environment (Recommended)

```bash
# From the project root
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Linux/macOS
source venv/bin/activate
```

### Step 3.3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Required packages:**
```
geopandas>=0.14.0
shapely>=2.0.0
pyproj>=3.6.0
fiona>=1.9.0
rasterio>=1.3.0
pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
earthengine-api>=0.1.380
requests>=2.31.0
pyyaml>=6.0
statsmodels>=0.14.0
scipy>=1.11.0
scikit-learn>=1.3.0
```

### Step 3.4: Verify Installation

```bash
python -c "import geopandas; import ee; import statsmodels; import sklearn; print('All packages installed successfully')"
```

---

## 4. Project Structure

```
EII_Bhutan_Protected_Areas/
│
├── 00_admin/                    # Project administration
│   ├── CHANGELOG.md             # Version history
│   ├── journal_targets.md       # Publication targets
│   ├── project_notes.md         # Project metadata
│   └── todo_checklist.md        # Task tracking
│
├── 01_data/                     # Data storage
│   ├── 01_raw/                  # Raw input data
│   │   ├── boundaries/          # Original shapefiles
│   │   └── gee_exports/         # GEE-derived data
│   │       ├── components/      # EII component rasters
│   │       ├── eii_global/      # Global EII rasters
│   │       └── npp_predictions/ # NPP data
│   ├── 02_processed/            # Cleaned data
│   │   └── vectors/             # GeoPackage files
│   └── 03_tables/               # Intermediate CSV tables
│
├── 02_scripts/                  # Python analysis pipeline
│   ├── 01_setup/                # Setup scripts
│   │   ├── 01_authenticate_gee.py
│   │   └── 02_define_aoi.py
│   ├── 02_download/             # Data download scripts
│   │   ├── 03_download_eii.py
│   │   ├── 04_download_components.py
│   │   ├── 05_download_npp.py
│   │   └── 12_prepare_covariates.py     # NEW: Covariate preparation
│   ├── 03_analysis/             # Analysis scripts
│   │   ├── 06_pa_zonal_stats.py
│   │   ├── 07_compare_pa_categories.py
│   │   ├── 08_summary_statistics.py
│   │   ├── 12_inside_outside_buffers.py # NEW: Counterfactual analysis
│   │   ├── 13_covariates_zonal_stats.py # NEW: Covariate concordance
│   │   ├── 14_sample_points_for_models.py # NEW: Stratified sampling
│   │   ├── 15_models_drivers.py         # NEW: Inferential modeling
│   │   └── 16_validation.py             # NEW: Empirical validation
│   ├── 04_visualization/        # Figure generation scripts
│   │   ├── 09_maps_eii.py
│   │   ├── 10_maps_components.py
│   │   ├── 11_figures_publication.py
│   │   └── 12_figures_counterfactual_and_covariates.py # NEW: Extended figures
│   ├── _shared/                 # Shared utilities
│   │   └── config.py            # Central configuration
│   ├── logs/                    # Execution logs
│   ├── run_all.py               # Master pipeline runner
│   └── run_order.yaml           # Execution order config
│
├── 03_results/                  # Analysis outputs
│   ├── figures/                 # Generated maps (PNG, 300 DPI)
│   └── tables/                  # Publication tables (CSV)
│
├── 04_manuscript/               # Publication materials
│
├── 05_reproducibility/          # Reproducibility documentation
│   ├── requirements.txt         # Python dependencies
│   ├── environment.yml          # Conda environment
│   ├── gee_assets_used.txt      # GEE assets log
│   ├── errors/                  # Error logs
│   └── validation/              # Validation reports
│
├── 06_Google_application_credentials/  # Ignored local GEE key plus tracked fake example
│
├── Scripting_prompt.md          # Original scripting specification
├── Manuscript_prompt.md         # Original manuscript specification
├── README.md                    # This file
├── requirements.txt             # Python dependencies
└── test_eii_public.py           # GEE connectivity test
```

---

## 5. Configuration

### 5.1 Central Configuration File

All settings are managed in `02_scripts/_shared/config.py`:

```python
CONFIG = {
    # GEE credentials are supplied by environment variables:
    # EII_GEE_SERVICE_ACCOUNT and EII_GEE_KEY_PATH

    # GEE Assets (DO NOT MODIFY)
    "gee_eii_asset": "projects/landler-open-data/assets/eii/global/eii_global_v1",
    "gee_npp_asset": "projects/landler-open-data/assets/eii/predictions/npp",

    # GEE Covariates for triangulation
    "gee_covariates": {
        "human_modification": {"asset": "CSP/HM/GlobalHumanModification", "band": "gHM"},
        "hansen_forest": {"asset": "UMD/hansen/global_forest_change_2024_v1_12", ...},
        "ndvi_modis": {"asset": "MODIS/061/MOD13Q1", "band": "NDVI"},
        "burned_area": {"asset": "MODIS/061/MCD64A1", "band": "BurnDate"},
        "worldcover": {"asset": "ESA/WorldCover/v200", "band": "Map"},
        "elevation": {"asset": "USGS/SRTMGL1_003", "band": "elevation"},
    },

    # Validation datasets
    "gee_validation": {
        "gedi_canopy": {"asset": "LARSE/GEDI/GEDI02_A_002_MONTHLY", "band": "rh98"},
    },

    # Buffer analysis
    "buffer_distances_m": [10000],  # 10km default

    # Model sampling
    "model_sampling": {
        "target_points": 50000,
        "min_points_per_stratum": 100,
        "random_seed": 42,
    },

    # Analysis Parameters
    "analysis_scale": 300,           # Meters
    "analysis_crs": "EPSG:4326",     # WGS84
    "percentiles": [5, 25, 50, 75, 95],

    # Output Settings
    "figure_dpi": 300,
    "figure_format": "png",
}
```

### 5.2 Command-Line Arguments

All scripts support these common arguments:

| Argument | Description |
|----------|-------------|
| `--base-dir PATH` | Override project base directory |
| `--overwrite` | Overwrite existing output files |
| `--allow-pa-count-mismatch` | Allow PA count different from 20 |
| `--allow-geometry-simplification` | Allow geometry simplification |
| `--enable-exports` | Enable GEE batch exports to Drive |
| `--enable-method-compare` | Enable EII sensitivity analysis |

**Extended analysis scripts (12-16) also support:**

| Argument | Description |
|----------|-------------|
| `--multi-buffer` | Enable multiple buffer distances (5, 10, 20 km) |
| `--buffer-km N` | Custom buffer distance in kilometers |
| `--target-points N` | Number of sample points for modeling (default: 50000) |
| `--force-fallback` | Force fallback validation method (NDVI instead of GEDI) |

### 5.3 Credential Setup

Recommended setup:

```bash
set EII_GEE_SERVICE_ACCOUNT=your-service-account@your-project.iam.gserviceaccount.com
set EII_GEE_KEY_PATH=D:\path\to\service-account-key.json
```

On Linux/macOS:

```bash
export EII_GEE_SERVICE_ACCOUNT=your-service-account@your-project.iam.gserviceaccount.com
export EII_GEE_KEY_PATH=/path/to/service-account-key.json
```

The repository includes `.env.example` as a template. Real JSON keys are ignored by Git.

---

## 6. Step-by-Step Execution Guide

### Option A: Run Full Pipeline (Recommended)

Execute all scripts in the correct order:

```bash
cd 02_scripts
python run_all.py
```

**With common options:**
```bash
# Overwrite existing outputs
python run_all.py --overwrite

# Enable sensitivity analysis
python run_all.py --enable-method-compare

# Dry run (show what would execute)
python run_all.py --dry-run
```

### Option B: Run Individual Stages

#### Stage 1: Setup

**Step 1.1: Authenticate to Google Earth Engine**

```bash
cd 02_scripts/01_setup
python 01_authenticate_gee.py
```

**What it does:**
- Loads service account credentials from environment variables or a local ignored JSON key
- Initializes Earth Engine
- Tests connectivity with FAO/GAUL Bhutan boundary
- Creates success marker: `_SUCCESS_01_authenticate_gee.txt`

**Expected output:**
```
[INFO] Authenticating to Google Earth Engine...
[INFO] Using service account: your-service-account@...
[INFO] Authentication successful!
[INFO] Testing GEE connectivity...
[INFO] GEE test passed. Ready to proceed.
```

**Step 1.2: Define Area of Interest**

```bash
python 02_define_aoi.py
```

**What it does:**
- Loads Protected Areas and Bhutan boundary
- Validates PA count (expects 20)
- Converts CRS from DRUKREF03 TM (EPSG:5266) to WGS84 (EPSG:4326)
- Exports GeoJSON for GEE operations

**Optional flags:**
```bash
# Allow PA count mismatch
python 02_define_aoi.py --allow-pa-count-mismatch

# Enable geometry simplification (for large complex geometries)
python 02_define_aoi.py --allow-geometry-simplification --simplify-tolerance 0.001
```

---

#### Stage 2: Download Data from GEE

**Step 2.1: Download EII Zonal Statistics (REQUIRED)**

```bash
cd 02_scripts/02_download
python 03_download_eii.py
```

**What it does:**
- Loads the public EII asset from GEE
- Computes zonal statistics for each of 20 protected-area network units:
  - Mean EII
  - Standard deviation
  - Percentiles (5th, 25th, 50th, 75th, 95th)
- Saves results to `01_data/03_tables/pa_eii_stats.csv`
- Logs GEE assets used to `05_reproducibility/gee_assets_used.txt`

**CRITICAL**: This script uses the precomputed `eii` band directly. It does NOT recalculate EII from components.

**Optional: Enable sensitivity analysis:**
```bash
python 03_download_eii.py --enable-method-compare
```
This computes additional indices (minimum, product, geometric mean) for method comparison.

**Step 2.2: Download Component Rasters (Optional)**

```bash
python 04_download_components.py --enable-exports
```

**What it does:**
- Downloads EII component rasters (functional, structural, compositional)
- Clips to Bhutan boundary
- Saves GeoTIFFs to `01_data/01_raw/gee_exports/components/`

**Note:** Requires `--enable-exports` flag. Exports go to your Google Drive first.

**Step 2.3: Download NPP Predictions (Optional)**

```bash
python 05_download_npp.py
```

**What it does:**
- Downloads Net Primary Productivity predictions
- Computes zonal statistics per PA
- For supplementary analysis only

---

#### Stage 3: Analysis

**Step 3.1: Process PA Zonal Statistics**

```bash
cd 02_scripts/03_analysis
python 06_pa_zonal_stats.py
```

**What it does:**
- Loads raw EII stats from `01_data/03_tables/pa_eii_stats.csv`
- Formats data for publication
- Creates:
  - `03_results/tables/table1_pa_eii_summary.csv` - PA-level EII summary
  - `03_results/tables/table2_components_by_pa.csv` - Component integrity by PA

**Step 3.2: Compare PA Categories**

```bash
python 07_compare_pa_categories.py
```

**What it does:**
- Groups PAs by category (park type)
- Computes category-level statistics
- Performs pairwise comparisons between categories

**Step 3.3: Generate Network Summary Statistics**

```bash
python 08_summary_statistics.py
```

**What it does:**
- Computes network-wide aggregates:
  - Simple mean (unweighted)
  - Area-weighted mean
  - Pixel-weighted mean
- Distribution statistics (median, std, range)
- Creates `03_results/tables/bhutan_network_summary.csv`

---

#### Stage 4: Visualization

**Step 4.1: Generate EII Choropleth Map**

```bash
cd 02_scripts/04_visualization
python 09_maps_eii.py
```

**What it does:**
- Creates choropleth map showing EII values across PAs
- Color scale: Low (red) to High (green)
- Output: `03_results/figures/fig1_eii_map.png` (300 DPI)

**Step 4.2: Generate Component Maps (Optional)**

```bash
python 10_maps_components.py
```

**What it does:**
- Creates 3-panel figure showing:
  - Functional integrity
  - Structural integrity
  - Compositional integrity
- Requires component rasters from Step 2.2
- Output: `03_results/figures/fig3_components.png`

**Step 4.3: Generate Publication Figures**

```bash
python 11_figures_publication.py
```

**What it does:**
- Creates bar chart comparing PA EII values
- Output: `03_results/figures/fig2_pa_comparison.png`
- With `--enable-method-compare`: Creates sensitivity analysis figure

---

#### Stage 5: Extended Analysis (Counterfactual & Triangulation)

**Step 5.1: Prepare Covariates**

```bash
cd 02_scripts/02_download
python 12_prepare_covariates.py
```

**What it does:**
- Validates all GEE covariate datasets are accessible
- Tests asset connectivity for each covariate
- Creates covariate manifest for downstream scripts
- Outputs:
  - `01_data/03_tables/covariate_assets_validation.csv`
  - `01_data/03_tables/covariate_manifest.json`

**Step 5.2: Inside vs Outside Buffer Analysis**

```bash
cd 02_scripts/03_analysis
python 12_inside_outside_buffers.py
```

**What it does:**
- Creates 10km buffers around each PA boundary
- Computes EII zonal stats inside vs outside (excluding other PAs)
- Calculates delta (inside - outside) for each PA
- Outputs:
  - `01_data/03_tables/pa_inside_outside_stats.csv`
  - `03_results/tables/table4_inside_vs_outside.csv`

**Optional flags:**
```bash
# Enable multiple buffer distances (5, 10, 20 km)
python 12_inside_outside_buffers.py --multi-buffer

# Custom buffer distance
python 12_inside_outside_buffers.py --buffer-km 15
```

**Step 5.3: Covariate Zonal Statistics**

```bash
python 13_covariates_zonal_stats.py
```

**What it does:**
- Computes per-PA zonal stats for all covariates:
  - Human Modification Index
  - Hansen forest cover / forest loss
  - NDVI trend (2015-2023)
  - Burned area frequency
  - ESA WorldCover proportions
  - Elevation and slope
- Calculates EII-covariate concordance (Pearson, Spearman)
- Outputs:
  - `01_data/03_tables/pa_covariates_stats.csv`
  - `03_results/tables/table5_covariates_summary.csv`
  - `03_results/tables/table5b_eii_covariate_concordance.csv`

**Step 5.4: Generate Sample Points for Modeling**

```bash
python 14_sample_points_for_models.py
```

**What it does:**
- Creates stratified random sample (~50,000 points)
- Stratifies by: inside/outside PA, elevation bands, PA identity
- Extracts EII and all covariates at each point
- Outputs:
  - `01_data/03_tables/model_points_eii_covariates.csv`

**Optional flags:**
```bash
# Custom number of sample points
python 14_sample_points_for_models.py --target-points 100000
```

**Step 5.5: Inferential Drivers Modeling**

```bash
python 15_models_drivers.py
```

**What it does:**
- **Model 1 (Counterfactual OLS)**: EII ~ PA_status + elevation + slope
  - Cluster-robust standard errors (by PA)
  - Tests if protected status predicts higher EII
- **Model 2 (Drivers OLS)**: EII ~ HMI + forest_loss + NDVI_trend + burned_area + ...
  - Identifies which pressures most strongly predict EII
- **Model 3 (RandomForest)**: Variable importance ranking
  - 5-fold cross-validation
  - Permutation importance scores
- Outputs:
  - `03_results/tables/table6_models_coefficients.csv`
  - `03_results/tables/table6b_models_diagnostics.csv`
  - `03_results/tables/table6c_rf_importance.csv`
  - `03_results/figures/fig5_counterfactual_coef.png`
  - `03_results/figures/fig6_drivers_coef.png`
  - `03_results/figures/fig6b_rf_importance.png`

**Step 5.6: Empirical Validation**

```bash
python 16_validation.py
```

**What it does:**
- **Primary validation**: GEDI canopy height (rh98) vs EII
- **Fallback validation**: NDVI mean, forest loss % vs EII
- Computes Pearson and Spearman correlations
- Outputs:
  - `03_results/tables/table7_validation.csv`
  - `03_results/figures/fig7_validation_scatter.png`

**Optional flags:**
```bash
# Force fallback validation (skip GEDI)
python 16_validation.py --force-fallback
```

**Step 5.7: Extended Figures**

```bash
cd 02_scripts/04_visualization
python 12_figures_counterfactual_and_covariates.py
```

**What it does:**
- Creates publication-quality figures for extended analysis:
  - Fig 8: Inside vs Outside boxplot
  - Fig 9: Delta (inside - outside) summary bar chart
  - Fig 10: EII vs Human Modification scatter
  - Fig 11: EII vs Forest Loss scatter
- Outputs:
  - `03_results/figures/fig8_inside_outside_boxplot.png`
  - `03_results/figures/fig9_delta_summary.png`
  - `03_results/figures/fig10_eii_vs_hmi.png`
  - `03_results/figures/fig11_eii_vs_forest_loss.png`

---

### Execution Summary Table

| Script | Stage | Required | Depends On | Output |
|--------|-------|----------|------------|--------|
| `01_authenticate_gee.py` | Setup | Yes | - | Success marker |
| `02_define_aoi.py` | Setup | Yes | Script 01 | GeoJSON, CSV |
| `03_download_eii.py` | Download | Yes | Script 02 | `pa_eii_stats.csv` |
| `04_download_components.py` | Download | No | Script 02 | GeoTIFFs |
| `05_download_npp.py` | Download | No | Script 02 | `npp_stats.csv` |
| `06_pa_zonal_stats.py` | Analysis | Yes | Script 03 | Table 1, Table 2 |
| `07_compare_pa_categories.py` | Analysis | Yes | Script 06 | Category comparison |
| `08_summary_statistics.py` | Analysis | Yes | Script 07 | Network summary |
| `09_maps_eii.py` | Visualization | Yes | Script 06 | `fig1_eii_map.png` |
| `10_maps_components.py` | Visualization | No | Script 06 | `fig3_components.png` |
| `11_figures_publication.py` | Visualization | Yes | Script 08 | `fig2_pa_comparison.png` |
| `12_prepare_covariates.py` | Extended | Yes | Script 03 | Covariate manifest |
| `12_inside_outside_buffers.py` | Extended | Yes | Script 03 | Table 4 |
| `13_covariates_zonal_stats.py` | Extended | Yes | Script 12 (prep) | Table 5, 5b |
| `14_sample_points_for_models.py` | Extended | Yes | Scripts 12 | Sample points CSV |
| `15_models_drivers.py` | Extended | Yes | Script 14 | Table 6, Fig 5-6 |
| `16_validation.py` | Extended | Yes | Script 03 | Table 7, Fig 7 |
| `12_figures_counterfactual...py` | Extended | Yes | Scripts 12, 13 | Fig 8-11 |

---

## 7. Output Files

### Publication Tables (`03_results/tables/`)

| File | Description | Columns |
|------|-------------|---------|
| `table1_pa_eii_summary.csv` | PA-level EII statistics | PA_name, Category, Area_km2, Mean_EII, StdDev, P5-P95 |
| `table2_components_by_pa.csv` | Component integrity by PA | PA_name, Functional, Structural, Compositional |
| `bhutan_network_summary.csv` | Network-wide summary | Aggregated statistics |
| `table4_inside_vs_outside.csv` | Counterfactual comparison | PA_name, EII_inside, EII_outside, Delta, Buffer_km |
| `table5_covariates_summary.csv` | Covariate stats by PA | PA_name, HMI, ForestCover, ForestLoss, NDVI, ... |
| `table5b_eii_covariate_concordance.csv` | EII-covariate correlations | Covariate, Pearson_r, Spearman_rho, p_value |
| `table6_models_coefficients.csv` | Regression coefficients | Variable, Coef, SE, t, p, Model |
| `table6b_models_diagnostics.csv` | Model fit statistics | Model, R2, AdjR2, RMSE, N |
| `table6c_rf_importance.csv` | RandomForest importance | Variable, Importance, Rank |
| `table7_validation.csv` | Validation results | Metric, Pearson_r, Spearman_rho, N, Method |

### Publication Figures (`03_results/figures/`)

| File | Description | Format |
|------|-------------|--------|
| `fig1_eii_map.png` | EII choropleth map | PNG, 300 DPI |
| `fig2_pa_comparison.png` | PA comparison bar chart | PNG, 300 DPI |
| `fig3_components.png` | Component integrity maps | PNG, 300 DPI |
| `fig4_method_sensitivity.png` | Sensitivity analysis (optional) | PNG, 300 DPI |
| `fig5_counterfactual_coef.png` | Counterfactual model coefficients | PNG, 300 DPI |
| `fig6_drivers_coef.png` | Drivers model coefficients | PNG, 300 DPI |
| `fig6b_rf_importance.png` | RandomForest variable importance | PNG, 300 DPI |
| `fig7_validation_scatter.png` | EII vs validation metric scatter | PNG, 300 DPI |
| `fig8_inside_outside_boxplot.png` | Inside vs outside EII boxplot | PNG, 300 DPI |
| `fig9_delta_summary.png` | Delta (inside-outside) by PA | PNG, 300 DPI |
| `fig10_eii_vs_hmi.png` | EII vs Human Modification | PNG, 300 DPI |
| `fig11_eii_vs_forest_loss.png` | EII vs Forest Loss | PNG, 300 DPI |

### Reproducibility Files (`05_reproducibility/`)

| File | Description |
|------|-------------|
| `gee_assets_used.txt` | Log of all GEE assets referenced |
| `validation/*.txt` | Validation reports for each successful script |
| `errors/*.txt` | Error logs for failed scripts |

---

## 8. Troubleshooting

### Common Issues

#### GEE Authentication Failed

**Error:** `Authentication failed: Invalid credentials`

**Solution:**
1. Verify `EII_GEE_KEY_PATH` points to a valid JSON key, or that exactly one non-example JSON key exists in `06_Google_application_credentials/`
2. Check `EII_GEE_SERVICE_ACCOUNT`, or confirm the key JSON contains `client_email`
3. Ensure the service account has Earth Engine access enabled

```bash
# Test GEE connectivity
python test_eii_public.py
```

#### PA Count Mismatch

**Error:** `Expected 20 Protected Areas, found X`

**Solution:**
1. Verify the input GeoPackage contains all 20 protected-area network units
2. Or use the override flag: `--allow-pa-count-mismatch`

#### Missing Input Files

**Error:** `FileNotFoundError: protected_areas_btn.gpkg not found`

**Solution:**
1. Run path validation:
```python
from _shared.config import validate_paths
validate_paths()
```
2. Ensure processed vector files exist in `01_data/02_processed/vectors/`

#### GEE Timeout or Network Error

**Error:** `EEException: Computation timed out`

**Solution:**
- The pipeline has automatic retry logic (3 attempts with exponential backoff)
- For persistent issues, try running during off-peak hours
- Check your internet connection

#### CRS Transformation Issues

**Error:** `CRS mismatch` or `Invalid geometry`

**Solution:**
1. Verify source data CRS is EPSG:5266 (DRUKREF03 TM)
2. The pipeline automatically converts to EPSG:4326 for GEE

#### GEDI Validation Fails

**Error:** `GEDI data unavailable for study area`

**Solution:**
- Use the fallback validation method:
```bash
python 16_validation.py --force-fallback
```
- This uses NDVI and forest loss instead of GEDI

#### Modeling Errors (Script 15)

**Error:** `Singular matrix` or `Collinearity detected`

**Solution:**
- Check for highly correlated covariates in the sample data
- The script automatically drops collinear variables (VIF > 10)
- Review `table6b_models_diagnostics.csv` for model fit issues

### Reading Error Logs

When a script fails, error details are saved to:
```
05_reproducibility/errors/error_SCRIPTNAME_TIMESTAMP.txt
05_reproducibility/errors/error_SCRIPTNAME_TIMESTAMP.json
```

The `.txt` file is formatted for easy reading and can be shared for debugging.

### Validation Reports

Successful runs create validation reports at:
```
05_reproducibility/validation/validation_SCRIPTNAME_TIMESTAMP.txt
```

These contain PASS/FAIL checklists for all validation steps.

---

## 9. Scientific Notes

### EII Calculation Method

**CRITICAL**: This pipeline uses the **precomputed EII band** from the Landler Open Data asset. It does NOT recalculate EII from components.

The EII band is computed as:
```
EII = f(Functional_Integrity, Structural_Integrity, Compositional_Integrity)
```

Using the precomputed band ensures:
- Consistency with published methodology
- Reproducibility across analyses
- Scientific validity for publication

### Zonal Statistics Parameters

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Scale | 300 m | Native EII raster resolution |
| CRS | EPSG:4326 | Required for GEE operations |
| Reducer | Mean, StdDev, Percentiles | Standard zonal statistics |
| Percentiles | 5, 25, 50, 75, 95 | Captures distribution shape |

### Protected Area Validation

The current processed dataset expects exactly **20 protected-area network units**:
- 5 National Parks
- 4 Wildlife Sanctuaries
- 1 Strict Nature Reserve
- 10 Biological Corridors / corridor units

### Coordinate Reference Systems

| CRS | EPSG | Use |
|-----|------|-----|
| DRUKREF03 TM | 5266 | Source data (Bhutan local) |
| WGS84 | 4326 | GEE operations |

### Counterfactual Analysis Method

The inside vs outside comparison uses:
- **Buffer distance**: 10 km (default), optionally 5/10/20 km
- **Exclusion**: Other PA polygons are excluded from "outside" zones
- **Metric**: Delta = EII_inside - EII_outside (positive = PA has higher EII)

### Statistical Modeling Approach

| Model | Method | Purpose |
|-------|--------|---------|
| Counterfactual OLS | Cluster-robust SE | Test PA status effect on EII |
| Drivers OLS | Cluster-robust SE | Identify pressure-EII relationships |
| RandomForest | 5-fold CV | Non-linear importance ranking |

**Cluster-robust standard errors** account for spatial autocorrelation within PAs.

---

## 10. Version History

See `00_admin/CHANGELOG.md` for detailed version history.

**Current Version:** 1.2.0 (2026-04-24)

### Script Versions

| Script | Version | Status |
|--------|---------|--------|
| 01_authenticate_gee.py | 1.1.0 | Complete |
| 02_define_aoi.py | 1.0.0 | Complete |
| 03_download_eii.py | 1.0.0 | Complete |
| 04_download_components.py | 1.0.0 | Complete |
| 05_download_npp.py | 1.0.0 | Complete |
| 06_pa_zonal_stats.py | 1.0.0 | Complete |
| 07_compare_pa_categories.py | 1.0.0 | Complete |
| 08_summary_statistics.py | 1.0.0 | Complete |
| 09_maps_eii.py | 1.0.0 | Complete |
| 10_maps_components.py | 1.0.0 | Complete |
| 11_figures_publication.py | 1.0.0 | Complete |
| 12_prepare_covariates.py | 1.0.0 | **NEW** |
| 12_inside_outside_buffers.py | 1.0.0 | **NEW** |
| 13_covariates_zonal_stats.py | 1.0.0 | **NEW** |
| 14_sample_points_for_models.py | 1.0.0 | **NEW** |
| 15_models_drivers.py | 1.1.0 | **NEW** |
| 16_validation.py | 1.0.0 | **NEW** |
| 12_figures_counterfactual_and_covariates.py | 1.0.0 | **NEW** |

---

## Quick Start Checklist

- [ ] Python 3.10+ installed
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] GEE credentials configured (`EII_GEE_KEY_PATH` or one ignored non-example JSON key in `06_Google_application_credentials/`)
- [ ] Input data verified (`01_data/02_processed/vectors/`)
- [ ] Run authentication: `python 02_scripts/01_setup/01_authenticate_gee.py`
- [ ] Run full pipeline: `python 02_scripts/run_all.py`
- [ ] Check outputs in `03_results/`

**For extended analysis (counterfactual, modeling, validation):**
- [ ] Run covariate preparation: `python 02_scripts/02_download/12_prepare_covariates.py`
- [ ] Run buffer analysis: `python 02_scripts/03_analysis/12_inside_outside_buffers.py`
- [ ] Run modeling pipeline: `python 02_scripts/03_analysis/15_models_drivers.py`
- [ ] Check extended outputs: Tables 4-7, Figures 5-11

---

## Contact & Support

For issues with this pipeline, check:
1. Error logs in `05_reproducibility/errors/`
2. Validation reports in `05_reproducibility/validation/`
3. The project specifications in `Scripting_prompt.md` and `Manuscript_prompt.md`

---

*This README was updated for the EII Bhutan Protected Areas Analysis Pipeline v1.2.0*

---

## 11. Research Operations

Feynman-style research operations are available through `02_scripts/research_ops.py`:

```bash
# Diagnose dependencies, credentials, required data, latest run, and outputs
python 02_scripts/research_ops.py doctor

# Generate output hashes, claims audit, replication report, and run doctor
python 02_scripts/research_ops.py all
```

Generated artifacts:

| Artifact | Purpose |
|----------|---------|
| `03_results/OUTPUT_INDEX.md` | Tables/figures inventory with generator script and SHA256 hashes |
| `05_reproducibility/REPLICATION_REPORT.md` | Latest run summary and replication metadata |
| `05_reproducibility/claims_audit.csv` | Claim-to-evidence map for manuscript review |

The short wrapper `python 02_scripts/doctor.py` is equivalent to `python 02_scripts/research_ops.py doctor`.
