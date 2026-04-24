#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
01_authenticate_gee.py
Authenticate Google Earth Engine using service account key (non-interactive).
"""

import sys
import json
from pathlib import Path
from datetime import datetime

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _shared.config import get_base_dir
from _shared.gee_utils import authenticate_gee, get_gee_service_account

__version__ = "1.1.0"

def main():
    print(f"[{datetime.now().isoformat()}] Starting GEE service account authentication (v{__version__})")

    try:
        base_dir = get_base_dir()
        key_path = authenticate_gee(base_dir=base_dir)
        service_account = get_gee_service_account()
        if not service_account:
            with open(key_path, "r", encoding="utf-8") as f:
                service_account = json.load(f).get("client_email", "<unknown>")
        print(f"✅ Using service account: {service_account}")
        print(f"✅ Credential file: {key_path}")
        print("✅ SUCCESS: Earth Engine authenticated via service account!")

        # Test with public dataset
        print("🌍 Testing with Bhutan boundary (FAO/GAUL)...")
        bhutan = ee.FeatureCollection("FAO/GAUL/2015/level0").filter(
            ee.Filter.eq('ADM0_NAME', 'Bhutan')
        )
        centroid = bhutan.geometry().centroid(100).getInfo()
        print(f"📍 Bhutan centroid: {centroid['coordinates']}")

        # Write success marker
        success_file = Path(__file__).with_name("_SUCCESS_01_authenticate_gee.txt")
        with open(success_file, "w", encoding="utf-8") as f:
            f.write(f"Authenticated at: {datetime.now().isoformat()}\n")
            f.write(f"Service account: {service_account}\n")
        print(f"✅ Success marker: {success_file}")

    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
