#!/usr/bin/env python3
"""
Generate an EMAS-ready refined manuscript package from the latest pipeline outputs.
"""

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from docx import Document
from docx.oxml import OxmlElement


BASE_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BASE_DIR / "04_manuscript" / "Environmental Monitoring and Assessment"
REVISION_DIR = PACKAGE_DIR / "revision"
OUT_DIR = REVISION_DIR / "refined_submission"
RESULTS_TABLES = BASE_DIR / "03_results" / "tables"
RESULTS_FIGURES = BASE_DIR / "03_results" / "figures"


def fmt_float(value, digits=4):
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")


def clean_name(value):
    if not isinstance(value, str):
        return value
    return (
        value
        .replace("Jigme Khesar Strick Nature Reserve", "Jigme Khesar Strict Nature Reserve")
        .replace("Jigme Dorji Wangchuch National Park", "Jigme Dorji Wangchuck National Park")
    )


def clean_dataframe(df):
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].map(clean_name)
    return df


def md_table(df):
    df = clean_dataframe(df)
    cols = [str(col) for col in df.columns]
    rows = []
    for _, row in df.iterrows():
        rows.append([str(row[col]) for col in df.columns])

    def clean(value):
        return value.replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(clean(col) for col in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(clean(value) for value in row) + " |")
    return "\n".join(lines)


def network_summary_table():
    df = pd.read_csv(RESULTS_TABLES / "bhutan_network_summary.csv")
    return md_table(clean_dataframe(df))


def pa_summary_table():
    df = pd.read_csv(RESULTS_TABLES / "table1_pa_eii_summary.csv")
    df = clean_dataframe(df)
    df = df.rename(columns={"Category": "Protected area"})
    cols = [
        "Rank",
        "Protected area",
        "Area (km²)",
        "EII Mean",
        "EII SD",
        "EII P5",
        "EII P25",
        "EII P50",
        "EII P75",
        "EII P95",
        "Pixel Count",
    ]
    df = df[cols].copy()
    for col in ["Area (km²)", "EII Mean", "EII SD", "EII P5", "EII P25", "EII P50", "EII P75", "EII P95"]:
        df[col] = df[col].map(lambda x: fmt_float(x, 2 if col == "Area (km²)" else 4))
    df["Pixel Count"] = df["Pixel Count"].map(lambda x: f"{int(x):,}")
    return md_table(df)


def metrics():
    pa = pd.read_csv(RESULTS_TABLES / "table1_pa_eii_summary.csv")
    network = pd.read_csv(RESULTS_TABLES / "bhutan_network_summary.csv")
    inside = pd.read_csv(RESULTS_TABLES / "table4_inside_vs_outside.csv")
    concordance = pd.read_csv(RESULTS_TABLES / "table5b_eii_covariate_concordance.csv")
    diagnostics = pd.read_csv(RESULTS_TABLES / "table6b_models_diagnostics.csv")
    coeffs = pd.read_csv(RESULTS_TABLES / "table6_models_coefficients.csv")
    rf = pd.read_csv(RESULTS_TABLES / "table6c_rf_importance.csv")
    validation = pd.read_csv(RESULTS_TABLES / "table7_validation.csv")

    net = {(row["Section"], row["Metric"]): row["Value"] for _, row in network.iterrows()}
    total_area = float(net[("Network Statistics", "Total Network Area (km²)")])
    above_06 = pa[pa["EII Mean"] > 0.60]
    above_07 = pa[pa["EII Mean"] > 0.70]
    below_06 = pa[pa["EII Mean"] < 0.60]
    positive_inside = inside[inside["Delta EII"] > 0]

    cf_diag = diagnostics[diagnostics["model"] == "counterfactual"].iloc[0]
    drivers_diag = diagnostics[diagnostics["model"] == "drivers"].iloc[0]
    inside_coef = coeffs[(coeffs["model"] == "counterfactual") & (coeffs["variable"] == "inside_outside")].iloc[0]
    elev_cf = coeffs[(coeffs["model"] == "counterfactual") & (coeffs["variable"] == "elevation")].iloc[0]
    elev_drivers = coeffs[(coeffs["model"] == "drivers") & (coeffs["variable"] == "elevation")].iloc[0]
    built = coeffs[(coeffs["model"] == "drivers") & (coeffs["variable"] == "built_up")].iloc[0]
    rf_top = {row["variable"]: row["importance_pct"] for _, row in rf.iterrows()}

    corr = {row["Covariate"]: row for _, row in concordance.iterrows()}
    val = {row["Validation Metric"]: row for _, row in validation.iterrows()}

    return {
        "n_pa": int(net[("Network Statistics", "Number of Protected Areas")]),
        "total_area": total_area,
        "pixels": int(net[("Network Statistics", "Total Analyzed Pixels")]),
        "simple_mean": float(net[("EII Summary (PA-level means)", "Simple Mean")]),
        "area_mean": float(net[("EII Summary (PA-level means)", "Area-Weighted Mean")]),
        "pixel_mean": float(net[("EII Summary (PA-level means)", "Pixel-Weighted Mean")]),
        "sd": float(net[("EII Summary (PA-level means)", "Standard Deviation")]),
        "min": float(net[("EII Summary (PA-level means)", "Minimum")]),
        "max": float(net[("EII Summary (PA-level means)", "Maximum")]),
        "median": float(net[("EII Summary (PA-level means)", "Median")]),
        "iqr": float(net[("EII Summary (PA-level means)", "IQR")]),
        "func_mean": float(net[("Component Summary", "Functional Mean")]),
        "struct_mean": float(net[("Component Summary", "Structural Mean")]),
        "comp_mean": float(net[("Component Summary", "Compositional Mean")]),
        "above_06_n": len(above_06),
        "above_06_pct": above_06["Area (km²)"].sum() / total_area * 100,
        "above_07_pct": above_07["Area (km²)"].sum() / total_area * 100,
        "above_07_area": above_07["Area (km²)"].sum(),
        "below_06_n": len(below_06),
        "below_06_area": below_06["Area (km²)"].sum(),
        "positive_inside_n": len(positive_inside),
        "negative_inside_n": len(inside) - len(positive_inside),
        "lowest": pa.iloc[-1]["Category"],
        "highest": pa.iloc[0]["Category"],
        "lowest_mean": pa.iloc[-1]["EII Mean"],
        "highest_mean": pa.iloc[0]["EII Mean"],
        "elevation_r": corr["elevation"]["Pearson r"],
        "elevation_p": corr["elevation"]["Pearson p"],
        "ndvi_r": corr["ndvi"]["Pearson r"],
        "ndvi_p": corr["ndvi"]["Pearson p"],
        "treecover_r": corr["treecover2000"]["Pearson r"],
        "treecover_p": corr["treecover2000"]["Pearson p"],
        "hmi_r": corr["hmi"]["Pearson r"],
        "hmi_p": corr["hmi"]["Pearson p"],
        "cf_r2": cf_diag["r_squared"],
        "drivers_r2": drivers_diag["r_squared"],
        "n_obs": int(cf_diag["n_observations"]),
        "n_clusters": int(cf_diag["n_clusters"]),
        "inside_coef": inside_coef["coefficient"],
        "inside_p": inside_coef["p_value"],
        "elev_cf_coef": elev_cf["coefficient"],
        "elev_cf_p": elev_cf["p_value"],
        "elev_drivers_coef": elev_drivers["coefficient"],
        "elev_drivers_p": elev_drivers["p_value"],
        "built_coef": built["coefficient"],
        "built_p": built["p_value"],
        "rf_elevation": rf_top["elevation"],
        "rf_hmi": rf_top["hmi"],
        "rf_ndvi": rf_top["ndvi_mean"],
        "rf_tree": rf_top["treecover2000"],
        "rf_trend": rf_top["ndvi_trend"],
        "rf_inside": rf_top["inside_outside"],
        "val_ndvi_r": val["ndvi_trend"]["Pearson r"],
        "val_ndvi_p": val["ndvi_trend"]["Pearson p"],
        "val_ndvi_s": val["ndvi_trend"]["Spearman rho"],
        "val_ndvi_sp": val["ndvi_trend"]["Spearman p"],
        "val_loss_r": val["forest_loss_inverse"]["Pearson r"],
        "val_loss_p": val["forest_loss_inverse"]["Pearson p"],
        "val_loss_s": val["forest_loss_inverse"]["Spearman rho"],
        "val_loss_sp": val["forest_loss_inverse"]["Spearman p"],
    }


def replace_between(text, start_pattern, end_pattern, replacement):
    pattern = re.compile(f"({start_pattern})(.*?)(?={end_pattern})", re.S)
    return pattern.sub(lambda m: m.group(1) + replacement, text)


def refine_manuscript():
    m = metrics()
    src = REVISION_DIR / "Manuscript_revised_MAIN.md"
    text = src.read_text(encoding="utf-8")

    abstract = (
        "Monitoring ecosystem integrity across protected-area networks is central to meeting the "
        "Kunming-Montreal Global Biodiversity Framework Target 3 commitment to conserve 30% of Earth's land by 2030, "
        "yet standardized national-scale assessments remain scarce in mountain biodiversity hotspots. We applied the "
        f"globally standardized Ecosystem Integrity Index (EII) to {m['n_pa']} protected-area network units in Bhutan's "
        f"Eastern Himalayan network, covering {m['total_area']:,.0f} km² at 300-m resolution using Google Earth Engine. "
        f"The network-wide area-weighted mean EII was {m['area_mean']:.4f} (SD = {m['sd']:.4f}), with individual means "
        f"ranging from {m['min']:.4f} to {m['max']:.4f}; {m['above_06_n']} of {m['n_pa']} units "
        f"({m['above_06_pct']:.1f}% of total network area) maintained mean EII values above 0.60. Structural and "
        f"compositional integrity were consistently high (means = {m['struct_mean']:.3f} and {m['comp_mean']:.3f}), "
        f"whereas functional integrity showed greater spatial heterogeneity (mean = {m['func_mean']:.4f}). Biological "
        "corridors exhibited the widest integrity range among protected-area categories, with direct implications for "
        f"landscape connectivity management. Counterfactual comparisons indicated that {m['positive_inside_n']} of "
        f"{m['n_pa']} units exhibited higher integrity inside their boundaries, while elevation ({m['rf_elevation']:.1f}%) "
        f"and human modification ({m['rf_hmi']:.1f}%) dominated spatial variation. These findings demonstrate how "
        "standardized integrity metrics can operationalize Target 3 compliance monitoring and provide a transferable "
        "framework for data-limited mountain regions."
    )
    text = replace_between(text, r"## Abstract\s*\n\n", r"\n\n\*\*Keywords:\*\*", abstract + "\n\n")

    replacements = {
        "all 19 protected areas and biological corridors": f"all {m['n_pa']} protected-area network units",
        "all 19 protected areas in Bhutan": f"all {m['n_pa']} protected-area network units in Bhutan",
        "19 protected areas and biological corridors": f"{m['n_pa']} protected-area network units",
        "19 protected areas": f"{m['n_pa']} protected-area network units",
        "19 protected-area clusters": f"{m['n_clusters']} protected-area clusters",
        "19,750.16 km²": f"{m['total_area']:,.2f} km²",
        "19,750 km²": f"{m['total_area']:,.0f} km²",
        "256,410 pixels": f"{m['pixels']:,} pixels",
        "nine biological corridors": "10 biological corridors",
        "13 of 19": f"{m['positive_inside_n']} of {m['n_pa']}",
        "13 of the 19": f"{m['positive_inside_n']} of the {m['n_pa']}",
        "14 of 19": f"{m['above_06_n']} of {m['n_pa']}",
        "89.6%": f"{m['above_06_pct']:.1f}%",
        "0.6785": f"{m['area_mean']:.4f}",
        "0.1019": f"{m['sd']:.4f}",
        "0.6511": f"{m['simple_mean']:.4f}",
        "0.6782": f"{m['pixel_mean']:.4f}",
        "0.6742": f"{m['median']:.4f}",
        "0.1374": f"{m['iqr']:.4f}",
        "0.6547": f"{m['func_mean']:.4f}",
        "0.9522": f"{m['struct_mean']:.4f}",
        "0.9520": f"{m['comp_mean']:.4f}",
        "49,933": f"{m['n_obs']:,}",
        "R² = 0.380": f"R² = {m['cf_r2']:.3f}",
        "R² = 0.2661": f"R² = {m['drivers_r2']:.4f}",
        "coefficient = 0.0133, p = 0.088": f"coefficient = {m['inside_coef']:.4f}, p = {m['inside_p']:.3f}",
        "coefficient = 5.2 × 10^−5^, p < 0.001": f"coefficient = {m['elev_cf_coef']:.1e}, p < 0.001",
        "drivers coefficient = 5.5 × 10^−5^, p < 0.001": f"drivers coefficient = {m['elev_drivers_coef']:.1e}, p < 0.001",
        "coefficient = −0.1388, p < 0.001": f"coefficient = {m['built_coef']:.4f}, p < 0.001",
        "0.618, 61.8%": f"{m['rf_elevation'] / 100:.3f}, {m['rf_elevation']:.1f}%",
        "0.207, 20.7%": f"{m['rf_hmi'] / 100:.3f}, {m['rf_hmi']:.1f}%",
        "0.101, 10.1%": f"{m['rf_ndvi'] / 100:.3f}, {m['rf_ndvi']:.1f}%",
        "0.039, 3.9%": f"{m['rf_tree'] / 100:.3f}, {m['rf_tree']:.1f}%",
        "0.026, 2.6%": f"{m['rf_trend'] / 100:.3f}, {m['rf_trend']:.1f}%",
        "less than 1%": f"{m['rf_inside']:.1f}%",
        "47.4%, approximately 9,371 km²": f"{m['above_07_pct']:.1f}%, approximately {m['above_07_area']:,.0f} km²",
        "2,048 km²": f"{m['below_06_area']:,.0f} km²",
        "Pearson's r = 0.791, p < 0.001": f"Pearson's r = {m['elevation_r']:.3f}, p < 0.001",
        "r = −0.654, p = 0.002": f"r = {m['ndvi_r']:.3f}, p = {m['ndvi_p']:.3f}",
        "r = −0.565, p = 0.012": f"r = {m['treecover_r']:.3f}, p = {m['treecover_p']:.3f}",
        "r = −0.536, p = 0.018": f"r = {m['hmi_r']:.3f}, p = {m['hmi_p']:.3f}",
        "Pearson's r = 0.308, p = 0.199; Spearman's ρ = 0.312, p = 0.193": (
            f"Pearson's r = {m['val_ndvi_r']:.3f}, p = {m['val_ndvi_p']:.3f}; "
            f"Spearman's ρ = {m['val_ndvi_s']:.3f}, p = {m['val_ndvi_sp']:.3f}"
        ),
        "Pearson's r = −0.212, p = 0.385; Spearman's ρ = 0.002, p = 0.994": (
            f"Pearson's r = {m['val_loss_r']:.3f}, p = {m['val_loss_p']:.3f}; "
            f"Spearman's ρ = {m['val_loss_s']:.3f}, p = {m['val_loss_sp']:.3f}"
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    table1 = "\n\n" + network_summary_table() + "\n\n"
    text = replace_between(
        text,
        r"\*\*Table 1\*\* Network summary statistics for Bhutan's protected area network\s*\n",
        r"\*EII ranges from 0 to 1",
        table1,
    )

    table2 = "\n\n" + pa_summary_table() + "\n\n"
    text = replace_between(
        text,
        r"\*\*Table 2\*\* Ecosystem Integrity Index \(EII\) summary statistics for Bhutan's protected areas\s*\n",
        r"\*EII values range from 0 to 1",
        table2,
    )

    text = text.replace("Full covariate summaries are provided in Table S6.", "Full covariate summaries and validation details are provided in Tables S6-S8.")
    text = clean_name(text)

    out_md = OUT_DIR / "Manuscript_refined_MAIN.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(text, encoding="utf-8")
    return out_md


def refine_supplementary():
    tables = [
        ("S1", "EII component statistics by protected-area network unit", "table2_components_by_pa.csv"),
        ("S2", "Category-level EII summary statistics", "category_eii_summary.csv"),
        ("S3", "Category-level EII component summaries", "category_component_summary.csv"),
        ("S4", "Pairwise differences in mean EII", "category_pairwise_differences.csv"),
        ("S5", "Inside-outside buffer comparison at 10-km distance", "table4_inside_vs_outside.csv"),
        ("S6", "Environmental and anthropogenic covariate summaries", "table5_covariates_summary.csv"),
        ("S7", "EII-covariate concordance", "table5b_eii_covariate_concordance.csv"),
        ("S8", "Validation summary", "table7_validation.csv"),
    ]
    lines = [
        "# Supplementary Materials: Ecosystem Integrity in Bhutan's Protected Area Network",
        "",
        f"Generated from latest pipeline outputs on {datetime.now().date().isoformat()}.",
        "",
    ]
    for table_id, title, filename in tables:
        df = pd.read_csv(RESULTS_TABLES / filename)
        lines.extend([f"## {table_id}. {title}", "", f"**Table {table_id}** {title}", "", md_table(df), ""])
    lines.extend(
        [
            "## Supplementary figures",
            "",
            "![](supplementary_assets/Fig_S1.png)",
            "",
            "**Fig. S1** EII component patterns across Bhutan's protected-area network.",
            "",
            "![](supplementary_assets/Fig_S2.png)",
            "",
            "**Fig. S2** Inside-outside EII distributions.",
            "",
            "![](supplementary_assets/Fig_S3.png)",
            "",
            "**Fig. S3** EII and Human Modification Index relationship.",
            "",
        ]
    )
    out_md = OUT_DIR / "supplementary_materials_refined.md"
    out_md.write_text(clean_name("\n".join(lines)) + "\n", encoding="utf-8")
    return out_md


def refined_cover_letter():
    text = """# Cover Letter

24 April 2026

J. Alexander Elvir  
Editor  
*Environmental Monitoring and Assessment*  
Springer Nature

**Re: Revised submission -- "Ecosystem Integrity in Bhutan's Protected Area Network: A Spatial Assessment Using the Ecosystem Integrity Index"**  
Submission ID: a8f591a4-a498-41d4-aa68-58e18aa3a904

Dear Dr Elvir,

We submit a refined revised version of our manuscript for consideration in *Environmental Monitoring and Assessment*. We have addressed the editorial screening requirements by replacing the keywords, ensuring that the main figures and tables with titles are included within the manuscript body, and revising the reference list toward APA 7 formatting with DOI links where available.

The study presents a national-scale assessment of ecosystem integrity across Bhutan's protected-area network using the globally standardized Ecosystem Integrity Index and Google Earth Engine. The analysis covers 20 protected-area network units across 20,151 km² at 300-m resolution and provides a reproducible monitoring baseline aligned with protected-area effectiveness assessment and Kunming-Montreal Global Biodiversity Framework reporting.

The manuscript has not been published previously and is not under consideration elsewhere. All authors have approved the revised submission and authorship order. The work uses spatial datasets and remote-sensing products only and did not involve human participants, animal subjects, or field sampling.

Field of interest/expertise: conservation monitoring, ecosystem integrity assessment, protected-area management, spatial ecology, and remote sensing.

Suggested reviewers should be inserted in the submission system as requested by the journal.

Yours sincerely,

Wangdi Wangdi  
on behalf of all authors
"""
    out_md = OUT_DIR / "Cover_Letter_refined.md"
    out_md.write_text(text, encoding="utf-8")
    return out_md


def refined_response():
    text = """# Point-by-Point Response to the Editor

Submission ID: a8f591a4-a498-41d4-aa68-58e18aa3a904

We thank the editor for the screening comments. The manuscript has not yet undergone peer review, and we have revised the submission files to address the editorial requirements before further consideration.

## Comment 1. Some keywords need to be replaced. See guidelines.

**Response:** Revised. The keyword list now contains six indexing terms and avoids duplicating the title wording where possible:

Ecosystem Integrity Index; protected area effectiveness; spatial analysis; Bhutan; Eastern Himalaya; Google Earth Engine.

## Comment 2. Figures and tables, with their titles, should be submitted within the body of the text. See guidelines.

**Response:** Revised. The main manuscript now includes the core figures and tables in the body of the text with titles and captions. Extended material has been moved to supplementary materials and is cited from the main text. The supplementary file includes supporting tables and figures with titles.

## Comment 3. Revise the in-text citations and the reference list accordingly. Preprints, theses/dissertations, and non-English journal references should be removed or replaced. References should follow APA 7 and include DOIs where available.

**Response:** Revised. The reference list was screened for non-compliant source types and revised toward APA 7 formatting. DOI links are included where available. The in-text citations and reference list were checked for consistency.

## General compliance

**Response:** The revised package includes the manuscript, supplementary material, cover letter, response letter, declarations, and a submission-readiness checklist. The manuscript uses a clean version without visible tracked changes.
"""
    out_md = OUT_DIR / "Response_to_Editor_refined.md"
    out_md.write_text(text, encoding="utf-8")
    return out_md


def copy_figures():
    fig_dir = OUT_DIR / "Figures"
    supp_dir = OUT_DIR / "supplementary_assets"
    fig_dir.mkdir(parents=True, exist_ok=True)
    supp_dir.mkdir(parents=True, exist_ok=True)

    source_study_map = REVISION_DIR / "Figures" / "Figure 1.png"
    shutil.copy2(source_study_map, fig_dir / "Figure 1.png")
    shutil.copy2(RESULTS_FIGURES / "fig1_eii_map.png", fig_dir / "Figure 2.png")
    shutil.copy2(RESULTS_FIGURES / "fig2_pa_comparison.png", fig_dir / "Figure 3.png")
    shutil.copy2(RESULTS_FIGURES / "fig9_delta_eii_summary.png", fig_dir / "Figure 6.png")
    shutil.copy2(RESULTS_FIGURES / "fig3_components.png", supp_dir / "Fig_S1.png")
    shutil.copy2(RESULTS_FIGURES / "fig8_inside_outside_boxplot.png", supp_dir / "Fig_S2.png")
    shutil.copy2(RESULTS_FIGURES / "fig10_eii_vs_hmi.png", supp_dir / "Fig_S3.png")


def run_pandoc(md_path, docx_path):
    subprocess.run(["pandoc", str(md_path), "-o", str(docx_path)], cwd=md_path.parent, check=True)


def add_line_numbers(docx_path):
    doc = Document(docx_path)
    for section in doc.sections:
        sect_pr = section._sectPr
        existing = sect_pr.find("./w:lnNumType", sect_pr.nsmap)
        if existing is not None:
            sect_pr.remove(existing)
        ln_num_type = OxmlElement("w:lnNumType")
        ln_num_type.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}countBy", "1")
        ln_num_type.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}restart", "continuous")
        sect_pr.append(ln_num_type)
    doc.save(docx_path)


def generate_docx(paths):
    for md_path in paths:
        docx_path = md_path.with_suffix(".docx")
        run_pandoc(md_path, docx_path)
        if md_path.name.startswith("Manuscript_"):
            add_line_numbers(docx_path)


def audit_report():
    checks = []
    manuscript = OUT_DIR / "Manuscript_refined_MAIN.md"
    text = manuscript.read_text(encoding="utf-8")
    checks.append(("No stale 19-unit wording", "19 protected" not in text and "13 of 19" not in text))
    checks.append(("Current 20-unit wording present", "20 protected-area network units" in text))
    checks.append(("Main figures embedded as markdown links", all(f"Figures/Figure {n}.png" in text for n in [1, 2, 3, 6])))
    checks.append(("Supplementary references present", all(token in text for token in ["Table S1", "Table S5", "Fig. S1"])))
    checks.append(("Declarations section present", "statements and declarations" in text.lower()))
    checks.append(("References section present", "## References" in text))

    lines = ["# EMAS Submission Readiness Checklist", "", f"Generated: {datetime.now().isoformat()}", ""]
    for name, ok in checks:
        lines.append(f"- [{'x' if ok else ' '}] {name}")
    lines.extend(
        [
            "",
            "## Files generated",
            "",
            "- `Manuscript_refined_MAIN.docx`",
            "- `supplementary_materials_refined.docx`",
            "- `Cover_Letter_refined.docx`",
            "- `Response_to_Editor_refined.docx`",
            "",
            "## Manual checks before upload",
            "",
            "- Insert three to five suggested reviewers in the Springer submission system.",
            "- Open the DOCX files in Word and confirm line numbering, page breaks, and table fit.",
            "- Confirm the final author contribution and declaration wording in the submission interface.",
            "- Upload clean files only; do not upload backup/source audit files unless requested.",
        ]
    )
    out = OUT_DIR / "SUBMISSION_READINESS_CHECKLIST.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def parse_args():
    parser = argparse.ArgumentParser(description="Generate refined EMAS manuscript package")
    parser.add_argument("--no-docx", action="store_true", help="Only generate markdown and assets")
    return parser.parse_args()


def main():
    args = parse_args()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    copy_figures()
    generated = [
        refine_manuscript(),
        refine_supplementary(),
        refined_cover_letter(),
        refined_response(),
    ]
    report = audit_report()
    if not args.no_docx:
        generate_docx(generated)

    print(f"Generated refined submission package: {OUT_DIR}")
    print(f"Audit checklist: {report}")


if __name__ == "__main__":
    raise SystemExit(main())
