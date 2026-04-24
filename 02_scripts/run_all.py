#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py
Master pipeline runner for EII Bhutan Protected Areas analysis.

This script orchestrates the execution of all analysis scripts in the
correct order as defined in run_order.yaml.

Version History:
    1.0.0 - Initial implementation
    1.2.0 - Dry-run is read-only; script-specific flags are routed safely
"""

__version__ = "1.2.0"

import argparse
import subprocess
import sys
import yaml
import json
from pathlib import Path
from datetime import datetime


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "run_all"
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
FLAG_ARG_NAMES = {
    "--overwrite": "overwrite",
    "--enable-exports": "enable_exports",
    "--enable-method-compare": "enable_method_compare",
    "--allow-pa-count-mismatch": "allow_pa_count_mismatch",
    "--allow-geometry-simplification": "allow_geometry_simplification",
}
SCRIPT_FLAG_ARG_NAMES = {
    "12_inside_outside_buffers.py": {
        "--multi-buffer": "multi_buffer",
    },
    "16_validation.py": {
        "--force-fallback": "force_fallback",
    },
}
SCRIPT_VALUE_ARG_NAMES = {
    "12_inside_outside_buffers.py": {
        "--buffer-km": "buffer_km",
    },
    "14_sample_points_for_models.py": {
        "--target-points": "target_points",
    },
}


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the complete EII Bhutan PA analysis pipeline"
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=str(BASE_DIR),
        help="Override base project directory"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files"
    )
    parser.add_argument(
        "--enable-exports",
        action="store_true",
        help="Enable GEE batch exports"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Enable sensitivity analysis with alternative methods"
    )
    parser.add_argument(
        "--allow-pa-count-mismatch",
        action="store_true",
        help="Allow PA count different from expected 20"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Allow geometry simplification"
    )
    parser.add_argument(
        "--stage",
        type=str,
        default="all",
        help="Run only a specific stage"
    )
    parser.add_argument(
        "--script",
        type=str,
        default=None,
        help="Run only a specific script (e.g., '03_download_eii.py')"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing"
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue execution even if a script fails"
    )
    parser.add_argument(
        "--multi-buffer",
        action="store_true",
        help="Pass --multi-buffer to scripts that support multiple buffer distances"
    )
    parser.add_argument(
        "--buffer-km",
        type=float,
        default=None,
        help="Pass a custom buffer distance in kilometers to supported scripts"
    )
    parser.add_argument(
        "--target-points",
        type=int,
        default=None,
        help="Pass target sample-point count to supported modeling sample scripts"
    )
    parser.add_argument(
        "--force-fallback",
        action="store_true",
        help="Pass --force-fallback to validation scripts that support it"
    )
    return parser.parse_args()


def load_run_order():
    """Load the pipeline execution order from YAML."""
    yaml_path = SCRIPTS_DIR / "run_order.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Run order file not found: {yaml_path}")

    with open(yaml_path, 'r') as f:
        return yaml.safe_load(f)


def build_command(script_info, args, run_order):
    """
    Build the command to execute a script.

    Args:
        script_info: Dictionary with script metadata
        args: Parsed command line arguments

    Returns:
        List of command arguments
    """
    script_path = SCRIPTS_DIR / script_info["path"]
    script_name = script_info["name"]
    cmd = [sys.executable, str(script_path)]

    # Add base directory
    cmd.extend(["--base-dir", args.base_dir])

    for flag in run_order.get("default_flags", []):
        if flag not in cmd:
            cmd.append(flag)

    # Add optional flags
    for flag, arg_name in FLAG_ARG_NAMES.items():
        if getattr(args, arg_name, False) and flag not in cmd:
            cmd.append(flag)

    for flag, arg_name in SCRIPT_FLAG_ARG_NAMES.get(script_name, {}).items():
        if getattr(args, arg_name, False) and flag not in cmd:
            cmd.append(flag)

    for flag, arg_name in SCRIPT_VALUE_ARG_NAMES.get(script_name, {}).items():
        value = getattr(args, arg_name, None)
        if value is not None and flag not in cmd:
            cmd.extend([flag, str(value)])

    return cmd


def run_script(script_info, args, run_log, run_order):
    """
    Run a single script.

    Args:
        script_info: Dictionary with script metadata
        args: Parsed command line arguments
        run_log: List to append execution results

    Returns:
        bool: True if successful, False otherwise
    """
    script_name = script_info["name"]
    script_path = SCRIPTS_DIR / script_info["path"]

    if not script_path.exists():
        print(f"  ERROR: Script not found: {script_path}")
        run_log.append({
            "script": script_name,
            "status": "not_found",
            "error": f"Script not found: {script_path}"
        })
        return False

    cmd = build_command(script_info, args, run_order)

    print(f"\n{'='*60}")
    print(f"Running: {script_name}")
    print(f"Path: {script_path}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")

    if args.dry_run:
        print("  [DRY RUN - Not executing]")
        run_log.append({
            "script": script_name,
            "status": "dry_run",
            "command": ' '.join(cmd)
        })
        return True

    start_time = datetime.now()

    try:
        result = subprocess.run(
            cmd,
            capture_output=False,
            text=True
        )

        elapsed = (datetime.now() - start_time).total_seconds()

        if result.returncode == 0:
            print(f"\n  SUCCESS: {script_name} completed in {elapsed:.1f}s")
            run_log.append({
                "script": script_name,
                "status": "success",
                "elapsed_seconds": elapsed
            })
            return True
        else:
            print(f"\n  FAILED: {script_name} (exit code: {result.returncode})")
            run_log.append({
                "script": script_name,
                "status": "failed",
                "exit_code": result.returncode,
                "elapsed_seconds": elapsed
            })
            return False

    except Exception as e:
        print(f"\n  ERROR: {script_name} - {e}")
        run_log.append({
            "script": script_name,
            "status": "error",
            "error": str(e)
        })
        return False


def main():
    try:
        run_order = load_run_order()
    except Exception as e:
        print(f"ERROR: Failed to load run_order.yaml: {e}")
        sys.exit(1)

    args = parse_args()

    valid_stages = {stage["stage"] for stage in run_order["stages"]}
    valid_stages.add("all")
    if args.stage not in valid_stages:
        print(f"ERROR: Invalid stage '{args.stage}'. Valid stages: {sorted(valid_stages)}")
        sys.exit(1)

    print("=" * 70)
    print("EII BHUTAN PROTECTED AREAS - ANALYSIS PIPELINE")
    print(f"Version: {__version__}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    print(f"\nPipeline: {run_order['pipeline']['name']} v{run_order['pipeline']['version']}")
    print(f"Base directory: {args.base_dir}")
    if run_order.get("default_flags"):
        print(f"Default flags: {' '.join(run_order['default_flags'])}")

    # Determine which scripts to run
    scripts_to_run = []

    for stage in run_order["stages"]:
        stage_name = stage["stage"]

        # Filter by stage if specified
        if args.stage != "all" and args.stage != stage_name:
            continue

        for script in stage["scripts"]:
            # Filter by script name if specified
            if args.script and script["name"] != args.script:
                continue

            scripts_to_run.append({
                "stage": stage_name,
                **script
            })

    if not scripts_to_run:
        print("\nNo scripts to run with the specified filters.")
        sys.exit(0)

    print(f"\nScripts to run: {len(scripts_to_run)}")
    for s in scripts_to_run:
        print(f"  - [{s['stage']}] {s['name']}")

    if args.dry_run:
        print("\n[DRY RUN MODE - Commands will be printed but not executed]")

    # Run scripts
    run_log = []
    failed_scripts = []
    start_time = datetime.now()

    for script in scripts_to_run:
        success = run_script(script, args, run_log, run_order)

        if not success:
            failed_scripts.append(script["name"])
            if not args.continue_on_error and not args.dry_run:
                print(f"\nPipeline stopped due to error in {script['name']}")
                print("Use --continue-on-error to continue past failures.")
                break

    total_elapsed = (datetime.now() - start_time).total_seconds()

    # Summary
    print("\n" + "=" * 70)
    print("PIPELINE EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Total time: {total_elapsed:.1f}s")
    print(f"Scripts run: {len(run_log)}")
    print(f"Successful: {len([r for r in run_log if r['status'] == 'success'])}")
    print(f"Failed: {len(failed_scripts)}")

    if failed_scripts:
        print(f"\nFailed scripts:")
        for name in failed_scripts:
            print(f"  - {name}")

    # Write run log only for real executions. Dry-run must remain read-only.
    if args.dry_run:
        print("\nDry run complete; no run log was written.")
    else:
        log_dir = Path(args.base_dir) / "05_reproducibility"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_path = log_dir / f"pipeline_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_path, 'w') as f:
            json.dump({
                "pipeline_version": __version__,
                "timestamp": datetime.now().isoformat(),
                "args": vars(args),
                "total_elapsed_seconds": total_elapsed,
                "scripts": run_log
            }, f, indent=2)

        print(f"\nRun log saved to: {log_path}")

    # Exit with error if any scripts failed
    if failed_scripts and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
