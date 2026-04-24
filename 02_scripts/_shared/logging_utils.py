#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logging_utils.py
Logging utilities for EII Bhutan Protected Areas analysis.
"""

__version__ = "1.0.0"

import logging
import sys
import platform
from datetime import datetime
from pathlib import Path


def setup_logger(name, log_file=None, level=logging.INFO):
    """
    Set up a logger with console and optional file output.

    Args:
        name: Logger name
        log_file: Optional path to log file
        level: Logging level

    Returns:
        logging.Logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers = []

    # Format
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def log_session_info(logger, script_name, version, args=None):
    """
    Log session information including environment details.

    Args:
        logger: Logger instance
        script_name: Name of the script
        version: Script version
        args: Optional argparse Namespace
    """
    logger.info("=" * 70)
    logger.info(f"Script: {script_name}")
    logger.info(f"Version: {version}")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("-" * 70)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Working directory: {Path.cwd()}")

    if args:
        logger.info("-" * 70)
        logger.info("Arguments:")
        for key, value in vars(args).items():
            logger.info(f"  {key}: {value}")

    logger.info("=" * 70)


def get_session_info_dict(script_name, version, args=None):
    """
    Get session information as a dictionary.

    Args:
        script_name: Name of the script
        version: Script version
        args: Optional argparse Namespace

    Returns:
        dict with session information
    """
    info = {
        "script_name": script_name,
        "version": version,
        "timestamp": datetime.now().isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "working_directory": str(Path.cwd()),
    }

    if args:
        info["arguments"] = {k: str(v) for k, v in vars(args).items()}

    # Try to get package versions
    packages = {}
    try:
        import geopandas
        packages["geopandas"] = geopandas.__version__
    except ImportError:
        pass

    try:
        import pandas
        packages["pandas"] = pandas.__version__
    except ImportError:
        pass

    try:
        import numpy
        packages["numpy"] = numpy.__version__
    except ImportError:
        pass

    try:
        import ee
        packages["earthengine-api"] = ee.__version__
    except (ImportError, AttributeError):
        pass

    try:
        import matplotlib
        packages["matplotlib"] = matplotlib.__version__
    except ImportError:
        pass

    try:
        import rasterio
        packages["rasterio"] = rasterio.__version__
    except ImportError:
        pass

    info["packages"] = packages

    return info


def write_session_info(filepath, script_name, version, args=None):
    """
    Write session info to a text file.

    Args:
        filepath: Path to output file
        script_name: Name of the script
        version: Script version
        args: Optional argparse Namespace
    """
    info = get_session_info_dict(script_name, version, args)
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("Session Information\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Script: {info['script_name']}\n")
        f.write(f"Version: {info['version']}\n")
        f.write(f"Timestamp: {info['timestamp']}\n")
        f.write(f"Python: {info['python_version']}\n")
        f.write(f"Platform: {info['platform']}\n")
        f.write(f"Working Directory: {info['working_directory']}\n")

        if info.get("arguments"):
            f.write("\nArguments:\n")
            for k, v in info["arguments"].items():
                f.write(f"  {k}: {v}\n")

        if info.get("packages"):
            f.write("\nPackage Versions:\n")
            for pkg, ver in sorted(info["packages"].items()):
                f.write(f"  {pkg}: {ver}\n")

    return filepath
