# =============================================================================
# FULL FIX (END-TO-END): Load -> validate -> align CRS -> clip -> QA -> map -> save
# Validation uses sf::st_make_valid() (works even when lwgeom has no export)
# Save outputs as GeoPackage (recommended) + optional Shapefile export
# =============================================================================

# 0) PACKAGES -----------------------------------------------------------------
pkgs <- c("sf", "ggplot2")
for (p in pkgs) {
  if (!requireNamespace(p, quietly = TRUE)) install.packages(p)
}
library(sf)
library(ggplot2)

# Optional stability: turn off s2 for some projected ops
sf_use_s2(FALSE)

# 1) PATHS --------------------------------------------------------------------
base_dir <- "C:/Users/DELL/Desktop/EII_Bhutan_Protected_Areas"
raw_dir  <- file.path(base_dir, "01_data", "01_raw", "boundaries")
out_dir  <- file.path(base_dir, "01_data", "02_processed", "vectors")

pa_raw   <- file.path(raw_dir, "PA_Bnd_Final_20230316.shp")
btn_raw  <- file.path(raw_dir, "Bhutan.shp")

if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE)

stopifnot(dir.exists(base_dir))
stopifnot(file.exists(pa_raw))
stopifnot(file.exists(btn_raw))

cat("\nBase dir : ", base_dir, "\n")
cat("Raw dir  : ", raw_dir, "\n")
cat("Out dir  : ", out_dir, "\n")
cat("PA shp   : ", pa_raw, "\n")
cat("BTN shp  : ", btn_raw, "\n")

# 2) READ DATA ----------------------------------------------------------------
cat("\n--- Loading Data ---\n")
pa  <- st_read(pa_raw,  quiet = TRUE, stringsAsFactors = FALSE)
btn <- st_read(btn_raw, quiet = TRUE, stringsAsFactors = FALSE)

# 3) BASIC CHECKS -------------------------------------------------------------
cat("\n--- CRS ---\n")
print(st_crs(pa))
print(st_crs(btn))

cat("\n--- PA fields ---\n");  print(names(pa))
cat("\n--- BTN fields ---\n"); print(names(btn))

# 4) GEOMETRY VALIDATION (FIXED) ----------------------------------------------
# Use sf::st_make_valid() because lwgeom::st_make_valid() is not exported in your build
cat("\n--- Making geometries valid (sf::st_make_valid) ---\n")
pa  <- sf::st_make_valid(pa)
btn <- sf::st_make_valid(btn)

# Drop Z/M if present (safety)
pa  <- st_zm(pa,  drop = TRUE, what = "ZM")
btn <- st_zm(btn, drop = TRUE, what = "ZM")

# Ensure consistent geometry type
pa <- st_cast(pa, "MULTIPOLYGON", warn = FALSE)

# 5) CRS ALIGNMENT ------------------------------------------------------------
# Use PA CRS as target (it prints EPSG:5266 in your output)
target_crs <- st_crs(pa)
if (st_crs(btn) != target_crs) {
  cat("\nAligning CRS: Transforming Bhutan boundary -> PA CRS\n")
  btn <- st_transform(btn, target_crs)
}

# 6) CLIP PA TO BHUTAN (SAFE) -------------------------------------------------
cat("\nClipping PAs to Bhutan boundary...\n")

# Ensure boundary is a single geometry (union) for stable intersection
btn_union <- st_union(st_geometry(btn))

# Keep PA attributes; intersect geometry only
pa_clipped <- st_intersection(pa, btn_union)
# Note: The warning "attribute variables are assumed..." is normal for intersection

# 7) AREA QA ------------------------------------------------------------------
cat("\n--- Area QA ---\n")
pa_clipped$Area_km2_geom <- as.numeric(st_area(pa_clipped)) / 1e6

if ("Area_km2" %in% names(pa_clipped)) {
  pa_clipped$Area_km2_diff <- pa_clipped$Area_km2_geom - pa_clipped$Area_km2
  print(pa_clipped[, c("PA_name", "Area_km2", "Area_km2_geom", "Area_km2_diff")])
} else {
  print(pa_clipped[, c("PA_name", "Area_km2_geom")])
}

# 8) QUICK MAP ----------------------------------------------------------------
p <- ggplot() +
  geom_sf(data = btn, fill = "white", color = "black", linewidth = 0.5) +
  geom_sf(data = pa_clipped, fill = "grey70", color = "white", alpha = 0.7) +
  theme_minimal() +
  labs(
    title = "Bhutan Protected Areas (Processed)",
    subtitle = "Validated geometries, aligned CRS, clipped to Bhutan boundary",
    caption = "sf + ggplot2"
  )
print(p)

# 9) SAVE OUTPUTS (GPKG RECOMMENDED) ------------------------------------------
cat("\n--- Saving (GeoPackage, recommended) ---\n")
pa_gpkg  <- file.path(out_dir, "protected_areas_btn.gpkg")
btn_gpkg <- file.path(out_dir, "bhutan_boundary.gpkg")

if (file.exists(pa_gpkg))  file.remove(pa_gpkg)
if (file.exists(btn_gpkg)) file.remove(btn_gpkg)

st_write(pa_clipped, pa_gpkg,  layer = "protected_areas_btn", driver = "GPKG", quiet = TRUE)
st_write(btn,        btn_gpkg, layer = "bhutan_boundary",     driver = "GPKG", quiet = TRUE)

cat("Saved:\n - ", pa_gpkg, "\n - ", btn_gpkg, "\n")

# 10) OPTIONAL: SHAPEFILE EXPORT ----------------------------------------------
# Shapefile limitations: 10-char field names, multiple files, encoding quirks.
cat("\n--- Optional Shapefile export ---\n")
pa_shp_dir  <- file.path(out_dir, "protected_areas_btn_shp")
btn_shp_dir <- file.path(out_dir, "bhutan_boundary_shp")

if (!dir.exists(pa_shp_dir))  dir.create(pa_shp_dir, recursive = TRUE)
if (!dir.exists(btn_shp_dir)) dir.create(btn_shp_dir, recursive = TRUE)

pa_shp  <- file.path(pa_shp_dir,  "protected_areas_btn.shp")
btn_shp <- file.path(btn_shp_dir, "bhutan_boundary.shp")

# Write shapefiles (delete_dsn removes existing dataset if present)
try({
  st_write(pa_clipped, pa_shp, delete_dsn = TRUE, quiet = TRUE)
  cat("Shapefile saved: ", pa_shp, "\n")
}, silent = TRUE)

try({
  st_write(btn, btn_shp, delete_dsn = TRUE, quiet = TRUE)
  cat("Shapefile saved: ", btn_shp, "\n")
}, silent = TRUE)

cat("\nDONE.\n")
