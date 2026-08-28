"""Compose separately validated GNSS baud-envelope evidence sources.

This analyzer never treats a prior failed run as retrospectively successful and
never constructs counter deltas across capture, firmware, contract, or baseline
boundaries.  It only assembles already source-local phase results into the
logical S01..S11 schedule and records the explicit S06 bridge and acquisition
gap between the historical prefix and continuation capture.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


ANALYSIS_TYPE = "otis_gnss_baud_envelope_composite_analysis_v1"
TOOL_ID = "otis_gnss_baud_envelope_composite_analyzer_v1"
COMPOSITE_TERMINAL = "composite_multi_artifact_characterization_complete"
CONTINUATION_TERMINAL = "continuation_capture_complete"

HISTORICAL_PHASE_KEYS = (
    ("S01", "ordinary"),
    ("S02", "ordinary"),
    ("S03", "ordinary"),
    ("S04", "ordinary"),
    ("S05", "ordinary"),
    ("S06", "ordinary_entry"),
)
CONTINUATION_PHASE_KEYS = (
    ("S06", "peak_status"),
    ("S06", "clean_requalification"),
    ("S07", "ordinary_entry"),
    ("S07", "peak_status"),
    ("S07", "clean_requalification"),
    ("S08", "ordinary_entry"),
    ("S08", "peak_status"),
    ("S08", "clean_requalification"),
    ("S09", "ordinary_entry"),
    ("S09", "peak_status"),
    ("S09", "clean_requalification"),
    ("S10", "ordinary_entry"),
    ("S10", "peak_status"),
    ("S10", "ordinary_soak"),
    ("S11", "closing_clean_soak"),
)
LOGICAL_PHASE_KEYS = HISTORICAL_PHASE_KEYS + CONTINUATION_PHASE_KEYS

_SOURCE_FIELDS = (
    "source_run_id",
    "source_artifact_sha256",
    "source_contract_sha256",
    "source_firmware_uf2_sha256",
    "source_firmware_source_sha256",
    "source_firmware_config_sha256",
    "original_contract_sha256",
    "continuation_contract_sha256",
    "counter_domain",
    "source_counter_baseline_id",
)
_ORDINARY_TERMINALS = {
    "multi_baud_characterization_complete",
    "multi_baud_characterization_partial_receiver_recovered",
}


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sha256(value: object, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(byte not in "0123456789abcdef" for byte in text):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


def _source(value: object, label: str) -> dict[str, str]:
    source = _mapping(value, label)
    result: dict[str, str] = {}
    for field in _SOURCE_FIELDS:
        if field not in source or not str(source[field]):
            raise ValueError(f"{label} lacks {field}")
        result[field] = str(source[field])
    for field in (
        "source_artifact_sha256",
        "source_contract_sha256",
        "source_firmware_uf2_sha256",
        "source_firmware_source_sha256",
        "source_firmware_config_sha256",
        "original_contract_sha256",
        "continuation_contract_sha256",
    ):
        _sha256(result[field], f"{label}.{field}")
    if result["counter_domain"] not in {
        "rp2040_timer0_extended",
        "host_monotonic_ns",
    }:
        raise ValueError(f"{label} counter domain is unsupported")
    return result


def _validate_source_lineage(
    historical: Mapping[str, str], continuation: Mapping[str, str]
) -> None:
    if historical["source_run_id"] == continuation["source_run_id"]:
        raise ValueError("historical and continuation sources must be distinct runs")
    if (
        historical["source_contract_sha256"]
        != historical["original_contract_sha256"]
        or continuation["source_contract_sha256"]
        != continuation["continuation_contract_sha256"]
        or historical["original_contract_sha256"]
        != continuation["original_contract_sha256"]
        or historical["continuation_contract_sha256"]
        != continuation["continuation_contract_sha256"]
    ):
        raise ValueError("original/continuation contract lineage differs")


def _counter_delta_scope(
    value: object, source: Mapping[str, str], label: str
) -> dict[str, str]:
    scope = _mapping(value, f"{label}.counter_delta_scope")
    expected = {
        "operation": "within_source_closing_minus_opening",
        "source_run_id": source["source_run_id"],
        "source_artifact_sha256": source["source_artifact_sha256"],
        "source_contract_sha256": source["source_contract_sha256"],
        "source_counter_baseline_id": source["source_counter_baseline_id"],
        "counter_domain": source["counter_domain"],
    }
    if dict(scope) != expected:
        raise ValueError(f"{label} attempts a cross-source counter delta")
    return expected


def _validated_phases(
    report: Mapping[str, Any],
    source: Mapping[str, str],
    expected_keys: tuple[tuple[str, str], ...],
    label: str,
) -> list[dict[str, Any]]:
    rows = report.get("phases")
    if not isinstance(rows, list):
        raise ValueError(f"{label} phases must be a list")
    actual_keys: list[tuple[str, str]] = []
    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        phase = _mapping(raw, f"{label}.phases[{index}]")
        key = (str(phase.get("logical_segment_id")), str(phase.get("phase_id")))
        if key in actual_keys:
            raise ValueError(f"duplicate logical phase: {key[0]}.{key[1]}")
        actual_keys.append(key)
        if phase.get("status") != "completed":
            raise ValueError(f"logical phase is not complete: {key[0]}.{key[1]}")
        if dict(_source(phase.get("source"), f"{label}.{key}.source")) != dict(source):
            raise ValueError(f"logical phase source tag differs: {key[0]}.{key[1]}")
        scope = _counter_delta_scope(phase.get("counter_delta_scope"), source, label)
        deltas = _mapping(phase.get("counter_deltas"), f"{label}.{key}.counter_deltas")
        if any(not isinstance(value, int) or value < 0 for value in deltas.values()):
            raise ValueError(f"logical phase counter deltas are invalid: {key[0]}.{key[1]}")
        validated.append(
            {
                "logical_segment_id": key[0],
                "phase_id": key[1],
                "status": "completed",
                "source": dict(source),
                "counter_delta_scope": scope,
                "counter_deltas": dict(deltas),
            }
        )
    actual = set(actual_keys)
    expected = set(expected_keys)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ValueError(
            f"{label} logical phase set differs: missing={missing}, extra={extra}"
        )
    by_key = {
        (phase["logical_segment_id"], phase["phase_id"]): phase
        for phase in validated
    }
    return [by_key[key] for key in expected_keys]


def _validate_bridge(
    historical: Mapping[str, Any], source: Mapping[str, str]
) -> list[dict[str, Any]]:
    bridge = _mapping(historical.get("bridge"), "historical bridge")
    events = bridge.get("events")
    if not isinstance(events, list):
        raise ValueError("historical bridge events must be a list")
    expected = {
        26: "transition_requested",
        27: "transition_confirmed",
    }
    by_sequence: dict[int, Mapping[str, Any]] = {}
    for raw in events:
        event = _mapping(raw, "historical bridge event")
        sequence = int(event.get("event_sequence", -1))
        if sequence in by_sequence:
            raise ValueError("historical bridge event is duplicated")
        by_sequence[sequence] = event
    if set(by_sequence) != set(expected):
        raise ValueError("historical bridge must retain exact events 26 and 27")
    validated: list[dict[str, Any]] = []
    for sequence, event_name in expected.items():
        event = by_sequence[sequence]
        if (
            event.get("event") != event_name
            or event.get("logical_segment_id") != "S06"
            or int(event.get("request_sequence", -1)) != 6
            or dict(_source(event.get("source"), "historical bridge source"))
            != dict(source)
        ):
            raise ValueError(f"historical bridge event {sequence} differs")
        if sequence == 27 and (
            int(event.get("confirmed_baud", -1)) != 57600
            or event.get("identity_confirmed") is not True
            or event.get("configuration_confirmed") is not True
            or event.get("first_dependent_snapshot_bound") is not True
        ):
            raise ValueError("historical bridge confirmation is incomplete")
        validated.append(dict(event))
    return validated


def _validate_gap(
    continuation: Mapping[str, Any],
    historical_source: Mapping[str, str],
    continuation_source: Mapping[str, str],
) -> dict[str, Any]:
    gap = _mapping(continuation.get("source_gap"), "continuation source gap")
    expected = {
        "historical_run_id": historical_source["source_run_id"],
        "continuation_run_id": continuation_source["source_run_id"],
        "capture_continuity": False,
        "firmware_continuity": False,
        "counter_baseline_continuity": False,
        "cross_run_counter_delta_permitted": False,
    }
    if dict(gap) != expected:
        raise ValueError("capture/firmware gap declaration differs")
    return expected


def _firmware_identity(source: Mapping[str, str]) -> tuple[str, str, str]:
    return (
        source["source_firmware_uf2_sha256"],
        source["source_firmware_source_sha256"],
        source["source_firmware_config_sha256"],
    )


def _firmware_strata(
    sources: tuple[Mapping[str, str], Mapping[str, str]],
    compatibility_proof: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_identity: dict[tuple[str, str, str], list[str]] = {}
    for source in sources:
        by_identity.setdefault(_firmware_identity(source), []).append(
            source["source_run_id"]
        )
    proof_summary: dict[str, Any] = {
        "provided": compatibility_proof is not None,
        "passed": False,
        "cross_firmware_join_permitted": False,
    }
    if compatibility_proof is not None:
        proof = _mapping(compatibility_proof, "firmware compatibility proof")
        expected_identities = sorted("/".join(identity) for identity in by_identity)
        if (
            proof.get("status") != "passed"
            or sorted(str(value) for value in proof.get("firmware_identities", []))
            != expected_identities
            or proof.get("counter_semantics_compatible") is not True
            or proof.get("phase_metric_schema_compatible") is not True
        ):
            raise ValueError("firmware compatibility proof differs")
        proof_summary = {
            "provided": True,
            "passed": True,
            "cross_firmware_join_permitted": True,
            "proof_artifact_sha256": _sha256(
                proof.get("proof_artifact_sha256"),
                "firmware compatibility proof artifact",
            ),
        }
    strata: list[dict[str, Any]] = []
    for identity, run_ids in sorted(by_identity.items()):
        strata.append(
            {
                "stratum_id": canonical_sha256(identity),
                "firmware_uf2_sha256": identity[0],
                "firmware_source_sha256": identity[1],
                "firmware_config_sha256": identity[2],
                "source_run_ids": sorted(run_ids),
            }
        )
    return strata, proof_summary


def _segments(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ordinal in range(1, 12):
        segment_id = f"S{ordinal:02d}"
        segment_phases = [
            phase for phase in phases if phase["logical_segment_id"] == segment_id
        ]
        sources: list[dict[str, str]] = []
        for phase in segment_phases:
            if phase["source"] not in sources:
                sources.append(phase["source"])
        result.append(
            {
                "logical_segment_id": segment_id,
                "status": "completed",
                "phase_ids": [phase["phase_id"] for phase in segment_phases],
                "source_provenance": sources,
                "counter_deltas_combined_across_sources": False,
            }
        )
    return result


def analyze_composite(
    *,
    historical_prefix: Mapping[str, Any],
    continuation_analysis: Mapping[str, Any],
    compatibility_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and compose one historical prefix and one continuation report."""
    historical = _mapping(historical_prefix, "historical prefix")
    continuation = _mapping(continuation_analysis, "continuation analysis")
    if (
        historical.get("report_type")
        != "otis_gnss_baud_envelope_validated_historical_prefix_v1"
        or historical.get("validation_status")
        != "validated_against_original_manifest_and_contract"
    ):
        raise ValueError("historical prefix is not independently validated")
    old_terminal = _mapping(
        historical.get("historical_terminal"), "historical terminal"
    )
    if (
        old_terminal.get("evidence_status") != "failed"
        or not str(old_terminal.get("programme_terminal", ""))
    ):
        raise ValueError("historical failed terminal is not preserved")
    if (
        continuation.get("analysis_type")
        != "otis_gnss_baud_envelope_continuation_analysis_v1"
        or continuation.get("evidence_status") != "passed"
        or continuation.get("completion_terminal") != CONTINUATION_TERMINAL
    ):
        raise ValueError("continuation analysis is not complete")
    if continuation.get("programme_terminal") in _ORDINARY_TERMINALS:
        raise ValueError("ordinary programme completion terminal is forbidden")
    if historical.get("cross_run_counter_delta_attempted") is not False or (
        continuation.get("cross_run_counter_delta_attempted") is not False
    ):
        raise ValueError("cross-run counter delta attempt is forbidden")

    historical_source = _source(historical.get("source"), "historical source")
    continuation_source = _source(
        continuation.get("source"), "continuation source"
    )
    _validate_source_lineage(historical_source, continuation_source)
    historical_phases = _validated_phases(
        historical,
        historical_source,
        HISTORICAL_PHASE_KEYS,
        "historical prefix",
    )
    continuation_phases = _validated_phases(
        continuation,
        continuation_source,
        CONTINUATION_PHASE_KEYS,
        "continuation analysis",
    )
    phases = historical_phases + continuation_phases
    if [(row["logical_segment_id"], row["phase_id"]) for row in phases] != list(
        LOGICAL_PHASE_KEYS
    ):
        raise ValueError("composite logical phase ordering differs")
    bridge = _validate_bridge(historical, historical_source)
    gap = _validate_gap(continuation, historical_source, continuation_source)
    strata, proof = _firmware_strata(
        (historical_source, continuation_source), compatibility_proof
    )
    if len(strata) > 1 and proof["cross_firmware_join_permitted"] is not True:
        phase_analysis_mode = "stratified_by_firmware_identity"
    else:
        phase_analysis_mode = "firmware_compatibility_join_permitted"

    result: dict[str, Any] = {
        "schema_version": 1,
        "analysis_type": ANALYSIS_TYPE,
        "tool": TOOL_ID,
        "evidence_status": "passed",
        "terminal": COMPOSITE_TERMINAL,
        "ordinary_programme_completion_terminal_permitted": False,
        "historical_terminal": {
            **dict(old_terminal),
            "preservation": "preserved_failed_not_reinterpreted_as_success",
            "source_run_id": historical_source["source_run_id"],
        },
        "contract_lineage": {
            "original_contract_sha256": historical_source[
                "original_contract_sha256"
            ],
            "continuation_contract_sha256": continuation_source[
                "continuation_contract_sha256"
            ],
        },
        "bridge": {
            "logical_segment_id": "S06",
            "historical_events": bridge,
            "capture_and_firmware_gap": gap,
        },
        "counter_delta_policy": {
            "rule": "subtract_only_within_one_source_run_artifact_contract_and_counter_baseline",
            "cross_source_subtraction_permitted": False,
            "counter_deltas_aggregated_across_sources": False,
        },
        "phase_analysis_mode": phase_analysis_mode,
        "firmware_strata": strata,
        "firmware_compatibility_proof": proof,
        "phases": phases,
        "segments": _segments(phases),
    }
    result["analysis_sha256"] = canonical_sha256(result)
    return result


def analyze(
    *,
    historical_prefix_path: Path,
    continuation_analysis_path: Path,
    output_path: Path | None = None,
    compatibility_proof_path: Path | None = None,
) -> dict[str, Any]:
    historical = json.loads(historical_prefix_path.read_text(encoding="utf-8"))
    continuation = json.loads(continuation_analysis_path.read_text(encoding="utf-8"))
    proof = (
        None
        if compatibility_proof_path is None
        else json.loads(compatibility_proof_path.read_text(encoding="utf-8"))
    )
    result = analyze_composite(
        historical_prefix=historical,
        continuation_analysis=continuation,
        compatibility_proof=proof,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-prefix", type=Path, required=True)
    parser.add_argument("--continuation-analysis", type=Path, required=True)
    parser.add_argument("--compatibility-proof", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = analyze(
        historical_prefix_path=args.historical_prefix,
        continuation_analysis_path=args.continuation_analysis,
        compatibility_proof_path=args.compatibility_proof,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
