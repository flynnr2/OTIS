from __future__ import annotations

import csv
import io
from pathlib import Path
import subprocess

from host.otis_tools.reference_quality import (
    REFERENCE_QUALITY_ALGORITHM_VERSION,
    ReceiverMetadata,
    ReferenceEvidence,
    ReferenceIdentityTracker,
    ReferenceQualityConfig,
    assess_reference_quality,
)


CONFIG = ReferenceQualityConfig()
PREVIOUS = ReferenceEvidence(1, 0, "fixture", 0, "ref.csv:REF:1")
CURRENT = ReferenceEvidence(2, 1_000_000, "fixture", 0, "ref.csv:REF:2")


def test_good_cadence_without_metadata_does_not_qualify_authority() -> None:
    result = assess_reference_quality(
        PREVIOUS,
        CURRENT,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=None,
        config=CONFIG,
    )
    assert result.cadence_state == "valid"
    assert result.receiver_authority_state == "unknown"
    assert result.qualification_state == "cadence_valid_authority_unknown"


def test_missing_reference_evidence_remains_unknown() -> None:
    result = assess_reference_quality(
        None,
        None,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=None,
        config=CONFIG,
    )
    assert result.cadence_state == "unavailable"
    assert result.capture_path_state == "unavailable"
    assert result.qualification_state == "unknown"
    assert "reference_unavailable" in result.reason_codes


def test_bad_cadence_remains_bad_with_healthy_receiver() -> None:
    metadata = ReceiverMetadata(
        ticks=600_000,
        evidence_ref="receiver.log:1",
        authority_state="qualified",
        utc_traceability_state="valid",
    )
    short = ReferenceEvidence(2, 600_000, "fixture", 0, "ref.csv:REF:2")
    result = assess_reference_quality(
        PREVIOUS,
        short,
        now_ticks=600_000,
        domain_hz=1_000_000,
        metadata=metadata,
        config=CONFIG,
    )
    assert result.cadence_state == "short"
    assert result.qualification_state == "unqualified"


def test_receiver_holdover_and_utc_invalid_are_distinct() -> None:
    holdover = ReceiverMetadata(
        ticks=1_000_000,
        evidence_ref="receiver.log:1",
        authority_state="holdover",
        utc_traceability_state="valid",
    )
    result = assess_reference_quality(
        PREVIOUS,
        CURRENT,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=holdover,
        config=CONFIG,
    )
    assert result.qualification_state == "holdover"

    utc_invalid = ReceiverMetadata(
        ticks=1_000_000,
        evidence_ref="receiver.log:2",
        authority_state="qualified",
        utc_traceability_state="invalid",
    )
    result = assess_reference_quality(
        PREVIOUS,
        CURRENT,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=utc_invalid,
        config=CONFIG,
    )
    assert result.qualification_state == "utc_invalid"


def test_stale_metadata_does_not_remain_authoritative() -> None:
    metadata = ReceiverMetadata(
        ticks=0,
        evidence_ref="receiver.log:1",
        authority_state="qualified",
        utc_traceability_state="valid",
    )
    result = assess_reference_quality(
        PREVIOUS,
        CURRENT,
        now_ticks=4_000_000_001,
        domain_hz=1_000_000,
        metadata=metadata,
        config=CONFIG,
    )
    assert result.metadata_freshness == "stale"
    assert result.qualification_state != "qualified"


def test_sequence_regression_is_capture_path_evidence() -> None:
    regressed = ReferenceEvidence(
        1, 1_000_000, "fixture", 0, "ref.csv:REF:1-duplicate"
    )
    result = assess_reference_quality(
        PREVIOUS,
        regressed,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=None,
        config=CONFIG,
    )
    assert result.capture_path_state == "sequence_gap"
    assert "reference_sequence_nonmonotonic" in result.reason_codes


def test_antenna_fault_overrides_nominal_receiver_authority() -> None:
    metadata = ReceiverMetadata(
        ticks=1_000_000,
        evidence_ref="receiver.log:1",
        authority_state="qualified",
        utc_traceability_state="valid",
        antenna_state="open",
    )
    result = assess_reference_quality(
        PREVIOUS,
        CURRENT,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=metadata,
        config=CONFIG,
    )
    assert result.qualification_state == "antenna_fault"
    assert "reference_antenna_fault" in result.reason_codes


def test_reconnect_identity_change_starts_a_new_derived_epoch() -> None:
    tracker = ReferenceIdentityTracker()
    first = tracker.observe(
        ReceiverMetadata(
            ticks=1,
            evidence_ref="receiver.log:1",
            receiver_identity="module-A",
            receiver_firmware="1.0",
        )
    )
    repeated = tracker.observe(
        ReceiverMetadata(
            ticks=2,
            evidence_ref="receiver.log:2",
            receiver_identity="module-A",
            receiver_firmware="1.0",
        )
    )
    reconnected = tracker.observe(
        ReceiverMetadata(
            ticks=3,
            evidence_ref="receiver.log:3",
            receiver_identity="module-B",
            receiver_firmware="2.0",
        )
    )
    assert first is not None and repeated is not None and reconnected is not None
    assert first.identity_epoch == repeated.identity_epoch
    assert reconnected.identity_epoch != first.identity_epoch
    assert reconnected.identity_epoch == "reference_source_epoch:2"


def test_future_dated_metadata_is_not_current() -> None:
    metadata = ReceiverMetadata(
        ticks=1_000_001,
        evidence_ref="receiver.log:future",
        authority_state="qualified",
        utc_traceability_state="valid",
    )
    result = assess_reference_quality(
        PREVIOUS,
        CURRENT,
        now_ticks=1_000_000,
        domain_hz=1_000_000,
        metadata=metadata,
        config=CONFIG,
    )
    assert result.metadata_freshness == "stale"
    assert result.qualification_state == "metadata_stale"


def test_sealed_reference_evidence_has_live_replay_parity(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    firmware = (
        root
        / "firmware"
        / "arduino"
        / "otis_nano_rp2040_connect"
    )
    executable = tmp_path / "reference_quality_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(root / "tests" / "cpp" / "reference_quality_harness.cpp"),
            str(firmware / "otis_reference_quality.cpp"),
            "-I",
            str(firmware),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=root,
    )
    fields = (
        "scenario",
        "cadence_state",
        "capture_path_state",
        "receiver_authority_state",
        "utc_traceability_state",
        "metadata_freshness",
        "qualification_state",
        "qualification_reason_codes",
        "algorithm_version",
        "config_hash",
    )
    live = list(
        csv.DictReader(
            io.StringIO(
                subprocess.run(
                    [str(executable)],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    cwd=root,
                ).stdout
            ),
            fieldnames=fields,
        )
    )
    scenarios = {
        "good_missing_metadata": (CURRENT, 1_000_000, None),
        "bad_cadence_healthy_receiver": (
            ReferenceEvidence(2, 600_000, "fixture", 0, "ref:2"),
            600_000,
            ReceiverMetadata(
                ticks=600_000,
                evidence_ref="metadata:1",
                authority_state="qualified",
                utc_traceability_state="valid",
                fix_holdover_state="current",
                antenna_state="ok",
            ),
        ),
        "stale_metadata": (
            CURRENT,
            4_000_000_001,
            ReceiverMetadata(
                ticks=0,
                evidence_ref="metadata:2",
                authority_state="qualified",
                utc_traceability_state="valid",
                fix_holdover_state="current",
                antenna_state="ok",
            ),
        ),
        "holdover": (
            CURRENT,
            1_000_000,
            ReceiverMetadata(
                ticks=1_000_000,
                evidence_ref="metadata:3",
                authority_state="holdover",
                utc_traceability_state="valid",
                fix_holdover_state="holdover",
                antenna_state="ok",
            ),
        ),
        "utc_invalid": (
            CURRENT,
            1_000_000,
            ReceiverMetadata(
                ticks=1_000_000,
                evidence_ref="metadata:4",
                authority_state="qualified",
                utc_traceability_state="invalid",
                fix_holdover_state="current",
                antenna_state="ok",
            ),
        ),
        "antenna_fault": (
            CURRENT,
            1_000_000,
            ReceiverMetadata(
                ticks=1_000_000,
                evidence_ref="metadata:5",
                authority_state="qualified",
                utc_traceability_state="valid",
                fix_holdover_state="current",
                antenna_state="fault",
            ),
        ),
        "sequence_regression": (
            ReferenceEvidence(1, 1_000_000, "fixture", 0, "ref:1"),
            1_000_000,
            None,
        ),
        "qualified": (
            CURRENT,
            1_000_000,
            ReceiverMetadata(
                ticks=1_000_000,
                evidence_ref="metadata:6",
                authority_state="qualified",
                utc_traceability_state="valid",
                fix_holdover_state="current",
                antenna_state="ok",
            ),
        ),
    }
    replay: list[dict[str, str]] = []
    for scenario, (current, now_ticks, metadata) in scenarios.items():
        quality = assess_reference_quality(
            PREVIOUS,
            current,
            now_ticks=now_ticks,
            domain_hz=1_000_000,
            metadata=metadata,
            config=CONFIG,
        )
        replay.append(
            {
                "scenario": scenario,
                "cadence_state": quality.cadence_state,
                "capture_path_state": quality.capture_path_state,
                "receiver_authority_state": quality.receiver_authority_state,
                "utc_traceability_state": quality.utc_traceability_state,
                "metadata_freshness": quality.metadata_freshness,
                "qualification_state": quality.qualification_state,
                "qualification_reason_codes": ";".join(quality.reason_codes),
                "algorithm_version": REFERENCE_QUALITY_ALGORITHM_VERSION,
                "config_hash": CONFIG.config_hash,
            }
        )
    assert live == replay
