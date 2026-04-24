# ============================================================
# PUBLICATION-GRADE MAP (LANDSCAPE) - CLEANER VERSION
# Using PA_name abbreviations on map, full names in legend
# ============================================================

# ---- 0) Packages --------------------------------------------
pkgs <- c("sf", "dplyr", "ggplot2", "ggspatial", "ggrepel", "stringr", "readr")
for (p in pkgs) if (!requireNamespace(p, quietly = TRUE)) install.packages(p)

library(sf)
library(dplyr)
library(ggplot2)
library(ggspatial)
library(ggrepel)
library(stringr)
library(readr)

# ---- 1) File paths ------------------------------------------
bhutan_path <- "C:/Users/DELL/Desktop/EII_Bhutan_Protected_Areas/01_data/02_processed/vectors/bhutan_boundary_shp/bhutan_boundary.shp"

pa_path <- "C:/Users/DELL/Desktop/EII_Bhutan_Protected_Areas/01_data/02_processed/vectors/protected_areas_btn_shp/protected_areas_btn.shp"

out_fig <- "C:/Users/DELL/Desktop/EII_Bhutan_Protected_Areas/03_results/figures/Figure_1_PA_network_Bhutan_landscape.png"

# ---- 2) Read data -------------------------------------------
bhutan <- st_read(bhutan_path, quiet = TRUE)
pa     <- st_read(pa_path, quiet = TRUE)

# ---- 3) Validate fields -------------------------------------
stopifnot(all(c("park", "PA_name", "Are_km2") %in% names(pa)))

if (is.na(st_crs(bhutan))) stop("Bhutan boundary CRS is missing.")
if (is.na(st_crs(pa)))     stop("Protected areas CRS is missing.")

# ---- 4) CRS harmonization -----------------------------------
pa <- st_transform(pa, st_crs(bhutan))

# ---- 5) Prepare data ----------------------------------------
pa2 <- pa %>%
  mutate(
    # Use PA_name for map labels (abbreviations)
    map_label = PA_name,
    # Create legend entry: Full name (Abbreviation)
    legend_label = paste0(park, " (", PA_name, ")"),
    # Classify type
    is_bc = str_detect(PA_name, "^BC\\s*[0-9]+$"),
    type = ifelse(is_bc, "Biological Corridor", "Protected Area")
  ) %>%
  # Sort by type and name for organized legend
  arrange(type, park)

# ---- 6) Label anchor points --------------------------------
lab_pts <- suppressWarnings(st_point_on_surface(pa2))
coords <- st_coordinates(lab_pts)
lab_pts$X <- coords[, 1]
lab_pts$Y <- coords[, 2]

# ---- 7) Create legend lookup table -------------------------
legend_df <- pa2 %>%
  st_drop_geometry() %>%
  select(PA_name, park, type, Are_km2) %>%
  arrange(type, park)

# Print legend for reference
cat("\n=== LEGEND REFERENCE ===\n")
print(as.data.frame(legend_df))
cat("\n")

# ---- 8) Build map -------------------------------------------
p <- ggplot() +
  
  geom_sf(
    data = bhutan,
    fill = "grey97",
    color = "black",
    linewidth = 0.7
  ) +
  
  geom_sf(
    data = pa2,
    aes(fill = type),
    color = "black",
    linewidth = 0.25,
    alpha = 0.8
  ) +
  
  # Use abbreviated PA_name for cleaner map
  geom_text_repel(
    data = lab_pts,
    aes(x = X, y = Y, label = map_label),
    size = 3.2,
    family = "Times",
    fontface = "bold",
    seed = 123,
    max.overlaps = Inf,
    min.segment.length = 0,
    box.padding = 0.3,
    point.padding = 0.25,
    segment.color = "grey30",
    segment.size = 0.25,
    force = 1.5,
    force_pull = 0.5
  ) +
  
  annotation_scale(
    location = "bl",
    width_hint = 0.18,
    text_cex = 0.95,
    text_family = "Times",
    pad_x = unit(0.5, "cm"),
    pad_y = unit(0.4, "cm")
  ) +
  
  annotation_north_arrow(
    location = "tl",
    style = north_arrow_minimal,
    height = unit(1.1, "cm"),
    width  = unit(1.1, "cm"),
    pad_x = unit(0.4, "cm"),
    pad_y = unit(0.4, "cm")
  ) +
  
  scale_fill_manual(
    name = "Category",
    values = c(
      "Protected Area" = "#2E8B57",
      "Biological Corridor" = "#7CB342"
    )
  ) +
  
  labs(
    title = "Protected Area Network of Bhutan",
    subtitle = "Protected areas and biological corridors for Ecosystem Integrity Index (EII) assessment",
    caption = "Source: Department of Forests and Park Services, Bhutan"
  ) +
  
  theme_minimal(base_family = "Times", base_size = 13) +
  theme(
    legend.position = "right",
    legend.text = element_text(size = 11),
    legend.title = element_text(size = 12, face = "bold"),
    legend.key.size = unit(0.8, "cm"),
    axis.title = element_blank(),
    axis.text = element_text(size = 9, color = "grey30"),
    panel.grid.major = element_line(color = "grey90", linewidth = 0.2),
    panel.grid.minor = element_blank(),
    panel.background = element_rect(fill = "white", color = NA),
    plot.background = element_rect(fill = "white", color = NA),
    plot.title = element_text(face = "bold", size = 17, hjust = 0),
    plot.subtitle = element_text(size = 12, hjust = 0, margin = margin(b = 8)),
    plot.caption = element_text(size = 9, hjust = 0, face = "italic", color = "grey40"),
    plot.margin = margin(12, 12, 12, 12)
  )

print(p)

# ---- 9) Export map ------------------------------------------
dir.create(dirname(out_fig), recursive = TRUE, showWarnings = FALSE)

ggsave(
  out_fig,
  plot = p,
  width = 297,
  height = 210,
  units = "mm",
  dpi = 600,
  bg = "white"
)

# ---- 10) Create separate legend table (CSV) -----------------
legend_csv <- gsub("\\.png$", "_legend.csv", out_fig)
write_csv(legend_df, legend_csv)

# ---- 11) Summary output -------------------------------------
cat("\n")
message("✓ Saved landscape map: ", basename(out_fig))
message("✓ Saved legend table: ", basename(legend_csv))
message("✓ Dimensions: 297 × 210 mm (A4 landscape)")
message("✓ Resolution: 600 DPI")
message("✓ Total features: ", nrow(pa2))
message("  - Protected Areas: ", sum(pa2$type == "Protected Area"))
message("  - Biological Corridors: ", sum(pa2$type == "Biological Corridor"))
cat("\n")

# ============================================================
# VERSION 2: WITH LEGEND TABLE INSET ON MAP
# ============================================================

library(gridExtra)
library(grid)

# ... (use same data preparation as above through line 84) ...

# ---- 8b) Create legend table for inset ---------------------
legend_table <- pa2 %>%
  st_drop_geometry() %>%
  select(PA_name, park) %>%
  arrange(PA_name) %>%
  mutate(
    Abbr. = PA_name,
    `Full Name` = park
  ) %>%
  select(Abbr., `Full Name`)

# Convert to grob for plotting
table_grob <- tableGrob(
  legend_table,
  rows = NULL,
  theme = ttheme_minimal(
    base_size = 7,
    base_family = "Times",
    core = list(fg_params = list(hjust = 0, x = 0.05)),
    colhead = list(fg_params = list(fontface = "bold"))
  )
)

# ---- 8c) Build map with table inset ------------------------
p_with_table <- p +
  annotation_custom(
    grob = table_grob,
    xmin = Inf, xmax = Inf,
    ymin = -Inf, ymax = Inf
  )

# Note: For better control, you might want to use cowplot or patchwork
# to arrange the map and legend table side by side

print(p)  # Show map without table first

# ---- 9) Export ----------------------------------------------
ggsave(
  out_fig,
  plot = p,
  width = 297,
  height = 210,
  units = "mm",
  dpi = 600,
  bg = "white"
)

message("\n✓ Map saved successfully!")
message("✓ Abbreviations (PA_name) shown on map")
message("✓ Full names (park) available in separate legend CSV")


