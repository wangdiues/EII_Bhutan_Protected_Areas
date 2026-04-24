import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "02_scripts"))

import run_all


def _args(**overrides):
    defaults = {
        "base_dir": str(PROJECT_ROOT),
        "overwrite": False,
        "enable_exports": False,
        "enable_method_compare": False,
        "allow_pa_count_mismatch": False,
        "allow_geometry_simplification": False,
        "multi_buffer": False,
        "buffer_km": None,
        "target_points": None,
        "force_fallback": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_common_flags_are_added_to_all_scripts():
    cmd = run_all.build_command(
        {"name": "03_download_eii.py", "path": "02_download/03_download_eii.py"},
        _args(overwrite=True),
        {"default_flags": []},
    )

    assert "--overwrite" in cmd


def test_script_specific_flags_are_not_added_to_unrelated_scripts():
    cmd = run_all.build_command(
        {"name": "03_download_eii.py", "path": "02_download/03_download_eii.py"},
        _args(force_fallback=True, multi_buffer=True),
        {"default_flags": []},
    )

    assert "--force-fallback" not in cmd
    assert "--multi-buffer" not in cmd


def test_script_specific_flags_are_routed_to_supported_scripts():
    validation_cmd = run_all.build_command(
        {"name": "16_validation.py", "path": "03_analysis/16_validation.py"},
        _args(force_fallback=True),
        {"default_flags": []},
    )
    buffer_cmd = run_all.build_command(
        {"name": "12_inside_outside_buffers.py", "path": "03_analysis/12_inside_outside_buffers.py"},
        _args(multi_buffer=True, buffer_km=15),
        {"default_flags": []},
    )

    assert "--force-fallback" in validation_cmd
    assert "--multi-buffer" in buffer_cmd
    assert "--buffer-km" in buffer_cmd
    assert "15" in buffer_cmd
