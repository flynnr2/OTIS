"""Offline fail-closed analysis of a CX318 Stage 4 live-preview capture.

The analyzer never opens a serial device.  It reconstructs the selected phase
and hybrid engines from the captured SNP/CNT boundaries, compares every RPH,
PHE and HPR field, and proves that the run carried no DAC/active authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path, PurePosixPath
import argparse
import csv
import json
import math
import tempfile
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from .contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from .cx317_frequency_preview_live_analyze import _firmware_build_binding
from .phase_frequency_hybrid_preview import load_profile as load_hybrid_profile
from .reference_relative_phase_estimator import load_profile as load_phase_profile
from .selected_preview_firmware_parity import (
    NUMERIC_ABSOLUTE_FLOOR,
    REPO_ROOT,
    _boundaries,
    _host_outputs,
)
from .cx318_stage4_static_code_preflight import (
    validate_static_proof as _validate_setup_static_proof,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .service_plane_probe import HOST_MARKER_PREFIX


TOOL_VERSION = "cx318_stage4_live_analyze_v1"
EXPECTED_STAGE = "CX318_STAGE4_NONACTUATING_LIVE_PREVIEW"
EXPECTED_PROFILE = "cx318_stage4_nonactuating_preview"
EXPECTED_BACKEND = "pio_wait_cumulative_snapshot_dma_v1"
PHASE_SELECTED = REPO_ROOT / "profiles/estimators/cx318_relative_phase_selected_v1.json"
HYBRID_SELECTED = REPO_ROOT / "profiles/discipline/cx318_hybrid_preview_selected_v1.json"
FREQUENCY_SELECTED = REPO_ROOT / "profiles/estimators/cx317_pps_gated_selected_v1.json"
FIRMWARE_MATRIX = REPO_ROOT / "firmware/arduino/firmware_matrix.json"
DEFAULT_OUTPUT = Path("reports/cx318_stage4_live_analysis_v1.json")
MAX_MISMATCHES = 32
REQUIRED_ZERO_HEALTH = (
    ("capture", "dropped_count"),
    ("capture", "pps_count_boundary_dropped_count"),
    ("capture", "error_flags"),
    ("pps_gate", "boundary_ring_dropped_count"),
    ("pps_gate", "rejected_window_count"),
    ("pps_gate", "missing_pps_count"),
    ("pps_gate", "pps_interval_anomaly_count"),
    ("pps_gate", "count_saturated_count"),
    ("pps_gate", "boundary_sequence_gap_count"),
    ("pps_gate", "boundary_sequence_duplicate_count"),
    ("pps_gate", "boundary_overflow_count"),
    ("pps_gate", "counter_snapshot_invalid_count"),
    ("pps_gate", "association_loss_count"),
    ("pps_gate", "snapshot_overwrite_count"),
    ("pps_gate", "snapshot_continuity_loss_count"),
    ("pps_gate", "snapshot_pio_rxstall_count"),
    ("pps_gate", "snapshot_dma_error_count"),
    ("pps_gate", "snapshot_dma_stopped_count"),
    ("pps_gate", "physical_pps_missing_count"),
    ("pps_d14", "rejected_short_count"),
    ("pps_d14", "rejected_long_count"),
    ("pps_d10", "short_interval_count"),
    ("pps_d10", "buffer_overflow_count"),
)


@dataclass(frozen=True)
class Check:
    identifier: str
    passed: bool
    evidence: str


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _contract_path(manifest: Any, contract: str) -> Path:
    paths = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(paths) != 1:
        raise ValueError(f"expected exactly one {contract} artifact, got {len(paths)}")
    return paths[0]


def _validate_contracts(manifest: Any, paths: dict[str, Path]) -> list[Check]:
    contracts = (
        ("counts", "count_observations_v1"),
        ("snapshots", "pps_snapshots_v1"),
        ("health", "health_v1"),
        ("environment", "environment_v1"),
        ("dac", "dac_steps_v1"),
        ("active", "active_transactions_v1"),
        ("rph", "relative_phase_observations_v1"),
        ("phe", "phase_estimator_outputs_v1"),
        ("hpr", "hybrid_preview_decisions_v1"),
    )
    checks: list[Check] = []
    for name, contract in contracts:
        result = validate_csv(
            paths[name],
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        checks.append(
            Check(
                f"contract_{contract}",
                result.ok,
                f"{result.row_count} rows; "
                + ("valid" if result.ok else "; ".join(result.errors[:4])),
            )
        )
    return checks


def _latest_health(rows: Iterable[dict[str, str]]) -> dict[tuple[str, str], str]:
    latest: dict[tuple[str, str], str] = {}
    for row in rows:
        latest[(row["component"], row["status_key"])] = row["status_value"].strip()
    return latest


def _parse_code(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("DAC code cannot be Boolean")
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError("DAC code must be an integer or numeric string")
    return int(value.rstrip("uU"), 0)


def _declared_minimum(value: Any, *, hard_minimum: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < hard_minimum:
        raise ValueError(f"{name} cannot weaken the fixed minimum {hard_minimum:g}")
    return parsed


def _safe_run_artifact(run_dir: Path, value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or not value:
        raise ValueError("evidence path must be a non-empty run-relative string")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value != relative.as_posix():
        raise ValueError("evidence path must be normalized and run-relative")
    path = run_dir
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("evidence path must not traverse a symbolic link")
    return value, path


def _safe_repo_artifact(value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or not value:
        raise ValueError("source run path must be a non-empty repository-relative string")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value != relative.as_posix():
        raise ValueError("source run path must be normalized and repository-relative")
    path = REPO_ROOT
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("source run path must not traverse a symbolic link")
    return value, path


def _validate_static_proof(proof: dict[str, Any]) -> tuple[int, int, str]:
    setup = _validate_setup_static_proof(proof)
    return setup.confirmed_code, setup.dac_epoch, setup.source_run_path


def _static_code_binding(run_dir: Path, manifest_data: dict[str, Any]) -> tuple[Check, dict[str, Any]]:
    try:
        live = manifest_data["stage4_live_preview"]
        code = _parse_code(live["static_code"])
        dac_epoch = int(live["dac_epoch"])
        evidence = live["static_code_evidence"]
        relative_path, evidence_path = _safe_run_artifact(run_dir, evidence["path"])
        actual_sha = _sha256_file(evidence_path)
        declared_sha = str(evidence["sha256"])
        proof = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(proof, dict):
            raise ValueError("static-code proof must be a JSON object")
        proof_code, proof_epoch, source_relative = _validate_static_proof(proof)
        comparisons = {
            "profile": live["profile_id"] == EXPECTED_PROFILE,
            "hard_range": 0xA800 <= code <= 0xAB00,
            "dac_epoch_nonnegative": dac_epoch >= 0,
            "evidence_sha256": actual_sha == declared_sha,
            "evidence_code": proof_code == code,
            "evidence_dac_epoch": proof_epoch == dac_epoch,
        }
        passed = all(comparisons.values())
        result = {
            "status": "pass" if passed else "fail",
            "static_code": code,
            "static_code_hex": f"0x{code:04X}",
            "dac_epoch": dac_epoch,
            "evidence_path": relative_path,
            "evidence_sha256": actual_sha,
            "source_run_path": source_relative,
            "comparisons": comparisons,
        }
        failed = [name for name, ok in comparisons.items() if not ok]
        return (
            Check(
                "exact_static_code_binding",
                passed,
                f"code 0x{code:04X}, epoch {dac_epoch}; "
                + ("exact retained-code evidence" if passed else "failed: " + ", ".join(failed)),
            ),
            result,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return (
            Check("exact_static_code_binding", False, f"invalid or absent binding: {exc}"),
            {"status": "fail", "reason": str(exc)},
        )


def _validate_binding_chain(profile: dict[str, Any]) -> None:
    bindings = profile.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError(f"{profile.get('profile_id')} has no binding chain")
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"profile binding {name} is malformed")
        _, path = _safe_repo_artifact(binding.get("path"))
        if _sha256_file(path) != binding.get("sha256"):
            raise ValueError(f"profile binding {name} differs from its source")


def _selected_profile_contract() -> tuple[Check, dict[str, Any]]:
    try:
        phase = json.loads(PHASE_SELECTED.read_text(encoding="utf-8"))
        hybrid = json.loads(HYBRID_SELECTED.read_text(encoding="utf-8"))
        frequency = json.loads(FREQUENCY_SELECTED.read_text(encoding="utf-8"))
        for profile, schema_name in (
            (phase, "cx318_relative_phase_selected_v1.schema.json"),
            (hybrid, "cx318_hybrid_preview_selected_v1.schema.json"),
        ):
            schema = json.loads((REPO_ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(profile)
            _validate_binding_chain(profile)
        phase_selection = phase["selection"]
        hybrid_selection = hybrid["selection"]
        frequency_policy = frequency["authoritative_policy"]
        comparisons = {
            "phase_profile_id": phase["profile_id"] == "cx318_relative_phase_selected_v1",
            "phase_method": phase_selection["raw_phase_method"] == "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
            "phase_frequency_method": phase_selection["frequency_method"] == "cx317_selected_600s_nonoverlap_v1",
            "phase_frequency_support": phase_selection["frequency_support_intervals"] == 600,
            "hybrid_profile_id": hybrid["profile_id"] == "cx318_hybrid_preview_selected_v1",
            "hybrid_candidate": hybrid_selection["selected_candidate_id"] == "p21600_cap1_v2",
            "hybrid_pull_in": hybrid_selection["pull_in_time_s"] == 21600,
            "hybrid_band": hybrid_selection["frequency_band_policy"] == "historical_v2",
            "frequency_profile_id": frequency["profile_id"] == "cx317_pps_gated_selected_v1",
            "frequency_method": frequency["method_id"] == "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1",
            "frequency_backend": frequency["expected_snapshot_backend"] == EXPECTED_BACKEND,
            "frequency_span": frequency_policy["span_s"] == 600,
            "frequency_mode": frequency_policy["output_mode"] == "non_overlapping",
            "frequency_cadence": frequency_policy["output_cadence_s"] == 600,
            "all_phase_authority_false": not any(phase["authority"].values()),
            "all_hybrid_authority_false": not any(hybrid["authority"].values()),
            "frequency_nonactionable": frequency["authority"]["observe_only"] is True
            and frequency["authority"]["actuation_authorized"] is False
            and frequency["authority"]["actionable"] is False,
        }
        passed = all(comparisons.values())
        result = {
            "status": "pass" if passed else "fail",
            "comparisons": comparisons,
            "identities": {
                "phase_selected_sha256": _sha256_file(PHASE_SELECTED),
                "hybrid_selected_sha256": _sha256_file(HYBRID_SELECTED),
                "frequency_selected_sha256": _sha256_file(FREQUENCY_SELECTED),
            },
        }
        failed = [name for name, ok in comparisons.items() if not ok]
        return Check("selected_profile_semantics", passed, "all exact" if passed else "failed: " + ", ".join(failed)), result
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return Check("selected_profile_semantics", False, str(exc)), {"status": "fail", "reason": str(exc)}


def _stage4_build_contract(
    manifest_data: dict[str, Any],
    build_manifest_path: Path | None,
    *,
    static_code: int,
    dac_epoch: int,
) -> Check:
    if build_manifest_path is None:
        return Check("stage4_build_profile_and_defines", False, "build manifest unavailable")
    try:
        build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
        configuration = build["provenance"]["configuration"]
        defines = configuration["defines"]
        firmware = manifest_data["firmware"]
        matrix = json.loads(FIRMWARE_MATRIX.read_text(encoding="utf-8"))
        profile = next(
            (
                item
                for item in matrix["profiles"]
                if item.get("id") == EXPECTED_PROFILE
            ),
            None,
        )
        if not isinstance(profile, dict):
            raise ValueError(f"firmware matrix lacks {EXPECTED_PROFILE}")
        expected = dict(profile["defines"])
        expected["OTIS_CX318_STAGE4_STATIC_CODE"] = f"0x{static_code:04X}u"
        expected["OTIS_CX318_STAGE4_DAC_EPOCH"] = f"{dac_epoch}u"
        missing_or_changed = {
            key: {"expected": value, "actual": defines.get(key)}
            for key, value in expected.items()
            if defines.get(key) != value
        }
        unexpected = {
            key: value for key, value in defines.items() if key not in expected
        }
        passed = (
            configuration["profile_id"] == EXPECTED_PROFILE
            and firmware.get("config_id") == EXPECTED_PROFILE
            and profile.get("expect") == "pass"
            and not missing_or_changed
            and not unexpected
        )
        return Check(
            "stage4_build_profile_and_defines",
            passed,
            "exact nonactuating profile and static-code defines"
            if passed
            else json.dumps(
                {
                    "build_profile": configuration.get("profile_id"),
                    "manifest_profile": firmware.get("config_id"),
                    "missing_or_changed_defines": missing_or_changed,
                    "unexpected_defines": unexpected,
                },
                sort_keys=True,
            ),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return Check("stage4_build_profile_and_defines", False, str(exc))


def _host_markers(raw_log: Path) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if not line.startswith(HOST_MARKER_PREFIX):
                continue
            value = json.loads(line[len(HOST_MARKER_PREFIX) :])
            if not isinstance(value, dict):
                raise ValueError("host marker is not a JSON object")
            markers.append(value)
    return markers


def _raw_csv_association(
    raw_log: Path, rows: dict[str, list[dict[str, str]]]
) -> tuple[Check, dict[str, Any]]:
    definitions = {
        "CNT": ("counts", "count_observations_v1"),
        "SNP": ("snapshots", "pps_snapshots_v1"),
        "RPH": ("rph", "relative_phase_observations_v1"),
        "PHE": ("phe", "phase_estimator_outputs_v1"),
        "HPR": ("hpr", "hybrid_preview_decisions_v1"),
        "DAC": ("dac", "dac_steps_v1"),
        "ACT": ("active", "active_transactions_v1"),
    }
    raw_records: dict[str, list[list[str]]] = {key: [] for key in definitions}
    with raw_log.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for raw_line in handle:
            record_type = raw_line.split(",", 1)[0]
            if record_type not in definitions:
                continue
            parsed = next(csv.reader([raw_line.rstrip("\r\n")]))
            raw_records[record_type].append(parsed)
    mismatches: dict[str, Any] = {}
    for record_type, (row_name, contract) in definitions.items():
        fields = CONTRACT_FIELDS[contract]
        expected = [[row.get(field, "") for field in fields] for row in rows[row_name]]
        actual = raw_records[record_type]
        if actual != expected:
            first_difference = next(
                (
                    index
                    for index, (raw_row, csv_row) in enumerate(
                        zip(actual, expected, strict=False), start=1
                    )
                    if raw_row != csv_row
                ),
                min(len(actual), len(expected)) + 1,
            )
            mismatches[record_type] = {
                "raw_count": len(actual),
                "csv_count": len(expected),
                "first_difference": first_difference,
            }
    passed = not mismatches
    return (
        Check(
            "raw_to_split_csv_exact_association",
            passed,
            "CNT/SNP/RPH/PHE/HPR/DAC/ACT exact in-order copies"
            if passed
            else json.dumps(mismatches, sort_keys=True),
        ),
        {
            "status": "pass" if passed else "fail",
            "raw_record_counts": {key: len(value) for key, value in raw_records.items()},
            "mismatches": mismatches,
        },
    )


def _transport_and_authority_checks(
    raw_log: Path,
    capture_state: dict[str, Any],
    health_rows: list[dict[str, str]],
    dac_rows: list[dict[str, str]],
    active_rows: list[dict[str, str]],
    hpr_rows: list[dict[str, str]] | None = None,
    *,
    static_code: int | None = None,
    dac_epoch: int | None = None,
) -> tuple[list[Check], dict[str, Any]]:
    markers = _host_markers(raw_log)
    sent_commands = [
        str(item.get("command", ""))
        for item in markers
        if item.get("event") == "host_command_sent"
    ]
    allowed_commands = {"CONFIG?", "DUALCORE?"}
    unexpected_commands = [item for item in sent_commands if item not in allowed_commands]
    marker_counts: dict[str, int] = {}
    for item in markers:
        event = str(item.get("event", ""))
        marker_counts[event] = marker_counts.get(event, 0) + 1
    latest = _latest_health(health_rows)
    expected_health = {
        ("build", "enable_dac_ad5693r"): "0",
        ("build", "enable_cx317_bounded_active"): "0",
        ("cx318_preview", "initialized"): "true",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "service_fault_capsule"): "clear",
        ("dual_core", "telemetry_dropped"): "0",
        ("dual_core", "service_publish_failures"): "0",
        ("dual_core", "service_take_accounting"): "successful_only",
        ("dual_core", "service_drain_budget_per_loop"): "16",
        ("dual_core", "core1_trace_sampling"): "bounded_coarse",
        ("dual_core", "core1_trace_period_ms"): "250",
    }
    optional_expected_health = {
        ("build", "enable_cx318_stage4_preview"): "1",
        ("build", "enable_cx317_i_only_preview"): "0",
        ("cx318_preview", "actionable"): "false",
        ("cx318_preview", "actuation_authorized"): "false",
        ("cx318_preview", "authorization_consumed"): "false",
    }
    if (
        static_code is not None
        and 0xA800 <= static_code <= 0xAB00
        and dac_epoch is not None
        and dac_epoch >= 0
    ):
        expected_health.update(
            {
                ("cx318_preview", "static_code"): f"0x{static_code:04X}",
            }
        )
        optional_expected_health.update(
            {
                ("cx318_preview", "confirmed_static_code"): f"0x{static_code:04X}",
                ("cx318_preview", "dac_epoch"): str(dac_epoch),
            }
        )
    health_mismatches = {
        f"{component}.{key}": {"expected": expected, "actual": latest.get((component, key))}
        for (component, key), expected in expected_health.items()
        if latest.get((component, key)) != expected
    }
    health_mismatches.update({
        f"{component}.{key}": {"expected": expected, "actual": latest.get((component, key))}
        for (component, key), expected in optional_expected_health.items()
        if (component, key) in latest and latest[(component, key)] != expected
    })
    history_violations: list[dict[str, str]] = []
    always_expected = {
        **expected_health,
        **optional_expected_health,
        **{key: "0" for key in REQUIRED_ZERO_HEALTH},
    }
    for row in health_rows:
        key = (row["component"], row["status_key"])
        expected = always_expected.get(key)
        if expected is not None and row["status_value"].strip() != expected:
            history_violations.append(
                {
                    "component": key[0],
                    "status_key": key[1],
                    "expected": expected,
                    "actual": row["status_value"].strip(),
                }
            )
    zero_health_mismatches = {
        f"{component}.{key}": latest.get((component, key))
        for component, key in REQUIRED_ZERO_HEALTH
        if latest.get((component, key)) != "0"
    }
    queue_mismatches: dict[str, Any] = {}
    for key, maximum_exclusive in (
        (("dual_core", "service_to_timing_depth"), 1),
        (("dual_core", "cx318_preview_depth"), 1),
        (("dual_core", "service_to_timing_high_water"), 16),
        (("dual_core", "cx318_preview_high_water"), 32),
    ):
        value = latest.get(key)
        try:
            valid = value is not None and int(value) < maximum_exclusive
        except ValueError:
            valid = False
        if not valid:
            queue_mismatches[f"{key[0]}.{key[1]}"] = {
                "actual": value,
                "maximum_exclusive": maximum_exclusive,
            }
    raw_record_counts = {"DAC": 0, "ACT": 0}
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            record_type = line.split(",", 1)[0]
            if record_type in raw_record_counts:
                raw_record_counts[record_type] += 1
    capture_clean = (
        capture_state.get("capture_active") is False
        and capture_state.get("serial_open") is False
        and capture_state.get("parser_errors") == 0
        and capture_state.get("malformed_utf8") == 0
        and capture_state.get("reconnect_count") == 0
        and capture_state.get("commands_rejected") == 0
        and capture_state.get("emergency_aborts_sent") == 0
        and capture_state.get("emergency_abort_latched") is False
        and capture_state.get("commands_sent") == len(sent_commands)
        and marker_counts.get("serial_disconnected", 0) == 0
        and marker_counts.get("reconnecting", 0) == 0
    )
    no_authority = (
        not dac_rows
        and not active_rows
        and raw_record_counts == {"DAC": 0, "ACT": 0}
        and not unexpected_commands
        and not any(
            row["component"] == "cx318_preview"
            and row["status_key"] == "dac_command_attempt"
            for row in health_rows
        )
    )
    preview_identity = hpr_rows is None or (
        bool(hpr_rows)
        and static_code is not None
        and dac_epoch is not None
        and all(
            row.get("actual_applied_code") == str(static_code)
            and row.get("dac_epoch") == str(dac_epoch)
            and row.get("actionable") == "false"
            and row.get("actuation_authorized") == "false"
            and row.get("authorization_consumed") == "false"
            for row in hpr_rows
        )
    )
    checks = [
        Check(
            "capture_transport_continuity",
            capture_clean,
            f"reconnects={capture_state.get('reconnect_count')}, "
            f"parser_errors={capture_state.get('parser_errors')}, markers={marker_counts}",
        ),
        Check(
            "zero_dac_active_or_unapproved_commands",
            no_authority and preview_identity,
            f"DAC/ACT rows={len(dac_rows)}/{len(active_rows)}, "
            f"raw={raw_record_counts}, commands={sent_commands}, "
            f"HPR_identity={preview_identity}",
        ),
        Check(
            "live_health_fail_static_and_authority_guards",
            not health_mismatches
            and not zero_health_mismatches
            and not queue_mismatches
            and not history_violations,
            "all exact"
            if not health_mismatches
            and not zero_health_mismatches
            and not queue_mismatches
            and not history_violations
            else json.dumps(
                {
                    "identity_or_fault": health_mismatches,
                    "zero_counters": zero_health_mismatches,
                    "queue_bounds": queue_mismatches,
                    "history": history_violations[:16],
                },
                sort_keys=True,
            ),
        ),
    ]
    return checks, {
        "capture_state": capture_state,
        "host_marker_counts": marker_counts,
        "commands_sent": sent_commands,
        "unexpected_commands": unexpected_commands,
        "raw_authority_record_counts": raw_record_counts,
        "health_mismatches": health_mismatches,
        "zero_health_mismatches": zero_health_mismatches,
        "queue_mismatches": queue_mismatches,
        "health_history_violation_count": len(history_violations),
        "first_health_history_violations": history_violations[:32],
    }


def _decimal_difference(actual: str, expected: float) -> float:
    try:
        return float(abs(Decimal(actual) - Decimal.from_float(float(expected))))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a finite decimal: {actual!r}") from exc


def _compare_float(actual: str, expected: float | None, field: str) -> str | None:
    if expected is None:
        return None if actual == "" else f"{field}: expected empty, got {actual!r}"
    if not math.isfinite(float(expected)):
        return f"{field}: non-finite host expectation"
    try:
        difference = _decimal_difference(actual, float(expected))
    except ValueError as exc:
        return f"{field}: {exc}"
    tolerance = max(math.ulp(float(expected)), NUMERIC_ABSOLUTE_FLOOR)
    return None if difference <= tolerance else f"{field}: difference {difference} exceeds {tolerance}"


def _compare_exact(actual: dict[str, str], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field, value in expected.items():
        expected_text = str(value).lower() if isinstance(value, bool) else str(value)
        if actual.get(field, "") != expected_text:
            errors.append(f"{field}: expected {expected_text!r}, got {actual.get(field, '')!r}")
    return errors


def _live_parity(
    snapshots: list[dict[str, str]],
    counts: list[dict[str, str]],
    rph_rows: list[dict[str, str]],
    phe_rows: list[dict[str, str]],
    hpr_rows: list[dict[str, str]],
    *,
    static_code: int,
    dac_epoch: int,
) -> tuple[list[Check], dict[str, Any]]:
    phase_profile, _phase_candidates_hash = load_phase_profile()
    phase_hash = _sha256_file(PHASE_SELECTED)
    hybrid_profile, _hybrid_candidates_hash = load_hybrid_profile()
    selected_hybrid = json.loads(HYBRID_SELECTED.read_text(encoding="utf-8"))
    hybrid_hash = _sha256_file(HYBRID_SELECTED)
    frequency_hash = _sha256_file(FREQUENCY_SELECTED)
    candidate_id = selected_hybrid["selection"]["selected_candidate_id"]
    candidate = next(item for item in hybrid_profile["candidates"] if item["candidate_id"] == candidate_id)
    boundary_args = {
        "snapshots": snapshots,
        "counts": counts,
        "timer_hz": 16_000_000,
        "events": [],
        "start_code": static_code,
    }
    expected = _host_outputs(
        _boundaries(**boundary_args),
        nominal_edges=10_000_000,
        timer_hz=16_000_000,
        period_ns=100.0,
        phase_profile=phase_profile,
        phase_configuration_sha256=phase_hash,
        hybrid_profile=hybrid_profile,
        selected_candidate=candidate,
        start_code=static_code,
        reset_first=True,
    )
    row_counts_equal = len(rph_rows) == len(phe_rows) == len(hpr_rows) == len(snapshots)
    mismatches: list[dict[str, Any]] = []
    mismatch_count = 0
    last_frequency_event_ticks: int | None = None
    frequency_event_count = 0
    compared = 0
    first_ticks: int | None = None
    last_ticks: int | None = None
    for index, (record, _raw_estimate, decision) in enumerate(expected):
        if index >= min(len(rph_rows), len(phe_rows), len(hpr_rows)):
            mismatch_count += 1
            if len(mismatches) < MAX_MISMATCHES:
                mismatches.append({"row": index + 1, "errors": ["derived output ended early"]})
            continue
        compared += 1
        rph = rph_rows[index]
        phe = phe_rows[index]
        hpr = hpr_rows[index]
        ticks = round(decision.timestamp_s * 16_000_000)
        first_ticks = ticks if first_ticks is None else first_ticks
        last_ticks = ticks
        if decision.frequency_observation_event:
            last_frequency_event_ticks = ticks
            frequency_event_count += 1
        frequency_available = decision.modeled_frequency_error_hz is not None
        estimate_age_s = (
            (ticks - last_frequency_event_ticks) / 16_000_000
            if frequency_available and last_frequency_event_ticks is not None
            else None
        )
        rph_expected = {
            "record_type": "RPH",
            "schema_version": 1,
            "phase_epoch": record.phase_epoch,
            "observation_sequence": record.observation_sequence,
            "capture_session": record.capture_session,
            "opening_snapshot_sequence": record.opening_snapshot_sequence,
            "closing_snapshot_sequence": record.closing_snapshot_sequence,
            "opening_reference_sequence": record.opening_reference_sequence,
            "closing_reference_sequence": record.closing_reference_sequence,
            "dac_epoch": dac_epoch,
            "source_backend": EXPECTED_BACKEND,
            "source_file_sha256": "live_stream_unsealed",
            "method_id": "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
            "configuration_sha256": phase_hash,
            "interval_edges": "" if record.interval_edges is None else record.interval_edges,
            "edge_error_cycles": "" if record.edge_error_cycles is None else record.edge_error_cycles,
            "relative_phase_cycles": record.relative_phase_cycles,
            "relative_phase_time_ns": int(record.relative_phase_time_ns),
            "qualification_state": record.qualification_state,
            "observation_age_s": 0,
            "discontinuity_reason": record.discontinuity_reason or "",
            "calibrated_uncertainty_status": "unavailable",
        }
        phe_qualification = (
            "invalid"
            if record.qualification_state == "invalid"
            else "qualified" if frequency_available else "initializing"
        )
        phe_reason = (
            record.discontinuity_reason or "invalid_phase_input"
            if record.qualification_state == "invalid"
            else (
                "selected_600_interval_frequency_fresh"
                if decision.frequency_observation_event
                else "selected_600_interval_frequency_retained"
            )
            if frequency_available
            else "selected_600_interval_frequency_initializing"
        )
        phe_expected = {
            "record_type": "PHE",
            "schema_version": 1,
            "phase_epoch": record.phase_epoch,
            "observation_sequence": record.observation_sequence,
            "source_relative_phase_observation": f"RPH:{record.phase_epoch}:{record.observation_sequence}",
            "raw_relative_phase_cycles": record.relative_phase_cycles,
            "raw_relative_phase_time_ns": int(record.relative_phase_time_ns),
            "filtered_relative_phase_cycles": record.relative_phase_cycles,
            "estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
            "configuration_sha256": phase_hash,
            "qualification_state": phe_qualification,
            "uncertainty_status": "unavailable",
            "reason_codes": phe_reason,
        }
        hpr_expected = {
            "record_type": "HPR",
            "schema_version": 1,
            "preview_sequence": index + 1,
            "candidate_id": candidate_id,
            "candidate_configuration_sha256": hybrid_hash,
            "phase_estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
            "phase_estimator_configuration_sha256": phase_hash,
            "frequency_estimator_id": "cx317_selected_600s_nonoverlap_v1",
            "frequency_estimator_configuration_sha256": frequency_hash,
            "configuration_sha256": hybrid_hash,
            "phase_epoch": record.phase_epoch,
            "observation_sequence": record.observation_sequence,
            "dac_epoch": dac_epoch,
            "decision_timestamp_ticks": ticks,
            "time_domain": "rp2040_timer0",
            "source_phase_estimate": f"PHE:{record.phase_epoch}:{record.observation_sequence}",
            "source_frequency_estimate": (
                f"PHE:{record.phase_epoch}:{record.observation_sequence}"
                if frequency_available
                else "unavailable"
            ),
            "raw_relative_phase_cycles": record.relative_phase_cycles,
            "actual_applied_code": static_code,
            "shadow_code_before": decision.shadow_code_before,
            "shadow_code_after": decision.shadow_code_after,
            "band_state_before": decision.band_state_before,
            "band_state_after": decision.band_state_after,
            "preview_state": decision.preview_state,
            "decision_reason": decision.decision_reason,
            "frequency_observation_event": decision.frequency_observation_event,
            "counterfactual_decision": decision.counterfactual_decision,
            "counterfactual_correction": decision.counterfactual_correction,
            "counterfactual_delta_codes": (
                "" if decision.limited_delta_codes is None else decision.limited_delta_codes
            ),
            "counterfactual_code": decision.shadow_code_after,
            "step_limited": decision.step_limited,
            "range_clamped": decision.range_clamped,
            "correction_count": decision.correction_count,
            "cumulative_movement_codes": decision.cumulative_movement_codes,
            "alternating_correction_count": decision.alternating_correction_count,
            "modeled_not_observed_after_divergence": decision.modeled_not_observed_after_divergence,
            "uncertainty_status": "unavailable",
            "actionable": False,
            "actuation_authorized": False,
            "authorization_consumed": False,
        }
        errors = [
            *[f"RPH.{item}" for item in _compare_exact(rph, rph_expected)],
            *[f"PHE.{item}" for item in _compare_exact(phe, phe_expected)],
            *[f"HPR.{item}" for item in _compare_exact(hpr, hpr_expected)],
        ]
        float_expectations = (
            ("PHE.estimated_frequency_error_hz", phe["estimated_frequency_error_hz"], decision.observed_frequency_error_hz if frequency_available else None),
            ("PHE.estimate_age_s", phe["estimate_age_s"], estimate_age_s),
            ("HPR.modeled_relative_phase_cycles", hpr["modeled_relative_phase_cycles"], decision.modeled_relative_phase_cycles),
            ("HPR.observed_frequency_error_hz", hpr["observed_frequency_error_hz"], decision.observed_frequency_error_hz),
            ("HPR.modeled_frequency_error_hz", hpr["modeled_frequency_error_hz"], decision.modeled_frequency_error_hz),
            ("HPR.frequency_term_hz", hpr["frequency_term_hz"], decision.frequency_term_hz),
            ("HPR.phase_bias_hz", hpr["phase_bias_hz"], decision.phase_bias_hz),
            ("HPR.combined_frequency_error_hz", hpr["combined_frequency_error_hz"], decision.combined_desired_frequency_change_hz),
            ("HPR.raw_counterfactual_delta_codes", hpr["raw_counterfactual_delta_codes"], decision.raw_delta_codes),
        )
        for field, actual, expected_value in float_expectations:
            if error := _compare_float(actual, expected_value, field):
                errors.append(error)
        if errors:
            mismatch_count += 1
            if len(mismatches) < MAX_MISMATCHES:
                mismatches.append(
                    {
                        "row": index + 1,
                        "snapshot_sequence": record.closing_snapshot_sequence,
                        "phase_epoch": record.phase_epoch,
                        "errors": errors[:12],
                    }
                )
    duration_s = (
        (last_ticks - first_ticks) / 16_000_000
        if first_ticks is not None and last_ticks is not None
        else 0.0
    )
    epoch_open_indexes = [
        index
        for index, row in enumerate(rph_rows)
        if row["qualification_state"] == "epoch_open"
    ]
    first_open = epoch_open_indexes[0] if len(epoch_open_indexes) == 1 else None
    leading_acquisition_ok = first_open is not None and all(
        row["qualification_state"] == "invalid"
        and row["discontinuity_reason"] == "reference_invalid_or_stale"
        for row in rph_rows[:first_open]
    )
    qualified_after_open = first_open is not None and all(
        row["qualification_state"] == "qualified"
        for row in rph_rows[first_open + 1 :]
    )
    # RECOVER_PREVIEW is also the expected, replayed hybrid state while a
    # newly opened phase epoch is waiting for its first 600-second frequency
    # estimate.  It is therefore not evidence of a phase discontinuity.  A
    # later reference loss is already exposed by an invalid RPH row or a
    # second epoch_open; retain explicit guards for reference-lost and fault
    # preview states as an independent cross-check.
    continuous_epoch = (
        first_open is not None
        and leading_acquisition_ok
        and qualified_after_open
        and len({row["phase_epoch"] for row in rph_rows[first_open:]}) == 1
        and len({row["capture_session"] for row in rph_rows}) == 1
        and all(
            row["preview_state"]
            not in {"REFERENCE_LOST_PREVIEW", "FAULT_PREVIEW"}
            for row in hpr_rows[first_open:]
        )
    )
    checks = [
        Check(
            "one_complete_record_group_per_snapshot",
            row_counts_equal and compared == len(snapshots),
            f"SNP/RPH/PHE/HPR={len(snapshots)}/{len(rph_rows)}/{len(phe_rows)}/{len(hpr_rows)}",
        ),
        Check(
            "live_host_firmware_phase_hybrid_parity",
            mismatch_count == 0 and compared > 0,
            f"{compared} groups; {mismatch_count} mismatches; tolerance=max(one ULP, 1e-15)",
        ),
        Check(
            "single_continuous_qualified_phase_epoch",
            continuous_epoch,
            "only leading reference acquisition, then one epoch-open and qualified "
            "boundaries with no reference-lost/fault preview",
        ),
    ]
    return checks, {
        "compared_record_groups": compared,
        "mismatch_count": mismatch_count,
        "first_mismatches": mismatches,
        "authoritative_frequency_event_count": frequency_event_count,
        "duration_s": duration_s,
        "numeric_tolerance": "max(one_ulp_at_expected, 1e-15)",
    }


def analyze_run(
    run_dir: Path,
    *,
    build_manifest_path: Path | None = None,
    uf2_path: Path | None = None,
    expected_stage: str = EXPECTED_STAGE,
    hard_minimum_frequency_events: int = 2,
    hard_minimum_duration_s: float = 7200,
    tool_version: str = TOOL_VERSION,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("capture is in progress; refusing offline Stage 4 analysis")
    manifest = load_manifest(run_dir)
    manifest_data = manifest.data
    paths = {
        "counts": _contract_path(manifest, "count_observations_v1"),
        "snapshots": _contract_path(manifest, "pps_snapshots_v1"),
        "health": _contract_path(manifest, "health_v1"),
        "environment": _contract_path(manifest, "environment_v1"),
        "dac": _contract_path(manifest, "dac_steps_v1"),
        "active": _contract_path(manifest, "active_transactions_v1"),
        "rph": _contract_path(manifest, "relative_phase_observations_v1"),
        "phe": _contract_path(manifest, "phase_estimator_outputs_v1"),
        "hpr": _contract_path(manifest, "hybrid_preview_decisions_v1"),
        "raw": run_dir / "raw/serial.log",
        "capture_state": run_dir / "reports/capture_device_state.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing Stage 4 inputs: " + ", ".join(missing))
    source_before = {name: _sha256_file(path) for name, path in paths.items()}
    rows = {name: _read_rows(paths[name]) for name in ("counts", "snapshots", "health", "environment", "dac", "active", "rph", "phe", "hpr")}
    capture_state = json.loads(paths["capture_state"].read_text(encoding="utf-8"))
    checks = _validate_contracts(manifest, paths)
    checks.append(Check("stage_identity", manifest_data.get("stage") == expected_stage, f"stage={manifest_data.get('stage')!r}"))
    checks.append(
        Check(
            "finite_capture_complete",
            (run_dir / "COMPLETE").is_file(),
            "COMPLETE marker present" if (run_dir / "COMPLETE").is_file() else "COMPLETE marker missing",
        )
    )
    profile_check, profile_contract = _selected_profile_contract()
    checks.append(profile_check)
    static_check, static_binding = _static_code_binding(run_dir, manifest_data)
    checks.append(static_check)
    code = int(static_binding.get("static_code", -1))
    dac_epoch = int(static_binding.get("dac_epoch", -1))
    transport_checks, transport = _transport_and_authority_checks(
        paths["raw"], capture_state, rows["health"], rows["dac"], rows["active"],
        rows["hpr"],
        static_code=code,
        dac_epoch=dac_epoch,
    )
    checks.extend(transport_checks)
    raw_association_check, raw_association = _raw_csv_association(paths["raw"], rows)
    checks.append(raw_association_check)
    firmware_check, firmware_binding = _firmware_build_binding(
        manifest_data, build_manifest_path, uf2_path
    )
    checks.append(firmware_check)
    checks.append(
        _stage4_build_contract(
            manifest_data,
            build_manifest_path,
            static_code=code,
            dac_epoch=dac_epoch,
        )
    )
    latest_health = _latest_health(rows["health"])
    static_health_ok = (
        0xA800 <= code <= 0xAB00
        and latest_health.get(("cx318_preview", "static_code")) == f"0x{code:04X}"
        and bool(rows["hpr"])
        and all(
            row["actual_applied_code"] == str(code)
            and row["dac_epoch"] == str(dac_epoch)
            and row["actionable"] == "false"
            and row["actuation_authorized"] == "false"
            and row["authorization_consumed"] == "false"
            for row in rows["hpr"]
        )
    )
    checks.append(
        Check(
            "emitted_static_code_and_epoch_identity",
            static_health_ok,
            f"expected 0x{code:04X}/epoch {dac_epoch}",
        )
    )
    parity: dict[str, Any] = {
        "status": "not_run",
        "reason": "static code binding unavailable",
    }
    if 0xA800 <= code <= 0xAB00 and dac_epoch >= 0:
        parity_checks, parity = _live_parity(
            rows["snapshots"], rows["counts"], rows["rph"], rows["phe"], rows["hpr"],
            static_code=code, dac_epoch=dac_epoch,
        )
        checks.extend(parity_checks)
        minimum_frequency_events = math.ceil(
            _declared_minimum(
                manifest_data.get("stage4_live_preview", {}).get(
                    "minimum_authoritative_frequency_estimates", hard_minimum_frequency_events
                ),
                hard_minimum=hard_minimum_frequency_events,
                name="minimum_authoritative_frequency_estimates",
            )
        )
        minimum_duration_s = _declared_minimum(
            manifest_data.get("stage4_live_preview", {}).get("minimum_duration_s", hard_minimum_duration_s),
            hard_minimum=hard_minimum_duration_s,
            name="minimum_duration_s",
        )
        checks.extend(
            [
                Check(
                    "minimum_authoritative_frequency_estimates",
                    parity["authoritative_frequency_event_count"] >= minimum_frequency_events,
                    f"{parity['authoritative_frequency_event_count']} >= {minimum_frequency_events}",
                ),
                Check(
                    "finite_live_duration",
                    parity["duration_s"] >= minimum_duration_s,
                    f"{parity['duration_s']:.3f}s >= {minimum_duration_s:.3f}s",
                ),
            ]
        )
    environment_sources = {row["source"] for row in rows["environment"]}
    checks.append(
        Check(
            "both_environment_streams_present",
            {"sht4x", "bmp280"} <= environment_sources,
            f"sources={sorted(environment_sources)}",
        )
    )
    source_after = {name: _sha256_file(path) for name, path in paths.items()}
    checks.append(Check("source_artifacts_unchanged", source_before == source_after, f"{len(source_before)} source files rehashed"))
    passed = all(check.passed for check in checks)
    source_artifacts_sha256 = {
        path.relative_to(run_dir).as_posix(): source_after[name]
        for name, path in paths.items()
    }
    return {
        "schema_version": 1,
        "tool": tool_version,
        "status": "passed" if passed else "failed",
        "run_id": manifest.run_id,
        "run_dir": str(run_dir),
        "run_manifest_sha256": _sha256_file(manifest.path),
        "checks": [asdict(check) for check in checks],
        "static_code_binding": static_binding,
        "selected_profile_contract": profile_contract,
        "firmware_build_binding": firmware_binding,
        "transport_and_authority": transport,
        "raw_csv_association": raw_association,
        "live_parity": parity,
        "source_sha256_before": source_before,
        "source_sha256_after": source_after,
        "source_artifacts_sha256": dict(sorted(source_artifacts_sha256.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--uf2", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze_run(
            args.run_dir,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    output = args.output or (args.run_dir / DEFAULT_OUTPUT)
    _write_json_atomic(output, result)
    print(json.dumps({"status": result["status"], "output": str(output)}, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
