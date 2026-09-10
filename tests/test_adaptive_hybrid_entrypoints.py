from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    "adaptive_hybrid_bundle",
    "adaptive_hybrid_supervisor",
    "adaptive_hybrid_structural_preflight",
    "adaptive_hybrid_analyze",
    "adaptive_hybrid_run",
    "adaptive_hybrid_monitor",
    "adaptive_hybrid_supersede",
)


def test_current_entrypoints_import_and_expose_no_io_help() -> None:
    for module in ENTRYPOINTS:
        completed = subprocess.run(
            [sys.executable, "-m", f"host.otis_tools.{module}", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        assert completed.returncode == 0, (
            f"{module} import/help failed:\n{completed.stdout}{completed.stderr}"
        )
        assert "usage:" in completed.stdout.lower()
