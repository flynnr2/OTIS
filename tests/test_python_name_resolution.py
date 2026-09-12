"""Reject unresolved Python names even in paths not reached by a runtime test."""
from pathlib import Path
import subprocess
import sys


def test_current_python_entrypoints_have_no_unresolved_names():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821,F822,F823",
         "host", "tools", "firmware/arduino/validation/scripts"],
        cwd=root, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
