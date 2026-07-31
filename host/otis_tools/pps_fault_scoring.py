"""Score pseudo-PPS truth without collapsing independent evidence planes."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GeneratorTruthEvent:
    event_id: str
    generator_session: str
    generator_sequence: int
    profile_id: str
    profile_version: int
    kind: str
    expected_classification: str | None = None
    scheduled_timestamp_ticks: int | None = None
    time_domain: str | None = None
    expected_snapshot_observed: bool | None = None
    expected_association_state: str | None = None
    expected_cnt_state: str | None = None

    def __post_init__(self) -> None:
        if self.expected_association_state not in {
            None,
            "associated",
            "associated_invalid",
            "lost",
            "quarantined",
            "anchor",
            "adjacent",
            "clean",
        }:
            raise ValueError("unsupported expected_association_state")
        if self.expected_cnt_state not in {
            None,
            "valid",
            "invalid",
            "absent",
            "invalid_or_absent",
        }:
            raise ValueError("unsupported expected_cnt_state")


@dataclass(frozen=True)
class PhysicalDetection:
    detection_id: str
    event_id: str | None
    classification: str
    reference_sequence: int
    timestamp_ticks: int | None = None
    time_domain: str | None = None


@dataclass(frozen=True)
class SnapshotValidity:
    event_id: str
    snapshot_sequence: int | None
    measurement_valid: bool
    reasons: tuple[str, ...] = ()
    snapshot_observed: bool = True
    associated_reference_sequence: int | None = None
    association_state: str = "associated"
    cnt_state: str = "unassessed"

    def __post_init__(self) -> None:
        if self.snapshot_observed != (self.snapshot_sequence is not None):
            raise ValueError(
                "snapshot_sequence must be present exactly when snapshot_observed"
            )
        if self.association_state not in {
            "associated",
            "associated_invalid",
            "lost",
            "quarantined",
            "anchor",
            "adjacent",
            "clean",
        }:
            raise ValueError("unsupported association_state")
        if self.cnt_state not in {"valid", "invalid", "absent", "unassessed"}:
            raise ValueError("unsupported cnt_state")
        if self.measurement_valid and (
            not self.snapshot_observed or self.cnt_state == "absent"
        ):
            raise ValueError(
                "a valid measurement requires an observed snapshot and CNT"
            )
        if self.cnt_state == "valid" and not self.measurement_valid:
            raise ValueError("cnt_state=valid requires measurement_valid=true")
        if any(not reason for reason in self.reasons):
            raise ValueError("reasons must contain non-empty reason codes")


@dataclass(frozen=True)
class DiagnosticObservation:
    diagnostic_id: str
    event_id: str | None
    transition: str
    reason_code: str


@dataclass(frozen=True)
class ScoredFaultEvent:
    truth: GeneratorTruthEvent
    detections: tuple[PhysicalDetection, ...]
    snapshots: tuple[SnapshotValidity, ...]
    diagnostics: tuple[DiagnosticObservation, ...]
    detected: bool
    missed: bool
    correctly_detected: bool
    classification_mismatch_count: int
    duplicate_detection_count: int
    detection_latency_ticks: int | None
    snapshot_outcome_correct: bool
    association_outcome_correct: bool
    cnt_outcome_correct: bool


@dataclass(frozen=True)
class TransitionScore:
    expected: int
    observed: int
    missing: int
    excess: int


@dataclass(frozen=True)
class FaultScoreReport:
    expected_event_count: int
    correctly_detected_event_count: int
    missed_detection_count: int
    false_detection_count: int
    duplicate_detection_count: int
    classification_mismatch_count: int
    outage_transitions: TransitionScore
    restoration_transitions: TransitionScore
    association_loss_transitions: TransitionScore
    expected_recovery_count: int
    clean_recovery_count: int
    missing_recovery_count: int
    fault_measurement_invalid_count: int
    fault_events_without_snapshot_assessment: int
    expected_snapshot_outcome_count: int
    correct_snapshot_outcome_count: int
    missing_snapshot_count: int
    unexpected_snapshot_count: int
    duplicate_snapshot_assessment_count: int
    orphan_snapshot_assessment_count: int
    association_mismatch_count: int
    cnt_outcome_mismatch_count: int
    valid_cnt_across_fault_count: int
    generator_truth: tuple[GeneratorTruthEvent, ...]
    physical_detections: tuple[PhysicalDetection, ...]
    snapshot_validity: tuple[SnapshotValidity, ...]
    diagnostic_observations: tuple[DiagnosticObservation, ...]
    events: tuple[ScoredFaultEvent, ...]
    false_detections: tuple[PhysicalDetection, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _require_unique(values: Iterable[str], name: str) -> None:
    materialized = list(values)
    if any(not value for value in materialized):
        raise ValueError(f"{name} must not contain empty identifiers")
    if len(set(materialized)) != len(materialized):
        raise ValueError(f"{name} must be unique")


def _latency(
    truth: GeneratorTruthEvent, detections: tuple[PhysicalDetection, ...]
) -> int | None:
    if truth.scheduled_timestamp_ticks is None:
        return None
    candidates = [
        detection
        for detection in detections
        if detection.timestamp_ticks is not None
        and detection.time_domain == truth.time_domain
        and detection.timestamp_ticks >= truth.scheduled_timestamp_ticks
    ]
    if not candidates:
        return None
    first = min(candidates, key=lambda item: int(item.timestamp_ticks or 0))
    return int(first.timestamp_ticks) - truth.scheduled_timestamp_ticks


def _transition_score(
    truth: tuple[GeneratorTruthEvent, ...],
    diagnostics: tuple[DiagnosticObservation, ...],
    *,
    truth_kind: str,
    diagnostic_transition: str,
) -> TransitionScore:
    expected = sum(item.kind == truth_kind for item in truth)
    observed = sum(
        item.transition == diagnostic_transition for item in diagnostics
    )
    return TransitionScore(
        expected=expected,
        observed=observed,
        missing=max(0, expected - observed),
        excess=max(0, observed - expected),
    )


def _cnt_state_matches(expected: str | None, observed: str) -> bool:
    if expected is None:
        return True
    if expected == "invalid_or_absent":
        return observed in {"invalid", "absent"}
    return observed == expected


def _transition_counts(expected: int, observed: int) -> TransitionScore:
    return TransitionScore(
        expected=expected,
        observed=observed,
        missing=max(0, expected - observed),
        excess=max(0, observed - expected),
    )


def _snapshot_outcomes(
    expected: GeneratorTruthEvent,
    assessments: tuple[SnapshotValidity, ...],
    *,
    default_snapshot_observed: bool,
) -> tuple[bool, bool, bool, bool, bool]:
    expected_observed = (
        expected.expected_snapshot_observed
        if expected.expected_snapshot_observed is not None
        else default_snapshot_observed
    )
    observed = tuple(item for item in assessments if item.snapshot_observed)
    absent = tuple(item for item in assessments if not item.snapshot_observed)
    if expected_observed:
        snapshot_correct = bool(observed)
        missing = not observed
        unexpected = False
    else:
        # Absence is evidence only when explicitly assessed. Silence in the
        # aligned file is not proof that the PIO emitted no word.
        snapshot_correct = not observed and bool(absent)
        missing = False
        unexpected = bool(observed)
    association_correct = (
        expected.expected_association_state is None
        or any(
            item.association_state == expected.expected_association_state
            for item in assessments
        )
    )
    cnt_correct = (
        expected.expected_cnt_state is None
        or any(
            _cnt_state_matches(expected.expected_cnt_state, item.cnt_state)
            for item in assessments
        )
    )
    return (
        snapshot_correct,
        association_correct,
        cnt_correct,
        missing,
        unexpected,
    )


def score_fault_injection(
    truth_events: Iterable[GeneratorTruthEvent],
    physical_detections: Iterable[PhysicalDetection],
    snapshot_validity: Iterable[SnapshotValidity],
    diagnostic_observations: Iterable[DiagnosticObservation],
) -> FaultScoreReport:
    """Join already-aligned evidence by stable event ID and compute metrics.

    Alignment from physical timestamps to event IDs is deliberately outside
    this function.  That keeps generator intent, observed PPS cadence,
    snapshot validity, and policy diagnostics distinct and reviewable.
    """

    truth = tuple(truth_events)
    detections = tuple(physical_detections)
    snapshots = tuple(snapshot_validity)
    diagnostics = tuple(diagnostic_observations)
    _require_unique((item.event_id for item in truth), "truth event IDs")
    _require_unique(
        (item.detection_id for item in detections), "physical detection IDs"
    )
    _require_unique(
        (item.diagnostic_id for item in diagnostics), "diagnostic IDs"
    )

    truth_by_id = {item.event_id: item for item in truth}
    detection_by_event: dict[str, list[PhysicalDetection]] = {}
    snapshot_by_event: dict[str, list[SnapshotValidity]] = {}
    diagnostic_by_event: dict[str, list[DiagnosticObservation]] = {}
    false_detections: list[PhysicalDetection] = []

    for detection in detections:
        target = truth_by_id.get(detection.event_id or "")
        if target is None or target.expected_classification is None:
            false_detections.append(detection)
            continue
        detection_by_event.setdefault(target.event_id, []).append(detection)
    for snapshot in snapshots:
        snapshot_by_event.setdefault(snapshot.event_id, []).append(snapshot)
    for diagnostic in diagnostics:
        if diagnostic.event_id is not None:
            diagnostic_by_event.setdefault(diagnostic.event_id, []).append(
                diagnostic
            )

    expected = tuple(
        item for item in truth if item.expected_classification is not None
    )
    scored: list[ScoredFaultEvent] = []
    correctly_detected = 0
    missed = 0
    duplicate_count = 0
    mismatch_count = 0
    fault_measurement_invalid = 0
    without_snapshot = 0
    correct_snapshot_outcome = 0
    missing_snapshot = 0
    unexpected_snapshot = 0
    association_mismatch = 0
    cnt_outcome_mismatch = 0
    valid_cnt_across_fault = 0
    duplicate_snapshot_assessments = sum(
        max(0, len(items) - 1) for items in snapshot_by_event.values()
    )
    orphan_snapshot_assessments = sum(
        len(items)
        for event_id, items in snapshot_by_event.items()
        if event_id not in truth_by_id
    )

    explicit_snapshot_expectations = tuple(
        item
        for item in truth
        if item.expected_snapshot_observed is not None
        or item.expected_association_state is not None
        or item.expected_cnt_state is not None
    )
    snapshot_expectations = explicit_snapshot_expectations + tuple(
        item for item in expected if item not in explicit_snapshot_expectations
    )
    for expected_snapshot in snapshot_expectations:
        outcomes = _snapshot_outcomes(
            expected_snapshot,
            tuple(snapshot_by_event.get(expected_snapshot.event_id, ())),
            default_snapshot_observed=True,
        )
        (
            snapshot_correct,
            association_correct,
            cnt_correct,
            missing,
            unexpected,
        ) = outcomes
        correct_snapshot_outcome += int(snapshot_correct)
        missing_snapshot += int(missing)
        unexpected_snapshot += int(unexpected)
        association_mismatch += int(not association_correct)
        cnt_outcome_mismatch += int(not cnt_correct)

    for expected_event in expected:
        event_detections = tuple(
            detection_by_event.get(expected_event.event_id, ())
        )
        event_snapshots = tuple(
            snapshot_by_event.get(expected_event.event_id, ())
        )
        event_diagnostics = tuple(
            diagnostic_by_event.get(expected_event.event_id, ())
        )
        event_correct = any(
            item.classification == expected_event.expected_classification
            for item in event_detections
        )
        event_mismatches = sum(
            item.classification != expected_event.expected_classification
            for item in event_detections
        )
        event_duplicates = max(0, len(event_detections) - 1)
        (
            snapshot_outcome_correct,
            association_outcome_correct,
            cnt_outcome_correct,
            _missing_snapshot,
            _unexpected_snapshot,
        ) = _snapshot_outcomes(
            expected_event,
            event_snapshots,
            default_snapshot_observed=True,
        )
        valid_cnt_across_fault += int(
            any(
                item.measurement_valid or item.cnt_state == "valid"
                for item in event_snapshots
            )
        )
        correctly_detected += int(event_correct)
        missed += int(not event_detections)
        mismatch_count += event_mismatches
        duplicate_count += event_duplicates
        if not event_snapshots:
            without_snapshot += 1
        elif all(not item.measurement_valid for item in event_snapshots):
            fault_measurement_invalid += 1
        scored.append(
            ScoredFaultEvent(
                truth=expected_event,
                detections=event_detections,
                snapshots=event_snapshots,
                diagnostics=event_diagnostics,
                detected=bool(event_detections),
                missed=not event_detections,
                correctly_detected=event_correct,
                classification_mismatch_count=event_mismatches,
                duplicate_detection_count=event_duplicates,
                detection_latency_ticks=_latency(
                    expected_event, event_detections
                ),
                snapshot_outcome_correct=snapshot_outcome_correct,
                association_outcome_correct=association_outcome_correct,
                cnt_outcome_correct=cnt_outcome_correct,
            )
        )

    recovery_truth = tuple(item for item in truth if item.kind == "recovery")
    clean_recovery = 0
    for expected_recovery in recovery_truth:
        valid_snapshot = any(
            item.snapshot_observed
            and item.measurement_valid
            and _cnt_state_matches(
                expected_recovery.expected_cnt_state, item.cnt_state
            )
            for item in snapshot_by_event.get(expected_recovery.event_id, ())
        )
        recovery_transition = any(
            item.transition == "recovery"
            for item in diagnostic_by_event.get(expected_recovery.event_id, ())
        )
        clean_recovery += int(valid_snapshot and recovery_transition)

    outage = _transition_score(
        truth, diagnostics, truth_kind="outage_start", diagnostic_transition="outage"
    )
    restoration = _transition_score(
        truth,
        diagnostics,
        truth_kind="restoration",
        diagnostic_transition="restoration",
    )
    association_loss = _transition_counts(
        sum(item.expected_association_state == "lost" for item in truth),
        sum(item.transition == "association_loss" for item in diagnostics),
    )
    return FaultScoreReport(
        expected_event_count=len(expected),
        correctly_detected_event_count=correctly_detected,
        missed_detection_count=missed,
        false_detection_count=len(false_detections),
        duplicate_detection_count=duplicate_count,
        classification_mismatch_count=mismatch_count,
        outage_transitions=outage,
        restoration_transitions=restoration,
        association_loss_transitions=association_loss,
        expected_recovery_count=len(recovery_truth),
        clean_recovery_count=clean_recovery,
        missing_recovery_count=max(0, len(recovery_truth) - clean_recovery),
        fault_measurement_invalid_count=fault_measurement_invalid,
        fault_events_without_snapshot_assessment=without_snapshot,
        expected_snapshot_outcome_count=len(snapshot_expectations),
        correct_snapshot_outcome_count=correct_snapshot_outcome,
        missing_snapshot_count=missing_snapshot,
        unexpected_snapshot_count=unexpected_snapshot,
        duplicate_snapshot_assessment_count=duplicate_snapshot_assessments,
        orphan_snapshot_assessment_count=orphan_snapshot_assessments,
        association_mismatch_count=association_mismatch,
        cnt_outcome_mismatch_count=cnt_outcome_mismatch,
        valid_cnt_across_fault_count=valid_cnt_across_fault,
        generator_truth=truth,
        physical_detections=detections,
        snapshot_validity=snapshots,
        diagnostic_observations=diagnostics,
        events=tuple(scored),
        false_detections=tuple(false_detections),
    )


def _load_aligned_evidence(path: Path) -> FaultScoreReport:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("aligned evidence schema_version must be 1")
    truth = [GeneratorTruthEvent(**item) for item in value.get("truth", [])]
    detections = [
        PhysicalDetection(**item)
        for item in value.get("physical_detections", [])
    ]
    snapshots = []
    for item in value.get("snapshot_validity", []):
        materialized = dict(item)
        materialized["reasons"] = tuple(materialized.get("reasons", ()))
        snapshots.append(SnapshotValidity(**materialized))
    diagnostics = [
        DiagnosticObservation(**item)
        for item in value.get("diagnostics", [])
    ]
    return score_fault_injection(
        truth, detections, snapshots, diagnostics
    )


def _strict_acceptance(report: FaultScoreReport) -> bool:
    return (
        report.expected_event_count > 0
        and report.correctly_detected_event_count
        == report.expected_event_count
        and report.missed_detection_count == 0
        and report.false_detection_count == 0
        and report.duplicate_detection_count == 0
        and report.classification_mismatch_count == 0
        and report.outage_transitions.missing == 0
        and report.outage_transitions.excess == 0
        and report.restoration_transitions.missing == 0
        and report.restoration_transitions.excess == 0
        and report.association_loss_transitions.missing == 0
        and report.association_loss_transitions.excess == 0
        and report.missing_recovery_count == 0
        and report.fault_measurement_invalid_count
        == report.expected_event_count
        and report.fault_events_without_snapshot_assessment == 0
        and report.correct_snapshot_outcome_count
        == report.expected_snapshot_outcome_count
        and report.missing_snapshot_count == 0
        and report.unexpected_snapshot_count == 0
        and report.duplicate_snapshot_assessment_count == 0
        and report.orphan_snapshot_assessment_count == 0
        and report.association_mismatch_count == 0
        and report.cnt_outcome_mismatch_count == 0
        and report.valid_cnt_across_fault_count == 0
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score explicitly aligned pseudo-PPS truth, physical detections, "
            "snapshot validity, and diagnostics without collapsing evidence planes."
        )
    )
    parser.add_argument("evidence", type=Path, help="Aligned evidence JSON v1.")
    parser.add_argument("--output", type=Path, help="Write the deterministic JSON report.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 unless every detection, transition, invalidation, and recovery gate passes.",
    )
    args = parser.parse_args(argv)
    try:
        report = _load_aligned_evidence(args.evidence)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    payload = report.to_dict()
    payload["disposition"] = "pass" if _strict_acceptance(report) else "fail"
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(args.output)
    return 2 if args.strict and payload["disposition"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
