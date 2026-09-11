"""Offline report/journal recovery; acquisition and success validation are doubled.

The full process rehearsal separately exercises independent successful-package
validation. These tests localize restart ordering and immutable report binding.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_operational_rehearsal as rehearsal
from host.otis_tools import evidence_finalization as finalization
from host.otis_tools.evidence_index import package_identity
from test_adaptive_hybrid_operational_rehearsal import _frozen_inputs, _binding, _write_json


@pytest.mark.parametrize("entry", ["public", "validated", "journal"])
@pytest.mark.parametrize("location", ["repository", "package"])
def test_invalid_index_is_rejected_before_preparation(tmp_path, monkeypatch, entry, location):
    run = tmp_path / "not-created"
    index = (Path(rehearsal.__file__).parents[2] / "runs/invalid-index.json"
             if location == "repository" else run / "index.json")
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda *_: pytest.fail("bundle validation must not start"))
    monkeypatch.setattr(rehearsal.pty, "openpty", lambda: pytest.fail("PTY must not open"))
    with pytest.raises(ValueError, match="outside"):
        if entry == "public":
            rehearsal.run_operational_rehearsal(bundle_path=tmp_path / "bundle", proposal_path=tmp_path / "proposal",
                run_dir=run, evidence_index_path=index)
        elif entry == "validated":
            rehearsal._run_validated(bundle_path=tmp_path / "bundle", bundle={}, proposal_path=tmp_path / "proposal",
                proposal={}, run_dir=run, evidence_index_path=index)
        else:
            finalization.begin_finalization(run_dir=run, index_path=index, registration={}, required_seal=rehearsal.SEAL_PATH)
    assert not run.exists()
    assert not finalization.journal_path_for(run).exists()


def sealed_receipt(tmp_path, monkeypatch):
    bundle_path, proposal_path = _frozen_inputs(monkeypatch, tmp_path)
    bundle = json.loads(bundle_path.read_text())
    proposal = json.loads(proposal_path.read_text())
    run = tmp_path / "sealed-run"
    (run / "reports").mkdir(parents=True)
    _write_json(run / "run_manifest.json", {
        "bundle": {**_binding(bundle_path), "bundle_sha256": bundle["bundle_sha256"]},
        "proposal": {**_binding(proposal_path), "proposal_sha256": proposal["proposal_sha256"]},
    })
    _write_json(run / "COMPLETE", {"capture_closed": True})
    _write_json(run / "evidence_manifest.json", {"run_state": "complete", "snapshot_digest": "a" * 64})
    _write_json(run / rehearsal.PROCESS_EVIDENCE_PATH, {"retained": True})
    checks = {key: True for key in (
        "private_nonphysical_manifest_exact", "actual_capture_process_bound_to_closure",
        "process_command_transcript_matches_raw", "supervisor_commands_match_capture_prefix",
        "read_only_monitor_observed_lifecycle", "setup_command_bound_to_retained_authority",
        "setup_first_consumer_exact", "progressive_evidence_phases_exact",
        "first_dependent_checkpoint_before_second_arm", "coordinator_timing_and_exact_progress_bound",
        "periodic_lease_and_snapshot_boundaries", "stale_command_timeout_rejected",
        "two_arm_envelopes_bound_to_supervisor_events", "two_transactions_replayed",
        "normal_fifo_revoked_after_obstruction", "priority_abort_preceded_source_close",
        "supervisor_terminal_is_operator_abort", "same_owner_rotation_then_physical_close",
        "shared_current_analyzer_consumers_exact",
    )}
    _write_json(run / rehearsal.SEAL_PATH, {"checks": checks, "status": "passed", "seal_sha256": "b" * 64})
    metadata = rehearsal._registration_metadata(bundle, classification="successful_rehearsal",
        reason="adaptive-hybrid operational rehearsal passed")
    journal = finalization.begin_finalization(run_dir=run, index_path=tmp_path / "old-index.json",
        registration=metadata, required_seal=rehearsal.SEAL_PATH)
    for phase in finalization.PHASES[:-1]:
        finalization.advance_phase(journal, phase, {})
    identity = package_identity(run)
    finalization.set_registration_intent(journal, registration=metadata,
        expected_content_sha256=identity["content_sha256"])
    calls = []
    def registered(**kwargs):
        calls.append(kwargs)
        return {"content_sha256": kwargs["expected_content_sha256"], "attempt_classification": "successful_rehearsal"}
    monkeypatch.setattr(finalization, "register_package", registered)
    return run, journal, bundle, bundle_path, calls


def test_report_recovers_after_registration_without_reacquiring_or_resealing(tmp_path, monkeypatch):
    run, journal, bundle, _, calls = sealed_receipt(tmp_path, monkeypatch)
    before = package_identity(run)
    index = tmp_path / "corrected-index.json"
    original = rehearsal._publish_authorization_report
    monkeypatch.setattr(rehearsal, "_publish_authorization_report", lambda **_: (_ for _ in ()).throw(OSError("report write interrupted")))
    with pytest.raises(OSError, match="report write"):
        rehearsal.recover_operational_rehearsal(run_dir=run, evidence_index_path=index)
    retained = json.loads(journal.read_text())
    assert retained["phases"]["registration"] is not None
    assert retained["recovery_attempts"][0]["previous_index_path"] == str(tmp_path / "old-index.json")
    assert retained["recovery_attempts"][0]["recovery_tool"] == _binding(Path(rehearsal.__file__))
    monkeypatch.setattr(rehearsal, "_publish_authorization_report", original)
    report = rehearsal.recover_operational_rehearsal(run_dir=run, evidence_index_path=index)
    report_bytes = report.read_bytes()
    assert rehearsal.recover_operational_rehearsal(run_dir=run, evidence_index_path=index) == report
    assert report.read_bytes() == report_bytes
    assert package_identity(run) == before
    assert json.loads(report_bytes)["tool_binding"] == bundle["host_tools"]["adaptive_hybrid_operational_rehearsal"]
    assert all(call["analyzer_identity"] == bundle["host_tools"]["adaptive_hybrid_operational_rehearsal"]["sha256"] for call in calls)


def test_recovery_checks_external_bundle_bytes_after_registration(tmp_path, monkeypatch):
    run, _, _, bundle_path, _ = sealed_receipt(tmp_path, monkeypatch)
    original = finalization.register_package
    def changed(**kwargs):
        result = original(**kwargs)
        bundle_path.write_text('{}\n')
        return result
    monkeypatch.setattr(finalization, "register_package", changed)
    with pytest.raises(ValueError, match="bundle differs from the sealed manifest binding"):
        rehearsal.recover_operational_rehearsal(run_dir=run, evidence_index_path=tmp_path / "index.json")
    assert not (run.parent / f"{run.name}-{rehearsal.REPORT_NAME}").exists()


def test_changed_producer_rejection_cannot_publish_recovery_report(tmp_path, monkeypatch):
    run, _, _, _, _ = sealed_receipt(tmp_path, monkeypatch)
    before = package_identity(run)
    def reject(_journal):
        raise ValueError("recorded producer bytes differ")
    monkeypatch.setattr(rehearsal, "recover_registration", reject)
    with pytest.raises(ValueError, match="producer bytes"):
        rehearsal.recover_operational_rehearsal(run_dir=run, evidence_index_path=tmp_path / "index.json")
    assert package_identity(run) == before
    assert not (run.parent / f"{run.name}-{rehearsal.REPORT_NAME}").exists()
