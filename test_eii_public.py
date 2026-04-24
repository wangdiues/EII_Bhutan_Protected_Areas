#!/usr/bin/env python3
"""
Smoke-check access to the public EII Earth Engine asset.

This is intentionally a command-line smoke test, not a pytest unit test. It
requires network access and valid Earth Engine credentials.
"""

import argparse
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent / "02_scripts"))

from _shared.config import CONFIG
from _shared.gee_utils import authenticate_gee


def parse_args():
    parser = argparse.ArgumentParser(description="Check public EII asset access")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Project base directory",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Also sample one point over Bhutan after reading metadata",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    authenticate_gee(base_dir=args.base_dir)

    eii_img = ee.Image(CONFIG["gee_eii_asset"])
    info = eii_img.getInfo()
    print("SUCCESS: EII asset loaded")
    print("Bands available:")
    for band in info["bands"]:
        print(f"  - {band['id']}")

    if args.sample:
        point = ee.Geometry.Point([90.5, 27.5])
        sample = eii_img.sample(point, scale=CONFIG["analysis_scale"]).first().getInfo()
        print("Sample values:", sample["properties"])


if __name__ == "__main__":
    main()
