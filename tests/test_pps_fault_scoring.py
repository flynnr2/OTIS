from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools.pps_fault_scoring import (
    DiagnosticObservation,
    GeneratorTruthEvent,
    PhysicalDetection,
    SnapshotValidity,
    score_fault_injection,
    main,
)


SCORING_FIXTURE = Path("tests/fixtures/pseudo_pps/scoring_v1.json")
PROFILES_FIXTURE = Path("tests/fixtures/pseudo_pps/profiles_v1.json")


def _load_score_fixture():
    fixture = json.loads(SCORING_FIXTURE.read_text(encoding="utf-8"))
    truth = [GeneratorTruthEvent(**value) for value in fixture["truth"]]
    detections = [
        PhysicalDetection(**value) for value in fixture["physical_detections"]
    ]
    snapshots = []
    for value in fixture["snapshot_validity"]:
        materialized = dict(value)
        materialized["reasons"] = tuple(materialized.get("reasons", ()))
        snapshots.append(SnapshotValidity(**materialized))
    diagnostics = [
        DiagnosticObservation(**value) for value in fixture["diagnostics"]
    ]
    return fixture, truth, detections, snapshots, diagnostics


def test_fault_score_fixture_reports_detection_failures_and_recovery() -> None:
    fixture, truth, detections, snapshots, diagnostics = _load_score_fixture()

    report = score_fault_injection(truth, detections, snapshots, diagnostics)

    for key, expected in fixture["expected_metrics"].items():
        assert getattr(report, key) == expected
    assert report.outage_transitions.expected == 1
    assert report.outage_transitions.observed == 1
    assert report.outage_transitions.missing == 0
    assert report.outage_transitions.excess == 0
    assert report.restoration_transitions.expected == 1
    assert report.restoration_transitions.observed == 1
    assert report.restoration_transitions.missing == 0
    assert report.restoration_transitions.excess == 0


def test_reminder_diagnostics_do_not_become_duplicate_outage_transitions() -> None:
    _fixture, truth, detections, snapshots, diagnostics = _load_score_fixture()
    report = score_fault_injection(truth, detections, snapshots, diagnostics)

    reminders = [item for item in diagnostics if item.transition == "reminder"]
    assert len(reminders) == 2
    assert report.outage_transitions.observed == 1
    assert report.outage_transitions.excess == 0


def test_scored_event_preserves_four_evidence_concepts_separately() -> None:
    _fixture, truth, detections, snapshots, diagnostics = _load_score_fixture()
    report = score_fault_injection(truth, detections, snapshots, diagnostics)
    short = next(item for item in report.events if item.truth.event_id == "short-1")
    payload = report.to_dict()

    assert short.truth.expected_classification == "short_interval"
    assert short.detections[0].classification == "short_interval"
    assert not short.snapshots[0].measurement_valid
    assert short.diagnostics == ()
    assert short.detection_latency_ticks == 16
    assert set(payload) >= {
        "generator_truth",
        "physical_detections",
        "snapshot_validity",
        "diagnostic_observations",
    }
    assert set(payload["events"][0]) >= {
        "truth",
        "detections",
        "snapshots",
        "diagnostics",
    }


def test_missing_false_duplicate_and_mismatch_are_not_collapsed() -> None:
    _fixture, truth, detections, snapshots, diagnostics = _load_score_fixture()
    report = score_fault_injection(truth, detections, snapshots, diagnostics)
    omit = next(item for item in report.events if item.truth.event_id == "omit-1")
    double = next(
        item for item in report.events if item.truth.event_id == "double-1"
    )

    assert omit.detections == ()
    assert not omit.detected
    assert omit.missed
    assert not omit.correctly_detected
    assert double.detected
    assert not double.missed
    assert double.correctly_detected
    assert double.duplicate_detection_count == 1
    assert double.classification_mismatch_count == 1
    assert [item.detection_id for item in report.false_detections] == ["d-orphan"]


def test_clean_recovery_requires_valid_snapshot_and_recovery_transition() -> None:
    _fixture, truth, detections, snapshots, diagnostics = _load_score_fixture()
    without_transition = [
        item for item in diagnostics if item.transition != "recovery"
    ]
    without_valid_snapshot = [
        SnapshotValidity(
            event_id=item.event_id,
            snapshot_sequence=item.snapshot_sequence,
            measurement_valid=False,
            reasons=("still_reacquiring",),
        )
        if item.event_id == "recovery-1"
        else item
        for item in snapshots
    ]

    no_transition = score_fault_injection(
        truth, detections, snapshots, without_transition
    )
    no_snapshot = score_fault_injection(
        truth, detections, without_valid_snapshot, diagnostics
    )

    assert no_transition.clean_recovery_count == 0
    assert no_transition.missing_recovery_count == 1
    assert no_snapshot.clean_recovery_count == 0
    assert no_snapshot.missing_recovery_count == 1


def test_transition_score_exposes_missing_and_excess_transitions() -> None:
    _fixture, truth, detections, snapshots, diagnostics = _load_score_fixture()
    no_restoration = [
        item for item in diagnostics if item.transition != "restoration"
    ]
    duplicate_outage = diagnostics + [
        DiagnosticObservation(
            "diag-outage-duplicate",
            "outage-1",
            "outage",
            "reference_missing_pps",
        )
    ]

    missing = score_fault_injection(truth, detections, snapshots, no_restoration)
    excess = score_fault_injection(truth, detections, snapshots, duplicate_outage)

    assert missing.restoration_transitions.missing == 1
    assert missing.restoration_transitions.excess == 0
    assert excess.outage_transitions.missing == 0
    assert excess.outage_transitions.excess == 1


def test_profile_fixture_covers_every_required_fault_class_and_acceptance_shape() -> None:
    fixture = json.loads(PROFILES_FIXTURE.read_text(encoding="utf-8"))
    profiles = {item["id"]: item for item in fixture["profiles"]}
    classes = {
        fault_class
        for profile in fixture["profiles"]
        for fault_class in profile["fault_classes"]
    }

    assert fixture["nominal_period_us"] == 1_000_000
    assert fixture["nominal_pulse_width_us"] == 100_000
    assert {
        "too_short_interval",
        "too_long_interval",
        "omitted_pulse",
        "double_pulse",
        "bounce_burst",
        "narrow_glitch",
        "positive_phase_step",
        "negative_phase_step",
        "positive_period_offset",
        "negative_period_offset",
        "repeated_omissions",
    } <= classes
    acceptance = profiles["composite_acceptance_v1"]
    assert acceptance["steps"][0] == {"kind": "clean", "pulse_count": 30}
    assert acceptance["steps"][2] == {"kind": "clean", "pulse_count": 10}
    assert acceptance["steps"][-1] == {"kind": "clean", "pulse_count": 30}
    assert all(profile["returns_to_clean"] for profile in fixture["profiles"])


def test_duplicate_evidence_identifiers_are_rejected() -> None:
    truth = [
        GeneratorTruthEvent("same", "g1", 1, "profile", 1, "fault", "short"),
        GeneratorTruthEvent("same", "g1", 2, "profile", 1, "fault", "long"),
    ]

    with pytest.raises(ValueError, match="truth event IDs must be unique"):
        score_fault_injection(truth, (), (), ())


def test_cli_writes_explicit_failure_disposition_and_strict_exit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "score.json"
    assert main([str(SCORING_FIXTURE), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["disposition"] == "fail"
    assert main([str(SCORING_FIXTURE), "--strict"]) == 2
