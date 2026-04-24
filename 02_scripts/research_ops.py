#!/usr/bin/env python3
"""
Research operations for publication-grade reproducibility.

This script adds Feynman-style research workflows to the EII Bhutan pipeline:
doctor checks, output indexing, replication reporting, and claim auditing.
"""

import argparse
import csv
import hashlib
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BASE_DIR / "02_scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from _shared.config import CONFIG, get_path, validate_paths


REQUIRED_PACKAGES = [
    "geopandas",
    "shapely",
    "pyproj",
    "fiona",
    "rasterio",
    "pandas",
    "numpy",
    "matplotlib",
    "ee",
    "yaml",
    "statsmodels",
    "scipy",
    "sklearn",
]

EXPECTED_TABLES = [
    ("table1_pa_eii_summary.csv", "PA-level EII summary", "06_pa_zonal_stats.py"),
    ("table2_components_by_pa.csv", "Component integrity by PA", "06_pa_zonal_stats.py"),
    ("bhutan_network_summary.csv", "Network-wide summary", "08_summary_statistics.py"),
    ("table4_inside_vs_outside.csv", "Inside vs outside PA comparison", "12_inside_outside_buffers.py"),
    ("table5_covariates_summary.csv", "Covariate summary by PA", "13_covariates_zonal_stats.py"),
    ("table5b_eii_covariate_concordance.csv", "EII-covariate concordance", "13_covariates_zonal_stats.py"),
    ("table6_models_coefficients.csv", "Regression model coefficients", "15_models_drivers.py"),
    ("table6b_models_diagnostics.csv", "Model diagnostics", "15_models_drivers.py"),
    ("table6c_rf_importance.csv", "RandomForest variable importance", "15_models_drivers.py"),
    ("table7_validation.csv", "Empirical validation summary", "16_validation.py"),
]

EXPECTED_FIGURES = [
    ("fig1_eii_map.png", "EII choropleth map", "09_maps_eii.py"),
    ("fig2_pa_comparison.png", "PA comparison chart", "11_figures_publication.py"),
    ("fig3_components.png", "Component integrity figure", "10_maps_components.py"),
    ("fig5_inside_outside_effect.png", "Inside/outside effect plot", "15_models_drivers.py"),
    ("fig6_driver_effects.png", "Driver coefficient plot", "15_models_drivers.py"),
    ("fig6b_rf_importance.png", "RandomForest importance plot", "15_models_drivers.py"),
    ("fig7_validation_scatter.png", "Validation scatter plot", "16_validation.py"),
    ("fig8_inside_outside_boxplot.png", "Inside/outside boxplot", "12_figures_counterfactual_and_covariates.py"),
    ("fig9_delta_eii_summary.png", "Delta EII summary", "12_figures_counterfactual_and_covariates.py"),
    ("fig10_eii_vs_hmi.png", "EII vs Human Modification", "12_figures_counterfactual_and_covariates.py"),
    ("fig11_eii_vs_forest_loss.png", "EII vs forest loss", "12_figures_counterfactual_and_covariates.py"),
]

CLAIMS_TEMPLATE = [
    {
        "claim_id": "C01",
        "claim": "Bhutan protected-area network units have measurable EII variation.",
        "primary_evidence": "03_results/tables/table1_pa_eii_summary.csv",
        "figure": "03_results/figures/fig2_pa_comparison.png",
        "generating_script": "02_scripts/03_analysis/06_pa_zonal_stats.py",
        "status": "ready_for_review",
        "notes": "Confirm exact wording against manuscript text.",
    },
    {
        "claim_id": "C02",
        "claim": "Inside protected-area EII differs from nearby outside-buffer EII.",
        "primary_evidence": "03_results/tables/table4_inside_vs_outside.csv",
        "figure": "03_results/figures/fig8_inside_outside_boxplot.png",
        "generating_script": "02_scripts/03_analysis/12_inside_outside_buffers.py",
        "status": "ready_for_review",
        "notes": "Use model table if making inferential rather than descriptive claim.",
    },
    {
        "claim_id": "C03",
        "claim": "Human pressure covariates are associated with EII patterns.",
        "primary_evidence": "03_results/tables/table5b_eii_covariate_concordance.csv",
        "figure": "03_results/figures/fig10_eii_vs_hmi.png",
        "generating_script": "02_scripts/03_analysis/13_covariates_zonal_stats.py",
        "status": "ready_for_review",
        "notes": "Avoid causal language unless supported by model specification.",
    },
    {
        "claim_id": "C04",
        "claim": "Driver models identify relative importance of pressure and condition variables.",
        "primary_evidence": "03_results/tables/table6_models_coefficients.csv",
        "figure": "03_results/figures/fig6_driver_effects.png",
        "generating_script": "02_scripts/03_analysis/15_models_drivers.py",
        "status": "ready_for_review",
        "notes": "Report uncertainty and diagnostics with coefficients.",
    },
    {
        "claim_id": "C05",
        "claim": "Independent validation metrics are consistent with EII patterns.",
        "primary_evidence": "03_results/tables/table7_validation.csv",
        "figure": "03_results/figures/fig7_validation_scatter.png",
        "generating_script": "02_scripts/03_analysis/16_validation.py",
        "status": "ready_for_review",
        "notes": "State whether GEDI or fallback validation was used.",
    },
]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_pipeline_run(base_dir):
    runs = sorted(
        (base_dir / "05_reproducibility").glob("pipeline_run_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return runs[0] if runs else None


def check_package(name):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        return False, str(exc)
    version = getattr(module, "__version__", "installed")
    return True, version


def command_doctor(args):
    base_dir = args.base_dir.resolve()
    checks = []

    path_result = validate_paths(base_dir=base_dir)
    checks.append(("Required input paths", path_result["valid"], "; ".join(path_result["missing"])))

    for package in REQUIRED_PACKAGES:
        ok, detail = check_package(package)
        checks.append((f"Python package: {package}", ok, detail))

    pa_path = get_path("protected_areas", base_dir)
    if pa_path.exists():
        try:
            import geopandas as gpd

            pa_count = len(gpd.read_file(pa_path, layer=CONFIG["protected_areas_layer"]))
            checks.append(
                (
                    "Protected-area count",
                    pa_count == CONFIG["expected_pa_count"],
                    f"found {pa_count}, expected {CONFIG['expected_pa_count']}",
                )
            )
        except Exception as exc:
            checks.append(("Protected-area count", False, str(exc)))

    run_path = latest_pipeline_run(base_dir)
    checks.append(("Latest pipeline run log", run_path is not None, str(run_path) if run_path else "missing"))
    if run_path:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        failed = [step["script"] for step in run.get("scripts", []) if step.get("status") != "success"]
        checks.append(("Latest pipeline status", not failed, ", ".join(failed) if failed else "all scripts succeeded"))

    missing_outputs = []
    for filename, _, _ in EXPECTED_TABLES:
        if not (base_dir / "03_results" / "tables" / filename).exists():
            missing_outputs.append(filename)
    for filename, _, _ in EXPECTED_FIGURES:
        if not (base_dir / "03_results" / "figures" / filename).exists():
            missing_outputs.append(filename)
    checks.append(("Expected result artifacts", not missing_outputs, ", ".join(missing_outputs) if missing_outputs else "all present"))

    print("EII Research Doctor")
    print("=" * 60)
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")

    if any(not ok for _, ok, _ in checks):
        return 1
    return 0


def output_record(base_dir, folder, filename, description, script):
    path = base_dir / "03_results" / folder / filename
    if not path.exists():
        return {
            "file": f"03_results/{folder}/{filename}",
            "description": description,
            "generated_by": script,
            "status": "missing",
            "size_bytes": "",
            "sha256": "",
        }
    return {
        "file": f"03_results/{folder}/{filename}",
        "description": description,
        "generated_by": script,
        "status": "present",
        "size_bytes": str(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def command_output_index(args):
    base_dir = args.base_dir.resolve()
    records = []
    for filename, description, script in EXPECTED_TABLES:
        records.append(output_record(base_dir, "tables", filename, description, script))
    for filename, description, script in EXPECTED_FIGURES:
        records.append(output_record(base_dir, "figures", filename, description, script))

    out_path = base_dir / "03_results" / "OUTPUT_INDEX.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Output Index",
        "",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "| File | Description | Generated by | Status | Size bytes | SHA256 |",
        "|------|-------------|--------------|--------|------------|--------|",
    ]
    for record in records:
        lines.append(
            "| {file} | {description} | {generated_by} | {status} | {size_bytes} | {sha256} |".format(**record)
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def command_claims_audit(args):
    base_dir = args.base_dir.resolve()
    out_path = base_dir / "05_reproducibility" / "claims_audit.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["claim_id", "claim", "primary_evidence", "figure", "generating_script", "status", "notes"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(CLAIMS_TEMPLATE)
    print(f"Wrote {out_path}")
    return 0


def command_replication_report(args):
    base_dir = args.base_dir.resolve()
    run_path = latest_pipeline_run(base_dir)
    out_path = base_dir / "05_reproducibility" / "REPLICATION_REPORT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Replication Report",
        "",
        f"Generated: {datetime.now().isoformat()}",
        f"Project: {CONFIG['project_title']}",
        "",
    ]

    if not run_path:
        lines.extend(["## Latest Pipeline Run", "", "No pipeline run log found.", ""])
    else:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        failed = [step for step in run.get("scripts", []) if step.get("status") != "success"]
        lines.extend(
            [
                "## Latest Pipeline Run",
                "",
                f"- Log: `{run_path.relative_to(base_dir)}`",
                f"- Pipeline version: `{run.get('pipeline_version')}`",
                f"- Timestamp: `{run.get('timestamp')}`",
                f"- Total elapsed seconds: `{run.get('total_elapsed_seconds')}`",
                f"- Overall status: `{'success' if not failed else 'failed'}`",
                "",
                "| Script | Status | Elapsed seconds |",
                "|--------|--------|-----------------|",
            ]
        )
        for step in run.get("scripts", []):
            lines.append(f"| {step.get('script')} | {step.get('status')} | {step.get('elapsed_seconds', '')} |")
        lines.append("")

    lines.extend(
        [
            "## Configuration",
            "",
            f"- Expected protected-area network units: `{CONFIG['expected_pa_count']}`",
            f"- EII asset: `{CONFIG['gee_eii_asset']}`",
            f"- Analysis scale: `{CONFIG['analysis_scale']}` m",
            f"- Analysis CRS: `{CONFIG['analysis_crs']}`",
            "",
            "## Reproducibility Artifacts",
            "",
            "- `03_results/OUTPUT_INDEX.md` records generated outputs and SHA256 hashes.",
            "- `05_reproducibility/claims_audit.csv` maps manuscript-style claims to evidence artifacts.",
            "- `05_reproducibility/gee_assets_used.txt` records Earth Engine assets used by the run.",
            "",
        ]
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def command_all(args):
    exit_codes = [
        command_output_index(args),
        command_claims_audit(args),
        command_replication_report(args),
        command_doctor(args),
    ]
    return 1 if any(exit_codes) else 0


def parse_args():
    parser = argparse.ArgumentParser(description="Research operations for EII Bhutan")
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR, help="Project base directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Diagnose setup, dependencies, outputs, and latest run")
    subparsers.add_parser("output-index", help="Generate 03_results/OUTPUT_INDEX.md")
    subparsers.add_parser("claims-audit", help="Generate claims-to-evidence audit CSV")
    subparsers.add_parser("replication-report", help="Generate latest-run replication report")
    subparsers.add_parser("all", help="Generate all research artifacts and run doctor")
    return parser.parse_args()


def main():
    args = parse_args()
    handlers = {
        "doctor": command_doctor,
        "output-index": command_output_index,
        "claims-audit": command_claims_audit,
        "replication-report": command_replication_report,
        "all": command_all,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
