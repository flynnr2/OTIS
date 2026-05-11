from pathlib import Path

from host.otis_tools.report_run import render_report
from host.otis_tools.run_loader import load_manifest
from host.otis_tools.validate_run import validate_run

EXAMPLE = Path("examples/h0_pps_tcxo_synthetic")


def test_load_manifest() -> None:
    manifest = load_manifest(EXAMPLE)
    assert manifest.run_id == "h0_pps_tcxo_synthetic_001"


def test_validate_example_run() -> None:
    assert validate_run(EXAMPLE) == 0


def test_render_report_mentions_contracts() -> None:
    report = render_report(EXAMPLE)
    assert "raw_events_v1" in report
    assert "count_observations_v1" in report
    assert "health_v1" in report
