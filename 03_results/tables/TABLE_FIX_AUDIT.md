# Table Fix Audit Report

**Date:** 2026-04-07
**Scope:** Table-generation pipeline only (scripts 07, 08).
**Validation:** 48/48 checks passed — 0 failures.

---

## 1. Summary of Issues and Root Causes

### 1.1 `bhutan_network_summary.csv` — Component Summary rows corrupt

**Root cause — `08_summary_statistics.py`, `create_summary_table()` (bug):**
The network summary dictionary has a doubly-nested structure for the Component Summary
section:

```
network_summary["Component Summary"] = {
    "Functional":     {"Mean": ..., "SD": ..., "Min": ..., "Max": ..., "Median": ...},
    "Structural":     {...},
    "Compositional":  {...},
}
```

The `create_summary_table()` loop unpacked only one level of nesting. When it reached
the "Component Summary" section, `metric = "Functional"` and `value = {"Mean": ..., "SD":
..., ...}` — a dict object, not a scalar. That dict object was cast to a Python `repr`
string and written as the CSV `Value` cell, producing three corrupt rows of the form:

```
Component Summary,Functional,"{'Mean': np.float64(0.6547), 'SD': np.float64(0.1001), ...}"
```

The EII summary statistics (rows 2–18) and top/bottom PA rows (19–26) were unaffected and
remained arithmetically correct.

**Fix:** Added a second `isinstance(value, dict)` branch inside `create_summary_table()`.
Nested component stats are now expanded into 15 individual scalar rows with `Metric` keys
of the form `"Functional Mean"`, `"Functional SD"`, etc.

---

### 1.2 `category_eii_summary.csv` — Impossible statistics (median > max)

**Root cause — `07_compare_pa_categories.py`, `compute_category_stats()` (design flaw):**
The upstream column `park` stores individual full PA names (e.g. "Biological Corridor 1",
"Bumdeling Wildlife Sanctuary"), **not** PA management-type categories. Grouping by this
column produced 19 singleton groups (n = 1 per "category").

Two independent problems arose from that:

1. For n = 1, `pandas.agg(['min','max'])` on `eii_mean` trivially returns
   `min = mean = max = eii_mean` for the single PA — making those statistics meaningless.

2. "Median EII" was computed as `eii_p50.mean()` — the pixel-level median of each PA —
   which is a **different quantity** from the PA-level mean. For BC 1:
   `eii_p50 = 0.8408` while `eii_mean = 0.8214`, so the reported "median" (0.8408)
   exceeded the reported "max" (0.8214) — a mathematical impossibility.

**Fix:**
* Added `derive_pa_type()`, which maps full PA names to five management-type labels:
  *Biological Corridor* (n = 8), *National Park* (n = 5), *Wildlife Sanctuary* (n = 4),
  *Strict Nature Reserve* (n = 1), *Botanical Park* (n = 1).
* Changed `groupby('park')` → `groupby('pa_type')` so each group contains multiple PAs.
* Replaced `'eii_p50': 'mean'` with `'eii_mean': 'median'` so "Median EII" is the
  median of PA-level EII means within the type group — the only defensible median for this
  aggregation.

*Note on n = 1 categories:* Strict Nature Reserve and Botanical Park each contain a single
PA. For these rows SD = NaN and min = mean = max = median, which is statistically correct
(degenerate but not invalid) and is documented here.

---

### 1.3 `category_component_summary.csv` — mean = min = max for all rows (same root cause)

**Root cause:** Same `groupby('park')` singleton issue in `compute_component_by_category()`.
Every row had n = 1 PA, making SD = NaN and mean = min = max across the board.

**Fix:** Same `pa_type` derivation and grouping applied inside
`compute_component_by_category()`. The resulting table now has 15 rows (5 types × 3
components). For multi-PA groups (Biological Corridor, National Park, Wildlife Sanctuary)
min < max and SD > 0.

---

## 2. Files Modified

| File | Change |
|------|--------|
| `02_scripts/03_analysis/08_summary_statistics.py` | Fixed `create_summary_table()` to handle doubly-nested Component Summary dict |
| `02_scripts/03_analysis/07_compare_pa_categories.py` | Added `derive_pa_type()`; changed all three groupby calls to use `pa_type`; replaced `eii_p50 mean` with `eii_mean median` |

No upstream data files were modified. All regenerated CSVs derive solely from
`01_data/03_tables/pa_eii_stats.csv` and `01_data/03_tables/pa_component_stats.csv`.

---

## 3. Before / After — Corrected Values

### bhutan_network_summary.csv — Component Summary (rows 27–41)

| | Before (corrupt) | After (correct) |
|---|---|---|
| Row 27 | `Functional, "{'Mean': np.float64(0.6547)...}"` | `Functional Mean, 0.6547` |
| Row 28 | `Structural, "{'Mean': np.float64(0.9522)...}"` | `Functional SD, 0.1001` |
| Row 29 | `Compositional, "{'Mean': np.float64(0.9517)...}"` | `Functional Min, 0.4763` |
| … | *(3 rows, each a dict string)* | *(15 rows, each a scalar)* |

EII summary statistics (rows 6–18) were already correct and are unchanged.

### category_eii_summary.csv

| Before: 19 rows (one per PA name, all n = 1) | After: 5 rows (one per PA type) |
|---|---|
| "Biological Corridor 1": Mean=0.8214, Min=0.8214, Max=0.8214, **Median=0.8408** (IMPOSSIBLE) | "Biological Corridor" (n=8): Mean=0.6580, Min=0.4781, Max=0.8214, Median=0.6781 |
| All rows: EII SD = NaN | EII SD = NaN only for n=1 categories (Strict Nature Reserve, Botanical Park) |
| "Wangchuck Centennial National Park" as its own category | "National Park" (n=5): Mean=0.6567, Min=0.5061, Max=0.7263, Median=0.6742 |

### category_component_summary.csv

| Before: 57 rows (19 PA names × 3 components, all Mean=Min=Max, SD=NaN) | After: 15 rows (5 PA types × 3 components) |
|---|---|
| Every row: SD = NaN, Mean = Min = Max | Multi-PA rows: SD > 0, Min < Max |
| "Biological Corridor 1 / Functional": Mean=Min=Max=0.8251, SD=NaN | "Biological Corridor / Functional" (n=8): Mean=0.6619, Min=0.4947, Max=0.8251, SD=0.1036 |

---

## 4. Validation Results (48 checks, 0 failures)

### bhutan_network_summary.csv (21 checks)
- Total area 19750.16 km² = sum of all 19 PA areas from upstream
- Total pixels 256410 = sum of all 19 PA pixel counts from upstream
- Area-weighted mean 0.6785 = `np.average(eii_mean, weights=Area_km2)` from upstream
- Pixel-weighted mean 0.6782 = `np.average(eii_mean, weights=pixel_count)` from upstream
- Component Summary: 15 scalar rows; each value matches upstream `pa_component_stats.csv`

### category_eii_summary.csv (12 checks)
- 5 rows (one per PA management type)
- All rows: min ≤ median ≤ max
- All rows: min ≤ mean ≤ max
- All statistics match recomputed values from upstream `pa_eii_stats.csv`
- n = 1 rows (Strict Nature Reserve, Botanical Park): min = mean = max = median — justified

### category_component_summary.csv (15 checks)
- 15 rows (5 types × 3 components)
- Multi-PA groups: mean ≠ min ≠ max, SD > 0
- n = 1 groups: mean = min = max — justified degenerate case, flagged as such
- All statistics derived from upstream `pa_component_stats.csv`

---

## 5. Tables Not Modified (Confirmed Valid)

| Table | Status |
|-------|--------|
| `table1_pa_eii_summary.csv` | Correct — PA-level data, no category grouping |
| `table2_components_by_pa.csv` | Correct — PA-level pivot, no category grouping |
| `table4_inside_vs_outside.csv` | Not in scope; not touched |
| `table5_covariates_summary.csv` | Not in scope; not touched |
| `table5b_eii_covariate_concordance.csv` | Not in scope; not touched |
| `table6_models_coefficients.csv` | Not in scope; not touched |
| `table6b_models_diagnostics.csv` | Not in scope; not touched |
| `table6c_rf_importance.csv` | Not in scope; not touched |
| `table7_validation.csv` | Not in scope; not touched |
| `category_pairwise_differences.csv` | Regenerated consistently with category fix (now 5×5 PA-type matrix) |

---

*End of audit. No manuscript files were modified.*
