#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
error_utils.py
Error handling utilities for EII Bhutan Protected Areas analysis.
"""

__version__ = "1.0.0"

import time
import traceback
import json
from pathlib import Path
from datetime import datetime
from functools import wraps


class ErrorBundle:
    """Container for error information to facilitate debugging."""

    def __init__(self, script_name, version):
        self.script_name = script_name
        self.version = version
        self.timestamp = datetime.now().isoformat()
        self.error_type = None
        self.error_message = None
        self.traceback = None
        self.context = {}

    def capture_exception(self, exc):
        """Capture exception details."""
        self.error_type = type(exc).__name__
        self.error_message = str(exc)
        self.traceback = traceback.format_exc()

    def add_context(self, key, value):
        """Add context information."""
        self.context[key] = value

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "script_name": self.script_name,
            "version": self.version,
            "timestamp": self.timestamp,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "context": self.context
        }

    def to_text(self):
        """Convert to human-readable text format."""
        lines = [
            "=" * 70,
            "ERROR REPORT",
            "=" * 70,
            f"Script: {self.script_name}",
            f"Version: {self.version}",
            f"Timestamp: {self.timestamp}",
            "",
            f"Error Type: {self.error_type}",
            f"Error Message: {self.error_message}",
            "",
            "Traceback:",
            "-" * 70,
            self.traceback or "No traceback available",
            "-" * 70,
        ]

        if self.context:
            lines.extend([
                "",
                "Context:",
                "-" * 70,
            ])
            for key, value in self.context.items():
                lines.append(f"  {key}: {value}")

        lines.append("=" * 70)
        return "\n".join(lines)


def write_error_bundle(error_bundle, output_dir):
    """
    Write error bundle to disk.

    Args:
        error_bundle: ErrorBundle instance
        output_dir: Directory to write error files

    Returns:
        Path to error text file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"error_{error_bundle.script_name}_{timestamp_str}"

    # Write text file (for pasting to Claude)
    txt_path = output_dir / f"{base_name}.txt"
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(error_bundle.to_text())

    # Write JSON file (for programmatic access)
    json_path = output_dir / f"{base_name}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(error_bundle.to_dict(), f, indent=2)

    return txt_path


def retry_with_backoff(max_retries=3, delay=5, exceptions=(Exception,)):
    """
    Decorator for retrying a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay in seconds
        exceptions: Tuple of exceptions to catch and retry

    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = delay * (2 ** attempt)
                        print(f"Attempt {attempt + 1} failed: {e}")
                        print(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        raise
            raise last_exception
        return wrapper
    return decorator


def validate_inputs(required_files):
    """
    Validate that required input files exist.

    Args:
        required_files: Dict of {name: path}

    Raises:
        FileNotFoundError with details of all missing files
    """
    missing = []
    for name, path in required_files.items():
        if not Path(path).exists():
            missing.append(f"  - {name}: {path}")

    if missing:
        raise FileNotFoundError(
            "Required input files missing:\n" + "\n".join(missing)
        )


def create_validation_report(script_name, version, checks, output_dir):
    """
    Create a validation report for successful script completion.

    Args:
        script_name: Name of the script
        version: Script version
        checks: Dict of {check_name: result}
        output_dir: Directory for validation reports

    Returns:
        Path to validation report
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"validation_{script_name}_{timestamp_str}.txt"

    with open(report_path, 'w') as f:
        f.write("VALIDATION REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Script: {script_name}\n")
        f.write(f"Version: {version}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write("\nValidation Checks:\n")
        f.write("-" * 60 + "\n")

        all_passed = True
        for check_name, result in checks.items():
            status = "PASS" if result else "FAIL"
            if not result:
                all_passed = False
            f.write(f"  [{status}] {check_name}\n")

        f.write("-" * 60 + "\n")
        overall = "PASSED" if all_passed else "FAILED"
        f.write(f"Overall: {overall}\n")

    return report_path
