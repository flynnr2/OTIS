from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_stage8_final_review import (
    _active_run_history,
    _decision,
    _gate_passed,
    _next_goal,
    _sealed_run_check,
)


def test_stage8_decision_uses_exact_programme_vocabulary() -> None:
    assert _decision({}) == "blocked_before_active_control"
    assert _decision({"campaign_a": True}) == "bounded_control_needs_revision"
    assert _decision({"campaign_a": True, "campaign_b": True}) == (
        "bounded_frequency_acquisition_passed"
    )
    all_pass = {
        "campaign_a": True,
        "campaign_b": True,
        "stage6": True,
        "stage7_a1": True,
        "stage7_a2": True,
        "stage7_b": True,
        "verification": True,
    }
    assert _decision(all_pass) == "dual_core_frequency_control_endurance_passed"
    all_pass["stage7_b"] = False
    all_pass["stage7_b_attempted"] = True
    assert _decision(all_pass) == "bounded_control_needs_revision"


def test_stage8_full_pass_selects_one_phase_estimator_goal() -> None:
    goal, rationale = _next_goal("dual_core_frequency_control_endurance_passed")

    assert goal == (
        "phase_estimator_definition_and_bounded_hybrid_phase_frequency_preview"
    )
    assert "largest remaining" in rationale


def test_gate_parsers_require_exact_pass_shapes() -> None:
    assert _gate_passed({"stage_exit_passed": True}, "campaign_a")
    assert _gate_passed(
        {"status": "pass", "checks": [{"passed": True}]}, "stage6"
    )
    assert not _gate_passed(
        {"status": "pass", "checks": [{"passed": False}]}, "stage7_b"
    )
    verification = {
        "schema_version": 1,
        "pytest": {
            "result": "pass",
            "passed": 1,
            "failed": 0,
            "errors": 0,
        },
        "firmware_matrix": {
            "result": "pass",
            "passed_profiles": 22,
            "expected_pass_profiles": 22,
            "guarded_failures_observed": 7,
            "expected_fail_profiles": 7,
        },
        "no_hardware_validation": {"result": "pass"},
    }
    assert _gate_passed(verification, "verification")


def test_active_run_inventory_preserves_diagnostic_and_passed_histories(
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign"
    for name, complete in (("attempt", False), ("passed", True)):
        run = campaign / "stage7" / name
        (run / "csv").mkdir(parents=True)
        (run / "reports").mkdir()
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": name,
                    "stage": "CX317_DUAL_CORE_ACTIVE_PART_A",
                    "firmware": {"uf2_sha256": name},
                }
            ),
            encoding="utf-8",
        )
        fields = (
            "event",
            "request_sequence",
            "requested_delta_codes",
            "requested_code",
            "applied_code",
            "pre_error_hz",
            "post_error_hz",
            "observed_response_hz",
            "response_class",
            "cumulative_movement_codes",
        )
        with (run / "csv/active_transactions_v1.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "event": "manual_start",
                    "request_sequence": 0,
                    "requested_delta_codes": 0,
                    "requested_code": 43008,
                    "applied_code": 43008,
                    "pre_error_hz": 0,
                    "post_error_hz": 0,
                    "observed_response_hz": 0,
                    "response_class": "unavailable",
                    "cumulative_movement_codes": 0,
                }
            )
        (run / "evidence_manifest.json").write_text(
            json.dumps(
                {
                    "run_state": "complete" if complete else "partial",
                    "snapshot_digest": name,
                }
            ),
            encoding="utf-8",
        )
        if complete:
            (run / "COMPLETE").touch()

    history = _active_run_history(campaign)

    assert [item["run_id"] for item in history] == ["attempt", "passed"]
    assert [item["evidence_run_state"] for item in history] == [
        "partial",
        "complete",
    ]
    assert all(item["final_confirmed_code"] == 43008 for item in history)


def test_stage8_requires_closed_complete_evidence_snapshot_for_each_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    (run / "reports").mkdir(parents=True)
    gate = run / "reports/gate.json"
    gate.write_text("{}\n", encoding="utf-8")
    (run / "COMPLETE").touch()
    (run / "evidence_manifest.json").write_text(
        json.dumps(
            {
                "run_state": "complete",
                "snapshot_digest": "a" * 64,
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "host.otis_tools.cx317_stage8_final_review.load_manifest",
        lambda path: object(),
    )
    monkeypatch.setattr(
        "host.otis_tools.cx317_stage8_final_review.validate_evidence_snapshot",
        lambda path, manifest: ([], []),
    )

    check, details = _sealed_run_check("fixture", gate)
    assert check.passed
    assert details["gate_in_snapshot"] is False

    (run / "capture_in_progress.flag").touch()
    check, details = _sealed_run_check("fixture", gate)
    assert not check.passed
    assert details["capture_active"] is True


def test_stage8_accepts_validated_partial_source_only_for_declared_subtest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "part_a1"
    (run / "reports").mkdir(parents=True)
    gate = run / "reports/part_a_fixed_code_stability_gate.json"
    gate.write_text("{}\n", encoding="utf-8")
    (run / "evidence_manifest.json").write_text(
        json.dumps(
            {
                "run_state": "partial",
                "snapshot_digest": "b" * 64,
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "host.otis_tools.cx317_stage8_final_review.load_manifest",
        lambda path: object(),
    )
    monkeypatch.setattr(
        "host.otis_tools.cx317_stage8_final_review.validate_evidence_snapshot",
        lambda path, manifest: ([], []),
    )

    check, details = _sealed_run_check("stage7_a1", gate)
    assert not check.passed
    assert details["seal_class"] == "unsealed"

    check, details = _sealed_run_check(
        "stage7_a1", gate, allow_partial_subtest=True
    )
    assert check.passed
    assert (
        details["seal_class"]
        == "validated_partial_source_for_transitively_sealed_subtest"
    )

    (run / "COMPLETE").touch()
    check, details = _sealed_run_check(
        "stage7_a1", gate, allow_partial_subtest=True
    )
    assert not check.passed
    assert details["seal_class"] == "unsealed"
