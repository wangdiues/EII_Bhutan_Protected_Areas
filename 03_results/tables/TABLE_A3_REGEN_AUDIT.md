# Table A3 Regeneration Audit

**Date:** 2026-04-07
**Scope:** Table A3 only — no other tables, text, figures, or manuscript sections modified.

---

## 1. Why the Old Table A3 Was Wrong

### Root cause — `07_compare_pa_categories.py`, `compute_component_by_category()`

The function grouped `pa_component_stats.csv` by the `park` column, which holds individual
full PA names (e.g., "Biological Corridor 1"). Because every PA name is unique, each
"category" group contained exactly **one PA (n = 1)**. For n = 1:

- `mean()`, `min()`, `max()` of a single-element series all return the same value.
- `std()` returns NaN (pandas default ddof = 1).

The result was that **Mean = Min = Max** for every one of the 57 rows, and **SD was
blank/NaN** — even though `table2_components_by_pa.csv` (Table A1) shows clearly
non-zero SDs for each PA.

### Specific contradiction with Table A1
Table A1 (table2_components_by_pa.csv) reports, for example:
- BC 1, Functional: Mean = 0.8251, **SD = 0.0956**
- BC 1, Structural: Mean = 0.9809, **SD = 0.0288**

Old Table A3 reported BC 1 / Functional: Mean = Min = Max = 0.825 — ignoring SD
entirely and fabricating equal Min/Max by reusing the mean.

---

## 2. Script Modified

| File | Change |
|------|--------|
| `02_scripts/03_analysis/07_compare_pa_categories.py` | `compute_component_by_category()` — changed `groupby('park')` to `groupby('pa_type')` in earlier fix session |
| `02_scripts/03_analysis/_generate_pa_level_category_tables.py` | **New script** — generates per-PA table directly from `pa_component_stats.csv` with all 9 statistics |
| `02_scripts/03_analysis/_replace_table_a3_in_docx.py` | **New script** — replaces Table A3 XML in DOCX |

The authoritative upstream source is:
`01_data/03_tables/pa_component_stats.csv`
(columns: `PA_name, park, Area_km2, band, mean, stdDev, count, p5, p25, p50, p75, p95`)

---

## 3. New Table A3 Structure

| Column | Source field | Notes |
|--------|-------------|-------|
| Protected area | `park` | Full PA name, sorted alphabetically |
| Component | `band` | Functional / Structural / Compositional |
| Mean | `mean` | Pixel-level mean within PA |
| SD | `stdDev` | Pixel-level SD within PA |
| P5 | `p5` | 5th percentile |
| P25 | `p25` | 25th percentile |
| Median | `p50` | 50th percentile |
| P75 | `p75` | 75th percentile |
| P95 | `p95` | 95th percentile |

**Row count:** 1 header + 57 data rows (19 PAs × 3 components)
**Column count:** 9 (was 5)

Min/Max columns were **removed** because the upstream GEE zonal stats export provides
only percentiles (P5–P95), not pixel-level absolute min/max. Using P5/P95 as "Min/Max"
labels would be misleading; reporting the full percentile distribution is more honest
and more useful.

---

## 4. Before / After Comparison (sample rows)

### Old Table A3 (invalid)
| Protected area | Component | Mean | Min | Max |
|---|---|---|---|---|
| Biological Corridor 1 | Functional | 0.825 | 0.825 | 0.825 |
| Biological Corridor 1 | Structural | 0.981 | 0.981 | 0.981 |
| Biological Corridor 1 | Compositional | 0.935 | 0.935 | 0.935 |

### New Table A3 (valid)
| Protected area | Component | Mean | SD | P5 | P25 | Median | P75 | P95 |
|---|---|---|---|---|---|---|---|---|
| Biological Corridor 1 | Functional | 0.8251 | 0.0956 | 0.6388 | 0.7718 | 0.8417 | 0.8966 | 0.9474 |
| Biological Corridor 1 | Structural | 0.9809 | 0.0288 | 0.9086 | 0.9800 | 0.9896 | 0.9988 | 1.0000 |
| Biological Corridor 1 | Compositional | 0.9347 | 0.0307 | 0.8820 | 0.9248 | 0.9403 | 0.9542 | 0.9640 |

---

## 5. Consistency Check with Table A1

New Table A3 Mean and SD values match `table2_components_by_pa.csv` exactly:

| PA | Component | Table A1 Mean | Table A3 Mean | Table A1 SD | Table A3 SD |
|----|-----------|--------------|--------------|------------|------------|
| BC 1 | Functional | 0.8251 | 0.8251 | 0.0956 | 0.0956 |
| BC 1 | Structural | 0.9809 | 0.9809 | 0.0288 | 0.0288 |
| PWS | Functional | 0.4763 | 0.4763 | 0.0619 | 0.0619 |
| WCNP | Structural | 0.9946 | 0.9946 | 0.0134 | 0.0134 |

Tables A1 and A3 are now internally consistent.

---

## 6. Output Files

| File | Action |
|------|--------|
| `03_results/tables/category_component_summary.csv` | Regenerated — 57 rows × 9 cols, all stats from upstream |
| `04_manuscript/.../supplementary_materials_UPDATED_tableA3fixed.docx` | Table A3 replaced — save as `supplementary_materials_UPDATED.docx` once reviewed |

**Note:** The DOCX was open when the script ran, so output was saved as
`supplementary_materials_UPDATED_tableA3fixed.docx`. Close the original in Word,
then rename (or copy over) the fixed file.

---

## 7. Validation

- 57 data rows regenerated, 0 suspicious rows (no row has all 9 stats identical)
- Every row satisfies P5 ≤ Median ≤ P95 (monotone percentiles by construction)
- Mean and SD match Table A1 exactly for all 19 PAs × 3 components

*No other tables, figures, text, or model outputs were modified.*
