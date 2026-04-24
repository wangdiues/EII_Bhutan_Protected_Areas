# Replication Report

Generated: 2026-04-24T12:19:51.948966
Project: Ecosystem Integrity of Bhutan's Protected Area Network

## Latest Pipeline Run

- Log: `05_reproducibility\pipeline_run_20260424_115549.json`
- Pipeline version: `1.2.0`
- Timestamp: `2026-04-24T11:55:49.790378`
- Total elapsed seconds: `1886.185253`
- Overall status: `success`

| Script | Status | Elapsed seconds |
|--------|--------|-----------------|
| 01_authenticate_gee.py | success | 6.279022 |
| 02_define_aoi.py | success | 8.880841 |
| 03_download_eii.py | success | 29.28903 |
| 04_download_components.py | success | 34.573165 |
| 05_download_npp.py | success | 7.236587 |
| 06_pa_zonal_stats.py | success | 0.925329 |
| 07_compare_pa_categories.py | success | 0.847184 |
| 08_summary_statistics.py | success | 0.842783 |
| 09_maps_eii.py | success | 3.135185 |
| 10_maps_components.py | success | 2.226961 |
| 11_figures_publication.py | success | 1.892184 |
| 12_prepare_covariates.py | success | 20.211471 |
| 12_inside_outside_buffers.py | success | 503.08326 |
| 13_covariates_zonal_stats.py | success | 145.082304 |
| 14_sample_points_for_models.py | success | 833.731421 |
| 15_models_drivers.py | success | 89.963283 |
| 16_validation.py | success | 191.970579 |
| 12_figures_counterfactual_and_covariates.py | success | 5.995912 |

## Configuration

- Expected protected-area network units: `20`
- EII asset: `projects/landler-open-data/assets/eii/global/eii_global_v1`
- Analysis scale: `300` m
- Analysis CRS: `EPSG:4326`

## Reproducibility Artifacts

- `03_results/OUTPUT_INDEX.md` records generated outputs and SHA256 hashes.
- `05_reproducibility/claims_audit.csv` maps manuscript-style claims to evidence artifacts.
- `05_reproducibility/gee_assets_used.txt` records Earth Engine assets used by the run.
