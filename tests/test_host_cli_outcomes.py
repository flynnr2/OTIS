"""Public shell outcomes must not promote a retained diagnostic into success."""
import json

import pytest

from host.otis_tools.__main__ import main


@pytest.mark.parametrize("status", ["abort_delivery_failed", "capture_closure_failed", "pending_review_capture_ended"])
def test_run_diagnostic_is_retained_and_nonzero(monkeypatch, capsys, status):
    from host.otis_tools import bench_entry
    monkeypatch.setattr(bench_entry, "start", lambda **kw: {"status": status})
    assert main(["run", "spec.json", "--rehearsal", "receipt.json", "--run-dir", "unused",
                 "--device", "/dev/never-open", "--operator-ref", "test", "--reason", "test"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_valid_diagnostic_package_verifies_but_failed_analysis_is_nonzero(monkeypatch, capsys):
    from host.otis_tools import adaptive_hybrid_analyze, evidence_package
    package = {"package_content_sha256": "a" * 64, "capture": {"integrity": "partial"},
               "analysis": {"status": "review_required", "outcome": "undetermined"}}
    monkeypatch.setattr(evidence_package, "validate_package", lambda path: package)
    assert main(["verify", "unused"]) == 0
    assert json.loads(capsys.readouterr().out)["capture"]["integrity"] == "partial"
    monkeypatch.setattr(adaptive_hybrid_analyze, "analyze", lambda *a, **kw: ("report", package["analysis"]))
    assert main(["analyse", "unused"]) == 2


def test_scientific_nonpass_is_successful_completed_operation(monkeypatch):
    from host.otis_tools import offline
    monkeypatch.setattr(offline, "finish_run", lambda *a, **kw: {
        "analysis": {"status": "passed", "outcome": "bounded_nonpass"}, "registration": None,
    })
    assert main(["package", "unused"]) == 0
