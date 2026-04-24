# Changelog

All notable changes to the EII Bhutan Protected Areas Analysis project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-04-24

### Added

- Git repository initialization and repository hygiene guidance.
- `.env.example` for portable Earth Engine credential configuration.
- `CONTRIBUTING.md` with validation and sharing rules.
- `pyproject.toml` and unit tests for shared config and pipeline flag routing.
- `.gitkeep` placeholder for the ignored credential directory.
- `02_scripts/research_ops.py` for doctor checks, output indexing, replication reporting, and claims auditing.
- `02_scripts/doctor.py` as a short wrapper for setup/output diagnosis.
- `02_scripts/manuscript_refine.py` for generating an EMAS-ready refined revision package from current pipeline outputs.

### Changed

- `run_all.py` dry-run mode is now read-only and does not write run logs.
- `run_all.py` now routes script-specific flags only to scripts that support them.
- GEE credential handling now prefers `EII_GEE_SERVICE_ACCOUNT` and `EII_GEE_KEY_PATH`, with fallback to a single local ignored JSON key.
- README now consistently documents the current 20 protected-area network units.
- README and pipeline metadata now report version 1.2.0.

### Fixed

- Removed hard-coded service-account identity and key filename from shared configuration.
- Fixed stale 19-unit documentation that conflicted with current run manifests.
- Replaced the live EII connectivity script with an explicit CLI smoke check guarded by `if __name__ == "__main__"`.

## [1.0.0] - 2025-01-22

### Added

#### Shared Utilities (`02_scripts/_shared/`)
- `__init__.py` (v1.0.0): Package initialization with exports
- `config.py` (v1.0.0): Central configuration with paths, GEE assets, and parameters
- `logging_utils.py` (v1.0.0): Logging setup and session info utilities
- `io_utils.py` (v1.0.0): File I/O helpers for GeoPackages and CSVs
- `error_utils.py` (v1.0.0): Error handling, retry logic, and validation reports

#### Setup Scripts (`02_scripts/01_setup/`)
- `01_authenticate_gee.py` (v1.0.1): GEE service account authentication
- `02_define_aoi.py` (v1.0.0): AOI definition with CRS conversion and validation

#### Download Scripts (`02_scripts/02_download/`)
- `03_download_eii.py` (v1.0.0): Download EII zonal statistics from GEE
  - Uses precomputed `eii` band (CRITICAL: does not recalculate EII)
  - Computes mean, stdDev, and percentiles (5, 25, 50, 75, 95)
  - Optional sensitivity analysis with --enable-method-compare
- `04_download_components.py` (v1.0.0): Download component rasters clipped to Bhutan
- `05_download_npp.py` (v1.0.0): Download NPP predictions (optional)

#### Analysis Scripts (`02_scripts/03_analysis/`)
- `06_pa_zonal_stats.py` (v1.0.0): Process and format PA-level statistics
  - Creates Table 1 (PA EII summary) and Table 2 (components by PA)
- `07_compare_pa_categories.py` (v1.0.0): Compare EII across PA categories
  - Computes category-level statistics and pairwise differences
- `08_summary_statistics.py` (v1.0.0): Compute network-wide summary
  - Simple, area-weighted, and pixel-weighted means
  - JSON and CSV outputs

#### Visualization Scripts (`02_scripts/04_visualization/`)
- `09_maps_eii.py` (v1.0.0): Generate EII choropleth map (fig1)
- `10_maps_components.py` (v1.0.0): Generate component integrity maps (fig3)
- `11_figures_publication.py` (v1.0.0): Generate PA comparison bar chart (fig2) and optional sensitivity figure (fig4)

#### Pipeline Infrastructure
- `run_all.py` (v1.0.0): Master pipeline runner
- `run_order.yaml` (v1.0.0): Pipeline execution order definition
- `requirements.txt`: Python dependencies

### Data Sources
- EII Asset: `projects/landler-open-data/assets/eii/global/eii_global_v1`
  - Bands: eii, functional_integrity, structural_integrity, compositional_integrity
- NPP Asset: `projects/landler-open-data/assets/eii/predictions/npp` (optional)
- Analysis scale: 300m
- CRS: WGS84 (EPSG:4326) for GEE operations

### Important Notes
- The EII value is taken DIRECTLY from the precomputed `eii` band
- EII is NOT recalculated using min(), product(), or any other reducer
- PA count validation expects the configured protected-area network unit count (currently 20)

---

## Version Tracking

| Script | Current Version | Last Updated |
|--------|-----------------|--------------|
| config.py | 1.2.0 | 2026-04-24 |
| logging_utils.py | 1.0.0 | 2025-01-22 |
| io_utils.py | 1.0.0 | 2025-01-22 |
| error_utils.py | 1.0.0 | 2025-01-22 |
| 01_authenticate_gee.py | 1.1.0 | 2026-04-24 |
| 02_define_aoi.py | 1.0.0 | 2025-01-22 |
| 03_download_eii.py | 1.0.0 | 2025-01-22 |
| 04_download_components.py | 1.0.0 | 2025-01-22 |
| 05_download_npp.py | 1.0.0 | 2025-01-22 |
| 06_pa_zonal_stats.py | 1.0.0 | 2025-01-22 |
| 07_compare_pa_categories.py | 1.0.0 | 2025-01-22 |
| 08_summary_statistics.py | 1.0.0 | 2025-01-22 |
| 09_maps_eii.py | 1.0.0 | 2025-01-22 |
| 10_maps_components.py | 1.0.0 | 2025-01-22 |
| 11_figures_publication.py | 1.0.0 | 2025-01-22 |
| run_all.py | 1.2.0 | 2026-04-24 |
