"""Cross-campaign adaptive-steering analysis over completed OTIS evidence.

The tool is intentionally offline-only.  It accepts three completed package
roots through a read-only repository root, validates every frozen identity,
writes one separate derived package, and never imports capture, serial, run,
upload, or actuator modules.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from fractions import Fraction
import gzip
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any, Iterable, Sequence

from .adaptive_steering_contract import (
    canonical_sha256,
    file_sha256,
    load_analysis_contract,
    validate_output_location,
)
from .evidence import validate_evidence_snapshot
from .evidence_index import package_identity
from .measurement_replay import COUNT_INVALID_FLAGS, REFERENCE_INVALID_FLAGS
from .run_loader import RunManifest
from .time_domains import time_domain


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "docs/60_EXPERIMENTS/OTIS_CROSS_CAMPAIGN_ADAPTIVE_STEERING_OFFLINE_STUDY"
    / "analysis_contract_v2.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "runs/derived/cross_campaign_adaptive_steering_offline_v2"
DEFAULT_TRACKED_REPORT = (
    REPO_ROOT
    / "docs/60_EXPERIMENTS/OTIS_CROSS_CAMPAIGN_ADAPTIVE_STEERING_OFFLINE_STUDY"
    / "study_report_v2.json"
)
TOOL_ID = "otis_cross_campaign_adaptive_steering_offline_study_v2"
ANALYSIS_TOOL_RELATIVE_PATHS = (
    "host/otis_tools/adaptive_steering_offline_study.py",
    "host/otis_tools/adaptive_steering_offline.py",
    "host/otis_tools/adaptive_steering_contract.py",
)
NOMINAL_FREQUENCY_HZ = 10_000_000
QUALIFIED_PHASE_STATES = frozenset({"qualified"})
EXPECTED_CAPTURE_BACKEND = "pio_wait_cumulative_snapshot_dma_v1"
EXPECTED_SELECTED_ESTIMATOR = "cx317_selected_600s_nonoverlap_v1"
EXPECTED_SELECTED_CONFIG = (
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c"
)
EXPECTED_RPH_METHOD = "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"
EXPECTED_PHE_ESTIMATOR = "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1"
EXPECTED_PHASE_CONFIG = (
    "449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4"
)
EXPECTED_COUNT_SOURCE_DOMAINS = {
    "cx317_fll_baseline": "h0_tcxo_16mhz",
    "cx322_coherent": "h1_cx317_ocxo_10mhz",
    "attempt4_sustained": "h1_cx317_ocxo_10mhz",
}


@dataclass(frozen=True)
class Interval:
    source_id: str
    package_content_sha256: str
    source_file_sha256: str
    source_files_sha256_json: str
    session: int
    count_sequence: int
    opening_snapshot_sequence: int
    closing_snapshot_sequence: int
    opening_reference_sequence: int
    closing_reference_sequence: int
    opening_reference_timestamp_ticks: int
    closing_reference_timestamp_ticks: int
    timer_domain: str
    capture_backend: str
    counted_edges: int
    edge_error_cycles: int
    fractional_frequency: Fraction
    measurement_qualified: bool
    measurement_exclusion_reason: str
    phase_available: bool
    phase_method: str
    phase_epoch: str
    relative_phase_cycles: int | None
    phase_exclusion_reason: str
    dac_epoch: int | None
    applied_code: int | None
    settled_same_code: bool
    control_input_eligible: bool
    control_decision_eligible: bool | None
    control_decision_eligibility_state: str
    control_decision_eligibility_reason: str
    opening_d14_event_sequence: int | None = None
    closing_d14_event_sequence: int | None = None
    opening_d14_flags: int | None = None
    closing_d14_flags: int | None = None
    count_flags: int = 0
    count_gate_domain: str = ""
    count_source_domain: str = ""
    opening_snapshot_status: int | None = None
    closing_snapshot_status: int | None = None
    native_phase_observation_sequence: int | None = None


@dataclass(frozen=True)
class Application:
    source_id: str
    request_sequence: int
    decision_sequence: int
    source_first_sequence: int
    source_last_sequence: int
    decision_timestamp_s: int
    application_timestamp_s: int
    current_code: int
    requested_delta_codes: int
    applied_code: int
    dac_epoch: int
    phase_materially_influenced: bool | None
    response_class: str
    transaction_source_sha256: str


@dataclass
class SourceData:
    binding: dict[str, Any]
    root: Path
    manifest: dict[str, Any]
    raw_events: list[dict[str, str]]
    counts: list[dict[str, str]]
    snapshots: list[dict[str, str]]
    estimates: list[dict[str, str]]
    phase: list[dict[str, str]]
    phase_outputs: list[dict[str, str]]
    decisions: list[dict[str, str]]
    transactions: list[dict[str, str]]
    environment: list[dict[str, str]]
    intervals: list[Interval]
    applications: list[Application]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _bool(value: str | None) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"malformed Boolean {value!r}")


def _source_provenance_json(
    binding: dict[str, Any], *relative_paths: str
) -> str:
    """Return a canonical, explicit mapping for every material source file."""

    consumed = binding["consumed_files"]
    selected = {
        relative_path: consumed[relative_path]
        for relative_path in sorted(set(relative_paths))
        if relative_path in consumed
    }
    missing = [
        relative_path
        for relative_path in relative_paths
        if relative_path not in consumed
    ]
    if missing:
        raise ValueError(
            f"material source files are not frozen for {binding['source_id']}: {missing}"
        )
    return json.dumps(selected, sort_keys=True, separators=(",", ":"))


def _measurement_provenance_json(
    binding: dict[str, Any], *, include_selected: bool = False
) -> str:
    paths = [
        "csv/raw_events.csv",
        "csv/pps_snapshots.csv",
        "csv/count_observations.csv",
        "csv/active_transactions_v1.csv",
    ]
    if include_selected:
        paths.append("csv/estimates_v2.csv")
    for optional in (
        "csv/relative_phase_observations_v1.csv",
        "csv/phase_estimator_outputs_v1.csv",
    ):
        if optional in binding["consumed_files"]:
            paths.append(optional)
    return _source_provenance_json(binding, *paths)


def _candidate_provenance_json(binding: dict[str, Any]) -> str:
    paths = ["csv/estimates_v2.csv", "csv/active_transactions_v1.csv"]
    for optional in (
        "csv/active_hybrid_decisions_v1.csv",
        "csv/relative_phase_observations_v1.csv",
        "csv/phase_estimator_outputs_v1.csv",
        "csv/control_previews_v1.csv",
    ):
        if optional in binding["consumed_files"]:
            paths.append(optional)
    return _source_provenance_json(binding, *paths)


def _semantic_identity_exact(value: dict[str, Any], field: str) -> bool:
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    return isinstance(claimed, str) and claimed == canonical_sha256(unsigned)


def validate_sources(
    contract: dict[str, Any], evidence_repository: Path
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate frozen files, historical manifests, attestations, and trees."""

    ledger: list[dict[str, Any]] = []
    pre_identities: dict[str, dict[str, Any]] = {}
    for binding in contract["sources"]:
        source_id = binding["source_id"]
        root = (evidence_repository / binding["logical_package_path"]).resolve()
        if not root.is_dir():
            raise ValueError(f"required completed source is unavailable: {source_id}")
        mismatches = [
            relative
            for relative, expected in binding["consumed_files"].items()
            if not (root / relative).is_file()
            or file_sha256(root / relative) != expected
        ]
        if mismatches:
            raise ValueError(f"source consumed-file identity differs: {source_id}: {mismatches}")

        manifest_value = _read_object(root / "run_manifest.json")
        historical = binding["historical_identity"]
        firmware = manifest_value.get("firmware", {})
        source_revision = firmware.get("git_commit", firmware.get("source_revision"))
        build_identity = firmware.get("build_identity")
        if source_revision != historical["source_revision"] or build_identity != historical[
            "firmware_build_identity"
        ]:
            raise ValueError(f"historical firmware identity differs: {source_id}")
        manifest = RunManifest(
            root=root,
            path=root / "run_manifest.json",
            data=manifest_value,
        )
        failures, warnings = validate_evidence_snapshot(root, manifest)
        if failures or warnings:
            raise ValueError(
                f"historical evidence snapshot differs: {source_id}: "
                f"failures={failures}; warnings={warnings}"
            )
        evidence = _read_object(root / "evidence_manifest.json")
        if (
            evidence.get("run_state") != "complete"
            or evidence.get("snapshot_digest")
            != binding["package_identity"]["evidence_snapshot_sha256"]
        ):
            raise ValueError(f"evidence snapshot terminal differs: {source_id}")

        tree = package_identity(root)
        expected_tree = binding["package_identity"]
        if any(
            tree[name] != expected_tree[name]
            for name in ("content_sha256", "file_count", "total_bytes")
        ):
            raise ValueError(f"full source tree identity differs: {source_id}")
        pre_identities[source_id] = {
            key: tree[key] for key in ("content_sha256", "file_count", "total_bytes")
        }

        attestation = binding["terminal_attestation"]
        attestation_value = _read_object(root / attestation["path"])
        semantic_field = "seal_sha256" if attestation["class"] == "physical_seal" else None
        semantic_exact = True
        if semantic_field is not None:
            semantic_exact = (
                _semantic_identity_exact(attestation_value, semantic_field)
                and attestation_value[semantic_field] == attestation["semantic_sha256"]
            )
        if not semantic_exact or attestation_value.get("status") != attestation["status"]:
            raise ValueError(f"terminal attestation differs: {source_id}")

        ledger.append(
            {
                "source_id": source_id,
                "logical_package_path": binding["logical_package_path"],
                "path_present": True,
                "required": True,
                "source_snapshot_valid": True,
                "full_tree_identity_valid": True,
                "semantic_attestation_valid": semantic_exact,
                "terminal_attestation_class": attestation["class"],
                "terminal_attestation_file_sha256": attestation["file_sha256"],
                "acquisition_terminal": attestation.get("acquisition_terminal"),
                "scientific_terminal": attestation.get("scientific_terminal"),
                "formal_status": attestation["status"],
                "package_identity": pre_identities[source_id],
                "evidence_snapshot_sha256": evidence["snapshot_digest"],
                "source_revision": source_revision,
                "firmware_build_identity": build_identity,
                "profile_identity": historical["profile_identity"],
                "policy_sha256": historical["policy_sha256"],
                "board": historical["board"],
                "board_serial": historical.get("board_serial", "not_retained"),
                "receiver_identity": historical["receiver_identity"],
                "timer_domain": historical["timer_domain"],
                "capture_backend": historical["capture_backend"],
                "rollover": historical["rollover"],
                "allowed_roles": binding["allowed_roles"],
                "explicit_exclusions": binding["explicit_exclusions"],
                "consumed_files": binding["consumed_files"],
            }
        )
    return ledger, pre_identities


def _applications(
    source_id: str,
    binding: dict[str, Any],
    transactions: list[dict[str, str]],
    decisions: list[dict[str, str]],
) -> list[Application]:
    decisions_by_sequence = {
        int(row["decision_sequence"]): row for row in decisions
    }
    result: list[Application] = []
    for row in transactions:
        if row.get("event") != "application":
            continue
        decision_sequence = int(row["decision_sequence"])
        decision = decisions_by_sequence.get(decision_sequence)
        result.append(
            Application(
                source_id=source_id,
                request_sequence=int(row["request_sequence"]),
                decision_sequence=decision_sequence,
                source_first_sequence=int(row["source_first_sequence"]),
                source_last_sequence=int(row["source_last_sequence"]),
                decision_timestamp_s=int(row["decision_timestamp_s"]),
                application_timestamp_s=int(row["application_timestamp_s"]),
                current_code=int(row["current_applied_code"]),
                requested_delta_codes=int(row["requested_delta_codes"]),
                applied_code=int(row["applied_code"]),
                dac_epoch=int(row["dac_epoch"]),
                phase_materially_influenced=(
                    None
                    if decision is None
                    else _bool(decision["phase_materially_influenced"])
                ),
                response_class=str(row.get("response_class", "")),
                transaction_source_sha256=binding["consumed_files"][
                    "csv/active_transactions_v1.csv"
                ],
            )
        )
    return result


def _validated_selected_frequency_rows(
    *,
    source_id: str,
    binding: dict[str, Any],
    estimates: list[dict[str, str]],
    intervals: list[Interval],
    decisions: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], set[int]]:
    """Replay each recorded selected-600 estimate against exact count support."""

    interval_by_reference: dict[int, Interval] = {}
    for interval in intervals:
        key = interval.closing_reference_sequence
        if key in interval_by_reference:
            raise ValueError(
                f"duplicate normalized reference sequence {key} in {source_id}"
            )
        interval_by_reference[key] = interval
    selected_estimates = [
        row
        for row in estimates
        if row.get("estimator_version") == EXPECTED_SELECTED_ESTIMATOR
    ]
    selected_estimates.sort(key=lambda row: int(row["estimate_seq"]))
    decision_by_frontier = {
        int(row["source_last_sequence"]): row for row in decisions
    }
    provenance = _measurement_provenance_json(binding, include_selected=True)
    support: set[int] = set()
    result: list[dict[str, Any]] = []
    for window_sequence, estimate in enumerate(selected_estimates):
        first = int(estimate["source_reference_first_seq"])
        last = int(estimate["source_reference_last_seq"])
        expected_sequences = list(range(first + 1, last + 1))
        selected = [interval_by_reference.get(item) for item in expected_sequences]
        reasons: list[str] = []
        if last - first != 600 or len(selected) != 600:
            reasons.append("selected_span_not_600_intervals")
        if any(row is None for row in selected):
            reasons.append("selected_support_missing_interval")
        exact = [row for row in selected if row is not None]
        if any(not row.measurement_qualified for row in exact):
            reasons.append("selected_support_unqualified_interval")
        if exact and (
            exact[0].opening_reference_sequence != first
            or exact[-1].closing_reference_sequence != last
        ):
            reasons.append("selected_opening_or_closing_boundary_mismatch")
        if exact and any(
            row.session != exact[0].session
            or row.timer_domain != exact[0].timer_domain
            or row.capture_backend != exact[0].capture_backend
            for row in exact
        ):
            reasons.append("selected_session_domain_or_backend_break")
        required_fields = bool(
            estimate.get("record_type") == "EST"
            and estimate.get("schema_version") == "2"
            and estimate.get("time_domain") == "rp2040_timer0"
            and estimate.get("config_hash") == EXPECTED_SELECTED_CONFIG
            and estimate.get("accepted_sample_count") == "600"
            and estimate.get("source_count_seq") == str(last)
            and estimate.get("source_count_ref") == f"live:CNT:{last}"
            and estimate.get("observation_validity") == "valid"
            and estimate.get("reference_validity") == "valid"
            and estimate.get("reference_age_s") == "0"
            and estimate.get("reference_continuity") == "true"
            and estimate.get("count_validity") == "valid"
            and estimate.get("count_age_s") == "0"
            and estimate.get("count_continuity") == "true"
            and estimate.get("diagnostic_health") == "healthy"
            and estimate.get("preview_eligibility") == "true"
        )
        if not required_fields:
            reasons.append("recorded_selected_estimator_identity_or_validity_mismatch")
        total = sum(row.counted_edges for row in exact)
        error = Fraction(total, 600) - NOMINAL_FREQUENCY_HZ if len(exact) == 600 else None
        # Firmware serialized the subtraction from a binary64 value near
        # 10 MHz.  Bind it within that value's half-ULP plus the 12-decimal
        # field half-unit; retain the exact count-domain fraction below.
        serialized_tolerance = math.ulp(float(NOMINAL_FREQUENCY_HZ)) / 2 + 5e-13
        if (
            error is not None
            and abs(float(error) - float(estimate["frequency_error_hz"]))
            > serialized_tolerance
        ):
            reasons.append("recorded_selected_frequency_error_mismatch")
        available = not reasons
        if available:
            support.update(expected_sequences)
        code_identities = {(row.dac_epoch, row.applied_code) for row in exact}
        summary_eligible = bool(
            available
            and len(code_identities) == 1
            and all(row.settled_same_code for row in exact)
        )
        closing = exact[-1] if exact else None
        opening = exact[0] if exact else None
        policy = decision_by_frontier.get(last)
        result.append(
            {
                "source_id": source_id,
                "window_sequence": window_sequence,
                "availability": "available" if available else "unavailable",
                "exclusion_reason": ";".join(reasons),
                "frequency_summary_eligible": summary_eligible,
                "frequency_summary_exclusion_reason": (
                    "" if summary_eligible else "support_not_entirely_settled_at_one_code"
                ),
                "estimator_id": EXPECTED_SELECTED_ESTIMATOR,
                "estimate_sequence": int(estimate["estimate_seq"]),
                "estimate_record_id": estimate["estimate_id"],
                "opening_boundary": "opening_exclusive",
                "closing_boundary": "closing_inclusive",
                "source_first_sequence": first,
                "source_last_sequence": last,
                "opening_timestamp_ticks": (
                    opening.opening_reference_timestamp_ticks if opening else ""
                ),
                "closing_timestamp_ticks": (
                    closing.closing_reference_timestamp_ticks if closing else ""
                ),
                "capture_session": closing.session if closing else "",
                "dac_epoch": closing.dac_epoch if closing else "",
                "applied_code": closing.applied_code if closing else "",
                "accepted_interval_count": len(exact),
                "total_counted_edges": total if error is not None else "",
                "frequency_error_fraction_numerator": (
                    error.numerator if error is not None else ""
                ),
                "frequency_error_fraction_denominator": (
                    error.denominator if error is not None else ""
                ),
                "frequency_error_hz": float(error) if error is not None else "",
                "absolute_frequency_error_hz": (
                    abs(float(error)) if error is not None else ""
                ),
                "historical_tight_state": (
                    policy.get("tight_state", "unavailable")
                    if policy is not None
                    else "unavailable"
                ),
                "historical_controller_state": (
                    policy.get("state_after", "unavailable")
                    if policy is not None
                    else "unavailable"
                ),
                "source_file_sha256": binding["consumed_files"][
                    "csv/estimates_v2.csv"
                ],
                "source_files_sha256_json": provenance,
            }
        )
    return result, support


def _validate_hybrid_decision_joins(
    *,
    source_id: str,
    estimates: list[dict[str, str]],
    phase_rows: list[dict[str, str]],
    phase_outputs: list[dict[str, str]],
    decisions: list[dict[str, str]],
) -> None:
    """Fail closed unless every AHY input binds to its exact EST/RPH/PHE rows."""

    if not decisions:
        return
    selected = {
        (int(row["source_reference_first_seq"]), int(row["source_reference_last_seq"])): row
        for row in estimates
        if row.get("estimator_version") == EXPECTED_SELECTED_ESTIMATOR
    }
    rph = {
        (row["phase_epoch"], row["observation_sequence"]): row
        for row in phase_rows
    }
    phe = {
        row["source_relative_phase_observation"]: row for row in phase_outputs
    }
    for decision in decisions:
        first = int(decision["source_first_sequence"])
        last = int(decision["source_last_sequence"])
        estimate = selected.get((first, last))
        phase_key = (
            decision["phase_epoch"], decision["phase_observation_sequence"]
        )
        phase = rph.get(phase_key)
        phase_identity = f"RPH:{phase_key[0]}:{phase_key[1]}"
        output = phe.get(phase_identity)
        exact = bool(
            estimate is not None
            and estimate.get("config_hash") == decision["frequency_estimator_sha256"]
            and abs(
                float(estimate["frequency_error_hz"])
                - float(decision["frequency_error_hz"])
            )
            <= 5e-13
            and phase is not None
            and phase.get("configuration_sha256") == decision["phase_estimator_sha256"]
            and phase.get("capture_session") == decision["capture_session"]
            and phase.get("relative_phase_cycles") == decision["relative_phase_cycles"]
            and phase.get("dac_epoch") == decision["phase_dac_epoch"]
            and output is not None
            and output.get("phase_epoch") == phase_key[0]
            and output.get("observation_sequence") == phase_key[1]
            and output.get("raw_relative_phase_cycles")
            == decision["relative_phase_cycles"]
            and output.get("estimator_id") == EXPECTED_PHE_ESTIMATOR
            and output.get("configuration_sha256")
            == decision["phase_estimator_sha256"]
            and output.get("qualification_state") == "qualified"
        )
        if not exact:
            raise ValueError(
                f"AHY EST/RPH/PHE identity mismatch in {source_id} decision "
                f"{decision['decision_sequence']}"
            )


def _epoch_codes(
    transactions: list[dict[str, str]],
) -> tuple[dict[int, int], int | None]:
    mapping: dict[int, int] = {}
    manual_code: int | None = None
    for row in transactions:
        if row.get("event") == "manual_start":
            manual_code = int(row["applied_code"])
            epoch = int(row["dac_epoch"])
            mapping[epoch if epoch > 0 else 0] = manual_code
            if epoch == 0:
                mapping[1] = manual_code
        elif row.get("event") == "application":
            mapping[int(row["dac_epoch"])] = int(row["applied_code"])
    return mapping, manual_code


def _strict_native_phase(
    native: dict[str, str] | None,
    phe_by_rph: dict[str, dict[str, str]],
    opening: dict[str, str] | None,
    closing: dict[str, str] | None,
    count: dict[str, str],
    edge_error: int,
) -> tuple[bool, str]:
    """Validate the exact interval -> RPH -> PHE identity chain."""

    if native is None:
        return False, "missing_native_phase_row"
    reasons: list[str] = []
    rph_identity = f"RPH:{native['phase_epoch']}:{native['observation_sequence']}"
    phe = phe_by_rph.get(rph_identity)
    exact_rph = bool(
        opening is not None
        and closing is not None
        and native.get("record_type") == "RPH"
        and native.get("schema_version") == "1"
        and int(native["capture_session"]) == int(closing["session"])
        and int(native["opening_snapshot_sequence"])
        == int(opening["snapshot_sequence"])
        and int(native["closing_snapshot_sequence"])
        == int(closing["snapshot_sequence"])
        and int(native["opening_reference_sequence"])
        == int(opening["reference_sequence"])
        and int(native["closing_reference_sequence"])
        == int(closing["reference_sequence"])
        and native.get("source_backend") == EXPECTED_CAPTURE_BACKEND
        and native.get("source_file_sha256") == "live_stream_unsealed"
        and native.get("method_id") == EXPECTED_RPH_METHOD
        and native.get("configuration_sha256") == EXPECTED_PHASE_CONFIG
        and native.get("interval_edges") == count["counted_edges"]
        and native.get("edge_error_cycles") == str(edge_error)
        and native.get("observation_age_s") == "0"
    )
    if not exact_rph:
        reasons.append("rph_interval_identity_mismatch")
    if native.get("qualification_state") not in QUALIFIED_PHASE_STATES:
        reasons.append(f"rph_{native.get('qualification_state', 'state_missing')}")
    exact_phe = bool(
        phe is not None
        and phe.get("record_type") == "PHE"
        and phe.get("schema_version") == "1"
        and phe.get("phase_epoch") == native["phase_epoch"]
        and phe.get("observation_sequence") == native["observation_sequence"]
        and phe.get("source_relative_phase_observation") == rph_identity
        and phe.get("raw_relative_phase_cycles") == native["relative_phase_cycles"]
        and phe.get("raw_relative_phase_time_ns") == native["relative_phase_time_ns"]
        and phe.get("estimator_id") == EXPECTED_PHE_ESTIMATOR
        and phe.get("configuration_sha256") == EXPECTED_PHASE_CONFIG
    )
    if not exact_phe:
        reasons.append("phe_rph_identity_mismatch")
    elif phe.get("qualification_state") not in QUALIFIED_PHASE_STATES:
        reasons.append(f"phe_{phe.get('qualification_state', 'state_missing')}")
    return not reasons, ";".join(reasons)


def _build_intervals(
    source_id: str,
    binding: dict[str, Any],
    raw_events: list[dict[str, str]],
    counts: list[dict[str, str]],
    snapshots: list[dict[str, str]],
    phase_rows: list[dict[str, str]],
    phase_outputs: list[dict[str, str]],
    transactions: list[dict[str, str]],
) -> list[Interval]:
    def unique_by_int(
        rows: list[dict[str, str]], field: str, label: str
    ) -> dict[int, dict[str, str]]:
        indexed: dict[int, dict[str, str]] = {}
        for row in rows:
            key = int(row[field])
            if key in indexed:
                raise ValueError(f"duplicate {label} identity {key} in {source_id}")
            indexed[key] = row
        return indexed

    snapshot_by_sequence = unique_by_int(
        snapshots, "snapshot_sequence", "snapshot_sequence"
    )
    count_by_sequence = unique_by_int(counts, "count_seq", "count_seq")
    phase_by_closing = unique_by_int(
        phase_rows, "closing_snapshot_sequence", "phase closing_snapshot_sequence"
    )
    d14_events = [
        row
        for row in raw_events
        if row.get("record_type") == "REF"
        and row.get("schema_version") == "1"
        and row.get("channel_id") == "1"
        and row.get("edge") == "R"
        and row.get("capture_domain") == "rp2040_timer0"
    ]
    d14_by_timestamp: dict[int, list[tuple[int, dict[str, str]]]] = {}
    for position, row in enumerate(d14_events):
        d14_by_timestamp.setdefault(int(row["timestamp_ticks"]), []).append(
            (position, row)
        )
    phe_by_rph: dict[str, dict[str, str]] = {}
    for row in phase_outputs:
        key = row["source_relative_phase_observation"]
        if key in phe_by_rph:
            raise ValueError(f"duplicate PHE source identity {key} in {source_id}")
        phe_by_rph[key] = row
    epoch_codes, manual_code = _epoch_codes(transactions)
    applications = [
        row for row in transactions if row.get("event") == "application"
    ]
    application_boundaries = sorted(
        (int(row["source_last_sequence"]), int(row["dac_epoch"]), int(row["applied_code"]))
        for row in applications
    )
    source_hash = binding["consumed_files"]["csv/count_observations.csv"]
    source_provenance = _measurement_provenance_json(
        binding, include_selected=True
    )
    package_hash = binding["package_identity"]["content_sha256"]
    result: list[Interval] = []
    derived_phase = 0
    derived_epoch = 1
    previous_interval: Interval | None = None
    expected_source_domain = binding.get("count_source_domain") or (
        EXPECTED_COUNT_SOURCE_DOMAINS.get(source_id)
    )
    if not expected_source_domain:
        raise ValueError(f"count source domain is not frozen for {source_id}")
    first_count_sequence = min(count_by_sequence)
    for count in counts:
        sequence = int(count["count_seq"])
        closing = snapshot_by_sequence.get(sequence)
        opening = snapshot_by_sequence.get(sequence - 1)
        if opening is None and closing is not None and sequence == first_count_sequence:
            continue
        reasons: list[str] = []
        opening_raw: dict[str, str] | None = None
        closing_raw: dict[str, str] | None = None
        if opening is None:
            reasons.append("missing_opening_snapshot")
        if closing is None:
            reasons.append("missing_closing_snapshot")
        if count.get("record_type") != "CNT" or count.get("schema_version") != "1":
            reasons.append("count_record_identity_mismatch")
        if count.get("channel_id") != "2" or count.get("source_edge") != "R":
            reasons.append("d8_count_wire_identity_mismatch")
        if count.get("gate_domain") != "rp2040_timer0":
            reasons.append("count_gate_domain_mismatch")
        if count.get("source_domain") != expected_source_domain:
            reasons.append("count_source_domain_mismatch")
        if int(count["flags"]) & COUNT_INVALID_FLAGS:
            reasons.append("count_invalid_flags")
        if opening is not None and closing is not None:
            if (
                opening.get("record_type") != "SNP"
                or closing.get("record_type") != "SNP"
                or opening.get("schema_version") != "1"
                or closing.get("schema_version") != "1"
            ):
                reasons.append("snapshot_record_identity_mismatch")
            if int(opening["status"]) != 0 or int(closing["status"]) != 0:
                reasons.append("snapshot_status_invalid")
            if (
                opening.get("backend") != EXPECTED_CAPTURE_BACKEND
                or closing.get("backend") != EXPECTED_CAPTURE_BACKEND
            ):
                reasons.append("snapshot_backend_mismatch")
            if int(opening["session"]) != int(closing["session"]):
                reasons.append("capture_session_change")
            if int(closing["snapshot_sequence"]) != int(opening["snapshot_sequence"]) + 1:
                reasons.append("nonconsecutive_snapshot_sequence")
            if int(closing["reference_sequence"]) != int(opening["reference_sequence"]) + 1:
                reasons.append("nonconsecutive_d14_reference_sequence")
            if int(count["count_seq"]) != int(closing["snapshot_sequence"]):
                reasons.append("count_closing_snapshot_sequence_mismatch")
            if int(count["gate_open_ticks"]) != int(opening["reference_timestamp_ticks"]):
                reasons.append("count_gate_open_snapshot_mismatch")
            if int(count["gate_close_ticks"]) != int(closing["reference_timestamp_ticks"]):
                reasons.append("count_gate_close_snapshot_mismatch")
            reconstructed = (
                int(opening["cumulative_down_counter"])
                - int(closing["cumulative_down_counter"])
            ) & 0xFFFFFFFF
            if reconstructed != int(count["counted_edges"]):
                reasons.append("snapshot_count_parity_mismatch")
            opening_matches = d14_by_timestamp.get(
                int(opening["reference_timestamp_ticks"]), []
            )
            closing_matches = d14_by_timestamp.get(
                int(closing["reference_timestamp_ticks"]), []
            )
            if len(opening_matches) != 1:
                reasons.append("opening_d14_raw_event_not_unique")
            if len(closing_matches) != 1:
                reasons.append("closing_d14_raw_event_not_unique")
            if len(opening_matches) == 1 and len(closing_matches) == 1:
                opening_position, opening_raw = opening_matches[0]
                closing_position, closing_raw = closing_matches[0]
                if closing_position != opening_position + 1:
                    reasons.append("d14_raw_event_stream_not_adjacent")
                if (
                    int(opening_raw["flags"]) & REFERENCE_INVALID_FLAGS
                    or int(closing_raw["flags"]) & REFERENCE_INVALID_FLAGS
                ):
                    reasons.append("d14_raw_event_invalid_flags")
        valid = not reasons

        edge_error = int(count["counted_edges"]) - NOMINAL_FREQUENCY_HZ
        native = phase_by_closing.get(sequence)
        if phase_rows:
            phase_exact, phase_reason = _strict_native_phase(
                native,
                phe_by_rph,
                opening,
                closing,
                count,
                edge_error,
            )
            phase_available = valid and phase_exact
            phase_method = native["method_id"] if native is not None else "native_unavailable"
            phase_epoch = native["phase_epoch"] if native is not None else "unavailable"
            relative_phase = int(native["relative_phase_cycles"]) if phase_available else None
            if not valid:
                phase_reason = ";".join(
                    item
                    for item in ("measurement_interval_invalid", phase_reason)
                    if item
                )
            dac_epoch = int(native["dac_epoch"]) if native is not None else None
            applied_code = epoch_codes.get(dac_epoch) if dac_epoch is not None else None
        else:
            phase_contiguous = bool(
                valid
                and previous_interval is not None
                and previous_interval.measurement_qualified
                and sequence == previous_interval.count_sequence + 1
                and closing is not None
                and int(closing["session"]) == previous_interval.session
            )
            if not phase_contiguous:
                derived_epoch += 1
                derived_phase = 0
            if valid:
                derived_phase += edge_error
            phase_available = valid
            phase_method = "derived_adjacent_d14_d8_integer_cumulative_phase_v1"
            phase_epoch = f"derived:{derived_epoch}"
            relative_phase = derived_phase if valid else None
            phase_reason = "" if valid else "measurement_interval_invalid"
            dac_epoch = 0
            applied_code = manual_code
            for boundary, epoch, code in application_boundaries:
                if sequence > boundary:
                    dac_epoch = epoch
                    applied_code = code

        most_recent_application = max(
            (
                int(row["source_last_sequence"])
                for row in applications
                if int(row["source_last_sequence"]) < sequence
            ),
            default=None,
        )
        settled = bool(
            valid
            and applied_code is not None
            and (
                most_recent_application is None
                or sequence - most_recent_application > 900
            )
        )
        session = int(closing["session"]) if closing is not None else -1
        interval = Interval(
                source_id=source_id,
                package_content_sha256=package_hash,
                source_file_sha256=source_hash,
                source_files_sha256_json=source_provenance,
                session=session,
                count_sequence=sequence,
                opening_snapshot_sequence=sequence - 1,
                closing_snapshot_sequence=sequence,
                opening_reference_sequence=(
                    int(opening["reference_sequence"]) if opening is not None else -1
                ),
                closing_reference_sequence=(
                    int(closing["reference_sequence"]) if closing is not None else -1
                ),
                opening_reference_timestamp_ticks=(
                    int(opening["reference_timestamp_ticks"]) if opening is not None else -1
                ),
                closing_reference_timestamp_ticks=(
                    int(closing["reference_timestamp_ticks"]) if closing is not None else -1
                ),
                timer_domain=binding["historical_identity"]["timer_domain"],
                capture_backend=(closing["backend"] if closing is not None else "unavailable"),
                counted_edges=int(count["counted_edges"]),
                edge_error_cycles=edge_error,
                fractional_frequency=Fraction(edge_error, NOMINAL_FREQUENCY_HZ),
                measurement_qualified=valid,
                measurement_exclusion_reason=";".join(reasons),
                phase_available=phase_available,
                phase_method=phase_method,
                phase_epoch=str(phase_epoch),
                relative_phase_cycles=relative_phase,
                phase_exclusion_reason=phase_reason,
                dac_epoch=dac_epoch,
                applied_code=applied_code,
                settled_same_code=settled,
                control_input_eligible=False,
                control_decision_eligible=None,
                control_decision_eligibility_state="unavailable",
                control_decision_eligibility_reason=(
                    "historical_gnss_metadata_cadence_exceeds_freshness_bound"
                ),
                opening_d14_event_sequence=(
                    int(opening_raw["event_seq"]) if opening_raw is not None else None
                ),
                closing_d14_event_sequence=(
                    int(closing_raw["event_seq"]) if closing_raw is not None else None
                ),
                opening_d14_flags=(
                    int(opening_raw["flags"]) if opening_raw is not None else None
                ),
                closing_d14_flags=(
                    int(closing_raw["flags"]) if closing_raw is not None else None
                ),
                count_flags=int(count["flags"]),
                count_gate_domain=count.get("gate_domain", ""),
                count_source_domain=count.get("source_domain", ""),
                opening_snapshot_status=(
                    int(opening["status"]) if opening is not None else None
                ),
                closing_snapshot_status=(
                    int(closing["status"]) if closing is not None else None
                ),
                native_phase_observation_sequence=(
                    int(native["observation_sequence"]) if native is not None else None
                ),
            )
        result.append(interval)
        previous_interval = interval
    return result


def load_source_data(
    contract: dict[str, Any], evidence_repository: Path
) -> list[SourceData]:
    result: list[SourceData] = []
    for binding in contract["sources"]:
        root = (evidence_repository / binding["logical_package_path"]).resolve()
        raw_events = _read_csv(root / "csv/raw_events.csv")
        counts = _read_csv(root / "csv/count_observations.csv")
        snapshots = _read_csv(root / "csv/pps_snapshots.csv")
        estimates = _read_csv(root / "csv/estimates_v2.csv")
        phase_path = root / "csv/relative_phase_observations_v1.csv"
        phase_output_path = root / "csv/phase_estimator_outputs_v1.csv"
        decision_path = root / "csv/active_hybrid_decisions_v1.csv"
        phase = _read_csv(phase_path) if phase_path.is_file() else []
        phase_outputs = (
            _read_csv(phase_output_path) if phase_output_path.is_file() else []
        )
        decisions = _read_csv(decision_path) if decision_path.is_file() else []
        transactions = _read_csv(root / "csv/active_transactions_v1.csv")
        environment = _read_csv(root / "csv/environment.csv")
        source_id = binding["source_id"]
        intervals = _build_intervals(
            source_id,
            binding,
            raw_events,
            counts,
            snapshots,
            phase,
            phase_outputs,
            transactions,
        )
        _, control_input_support = _validated_selected_frequency_rows(
            source_id=source_id,
            binding=binding,
            estimates=estimates,
            intervals=intervals,
            decisions=decisions,
        )
        _validate_hybrid_decision_joins(
            source_id=source_id,
            estimates=estimates,
            phase_rows=phase,
            phase_outputs=phase_outputs,
            decisions=decisions,
        )
        intervals = [
            replace(
                interval,
                control_input_eligible=(
                    interval.closing_reference_sequence in control_input_support
                ),
            )
            for interval in intervals
        ]
        result.append(
            SourceData(
                binding=binding,
                root=root,
                manifest=_read_object(root / "run_manifest.json"),
                raw_events=raw_events,
                counts=counts,
                snapshots=snapshots,
                estimates=estimates,
                phase=phase,
                phase_outputs=phase_outputs,
                decisions=decisions,
                transactions=transactions,
                environment=environment,
                intervals=intervals,
                applications=_applications(
                    source_id, binding, transactions, decisions
                ),
            )
        )
    return result


def _contiguous_segments(
    rows: Iterable[Interval],
    *,
    keys: Sequence[str],
    require_phase: bool = False,
    require_settled: bool = False,
) -> list[list[Interval]]:
    segments: list[list[Interval]] = []
    active: list[Interval] = []
    for row in rows:
        eligible = (
            row.measurement_qualified
            and (not require_phase or row.phase_available)
            and (not require_settled or row.settled_same_code)
        )
        joins = bool(
            eligible
            and (
                not active
                or (
                    row.count_sequence == active[-1].count_sequence + 1
                    and all(getattr(row, key) == getattr(active[-1], key) for key in keys)
                )
            )
        )
        if not joins and active:
            segments.append(active)
            active = []
        if eligible:
            active.append(row)
    if active:
        segments.append(active)
    return segments


def selected_frequency_windows(source: SourceData) -> list[dict[str, Any]]:
    """Return recorded selected-600 estimates replayed without a phase join."""

    rows, _ = _validated_selected_frequency_rows(
        source_id=source.binding["source_id"],
        binding=source.binding,
        estimates=source.estimates,
        intervals=source.intervals,
        decisions=source.decisions,
    )
    return rows


def _ols_exact(points: Sequence[tuple[int, int]]) -> tuple[int, int, float]:
    if len(points) < 2:
        raise ValueError("OLS requires at least two points")
    n = len(points)
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    numerator = n * sum(x * y for x, y in points) - sum_x * sum_y
    denominator = n * sum(x * x for x, _ in points) - sum_x * sum_x
    if denominator == 0:
        raise ValueError("OLS denominator is zero")
    return numerator, denominator, numerator / denominator


def _phase_window_record(
    source: SourceData,
    selected: Sequence[Interval],
    *,
    horizon_s: int,
    alignment: str,
    application: Application | None = None,
) -> dict[str, Any]:
    points = [
        (row.closing_reference_sequence, int(row.relative_phase_cycles))
        for row in selected
        if row.relative_phase_cycles is not None
    ]
    numerator, denominator, slope = _ols_exact(points)
    phase = [value for _, value in points]
    opening = selected[0]
    closing = selected[-1]
    provenance = _measurement_provenance_json(source.binding)
    return {
        "source_id": source.binding["source_id"],
        "availability": "available",
        "exclusion_reason": "",
        "alignment": alignment,
        "application_request_sequence": (
            application.request_sequence if application is not None else ""
        ),
        "horizon_s": horizon_s,
        "window_count": len(points),
        "capture_session": opening.session,
        "phase_method": opening.phase_method,
        "phase_epoch": opening.phase_epoch,
        "source_first_sequence": opening.closing_reference_sequence,
        "source_last_sequence": closing.closing_reference_sequence,
        "ols_slope_exact_numerator": numerator,
        "ols_slope_exact_denominator": denominator,
        "signed_ols_slope_cycles_per_d14_s": slope,
        "absolute_ols_slope_cycles_per_d14_s": abs(slope),
        "signed_endpoint_movement_cycles": phase[-1] - phase[0],
        "peak_to_peak_phase_excursion_cycles": max(phase) - min(phase),
        "maximum_absolute_excursion_from_origin_cycles": max(
            abs(value - phase[0]) for value in phase
        ),
        "source_file_sha256": source.binding["consumed_files"].get(
            "csv/relative_phase_observations_v1.csv",
            source.binding["consumed_files"]["csv/count_observations.csv"],
        ),
        "source_files_sha256_json": provenance,
    }


def phase_windows(
    source: SourceData, horizons_s: Sequence[int]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    segments = _contiguous_segments(
        source.intervals,
        keys=(
            "session",
            "timer_domain",
            "capture_backend",
            "phase_method",
            "phase_epoch",
        ),
        require_phase=True,
    )
    for horizon in horizons_s:
        for segment in segments:
            emitted = 0
            for start in range(0, len(segment) - horizon, horizon):
                selected = segment[start : start + horizon + 1]
                if len(selected) == horizon + 1:
                    result.append(
                        _phase_window_record(
                            source,
                            selected,
                            horizon_s=horizon,
                            alignment="segment_origin_nonoverlap",
                        )
                    )
                    emitted += 1
            if emitted == 0:
                result.append(
                    {
                        "source_id": source.binding["source_id"],
                        "availability": "unavailable",
                        "exclusion_reason": (
                            "insufficient_complete_unjoined_segment_origin_horizon_support"
                        ),
                        "alignment": "segment_origin_nonoverlap",
                        "application_request_sequence": "",
                        "horizon_s": horizon,
                        "window_count": 0,
                        "capture_session": segment[0].session,
                        "phase_method": segment[0].phase_method,
                        "phase_epoch": segment[0].phase_epoch,
                        "source_first_sequence": segment[0].closing_reference_sequence,
                        "source_last_sequence": segment[-1].closing_reference_sequence,
                        "source_file_sha256": source.binding["consumed_files"].get(
                            "csv/relative_phase_observations_v1.csv",
                            source.binding["consumed_files"]["csv/count_observations.csv"],
                        ),
                        "source_files_sha256_json": _measurement_provenance_json(
                            source.binding
                        ),
                    }
                )
        by_sequence = {
            row.closing_reference_sequence: (segment_index, row_index)
            for segment_index, segment in enumerate(segments)
            for row_index, row in enumerate(segment)
        }
        for application in source.applications:
            location = by_sequence.get(application.source_last_sequence)
            for direction in ("application_pre", "application_post"):
                unavailable = {
                    "source_id": source.binding["source_id"],
                    "availability": "unavailable",
                    "exclusion_reason": "application_frontier_not_in_qualified_phase_segment",
                    "alignment": direction,
                    "application_request_sequence": application.request_sequence,
                    "horizon_s": horizon,
                    "window_count": 0,
                    "phase_method": "unavailable",
                    "phase_epoch": "unavailable",
                    "source_file_sha256": source.binding["consumed_files"].get(
                        "csv/relative_phase_observations_v1.csv",
                        source.binding["consumed_files"]["csv/count_observations.csv"],
                    ),
                    "source_files_sha256_json": _measurement_provenance_json(
                        source.binding
                    ),
                }
                if location is None:
                    result.append(unavailable)
                    continue
                segment_index, index = location
                segment = segments[segment_index]
                start = index - horizon if direction == "application_pre" else index
                end = index + 1 if direction == "application_pre" else index + horizon + 1
                selected = segment[max(0, start) : min(len(segment), end)]
                if start < 0 or end > len(segment) or len(selected) != horizon + 1:
                    unavailable["exclusion_reason"] = "insufficient_complete_unjoined_horizon_support"
                    result.append(unavailable)
                else:
                    result.append(
                        _phase_window_record(
                            source,
                            selected,
                            horizon_s=horizon,
                            alignment=direction,
                            application=application,
                        )
                    )
    return result


def frequency_summary(
    source: SourceData, windows: list[dict[str, Any]], bands: Sequence[float]
) -> dict[str, Any]:
    summary_windows = [
        row
        for row in windows
        if row["availability"] == "available"
        and row["frequency_summary_eligible"] is True
    ]
    values = [float(row["frequency_error_hz"]) for row in summary_windows]
    absolute = [abs(value) for value in values]
    measurement_duration = sum(row.measurement_qualified for row in source.intervals)
    control_input_duration = sum(row.control_input_eligible for row in source.intervals)
    settled_duration = sum(row.settled_same_code for row in source.intervals)
    if not values:
        return {
            "source_id": source.binding["source_id"],
            "available": False,
            "reason": "no_complete_selected600_windows",
            "measurement_qualified_duration_s": measurement_duration,
            "control_input_eligible_duration_s": control_input_duration,
            "control_decision_eligible_duration_s": None,
            "control_decision_eligibility_state": "unavailable",
            "control_decision_eligibility_reason": (
                "historical_gnss_metadata_cadence_exceeds_freshness_bound"
            ),
            "settled_same_code_duration_s": settled_duration,
        }
    ordered = sorted(values)
    ordered_abs = sorted(absolute)

    def quantile(selected: list[float], fraction: float) -> float:
        position = fraction * (len(selected) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return selected[lower]
        weight = position - lower
        return selected[lower] * (1.0 - weight) + selected[upper] * weight

    return {
        "source_id": source.binding["source_id"],
        "available": True,
        "selected600_window_count": len(values),
        "rms_signed_frequency_error_hz": math.sqrt(
            statistics.fmean(value * value for value in values)
        ),
        "median_signed_frequency_error_hz": quantile(ordered, 0.5),
        "signed_quantiles_hz": {
            str(item): quantile(ordered, item) for item in (0.05, 0.5, 0.95, 0.99)
        },
        "absolute_quantiles_hz": {
            str(item): quantile(ordered_abs, item) for item in (0.5, 0.95, 0.99)
        },
        "maximum_absolute_frequency_error_hz": max(absolute),
        "common_band_occupancy": {
            str(band): sum(value <= band for value in absolute) / len(absolute)
            for band in bands
        },
        "measurement_qualified_duration_s": measurement_duration,
        "control_input_eligible_duration_s": control_input_duration,
        "control_decision_eligible_duration_s": None,
        "control_decision_eligibility_state": "unavailable",
        "control_decision_eligibility_reason": (
            "historical_gnss_metadata_cadence_exceeds_freshness_bound"
        ),
        "settled_same_code_duration_s": settled_duration,
        "excluded_duration_s": len(source.intervals) - measurement_duration,
        "historical_policy_state_occupancy": {
            state: sum(
                row.get("tight_state") == state for row in source.decisions
            )
            / len(source.decisions)
            for state in sorted(
                {row.get("tight_state", "unavailable") for row in source.decisions}
            )
        }
        if source.decisions
        else {"unavailable": 1.0},
    }


def _window_error(
    rows_by_sequence: dict[int, Interval],
    first_exclusive: int,
    last_inclusive: int,
    *,
    required_epoch: int | None,
    required_code: int | None,
) -> tuple[Fraction | None, str]:
    sequences = range(first_exclusive + 1, last_inclusive + 1)
    selected = [rows_by_sequence.get(sequence) for sequence in sequences]
    if len(selected) != 600:
        return None, "requested_window_not_600_intervals"
    if any(row is None for row in selected):
        return None, "d14_d8_continuity_break_or_missing_interval"
    exact = [row for row in selected if row is not None]
    if any(not row.measurement_qualified for row in exact):
        return None, "unqualified_d14_d8_interval"
    if any(row.dac_epoch != required_epoch or row.applied_code != required_code for row in exact):
        return None, "subsequent_application_or_dac_epoch_break"
    if any(
        row.session != exact[0].session
        or row.timer_domain != exact[0].timer_domain
        or row.capture_backend != exact[0].capture_backend
        for row in exact
    ):
        return None, "session_domain_or_backend_break"
    total = sum(row.counted_edges for row in exact)
    return Fraction(total, 600) - NOMINAL_FREQUENCY_HZ, ""


def response_horizons(
    source: SourceData, horizons_s: Sequence[int], settling_exclusion_s: int
) -> list[dict[str, Any]]:
    rows_by_sequence = {
        row.closing_reference_sequence: row
        for row in source.intervals
        if row.closing_reference_sequence >= 0
    }
    result: list[dict[str, Any]] = []
    maximum_sequence = max(rows_by_sequence, default=-1)
    for application in source.applications:
        epoch_rows = sorted(
            sequence
            for sequence, row in rows_by_sequence.items()
            if row.dac_epoch == application.dac_epoch
            and row.applied_code == application.applied_code
        )
        if not epoch_rows:
            application_frontier = application.source_last_sequence
        else:
            application_frontier = epoch_rows[0] - 1
        pre_epoch = rows_by_sequence.get(application_frontier)
        pre_error, pre_reason = _window_error(
            rows_by_sequence,
            application_frontier - 600,
            application_frontier,
            required_epoch=(pre_epoch.dac_epoch if pre_epoch is not None else None),
            required_code=(pre_epoch.applied_code if pre_epoch is not None else None),
        )
        for horizon in horizons_s:
            for estimand in (
                "trailing_selected600_at_horizon",
                "settled_selected600_at_horizon",
            ):
                base = {
                    "source_id": source.binding["source_id"],
                    "request_sequence": application.request_sequence,
                    "decision_sequence": application.decision_sequence,
                    "source_application_frontier": application_frontier,
                    "decision_timestamp_s": application.decision_timestamp_s,
                    "application_timestamp_s": application.application_timestamp_s,
                    "requested_delta_codes": application.requested_delta_codes,
                    "applied_code": application.applied_code,
                    "dac_epoch": application.dac_epoch,
                    "phase_materially_influenced": (
                        "unavailable"
                        if application.phase_materially_influenced is None
                        else str(application.phase_materially_influenced).lower()
                    ),
                    "estimand": estimand,
                    "requested_horizon_s": horizon,
                    "actual_horizon_s": "",
                    "source_file_sha256": application.transaction_source_sha256,
                    "source_files_sha256_json": _measurement_provenance_json(
                        source.binding, include_selected=True
                    ),
                }
                if pre_error is None:
                    result.append(
                        {
                            **base,
                            "availability": "unavailable",
                            "censor_reason": f"pre_application_support:{pre_reason}",
                        }
                    )
                    continue
                opening = application_frontier + horizon - 600
                closing = application_frontier + horizon
                if (
                    estimand == "settled_selected600_at_horizon"
                    and opening < application_frontier + settling_exclusion_s
                ):
                    result.append(
                        {
                            **base,
                            "availability": "unavailable",
                            "censor_reason": "settled_window_cannot_complete_by_requested_horizon",
                        }
                    )
                    continue
                if closing > maximum_sequence:
                    result.append(
                        {
                            **base,
                            "availability": "unavailable",
                            "censor_reason": "right_censored_at_terminal",
                        }
                    )
                    continue
                post_error, reason = _window_error(
                    rows_by_sequence,
                    opening,
                    closing,
                    required_epoch=application.dac_epoch,
                    required_code=application.applied_code,
                )
                if post_error is None:
                    result.append(
                        {
                            **base,
                            "availability": "unavailable",
                            "censor_reason": reason,
                        }
                    )
                    continue
                response = post_error - pre_error
                gain = response / application.requested_delta_codes
                pre = float(pre_error)
                post = float(post_error)
                observed = float(response)
                result.append(
                    {
                        **base,
                        "availability": "available",
                        "censor_reason": "",
                        "actual_horizon_s": closing - application_frontier,
                        "post_window_first_sequence": opening,
                        "post_window_last_sequence": closing,
                        "settling_transient_included": (
                            opening < application_frontier + settling_exclusion_s
                        ),
                        "pre_error_hz": pre,
                        "post_error_hz": post,
                        "signed_response_hz": observed,
                        "code_domain_gain_hz_per_code": float(gain),
                        "wrong_sign": float(gain) <= 0.0,
                        "near_resolution": abs(observed) <= 1.0 / 600.0,
                        "overshoot": abs(post) > abs(pre) and pre * post < 0.0,
                        "recovered_to_common_band": abs(post) <= 1.0 / 600.0,
                    }
                )
    return result


def _unwrap_domain_ticks(values: Sequence[int], domain_name: str) -> list[int]:
    """Unwrap one causally ordered modular timestamp sequence exactly once."""

    if not values:
        return []
    domain = time_domain(domain_name)
    if not domain.permits_rollover or domain.modulus_ticks is None:
        if any(current < previous for previous, current in zip(values, values[1:])):
            raise ValueError(f"illegal backward movement in {domain_name}")
        return list(values)
    result = [values[0]]
    for previous, current in zip(values, values[1:]):
        distance = (
            current - previous
            if current >= previous
            else domain.modulus_ticks - previous + current
        )
        maximum = domain.maximum_unambiguous_forward_ticks
        if maximum is not None and distance >= maximum:
            raise ValueError(f"ambiguous modular gap in {domain_name}")
        result.append(result[-1] + distance)
    return result


def environment_associations(
    source: SourceData,
    windows: list[dict[str, Any]],
    *,
    lags_s: Sequence[int],
    maximum_age_s: float,
) -> list[dict[str, Any]]:
    primary = [
        row
        for row in source.environment
        if row.get("source") == "sht4x"
        and row.get("role") == "vcocxo_near"
        and int(row.get("flags", "-1")) == 0
        and row.get("observation_domain") == "rp2040_timer0"
    ]
    pressure = [
        row
        for row in source.environment
        if row.get("source") == "bmp280"
        and row.get("role") == "pressure_reference"
        and int(row.get("flags", "-1")) == 0
        and row.get("observation_domain") == "rp2040_timer0"
    ]
    primary.sort(key=lambda row: int(row["env_seq"]))
    pressure.sort(key=lambda row: int(row["env_seq"]))
    primary_ticks = _unwrap_domain_ticks(
        [int(row["timestamp_ticks"]) for row in primary], "rp2040_timer0"
    )
    pressure_ticks = _unwrap_domain_ticks(
        [int(row["timestamp_ticks"]) for row in pressure], "rp2040_timer0"
    )
    ordered_intervals = sorted(
        source.intervals, key=lambda row: row.closing_reference_sequence
    )
    interval_ticks = _unwrap_domain_ticks(
        [row.closing_reference_timestamp_ticks for row in ordered_intervals],
        "rp2040_timer0",
    )
    unwrapped_interval_tick = {
        row.closing_reference_sequence: tick
        for row, tick in zip(ordered_intervals, interval_ticks)
    }

    def causal_sample(
        rows: list[dict[str, str]], ticks: list[int], target: int
    ) -> tuple[dict[str, str] | None, float | None]:
        index = bisect_left(ticks, target)
        if index >= len(ticks) or ticks[index] > target:
            index -= 1
        if index < 0:
            return None, None
        age = (target - ticks[index]) / 16_000_000.0
        if age < 0.0 or age > maximum_age_s:
            return None, age
        return rows[index], age

    result: list[dict[str, Any]] = []
    for window in windows:
        for lag in lags_s:
            frontier = int(window["source_last_sequence"])
            if frontier not in unwrapped_interval_tick:
                raise ValueError(
                    f"environment window frontier absent from normalized intervals: {frontier}"
                )
            target = unwrapped_interval_tick[frontier] - lag * 16_000_000
            sample, age = causal_sample(primary, primary_ticks, target)
            bmp, bmp_age = causal_sample(pressure, pressure_ticks, target)
            result.append(
                {
                    "source_id": source.binding["source_id"],
                    "window_sequence": window["window_sequence"],
                    "source_first_sequence": window["source_first_sequence"],
                    "source_last_sequence": window["source_last_sequence"],
                    "lag_s": lag,
                    "availability": "available" if sample is not None else "unavailable",
                    "exclusion_reason": (
                        "" if sample is not None else "missing_or_stale_sht4x_vcocxo_near"
                    ),
                    "environment_source": "sht4x",
                    "environment_role": "vcocxo_near",
                    "environment_sample_sequence": (
                        int(sample["env_seq"]) if sample is not None else ""
                    ),
                    "environment_timestamp_ticks": (
                        int(sample["timestamp_ticks"]) if sample is not None else ""
                    ),
                    "environment_timestamp_unwrapped_ticks": (
                        target - int(round(age * 16_000_000))
                        if sample is not None and age is not None
                        else ""
                    ),
                    "sample_age_s": age if age is not None else "",
                    "fresh": sample is not None,
                    "temperature_c": (
                        float(sample["temperature_c"]) if sample is not None else ""
                    ),
                    "relative_humidity_pct": (
                        float(sample["relative_humidity_pct"])
                        if sample is not None
                        else ""
                    ),
                    "bmp280_sample_sequence": int(bmp["env_seq"]) if bmp is not None else "",
                    "bmp280_source": "bmp280" if bmp is not None else "",
                    "bmp280_role": "pressure_reference" if bmp is not None else "",
                    "bmp280_sample_age_s": bmp_age if bmp_age is not None else "",
                    "bmp280_temperature_c": (
                        float(bmp["temperature_c"]) if bmp is not None else ""
                    ),
                    "bmp280_pressure_pa": (
                        float(bmp["pressure_pa"]) if bmp is not None else ""
                    ),
                    "frequency_error_hz": window["frequency_error_hz"],
                    "source_file_sha256": source.binding["consumed_files"][
                        "csv/environment.csv"
                    ],
                    "source_files_sha256_json": _source_provenance_json(
                        source.binding,
                        "csv/environment.csv",
                        "csv/estimates_v2.csv",
                        "csv/raw_events.csv",
                        "csv/pps_snapshots.csv",
                        "csv/count_observations.csv",
                    ),
                }
            )
    return result


def _linear_fit(
    points: Sequence[tuple[float, float]],
    *,
    minimum_samples: int,
    minimum_temperature_range_c: float,
) -> dict[str, Any]:
    if len(points) < minimum_samples:
        return {
            "available": False,
            "reason": "insufficient_samples",
            "sample_count": len(points),
            "minimum_samples": minimum_samples,
        }
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    temperature_range = max(xs) - min(xs)
    if temperature_range < minimum_temperature_range_c:
        return {
            "available": False,
            "reason": "insufficient_temperature_range",
            "sample_count": len(points),
            "temperature_range_c": temperature_range,
            "minimum_temperature_range_c": minimum_temperature_range_c,
        }
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator == 0.0:
        return {"available": False, "reason": "zero_covariate_range"}
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = numerator / denominator
    variance_y = sum((value - mean_y) ** 2 for value in ys)
    correlation = (
        numerator / math.sqrt(denominator * variance_y) if variance_y > 0 else None
    )
    return {
        "available": True,
        "sample_count": len(points),
        "temperature_range_c": max(xs) - min(xs),
        "frequency_range_hz": max(ys) - min(ys),
        "frequency_error_slope_hz_per_nearby_air_c": slope,
        "pearson_correlation": correlation,
    }


def environment_summary(
    source_id: str,
    associations: list[dict[str, Any]],
    lags_s: Sequence[int],
    *,
    minimum_samples: int,
    minimum_temperature_range_c: float,
) -> dict[str, Any]:
    by_lag: dict[str, Any] = {}
    for lag in lags_s:
        rows = [
            row
            for row in associations
            if row["lag_s"] == lag and row["availability"] == "available"
        ]
        points = [
            (float(row["temperature_c"]), float(row["frequency_error_hz"]))
            for row in rows
        ]
        by_lag[str(lag)] = _linear_fit(
            points,
            minimum_samples=minimum_samples,
            minimum_temperature_range_c=minimum_temperature_range_c,
        )
    temperatures = [
        float(row["temperature_c"])
        for row in associations
        if row["lag_s"] == 0 and row["availability"] == "available"
    ]
    humidities = [
        float(row["relative_humidity_pct"])
        for row in associations
        if row["lag_s"] == 0 and row["availability"] == "available"
    ]
    rate_rows = sorted(
        (
            row
            for row in associations
            if row["lag_s"] == 0 and row["availability"] == "available"
        ),
        key=lambda row: int(row["source_last_sequence"]),
    )
    rates = [
        (float(right["temperature_c"]) - float(left["temperature_c"]))
        / (int(right["source_last_sequence"]) - int(left["source_last_sequence"]))
        for left, right in zip(rate_rows, rate_rows[1:])
        if int(right["source_last_sequence"]) > int(left["source_last_sequence"])
    ]
    return {
        "source_id": source_id,
        "primary_covariate": "sht4x_vcocxo_near_valid_flags",
        "causal_authority": False,
        "nearby_air_temperature_range_c": (
            [min(temperatures), max(temperatures)] if temperatures else None
        ),
        "nearby_air_humidity_range_pct": (
            [min(humidities), max(humidities)] if humidities else None
        ),
        "lag_results": by_lag,
        "temperature_rate_c_per_s": (
            {
                "available": True,
                "sample_count": len(rates),
                "minimum": min(rates),
                "median": statistics.median(rates),
                "maximum": max(rates),
                "method": "finite_difference_between_causal_selected600_covariates",
            }
            if rates
            else {"available": False, "reason": "insufficient_contiguous_samples"}
        ),
        "secondary_covariate": "bmp280_pressure_reference_kept_separate",
        "secondary_available_association_count": sum(
            row.get("bmp280_role") == "pressure_reference"
            for row in associations
            if row["lag_s"] == 0
        ),
        "limitation": (
            "nearby-air association only; not an OCXO temperature coefficient, "
            "internal-state measurement, causal effect, or predictive authority"
        ),
    }


def environment_cross_campaign_consistency(
    summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Report a noncausal leave-one-campaign-out slope-sign diagnostic."""

    slopes = {
        source_id: value["lag_results"]["0"].get(
            "frequency_error_slope_hz_per_nearby_air_c"
        )
        for source_id, value in summaries.items()
        if value["lag_results"]["0"].get("available") is True
    }
    if len(slopes) < 3:
        return {
            "available": False,
            "reason": "fewer_than_three_campaign_level_lag0_fits",
            "causal_authority": False,
        }
    held_out = {}
    for source_id, slope in slopes.items():
        training = [value for other, value in slopes.items() if other != source_id]
        training_median = statistics.median(training)
        held_out[source_id] = {
            "held_out_slope_hz_per_c": slope,
            "training_median_slope_hz_per_c": training_median,
            "sign_consistent": slope * training_median > 0.0,
        }
    return {
        "available": True,
        "method": "leave_one_campaign_out_lag0_slope_sign_consistency",
        "held_out": held_out,
        "all_sign_consistent": all(row["sign_consistent"] for row in held_out.values()),
        "causal_authority": False,
        "limitation": "association-only diagnostic; not a plant or thermal model gate",
    }


def actuator_summary(source: SourceData) -> dict[str, Any]:
    applications = source.applications
    deltas = [item.requested_delta_codes for item in applications]
    path = sum(abs(value) for value in deltas)
    net = sum(deltas)
    directions = [1 if value > 0 else -1 for value in deltas]
    measurement_duration = sum(row.measurement_qualified for row in source.intervals)
    control_input_duration = sum(row.control_input_eligible for row in source.intervals)
    settled_duration = sum(row.settled_same_code for row in source.intervals)
    denominators = {
        "measurement_qualified": measurement_duration,
        "control_input_eligible": control_input_duration,
        "settled_same_code": settled_duration,
    }
    code_residence: dict[str, int] = {}
    for row in source.intervals:
        if row.measurement_qualified and row.applied_code is not None:
            code_residence[str(row.applied_code)] = code_residence.get(
                str(row.applied_code), 0
            ) + 1
    return {
        "source_id": source.binding["source_id"],
        "duration_denominators_s": denominators,
        "application_count": len(applications),
        "application_deltas_codes": deltas,
        "absolute_dac_path_codes": path,
        "net_movement_codes": net,
        "net_path_efficiency": abs(net) / path if path else None,
        "applications_per_named_duration_hour": {
            name: len(applications) / (duration / 3600.0) if duration else None
            for name, duration in denominators.items()
        },
        "path_codes_per_named_duration_hour": {
            name: path / (duration / 3600.0) if duration else None
            for name, duration in denominators.items()
        },
        "step_distribution_codes": sorted(deltas),
        "code_residence_s": code_residence,
        "direction_reversal_count": sum(
            left != right for left, right in zip(directions, directions[1:])
        ),
        "repeated_alternation": any(
            sum(left != right for left, right in zip(window, window[1:])) == 3
            for window in zip(
                directions,
                directions[1:],
                directions[2:],
                directions[3:],
            )
        ),
        "phase_material_application_count": sum(
            item.phase_materially_influenced is True for item in applications
        ),
        "frequency_only_or_phase_unavailable_application_count": sum(
            item.phase_materially_influenced is not True for item in applications
        ),
        "control_decision_eligibility_state": "unavailable",
        "control_decision_eligibility_reason": (
            "historical_gnss_metadata_cadence_exceeds_freshness_bound"
        ),
        "metadata_hold_duration_s": None,
        "metadata_hold_lost_control_opportunity_count": None,
        "metadata_hold_chronology_reason": (
            "historical_schema_cannot_reconstruct_transaction_aware_holds"
        ),
        "terminal_code": applications[-1].applied_code if applications else None,
        "formal_terminal": source.binding["terminal_attestation"],
        "code_domain_only_no_dac_voltage_claim": True,
    }


def exact_replays(sources: list[SourceData]) -> dict[str, Any]:
    """Dispatch each chronology through its own historically bound law."""

    from .active_hybrid_evidence_guard import replay_active_hybrid_history

    by_id = {source.binding["source_id"]: source for source in sources}
    fll = by_id["cx317_fll_baseline"]
    exit_gate = _read_object(fll.root / "reports/stage7_exit_gate.json")
    replay_checks = {
        item["identifier"]: item["passed"] for item in exit_gate.get("checks", [])
    }
    fll_exact = bool(
        exit_gate.get("status") == "pass"
        and replay_checks.get("raw_snapshot_count_parity") is True
        and replay_checks.get("estimator_host_firmware_parity") is True
        and replay_checks.get("controller_host_firmware_exact_replay") is True
        and replay_checks.get("exact_four_phase_cross_core_transactions") is True
    )
    result: dict[str, Any] = {
        "cx317_fll_baseline": {
            "claim_layer": "historical_exact",
            "replay_adapter": "historical_stage7_exit_gate_bound_replay_v1",
            "exact": fll_exact,
            "control_decision_count": len(
                exit_gate.get("controller_replay", {}).get("comparisons", [])
            ),
            "application_count": exit_gate.get("transactions", {}).get(
                "application_count"
            ),
            "application_deltas": [
                item["delta_codes"]
                for item in exit_gate.get("transactions", {}).get("corrections", [])
            ],
            "terminal_attestation_sha256": fll.binding["terminal_attestation"][
                "file_sha256"
            ],
            "source_files_sha256_json": _candidate_provenance_json(fll.binding),
        }
    }
    policy_paths = {
        "cx322_coherent": REPO_ROOT
        / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
        "attempt4_sustained": REPO_ROOT
        / "profiles/discipline/otis_sustained_hybrid_regulation_v1.json",
    }
    for source_id, policy_path in policy_paths.items():
        source = by_id[source_id]
        historical = source.binding["historical_identity"]
        replay = replay_active_hybrid_history(
            source.decisions,
            source.transactions,
            policy_path=policy_path,
            expected_run_identity=historical["run_identity"],
            expected_build_identity=historical["firmware_build_identity"],
            expected_profile_identity=historical["profile_identity"],
            expected_active_policy_sha256=historical["policy_sha256"],
            estimate_rows=source.estimates,
        )
        application_deltas = [
            int(row["requested_delta_codes"])
            for row in source.transactions
            if row.get("event") == "application"
        ]
        result[source_id] = {
            "claim_layer": "historical_exact",
            "replay_adapter": "active_hybrid_evidence_guard_v1",
            "exact": replay["exact"],
            "decision_count": replay["decision_count"],
            "phase_nonzero_decision_count": replay["phase_nonzero_decision_count"],
            "phase_material_decision_count": replay["phase_material_decision_count"],
            "completed_response_decision_sequences": replay[
                "completed_response_decision_sequences"
            ],
            "all_response_checkpoints_passed": replay[
                "all_response_checkpoints_passed"
            ],
            "application_deltas": application_deltas,
            "formal_physical_qualification_status": source.binding[
                "terminal_attestation"
            ]["status"],
            "scientific_terminal": source.binding["terminal_attestation"].get(
                "scientific_terminal"
            ),
            "source_files_sha256_json": _candidate_provenance_json(source.binding),
        }
    result["unchanged_cx322_on_cx322"] = {
        **result["cx322_coherent"],
        "claim_layer": "historical_exact",
        "calculation": "unchanged_cx322_request_law",
        "first_divergence_decision_sequence": None,
    }
    return result


def _round_half_away_float(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def unchanged_cx322_on_attempt4(source: SourceData) -> dict[str, Any]:
    """Apply the CX322 finite envelope to A4 as a labeled counterfactual."""

    current_code = 0xA83C
    applications = 0
    cumulative_path = 0
    comparisons: list[dict[str, Any]] = []
    file_provenance = _candidate_provenance_json(source.binding)
    divergence: int | None = None
    for row in source.decisions:
        historical = int(row["requested_delta_codes"])
        raw = float(row["raw_combined_delta_codes"])
        calculated = 0
        reason = "source_nonrequest_frontier"
        if historical != 0 or raw != 0.0:
            limited = min(21.0, max(-21.0, raw))
            calculated = _round_half_away_float(limited)
            calculated = min(0xAB00, max(0xA800, current_code + calculated)) - current_code
            if applications + (calculated != 0) > 4:
                calculated = 0
                reason = "cx322_four_application_envelope_exhausted"
            elif cumulative_path + abs(calculated) > 84:
                calculated = 0
                reason = "cx322_cumulative_path_envelope_exhausted"
            else:
                reason = "cx322_request_calculation"
        exact_so_far = divergence is None and calculated == historical
        comparisons.append(
            {
                "decision_sequence": int(row["decision_sequence"]),
                "claim_layer": (
                    "causal_one_step" if divergence is None else "modeled_continuation"
                ),
                "historical_sustained_delta_codes": historical,
                "counterfactual_cx322_delta_codes": calculated,
                "reason": reason,
                "exact_until_frontier": exact_so_far,
                "source_files_sha256_json": file_provenance,
            }
        )
        if divergence is None and calculated != historical:
            divergence = int(row["decision_sequence"])
            break
        if calculated != 0:
            applications += 1
            cumulative_path += abs(calculated)
            current_code += calculated
    return {
        "source_id": source.binding["source_id"],
        "policy_id": "cx322_unchanged",
        "claim_at_first_evaluated_frontier": "causal_one_step_counterfactual",
        "physical_claim": False,
        "first_divergence_decision_sequence": divergence,
        "comparisons_through_first_divergence": comparisons,
        "source_files_sha256_json": file_provenance,
        "never_rejoin_physical_claim": True,
    }


def validate_counterfactual_model(
    responses_by_source: dict[str, list[dict[str, Any]]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    gate = contract["counterfactual_model"]["held_out_validation"]
    selected: list[dict[str, Any]] = []
    for source_id in gate["sources"]:
        selected.extend(
            row
            for row in responses_by_source[source_id]
            if row["estimand"] == "settled_selected600_at_horizon"
            and row["requested_horizon_s"] == 1500
            and row["availability"] == "available"
        )
    gains = [float(row["code_domain_gain_hz_per_code"]) for row in selected]
    envelope = contract["controller_comparison"]["combined_demand_interval"][
        "positive_plant_gain_envelope_hz_per_code"
    ]
    nominal = float(envelope["nominal"])
    minimum = float(envelope["minimum"])
    maximum = float(envelope["maximum"])
    positive_fraction = (
        sum(value > 0.0 for value in gains) / len(gains) if gains else 0.0
    )
    coverage = (
        sum(minimum <= value <= maximum for value in gains) / len(gains)
        if gains
        else 0.0
    )
    median_error = (
        statistics.median(abs(value - nominal) for value in gains)
        if gains
        else None
    )
    checks = {
        "minimum_exact_settled_response_count": len(gains)
        >= gate["minimum_exact_settled_response_count"],
        "minimum_positive_direction_fraction": positive_fraction
        >= gate["minimum_positive_direction_fraction"],
        "maximum_median_absolute_gain_error_hz_per_code": (
            median_error is not None
            and median_error
            <= gate["maximum_median_absolute_gain_error_hz_per_code"]
        ),
        "minimum_gain_envelope_coverage_fraction": coverage
        >= gate["minimum_gain_envelope_coverage_fraction"],
    }
    return {
        "model_id": contract["counterfactual_model"]["model_id"],
        "valid_for_decision_bearing_continuation": all(checks.values()),
        "checks": checks,
        "exact_settled_response_count": len(gains),
        "positive_direction_fraction": positive_fraction,
        "gain_envelope_coverage_fraction": coverage,
        "median_absolute_gain_error_hz_per_code": median_error,
        "observed_gains_hz_per_code": gains,
        "consequence_on_failure": gate["invalidity"],
        "claim_boundary": (
            "held-out physical response validation of the frozen model only; "
            "no candidate post-divergence value is physical evidence"
        ),
    }


def _fraction_record(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": float(value),
    }


def _raw_component_increments(row: dict[str, str]) -> tuple[Fraction, Fraction]:
    """Allocate the retained full raw request back to its FLL/PLL terms."""

    total = Fraction(row["raw_combined_delta_codes"])
    combined = Fraction(row["combined_demand_hz"])
    if combined == 0:
        if total != 0:
            raise ValueError("nonzero raw demand has a zero combined-demand basis")
        return Fraction(0), Fraction(0)
    fll = total * Fraction(row["frequency_term_hz"]) / combined
    return fll, total - fll


def _persistence_observation(
    row: dict[str, str],
    *,
    gain_minimum: Fraction,
    gain_maximum: Fraction,
):
    from .adaptive_steering_offline import (
        DemandIntervalObservation,
        PersistenceIdentity,
        RationalInterval,
        combined_correction_demand_interval,
    )

    count = int(row["accumulated_edge_error_counts"])
    fll = RationalInterval(
        -Fraction(2 * count + 1, 1200),
        -Fraction(2 * count - 1, 1200),
    )
    pll_value = Fraction(row["phase_term_hz"])
    combined = combined_correction_demand_interval(
        fll,
        RationalInterval(pll_value, pll_value),
        positive_plant_gain=RationalInterval(gain_minimum, gain_maximum),
    )
    return DemandIntervalObservation(
        identity=PersistenceIdentity(
            capture_session=row["capture_session"],
            continuity_segment=f"{row['capture_session']}:{row['phase_epoch']}",
            applied_code=int(row["current_applied_code"]),
            dac_epoch=int(row["dac_epoch"]),
            phase_state_id=row["phase_epoch"],
        ),
        opening_frontier=int(row["source_first_sequence"]),
        closing_frontier=int(row["source_last_sequence"]),
        combined_demand=combined,
        qualified=True,
        settled=True,
        cadence_eligible=not _bool(row["cadence_limited"]),
    )


def _frequency_only_delta(
    state: Any,
    *,
    provenance: Any,
    decision_id: str,
    request_id: str,
    raw_fll: Fraction,
    limits: Any,
) -> int:
    """Apply the identical debt path after removing all PLL-origin demand."""

    from .adaptive_steering_offline import (
        CorrectionDebtState,
        DebtEvent,
        TaggedCorrectionDebt,
        evaluate_correction_debt,
    )

    fll_only = CorrectionDebtState(
        committed=TaggedCorrectionDebt(
            state.committed.fll_codes,
            Fraction(0),
            state.committed.provenance,
            "frequency_only_counterfactual",
        ),
        mode=state.mode,
        mode_reason=state.mode_reason,
    )
    transition = evaluate_correction_debt(
        fll_only,
        provenance=provenance,
        decision_id=f"{decision_id}:frequency_only",
        request_id=f"{request_id}:frequency_only",
        raw_fll_increment_codes=raw_fll,
        raw_pll_increment_codes=Fraction(0),
        limits=limits,
    )
    if transition.event is DebtEvent.REQUEST_PROPOSED:
        assert transition.proposal is not None
        return transition.proposal.integer_request_delta_codes
    return 0


def _changed_candidate_trace(
    source: SourceData,
    *,
    candidate: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Replay physical evidence exactly only through the first changed request."""

    from .adaptive_steering_offline import (
        DebtEvent,
        DebtLimits,
        DebtProvenance,
        advance_persistence,
        complete_debt_response,
        evaluate_correction_debt,
        initial_correction_debt,
        initial_persistence,
        mark_debt_proposal_accepted,
        commit_debt_application,
    )

    comparison = contract["controller_comparison"]
    debt_contract = comparison["debt"]
    gain = comparison["combined_demand_interval"][
        "positive_plant_gain_envelope_hz_per_code"
    ]
    limits = DebtLimits(
        minimum_code=debt_contract["range_minimum_code"],
        maximum_code=debt_contract["range_maximum_code"],
        maximum_step_codes=debt_contract["step_limit_codes"],
        maximum_abs_committed_debt_codes=Fraction(
            debt_contract["maximum_committed_absolute_codes"]
        ),
    )
    gain_minimum = Fraction(str(gain["minimum"]))
    gain_maximum = Fraction(str(gain["maximum"]))
    persistence_count = int(candidate["same_sign_persistence_count"])
    persistence = initial_persistence(persistence_count)
    applications_by_decision = {
        item.decision_sequence: item for item in source.applications
    }
    state = None
    trace: list[dict[str, Any]] = []
    file_provenance = _candidate_provenance_json(source.binding)
    divergence: dict[str, Any] | None = None
    application_count = 0
    cumulative_path = 0
    qualifying_reasons = {
        "phase_qualified_first_transaction_eligible",
        "first_phase_observation_recorded_and_tight_reacquired",
        "phase_material_request_ready",
        "combined_nonmaterial_request_ready",
        "zero_rounded_or_range_hold",
        "phase_direction_coherence_hold",
        "global_application_budget_hold",
        "prospective_low_efficiency_path",
    }
    evaluation_reasons = {
        "phase_material_request_ready",
        "combined_nonmaterial_request_ready",
        "zero_rounded_or_range_hold",
    }

    for row in source.decisions:
        reason = row["reason"]
        decision_sequence = int(row["decision_sequence"])
        persistence_reason = "not_a_qualified_persistence_frontier"
        persistence_sign = None
        if persistence_count > 1 and reason in qualifying_reasons:
            observation = _persistence_observation(
                row,
                gain_minimum=gain_minimum,
                gain_maximum=gain_maximum,
            )
            transition = advance_persistence(persistence, observation)
            persistence = transition.state
            persistence_reason = transition.reason
            persistence_sign = observation.combined_demand.sign.value

        historical_delta = int(row["requested_delta_codes"])
        if reason not in evaluation_reasons:
            continue

        current_code = int(row["current_applied_code"])
        dac_epoch = int(row["dac_epoch"])
        phase_epoch = row["phase_epoch"]
        phase_frontier = int(row["phase_observation_sequence"])
        provenance = DebtProvenance(
            policy_id=candidate["candidate_id"],
            plant_gain_id="cx322_positive_gain_envelope_v1",
            capture_session=row["capture_session"],
            estimator_id=(
                f"{row['frequency_estimator_sha256']}:"
                f"{row['phase_estimator_sha256']}"
            ),
            evidence_frontier=int(row["source_last_sequence"]),
            applied_code=current_code,
            dac_epoch=dac_epoch,
            phase_epoch=phase_epoch,
            phase_frontier=phase_frontier,
        )
        if state is None:
            initial_provenance = DebtProvenance(
                policy_id=provenance.policy_id,
                plant_gain_id=provenance.plant_gain_id,
                capture_session=provenance.capture_session,
                estimator_id=provenance.estimator_id,
                evidence_frontier=int(row["source_first_sequence"]) - 1,
                applied_code=current_code,
                dac_epoch=dac_epoch,
            )
            state = initial_correction_debt(initial_provenance)

        raw_fll, raw_pll = _raw_component_increments(row)
        candidate_delta = 0
        frequency_only_delta = 0
        transition_reason = reason
        debt_before = state.committed.total_codes
        debt_after = debt_before
        limit_reasons: Sequence[str] = ()

        if persistence_count > 1 and not persistence.satisfied:
            transition_reason = f"persistence_suppressed:{persistence_reason}"
        elif application_count >= 4 or cumulative_path >= 84:
            transition_reason = "cx322_finite_authority_exhausted_debt_frozen"
        else:
            decision_id = f"{source.binding['source_id']}:{decision_sequence}"
            request_id = f"{candidate['candidate_id']}:{decision_id}"
            transition = evaluate_correction_debt(
                state,
                provenance=provenance,
                decision_id=decision_id,
                request_id=request_id,
                raw_fll_increment_codes=raw_fll,
                raw_pll_increment_codes=raw_pll,
                limits=limits,
            )
            transition_reason = transition.reason
            limit_reasons = transition.limit_reasons
            frequency_only_delta = _frequency_only_delta(
                state,
                provenance=provenance,
                decision_id=decision_id,
                request_id=request_id,
                raw_fll=raw_fll,
                limits=limits,
            )
            if transition.event is DebtEvent.REQUEST_PROPOSED:
                assert transition.proposal is not None
                candidate_delta = transition.proposal.integer_request_delta_codes
                if candidate_delta * Fraction(row["phase_term_hz"]) < 0:
                    candidate_delta = 0
                    transition_reason = "phase_direction_coherence_hold"
                else:
                    state = transition.state
            elif transition.event is DebtEvent.DEBT_UPDATED_WITHOUT_REQUEST:
                state = transition.state
                debt_after = state.committed.total_codes
            else:
                transition_reason = f"nonactionable:{transition.reason}"

        record = {
            "source_id": source.binding["source_id"],
            "candidate_id": candidate["candidate_id"],
            "decision_sequence": decision_sequence,
            "source_first_sequence": int(row["source_first_sequence"]),
            "source_last_sequence": int(row["source_last_sequence"]),
            "claim_layer": "causal_one_step_counterfactual",
            "historical_delta_codes": historical_delta,
            "candidate_delta_codes": candidate_delta,
            "frequency_only_candidate_delta_codes": frequency_only_delta,
            "phase_materially_influenced": candidate_delta != frequency_only_delta,
            "raw_fll_increment_codes": _fraction_record(raw_fll),
            "raw_pll_increment_codes": _fraction_record(raw_pll),
            "committed_debt_before_codes": _fraction_record(debt_before),
            "committed_debt_after_zero_request_codes": _fraction_record(debt_after),
            "persistence_count": persistence.count,
            "persistence_sign": persistence_sign,
            "persistence_reason": persistence_reason,
            "transition_reason": transition_reason,
            "limit_reasons": list(limit_reasons),
            "physical_claim": False,
            "source_files_sha256_json": file_provenance,
        }
        trace.append(record)
        if candidate_delta != historical_delta:
            divergence = record
            break

        if candidate_delta != 0:
            application = applications_by_decision.get(decision_sequence)
            if application is None:
                raise ValueError(
                    f"historical application missing at matched candidate decision {decision_sequence}"
                )
            assert state is not None
            request_id = f"{candidate['candidate_id']}:{source.binding['source_id']}:{decision_sequence}"
            accepted = mark_debt_proposal_accepted(state, request_id)
            state = accepted.state
            committed = commit_debt_application(
                state,
                request_id=request_id,
                actual_applied_code=application.applied_code,
                actual_dac_epoch=application.dac_epoch,
                first_consumer_frontier=int(row["source_last_sequence"]) + 1,
            )
            state = committed.state
            completed = complete_debt_response(
                state,
                request_id=request_id,
                response_frontier=int(row["source_last_sequence"]) + 2,
            )
            state = completed.state
            application_count += 1
            cumulative_path += abs(candidate_delta)

    return {
        "source_id": source.binding["source_id"],
        "candidate_id": candidate["candidate_id"],
        "claim_layer": "causal_one_step_counterfactual_until_first_different_application",
        "physical_claim": False,
        "first_divergence_decision_sequence": (
            None if divergence is None else divergence["decision_sequence"]
        ),
        "first_divergence": divergence,
        "comparisons_through_first_divergence": trace,
        "source_files_sha256_json": file_provenance,
        "never_rejoin_physical_claim": True,
    }


def _first_divergence_sensitivity(
    trace: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    divergence = trace["first_divergence"]
    if divergence is None:
        return {
            "available": False,
            "reason": "no_application_divergence_in_retained_chronology",
        }
    code_difference = (
        divergence["candidate_delta_codes"] - divergence["historical_delta_codes"]
    )
    comparison = contract["controller_comparison"]["combined_demand_interval"]
    gain_values = comparison["positive_plant_gain_envelope_hz_per_code"]
    residual_values = contract["counterfactual_model"]["residual_cases_hz"]
    cases: list[dict[str, Any]] = []
    for gain_name in contract["counterfactual_model"]["gain_cases"]:
        gain_value = float(gain_values[gain_name])
        for residual_name, residual_hz in residual_values.items():
            delta_frequency = gain_value * code_difference + float(residual_hz)
            cases.append(
                {
                    "gain_case": gain_name,
                    "residual_case": residual_name,
                    "candidate_minus_historical_code": code_difference,
                    "first_600s_frequency_difference_hz": delta_frequency,
                    "first_600s_phase_difference_cycles": delta_frequency * 600.0,
                    "claim_layer": "model_sensitivity_only",
                    "physical_claim": False,
                }
            )
    return {
        "available": True,
        "model_id": contract["counterfactual_model"]["model_id"],
        "initialization": contract["counterfactual_model"]["divergence_state"],
        "frequency_equation": contract["counterfactual_model"]["frequency_equation"],
        "phase_equation": contract["counterfactual_model"]["phase_equation"],
        "decision_bearing": False,
        "cases": cases,
    }


def candidate_comparison(
    *,
    sources: list[SourceData],
    contract: dict[str, Any],
    model_validation: dict[str, Any],
    own_law_exact: bool,
    generation_utc: str,
    tool_sha256: str,
    tool_files_sha256: dict[str, str],
    tool_bundle_sha256: str,
) -> dict[str, Any]:
    by_id = {source.binding["source_id"]: source for source in sources}
    candidates: list[dict[str, Any]] = []
    for definition in contract["controller_comparison"]["candidates"]:
        candidate_id = definition["candidate_id"]
        if not definition["debt"]:
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "role": "baseline",
                    "cx322_exact_replay": own_law_exact,
                    "attempt4_counterfactual": unchanged_cx322_on_attempt4(
                        by_id["attempt4_sustained"]
                    ),
                    "selection_status": "provisionally_retained",
                }
            )
            continue
        traces = {
            source_id: _changed_candidate_trace(
                by_id[source_id], candidate=definition, contract=contract
            )
            for source_id in ("cx322_coherent", "attempt4_sustained")
        }
        sensitivity = {
            source_id: _first_divergence_sensitivity(trace, contract)
            for source_id, trace in traces.items()
        }
        model_valid = model_validation["valid_for_decision_bearing_continuation"]
        continuation_cases = [
            {
                "source_id": source_id,
                "gain_case": gain_name,
                "residual_case": residual_name,
                "availability": "unavailable",
                "execution_state": "not_executed",
                "reason": (
                    "held_out_static_model_invalid_blocks_decision_bearing_continuation"
                    if not model_valid
                    else "all_case_continuation_not_implemented"
                ),
                "frequency_metrics": None,
                "phase_metrics": None,
                "actuator_metrics": None,
                "physical_claim": False,
            }
            for source_id in ("cx322_coherent", "attempt4_sustained")
            for gain_name in contract["counterfactual_model"]["gain_cases"]
            for residual_name in contract["counterfactual_model"]["residual_cases_hz"]
        ]
        gates = {
            "own_law_exact_replay": own_law_exact,
            "static_model_held_out_validation": model_valid,
            "all_gain_and_residual_case_metrics_available": "not_evaluated",
            "frequency_no_worse": "not_evaluated",
            "phase_no_worse": "not_evaluated",
            "actuator_no_worse": "not_evaluated",
            "material_frequency_phase_and_actuator_improvement": "not_evaluated",
            "runtime_identity_safety_range_cadence_transaction_perturbations": (
                "covered_by_deterministic_host_test_suite"
            ),
        }
        candidates.append(
            {
                "candidate_id": candidate_id,
                "role": "minimal_changed_candidate",
                "traces": traces,
                "post_divergence_model_sensitivity": sensitivity,
                "model_decision_bearing": model_valid,
                "all_case_continuation": {
                    "availability": "unavailable",
                    "execution_state": "not_executed",
                    "reason": (
                        "held_out_static_model_invalid"
                        if not model_valid
                        else "continuation_engine_unavailable"
                    ),
                    "required_case_count": len(continuation_cases),
                    "generated_continuation_row_count": 0,
                    "cases": continuation_cases,
                },
                "selection_gates": gates,
                "clears_frozen_selection_rule": False,
                "selection_status": (
                    "not_selectable_model_invalid_sensitivity_only"
                    if not model_valid
                    else "not_selectable_incomplete_all_case_no_worse_evidence"
                ),
            }
        )

    if not own_law_exact:
        terminal = "study_invalid_due_to_evidence_or_replay_mismatch"
        recommendation = "none_study_invalid"
    else:
        terminal = "provisional_cx322_unchanged_pending_d9_gate"
        recommendation = "cx322_unchanged"
    result = {
        "schema_version": 2,
        "report_type": "adaptive_steering_candidate_comparison_v2",
        "contract_sha256": contract["contract_sha256"],
        "analysis_base_revision": contract["analysis_base_revision"],
        "tool_file_sha256": tool_sha256,
        "analysis_tool_files_sha256": tool_files_sha256,
        "analysis_tool_bundle_sha256": tool_bundle_sha256,
        "generation_utc": generation_utc,
        "baseline": contract["controller_comparison"]["baseline"],
        "model_validation": model_validation,
        "source_files_sha256": {
            source_id: dict(sorted(source.binding["consumed_files"].items()))
            for source_id, source in by_id.items()
        },
        "candidates": candidates,
        "provisional_recommendation": recommendation,
        "terminal": terminal,
        "later_gate": (
            "D9 waveform and frequency-only FLL-output soak; may confirm or block "
            "integration but may not retune a rejected candidate"
        ),
    }
    return _with_semantic_digest(result, "report_sha256")


def stability_results(
    source: SourceData,
    *,
    tau_grid_s: Sequence[int],
    minimum_term_count: int,
) -> list[dict[str, Any]]:
    """Compute exact-term OADEV/OHDEV without joining segment endpoints."""

    from .adaptive_steering_offline import (
        InsufficientDeviationSupport,
        overlapping_allan_deviation,
        overlapping_hadamard_deviation,
        pool_deviation_estimates,
    )

    populations = {
        "whole_controller_unjoined_phase_epoch": _contiguous_segments(
            source.intervals,
            keys=(
                "session",
                "timer_domain",
                "capture_backend",
                "phase_method",
                "phase_epoch",
            ),
            require_phase=True,
        ),
        "settled_same_code": _contiguous_segments(
            source.intervals,
            keys=(
                "session",
                "timer_domain",
                "capture_backend",
                "phase_method",
                "phase_epoch",
                "dac_epoch",
                "applied_code",
            ),
            require_phase=True,
            require_settled=True,
        ),
    }
    functions = {
        "overlapping_allan_deviation": overlapping_allan_deviation,
        "overlapping_hadamard_deviation": overlapping_hadamard_deviation,
    }
    rows: list[dict[str, Any]] = []
    for population, segments in populations.items():
        for tau in tau_grid_s:
            for statistic, function in functions.items():
                estimates = []
                for segment_sequence, segment in enumerate(segments, start=1):
                    base = {
                        "source_id": source.binding["source_id"],
                        "population": population,
                        "population_identity": (
                            f"{source.binding['source_id']}:{population}:segment:{segment_sequence}"
                        ),
                        "statistic": statistic,
                        "estimator_definition": (
                            "overlapping_block_average_fractional_frequency_difference"
                        ),
                        "tau_s": tau,
                        "base_sampling_interval_s": 1,
                        "overlap_policy": "fully_overlapping_within_segment_only",
                        "detrending": "none",
                        "segment_sequence": segment_sequence,
                        "segment_count": 1,
                        "source_first_sequence": segment[0].opening_reference_sequence,
                        "source_last_sequence": segment[-1].closing_reference_sequence,
                        "source_file_sha256": source.binding["consumed_files"][
                            "csv/count_observations.csv"
                        ],
                        "source_files_sha256_json": _measurement_provenance_json(
                            source.binding
                        ),
                    }
                    try:
                        estimate = function(
                            [row.fractional_frequency for row in segment],
                            averaging_factor=tau,
                            base_sampling_interval=1,
                            minimum_term_count=minimum_term_count,
                        )
                    except InsufficientDeviationSupport as exc:
                        rows.append(
                            {
                                **base,
                                "availability": "unavailable",
                                "exclusion_reason": "insufficient_difference_term_count",
                                "sample_count": exc.sample_count,
                                "difference_term_count": exc.term_count,
                                "minimum_difference_term_count": exc.minimum_term_count,
                            }
                        )
                        continue
                    estimates.append(estimate)
                    rows.append(
                        {
                            **base,
                            "availability": "available",
                            "exclusion_reason": "",
                            "sample_count": estimate.sample_count,
                            "difference_term_count": estimate.term_count,
                            "minimum_difference_term_count": minimum_term_count,
                            "squared_difference_sum_numerator": (
                                estimate.squared_difference_sum.numerator
                            ),
                            "squared_difference_sum_denominator": (
                                estimate.squared_difference_sum.denominator
                            ),
                            "fractional_frequency_deviation": estimate.deviation,
                            "ten_mhz_equivalent_hz": estimate.equivalent_hz(),
                            "quantization_reference_calibration_limitation": (
                                "empirical D8-relative-to-D14 result; receiver sawtooth, "
                                "reference calibration, cable delay and complete uncertainty unavailable"
                            ),
                        }
                    )
                if estimates:
                    pooled = pool_deviation_estimates(estimates)
                    rows.append(
                        {
                            "source_id": source.binding["source_id"],
                            "population": population,
                            "population_identity": (
                                f"{source.binding['source_id']}:{population}:pooled"
                            ),
                            "statistic": statistic,
                            "estimator_definition": (
                                "term_count_weighted_pooled_squared_difference_numerator"
                            ),
                            "tau_s": tau,
                            "base_sampling_interval_s": 1,
                            "overlap_policy": "overlap_within_segments_never_stitch_endpoints",
                            "detrending": "none",
                            "segment_sequence": "pooled",
                            "segment_count": len(estimates),
                            "availability": "available",
                            "exclusion_reason": "",
                            "sample_count": pooled.sample_count,
                            "difference_term_count": pooled.term_count,
                            "minimum_difference_term_count": minimum_term_count,
                            "squared_difference_sum_numerator": (
                                pooled.squared_difference_sum.numerator
                            ),
                            "squared_difference_sum_denominator": (
                                pooled.squared_difference_sum.denominator
                            ),
                            "fractional_frequency_deviation": pooled.deviation,
                            "ten_mhz_equivalent_hz": pooled.equivalent_hz(),
                            "source_first_sequence": "multiple_unjoined",
                            "source_last_sequence": "multiple_unjoined",
                            "source_file_sha256": source.binding["consumed_files"][
                                "csv/count_observations.csv"
                            ],
                            "source_files_sha256_json": _measurement_provenance_json(
                                source.binding
                            ),
                            "quantization_reference_calibration_limitation": (
                                "empirical D8-relative-to-D14 result; receiver sawtooth, "
                                "reference calibration, cable delay and complete uncertainty unavailable"
                            ),
                        }
                    )
    return rows


def _with_semantic_digest(value: dict[str, Any], field: str) -> dict[str, Any]:
    unsigned = {key: item for key, item in value.items() if key != field}
    return {**unsigned, field: canonical_sha256(unsigned)}


def _bound_rows(
    rows: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    generation_utc: str,
    tool_sha256: str,
    tool_bundle_sha256: str,
) -> list[dict[str, Any]]:
    common = {
        "contract_sha256": contract["contract_sha256"],
        "analysis_base_revision": contract["analysis_base_revision"],
        "tool_id": TOOL_ID,
        "tool_file_sha256": tool_sha256,
        "analysis_tool_bundle_sha256": tool_bundle_sha256,
        "generation_utc": generation_utc,
    }
    return [{**common, **row} for row in rows]


def _interval_rows(intervals: Iterable[Interval]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for interval in intervals:
        value = asdict(interval)
        fractional = interval.fractional_frequency
        value.pop("fractional_frequency")
        value["fractional_frequency_numerator"] = fractional.numerator
        value["fractional_frequency_denominator"] = fractional.denominator
        value["fractional_frequency"] = float(fractional)
        value["availability"] = (
            "available" if interval.measurement_qualified else "unavailable"
        )
        value["exclusion_reason"] = interval.measurement_exclusion_reason
        result.append(value)
    return result


def _transaction_rows(source: SourceData) -> list[dict[str, Any]]:
    source_hash = source.binding["consumed_files"]["csv/active_transactions_v1.csv"]
    provenance = _source_provenance_json(
        source.binding, "csv/active_transactions_v1.csv"
    )
    return [
        {
            "source_id": source.binding["source_id"],
            "availability": "available",
            "exclusion_reason": "",
            "source_file_sha256": source_hash,
            "source_files_sha256_json": provenance,
            **row,
        }
        for row in source.transactions
    ]


def _episode_rows(source: SourceData) -> list[dict[str, Any]]:
    attestation = source.binding["terminal_attestation"]
    provenance_paths = ["csv/active_transactions_v1.csv"]
    if source.decisions:
        provenance_paths.append("csv/active_hybrid_decisions_v1.csv")
    if "csv/health.csv" in source.binding["consumed_files"]:
        provenance_paths.append("csv/health.csv")
    provenance = _source_provenance_json(source.binding, *provenance_paths)
    rows: list[dict[str, Any]] = [
        {
            "source_id": source.binding["source_id"],
            "episode_type": "gnss_serial_metadata_hold_chronology",
            "availability": "unavailable",
            "exclusion_reason": (
                "historical_schema_and_metadata_cadence_cannot_reconstruct_"
                "transaction_aware_hold_intervals"
            ),
            "control_decision_eligibility_state": "unavailable",
            "hold_or_degraded_reason": "metadata_chronology_unavailable",
            "duration_s": "",
            "lost_control_opportunity_count": "",
            "source_file_sha256": source.binding["consumed_files"].get(
                "csv/health.csv", "unavailable"
            ),
            "source_files_sha256_json": provenance,
        }
    ]
    rows.extend(
        {
            "source_id": source.binding["source_id"],
            "episode_type": "recorded_controller_decision_window",
            "availability": "available",
            "exclusion_reason": "",
            "control_decision_eligibility_state": "unavailable",
            "control_decision_eligibility_reason": (
                "historical_gnss_metadata_cadence_exceeds_freshness_bound"
            ),
            "hold_or_degraded_reason": decision.get("reason", "unavailable"),
            "duration_s": (
                int(decision["source_last_sequence"])
                - int(decision["source_first_sequence"])
            ),
            "lost_control_opportunity_count": "",
            "decision_sequence": int(decision["decision_sequence"]),
            "state_before": decision.get("state_before", "unavailable"),
            "state_after": decision.get("state_after", "unavailable"),
            "authority_state": decision.get("authority_state", "unavailable"),
            "source_file_sha256": source.binding["consumed_files"][
                "csv/active_hybrid_decisions_v1.csv"
            ],
            "source_files_sha256_json": provenance,
        }
        for decision in source.decisions
    )
    rows.append(
        {
            "source_id": source.binding["source_id"],
            "episode_type": "acquisition_and_scientific_terminal",
            "availability": "available",
            "exclusion_reason": "",
            "control_decision_eligibility_state": "not_applicable",
            "hold_or_degraded_reason": "terminal_attestation_not_hold_chronology",
            "duration_s": "",
            "lost_control_opportunity_count": "",
            "acquisition_terminal": attestation.get("acquisition_terminal", "not_retained"),
            "scientific_terminal": attestation.get("scientific_terminal", "not_retained"),
            "formal_status": attestation["status"],
            "source_file_sha256": attestation["file_sha256"],
            "source_files_sha256_json": json.dumps(
                {attestation["path"]: attestation["file_sha256"]},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], *, gzip_output: bool = False) -> None:
    if path.exists():
        raise FileExistsError(path)
    field_set = {field for row in rows for field in row}
    preferred = [
        "contract_sha256",
        "analysis_base_revision",
        "tool_id",
        "tool_file_sha256",
        "generation_utc",
        "source_id",
        "availability",
        "exclusion_reason",
    ]
    fields = [field for field in preferred if field in field_set]
    fields.extend(sorted(field_set - set(fields)))
    opener = gzip.open if gzip_output else open
    with opener(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _post_source_identities(
    sources: list[SourceData], pre: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = source.binding["source_id"]
        identity = package_identity(source.root)
        post = {
            key: identity[key] for key in ("content_sha256", "file_count", "total_bytes")
        }
        result[source_id] = {
            "pre": pre[source_id],
            "post": post,
            "exact": pre[source_id] == post,
            "files_added": post["file_count"] - pre[source_id]["file_count"],
            "bytes_changed": post["total_bytes"] - pre[source_id]["total_bytes"],
        }
        if pre[source_id] != post:
            raise ValueError(f"immutable source changed during analysis: {source_id}")
    return result


def _artifact_record(path: Path, row_count: int | None) -> dict[str, Any]:
    return {
        "path": path.name,
        "sha256": file_sha256(path),
        "size_bytes": path.stat().st_size,
        "row_count": row_count,
    }


def run_study(
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    evidence_repository: Path,
    output_dir: Path = DEFAULT_OUTPUT,
    tracked_report_path: Path | None = DEFAULT_TRACKED_REPORT,
) -> tuple[Path, dict[str, Any]]:
    contract = load_analysis_contract(contract_path)
    evidence_repository = evidence_repository.expanduser().resolve()
    source_roots = [
        (evidence_repository / source["logical_package_path"]).resolve()
        for source in contract["sources"]
    ]
    output = validate_output_location(output_dir, source_roots)
    output.parent.mkdir(parents=True, exist_ok=True)
    tool_sha = file_sha256(Path(__file__))
    tool_files_sha256 = {
        relative_path: file_sha256(REPO_ROOT / relative_path)
        for relative_path in ANALYSIS_TOOL_RELATIVE_PATHS
    }
    tool_bundle_sha256 = canonical_sha256(tool_files_sha256)
    generation_utc = _utc_now()

    ledger, pre_identities = validate_sources(contract, evidence_repository)
    sources = load_source_data(contract, evidence_repository)
    selected_by_source = {
        source.binding["source_id"]: selected_frequency_windows(source)
        for source in sources
    }
    phase_by_source = {
        source.binding["source_id"]: phase_windows(
            source, contract["phase_analysis"]["horizons_s"]
        )
        for source in sources
    }
    stability_by_source = {
        source.binding["source_id"]: stability_results(
            source,
            tau_grid_s=contract["stability_analysis"]["tau_grid_s"],
            minimum_term_count=contract["stability_analysis"][
                "minimum_difference_term_count"
            ],
        )
        for source in sources
    }
    responses_by_source = {
        source.binding["source_id"]: response_horizons(
            source,
            contract["response_analysis"]["horizons_s"],
            contract["response_analysis"]["settling_exclusion_s"],
        )
        for source in sources
    }
    environment_by_source = {
        source.binding["source_id"]: environment_associations(
            source,
            selected_by_source[source.binding["source_id"]],
            lags_s=contract["environment_analysis"]["lags_s"],
            maximum_age_s=contract["environment_analysis"]["maximum_sample_age_s"],
        )
        for source in sources
    }
    frequency_summaries = {
        source.binding["source_id"]: frequency_summary(
            source,
            selected_by_source[source.binding["source_id"]],
            contract["selected_frequency_analysis"]["common_bands_absolute_hz"],
        )
        for source in sources
    }
    environment_summaries = {
        source.binding["source_id"]: environment_summary(
            source.binding["source_id"],
            environment_by_source[source.binding["source_id"]],
            contract["environment_analysis"]["lags_s"],
            minimum_samples=contract["environment_analysis"]["minimum_samples"],
            minimum_temperature_range_c=contract["environment_analysis"][
                "minimum_temperature_range_c"
            ],
        )
        for source in sources
    }
    environment_consistency = environment_cross_campaign_consistency(
        environment_summaries
    )
    actuator_summaries = {
        source.binding["source_id"]: actuator_summary(source) for source in sources
    }
    replays = exact_replays(sources)
    own_law_exact = all(
        replays[source_id]["exact"]
        for source_id in (
            "cx317_fll_baseline",
            "cx322_coherent",
            "attempt4_sustained",
            "unchanged_cx322_on_cx322",
        )
    )
    if not own_law_exact:
        study_terminal = "study_invalid_due_to_evidence_or_replay_mismatch"
    else:
        study_terminal = "provisional_cx322_unchanged_pending_d9_gate"
    attempt4 = next(
        source for source in sources if source.binding["source_id"] == "attempt4_sustained"
    )
    replay_and_divergence: dict[str, Any] = {
        "schema_version": 2,
        "report_type": "adaptive_steering_replay_and_divergence_v2",
        "contract_sha256": contract["contract_sha256"],
        "analysis_base_revision": contract["analysis_base_revision"],
        "tool_file_sha256": tool_sha,
        "analysis_tool_files_sha256": tool_files_sha256,
        "analysis_tool_bundle_sha256": tool_bundle_sha256,
        "generation_utc": generation_utc,
        "source_files_sha256": {
            source.binding["source_id"]: dict(
                sorted(source.binding["consumed_files"].items())
            )
            for source in sources
        },
        "own_law_replays": replays,
        "cx322_on_attempt4": unchanged_cx322_on_attempt4(attempt4),
    }
    replay_and_divergence = _with_semantic_digest(
        replay_and_divergence, "report_sha256"
    )
    model_validation = validate_counterfactual_model(responses_by_source, contract)
    candidate = candidate_comparison(
        sources=sources,
        contract=contract,
        model_validation=model_validation,
        own_law_exact=own_law_exact,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_files_sha256=tool_files_sha256,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    study_terminal = candidate["terminal"]

    source_immutability = _post_source_identities(sources, pre_identities)
    if not all(item["exact"] for item in source_immutability.values()):
        raise ValueError("source immutability proof failed")

    source_ledger = _with_semantic_digest(
        {
            "schema_version": 2,
            "report_type": "adaptive_steering_source_ledger_v2",
            "contract_sha256": contract["contract_sha256"],
            "analysis_base_revision": contract["analysis_base_revision"],
            "tool_file_sha256": tool_sha,
            "analysis_tool_files_sha256": tool_files_sha256,
            "analysis_tool_bundle_sha256": tool_bundle_sha256,
            "generation_utc": generation_utc,
            "sources": ledger,
            "explicit_source_exclusions": contract["explicit_source_exclusions"],
            "source_immutability": source_immutability,
        },
        "ledger_sha256",
    )

    interval_rows = _bound_rows(
        _interval_rows(
            interval for source in sources for interval in source.intervals
        ),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    selected_rows = _bound_rows(
        (row for rows in selected_by_source.values() for row in rows),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    phase_rows = _bound_rows(
        (row for rows in phase_by_source.values() for row in rows),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    stability_rows = _bound_rows(
        (row for rows in stability_by_source.values() for row in rows),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    transaction_rows = _bound_rows(
        (row for source in sources for row in _transaction_rows(source)),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    response_rows = _bound_rows(
        (row for rows in responses_by_source.values() for row in rows),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    episode_rows = _bound_rows(
        (row for source in sources for row in _episode_rows(source)),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )
    environment_rows = _bound_rows(
        (row for rows in environment_by_source.values() for row in rows),
        contract=contract,
        generation_utc=generation_utc,
        tool_sha256=tool_sha,
        tool_bundle_sha256=tool_bundle_sha256,
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        _write_json(temporary / "source_ledger_v2.json", source_ledger)
        _write_csv(
            temporary / "qualified_intervals_v2.csv.gz",
            interval_rows,
            gzip_output=True,
        )
        _write_csv(temporary / "selected_windows_v2.csv", selected_rows)
        _write_csv(temporary / "phase_windows_v2.csv", phase_rows)
        _write_csv(temporary / "stability_v2.csv", stability_rows)
        _write_csv(temporary / "actuator_transactions_v2.csv", transaction_rows)
        _write_csv(temporary / "response_horizons_v2.csv", response_rows)
        _write_csv(temporary / "controller_episodes_v2.csv", episode_rows)
        _write_csv(
            temporary / "environment_associations_v2.csv", environment_rows
        )
        _write_json(
            temporary / "replay_and_divergence_v2.json", replay_and_divergence
        )
        _write_json(temporary / "candidate_comparison_v2.json", candidate)
        row_counts = {
            "source_ledger_v2.json": len(ledger),
            "qualified_intervals_v2.csv.gz": len(interval_rows),
            "selected_windows_v2.csv": len(selected_rows),
            "phase_windows_v2.csv": len(phase_rows),
            "stability_v2.csv": len(stability_rows),
            "actuator_transactions_v2.csv": len(transaction_rows),
            "response_horizons_v2.csv": len(response_rows),
            "controller_episodes_v2.csv": len(episode_rows),
            "environment_associations_v2.csv": len(environment_rows),
            "replay_and_divergence_v2.json": None,
            "candidate_comparison_v2.json": None,
        }
        artifacts = [
            _artifact_record(temporary / name, row_count)
            for name, row_count in row_counts.items()
        ]
        package_manifest = _with_semantic_digest(
            {
                "schema_version": 2,
                "manifest_type": "adaptive_steering_derived_package_v2",
                "contract_sha256": contract["contract_sha256"],
                "analysis_base_revision": contract["analysis_base_revision"],
                "tool_id": TOOL_ID,
                "tool_file_sha256": tool_sha,
                "analysis_tool_files_sha256": tool_files_sha256,
                "analysis_tool_bundle_sha256": tool_bundle_sha256,
                "generation_utc": generation_utc,
                "source_file_sha256": {
                    source.binding["source_id"]: source.binding["consumed_files"]
                    for source in sources
                },
                "source_immutability": source_immutability,
                "artifacts": artifacts,
                "study_terminal": study_terminal,
            },
            "manifest_sha256",
        )
        _write_json(
            temporary / "derived_package_manifest_v2.json", package_manifest
        )
        os.replace(temporary, output)
    except Exception:
        # Preserve a failed temporary derived tree for diagnosis without ever
        # touching a source package.  It remains outside the semantic result.
        raise

    tracked_report = _with_semantic_digest(
        {
            "schema_version": 2,
            "report_type": "adaptive_steering_offline_study_report_v2",
            "contract_sha256": contract["contract_sha256"],
            "analysis_base_revision": contract["analysis_base_revision"],
            "tool_id": TOOL_ID,
            "tool_file_sha256": tool_sha,
            "analysis_tool_files_sha256": tool_files_sha256,
            "analysis_tool_bundle_sha256": tool_bundle_sha256,
            "generation_utc": generation_utc,
            "terminal": study_terminal,
            "derived_package_manifest_sha256": package_manifest["manifest_sha256"],
            "derived_artifacts": package_manifest["artifacts"],
            "source_ledger_sha256": source_ledger["ledger_sha256"],
            "source_immutability": source_immutability,
            "data_completeness_and_comparability": {
                source.binding["source_id"]: {
                    "interval_count": len(source.intervals),
                    "measurement_qualified_interval_count": sum(
                        row.measurement_qualified for row in source.intervals
                    ),
                    "phase_method": sorted(
                        {row.phase_method for row in source.intervals if row.phase_available}
                    ),
                    "selected600_window_count": len(
                        selected_by_source[source.binding["source_id"]]
                    ),
                    "selected600_frequency_summary_eligible_count": sum(
                        row["frequency_summary_eligible"]
                        for row in selected_by_source[source.binding["source_id"]]
                    ),
                    "application_count": len(source.applications),
                    "formal_status": source.binding["terminal_attestation"]["status"],
                    "comparable_roles": source.binding["allowed_roles"],
                    "exclusions": source.binding["explicit_exclusions"],
                }
                for source in sources
            },
            "frequency_results": frequency_summaries,
            "environment_results": environment_summaries,
            "environment_cross_campaign_consistency": environment_consistency,
            "actuator_results": actuator_summaries,
            "phase_result_artifact": "phase_windows_v2.csv",
            "stability_result_artifact": "stability_v2.csv",
            "response_result_artifact": "response_horizons_v2.csv",
            "own_law_replays": replays,
            "counterfactual_model_validation": model_validation,
            "candidate_decision": candidate["provisional_recommendation"],
            "operational_semantics_document": "OPERATIONAL_SEMANTICS.md",
            "historical_limitations": [
                "CX317 has no native relative-phase file; its phase is reconstructed from exact adjacent D14/D8 integer evidence.",
                "Attempt 4 remains a failed physical qualification while retaining a replayable scientific chronology.",
                "D8-relative-to-D14 stability is not UTC traceability, oscillator-only stability, calibrated accuracy, thermal causality, or delivered-output qualification.",
            ],
            "analyzer_defects_discovered": [
                "The historical response helper selected the first AHY decision after a target without proving a complete source window; the derived response table uses exact trailing and settled 600-second support.",
                "The historical targeted-characterization analyzer aggregated BMP280 temperatures while labeling the aggregate SHT41 nearby air; the derived view filters exact sht4x/vcocxo_near/flags and keeps BMP280 separate.",
                "Current live metadata handling combines GNSS metadata and D14/D8 health; the implementation map separates GNSS_METADATA_HOLD from authoritative measurement health.",
            ],
            "stop_boundary": (
                "offline source ledger, derived analysis, finite policy decision, "
                "operational semantics, deterministic host tests and firmware change map only"
            ),
            "next_authorized_gate": (
                "after the GNSS soak is stopped, finalized and sealed: integrate finalized UART changes, "
                "qualify D9/GPOUT0 and D6 in unchanged FLL, run the D9 waveform/frequency-only soak, "
                "then confirm or reject this provisional decision without retuning"
            ),
        },
        "report_sha256",
    )
    if tracked_report_path is not None:
        _atomic_new_json(tracked_report_path.resolve(), tracked_report)
    return output, tracked_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--evidence-repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tracked-report", type=Path, default=DEFAULT_TRACKED_REPORT)
    parser.add_argument("--no-tracked-report", action="store_true")
    args = parser.parse_args(argv)
    output, report = run_study(
        contract_path=args.contract,
        evidence_repository=args.evidence_repository,
        output_dir=args.output,
        tracked_report_path=None if args.no_tracked_report else args.tracked_report,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "terminal": report["terminal"],
                "report_sha256": report["report_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["terminal"] != "study_invalid_due_to_evidence_or_replay_mismatch" else 1


if __name__ == "__main__":
    raise SystemExit(main())
