# ============================================================
# Project: EII_Bhutan_Protected_Areas
# Purpose: Create publication-grade directory structure
# ============================================================

base_dir <- "C:/Users/DELL/Desktop/EII_Bhutan_Protected_Areas"

make_dir <- function(path) if (!dir.exists(path)) dir.create(path, recursive = TRUE)
make_text_file <- function(path, lines = character()) {
  if (!file.exists(path)) writeLines(lines, con = path, useBytes = TRUE)
}

make_dir(base_dir)

# 00_admin
make_dir(file.path(base_dir, "00_admin"))
make_text_file(file.path(base_dir, "00_admin", "project_notes.md"),
               c("# Project notes", "", "-"))
make_text_file(file.path(base_dir, "00_admin", "journal_targets.md"),
               c("# Journal targets", "", "-"))
make_text_file(file.path(base_dir, "00_admin", "todo_checklist.md"),
               c("# TODO checklist", "", "- [ ]"))

# 01_data
make_dir(file.path(base_dir, "01_data", "01_raw", "boundaries"))
make_dir(file.path(base_dir, "01_data", "01_raw", "gee_exports", "eii_global"))
make_dir(file.path(base_dir, "01_data", "01_raw", "gee_exports", "components"))
make_dir(file.path(base_dir, "01_data", "01_raw", "gee_exports", "npp_predictions"))

make_dir(file.path(base_dir, "01_data", "02_processed", "rasters"))
make_dir(file.path(base_dir, "01_data", "02_processed", "vectors"))

make_dir(file.path(base_dir, "01_data", "03_tables"))
make_text_file(file.path(base_dir, "01_data", "03_tables", "pa_eii_stats.csv"),
               "pa_name,iucn_cat,eii_mean,eii_min,eii_max\n")
make_text_file(file.path(base_dir, "01_data", "03_tables", "pa_component_stats.csv"),
               "pa_name,functional_mean,structural_mean,compositional_mean\n")

# 02_scripts (placeholders are OK as empty .py)
make_dir(file.path(base_dir, "02_scripts", "01_setup"))
make_text_file(file.path(base_dir, "02_scripts", "01_setup", "01_authenticate_gee.py"))
make_text_file(file.path(base_dir, "02_scripts", "01_setup", "02_define_aoi.py"))

make_dir(file.path(base_dir, "02_scripts", "02_download"))
make_text_file(file.path(base_dir, "02_scripts", "02_download", "03_download_eii.py"))
make_text_file(file.path(base_dir, "02_scripts", "02_download", "04_download_components.py"))
make_text_file(file.path(base_dir, "02_scripts", "02_download", "05_download_npp.py"))

make_dir(file.path(base_dir, "02_scripts", "03_analysis"))
make_text_file(file.path(base_dir, "02_scripts", "03_analysis", "06_pa_zonal_stats.py"))
make_text_file(file.path(base_dir, "02_scripts", "03_analysis", "07_compare_pa_categories.py"))
make_text_file(file.path(base_dir, "02_scripts", "03_analysis", "08_summary_statistics.py"))

make_dir(file.path(base_dir, "02_scripts", "04_visualization"))
make_text_file(file.path(base_dir, "02_scripts", "04_visualization", "09_maps_eii.py"))
make_text_file(file.path(base_dir, "02_scripts", "04_visualization", "10_maps_components.py"))
make_text_file(file.path(base_dir, "02_scripts", "04_visualization", "11_figures_publication.py"))

# 03_results
make_dir(file.path(base_dir, "03_results", "figures"))
make_text_file(file.path(base_dir, "03_results", "figures", "README.md"),
               c("# Figures output", "", "Place generated figures here (PNG/PDF/SVG)."))

make_dir(file.path(base_dir, "03_results", "tables"))
make_text_file(file.path(base_dir, "03_results", "tables", "table1_pa_eii_summary.csv"),
               "pa_name,iucn_cat,eii_mean,eii_sd\n")
make_text_file(file.path(base_dir, "03_results", "tables", "table2_components_by_pa.csv"),
               "pa_name,functional_mean,structural_mean,compositional_mean\n")

# 04_manuscript (use real docx later; keep placeholders as text/markdown)
make_dir(file.path(base_dir, "04_manuscript"))
make_text_file(file.path(base_dir, "04_manuscript", "manuscript.md"),
               c("# Manuscript draft", "", ""))
make_text_file(file.path(base_dir, "04_manuscript", "abstract.txt"),
               "")
make_text_file(file.path(base_dir, "04_manuscript", "figures_captions.md"),
               c("# Figure captions", "", ""))
make_text_file(file.path(base_dir, "04_manuscript", "references.bib"),
               "")

# 05_reproducibility
make_dir(file.path(base_dir, "05_reproducibility"))
make_text_file(file.path(base_dir, "05_reproducibility", "environment.yml"),
               c("name: eii-bhutan-pa", "channels:", "  - conda-forge", "dependencies:", "  - python=3.10"))
make_text_file(file.path(base_dir, "05_reproducibility", "requirements.txt"),
               "")
make_text_file(file.path(base_dir, "05_reproducibility", "gee_assets_used.txt"),
               c("projects/landler-open-data/assets/eii/global/eii_global_v1",
                 "projects/landler-open-data/assets/eii/products/v1/structural_integrity/core_area",
                 "projects/landler-open-data/assets/eii/predictions/npp"))

# README
make_text_file(file.path(base_dir, "README.md"),
               c("# EII Bhutan Protected Areas", "",
                 "This project evaluates Ecosystem Integrity Index (EII) metrics for Bhutan protected areas."))

cat("Project directory structure created successfully.\n")
