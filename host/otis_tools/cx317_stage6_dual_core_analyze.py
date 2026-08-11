"""Offline exit-gate analyzer for the Stage 6 dual-core live proof."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
import tempfile
from typing import Any

from .cx317_i_only_preview_replay import (
    IOnlyPreviewEngine,
    Observation,
    POST_CAMPAIGN_POLICY,
    load_post_campaign_policy,
)
from .cx317_frequency_preview_live_analyze import (
    EXPECTED_BACKEND,
    SERIALIZED_12_DECIMAL_HALF_UNIT,
    TICKS_PER_SECOND,
    _check_continuity,
    _host_markers,
    _latest_health,
    _one_marker,
    _read_rows,
    _serialized_difference,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .timebase import unwrap_ticks


EXPECTED_STAGE = "CX317_DUAL_CORE_POST_CAMPAIGN_PREVIEW"
EXPECTED_CODE = 0xA82A
EXPECTED_COMMIT = "6ac3ae66861fedf3a90930b16332e5d0368c6dbb"
EXPECTED_SOURCE = "7e7175422c9c8aac9d61672dd6867d202127eec347f815eec3c43ad4b9ac6fbf"
EXPECTED_CONFIG = "a2d4e934e612682cc47db261a24dc0b50561ca6013338e161f265b5c94b67705"
EXPECTED_UF2 = "ed6f726a56a6efe166208902b96194e300ed8ebe5029d4be727bebbe7d216bd2"
EXPECTED_BUILD_MANIFEST = "2a2a0e7c756335556d02100bb9aee85e2b83bc3d3ad1e0f409c0ce531c1f3a85"


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


def _write_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    temporary.replace(path)


def _utc_seconds(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _bool(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError(f"invalid serialized bool {value!r}")
    return value == "true"


def _rows_for(manifest: Any, run_dir: Path, contract: str) -> list[dict[str, str]]:
    matches = [entry for entry in manifest.files if entry.get("contract") == contract]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {contract} file")
    return _read_rows(run_dir / str(matches[0]["path"]))


def _estimator_parity(
    rows: list[dict[str, str]], count_by_seq: dict[int, dict[str, str]],
    estimator_hash: str, *, minimum_selected: int = 4,
) -> tuple[Check, dict[str, dict[str, str]]]:
    by_id: dict[str, dict[str, str]] = {}
    maximum_difference = 0.0
    valid = [int(row["estimate_seq"]) for row in rows] == list(range(len(rows)))
    selected = 0
    for row in rows:
        by_id[row["estimate_id"]] = row
        diagnostic = row["estimator_version"] == "cx317_diagnostic_60s_overlap_v1"
        chosen = row["estimator_version"] == "cx317_selected_600s_nonoverlap_v1"
        span = 60 if diagnostic else 600 if chosen else 0
        selected += int(chosen)
        first = int(row["source_reference_first_seq"])
        last = int(row["source_reference_last_seq"])
        sources = [count_by_seq.get(sequence) for sequence in range(first + 1, last + 1)]
        if span == 0 or len(sources) != span or any(source is None for source in sources):
            valid = False
            continue
        frequency = sum(int(source["counted_edges"]) for source in sources if source) / span
        difference = max(
            _serialized_difference(row["frequency_estimate_hz"], frequency),
            _serialized_difference(row["frequency_error_hz"], frequency - 10_000_000.0),
        )
        maximum_difference = max(maximum_difference, difference)
        valid = valid and (
            row["config_hash"] == estimator_hash
            and row["observation_validity"] == "valid"
            and row["reference_validity"] == "valid"
            and row["count_validity"] == "valid"
            and row["diagnostic_health"] == "healthy"
            and difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
        )
    return Check(
        "estimator_host_firmware_parity",
        valid and selected >= minimum_selected,
        f"{len(rows)} estimates, {selected} selected; maximum difference {maximum_difference:.17g} Hz",
    ), by_id


def _mapped_state(value: str) -> str:
    return {
        "WARMUP_INHIBIT": "WARMUP_INHIBIT",
        "QUALIFYING": "QUALIFYING",
        "SETTLING_INHIBIT": "SETTLE_PREVIEW",
        "TRACKING": "LOCKED_PREVIEW",
        "FAULT": "FAULT",
        "ABORTED": "FAULT",
    }[value]


def _controller_parity(
    rows: list[dict[str, str]], estimates: dict[str, dict[str, str]],
) -> tuple[Check, dict[str, Any]]:
    policy = load_post_campaign_policy()
    engine = IOnlyPreviewEngine(policy)
    ticks, wraps = unwrap_ticks([int(row["decision_timestamp_ticks"]) for row in rows])
    comparisons: list[dict[str, Any]] = []
    valid = [int(row["control_seq"]) for row in rows] == list(range(len(rows)))
    max_error = 0.0
    max_delta = 0.0
    for row, timestamp_ticks in zip(rows, ticks, strict=True):
        source = estimates.get(row["est_input_ref"])
        frequency_error = float(source["frequency_error_hz"]) if source else None
        reason = row["decision_reason_code"]
        reference_valid = reason != "reference_invalid"
        recovery = reason == "explicit_recovery_fresh_support"
        previous = engine.state
        host = engine.process(Observation(
            timestamp_s=timestamp_ticks // TICKS_PER_SECOND,
            frequency_error_hz=frequency_error,
            current_code=int(row["current_dac_code"]),
            reference_valid=reference_valid,
            estimator_valid=reference_valid,
            count_valid=reference_valid,
            model_applicable=row["model_applicability"] == "applicable",
            recovery_requested=recovery,
        ))
        host_error = host["frequency_error_hz"]
        error_difference = (
            0.0 if row["frequency_error_hz"] == "" and host_error is None
            else math.inf if row["frequency_error_hz"] == "" or host_error is None
            else _serialized_difference(row["frequency_error_hz"], float(host_error))
        )
        host_delta = host["raw_delta_codes"]
        delta_difference = (
            0.0 if row["raw_delta_codes"] == "" and host_delta is None
            else math.inf if row["raw_delta_codes"] == "" or host_delta is None
            else _serialized_difference(row["raw_delta_codes"], float(host_delta))
        )
        exact = (
            row["policy_version"] == policy.policy_id
            and row["config_hash"] == policy.config_hash
            and row["plant_model_hash"] == policy.plant_model_hash
            and row["control_state"] == _mapped_state(str(host["state"]))
            and row["previous_control_state"] == _mapped_state(previous)
            and row["decision_reason_code"] == host["reason"]
            and _bool(row["preview_available"]) == bool(host["preview_available"])
            and _bool(row["preview_only"])
            and not _bool(row["actuation_authorized"])
            and not _bool(row["actionable"])
            and int(row["current_dac_code"]) == EXPECTED_CODE
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and delta_difference <= (abs(policy.integrator_gain) + 1.0) * SERIALIZED_12_DECIMAL_HALF_UNIT
        )
        if host["preview_available"]:
            exact = exact and (
                int(row["limited_delta_codes"]) == host["limited_delta_codes"]
                and int(row["proposed_dac_code"]) == host["proposed_code"]
                and _bool(row["step_limited"]) == host["step_limited"]
                and _bool(row["range_clamped"]) == host["range_clamped"]
            )
        else:
            exact = exact and all(
                row[field] == "" for field in
                ("raw_delta_codes", "limited_delta_codes", "proposed_dac_code")
            )
        max_error = max(max_error, error_difference)
        max_delta = max(max_delta, delta_difference)
        valid = valid and exact
        comparisons.append({
            "control_seq": row["control_seq"], "reason": reason,
            "host_reason": host["reason"], "preview": host["preview_available"],
            "pass": exact,
        })
    fault_positions = [index for index, row in enumerate(rows) if row["control_state"] == "FAULT"]
    recovery_positions = [index for index, row in enumerate(rows) if row["decision_reason_code"] == "explicit_recovery_fresh_support"]
    terminal_positions = [index for index, row in enumerate(rows) if _bool(row["preview_available"])]
    mechanism = (
        bool(fault_positions) and len(recovery_positions) == 1 and bool(terminal_positions)
        and fault_positions[0] < recovery_positions[0] < terminal_positions[-1]
    )
    return Check(
        "controller_host_firmware_and_recovery_parity", valid and mechanism,
        f"{len(rows)} controls; faults {len(fault_positions)}, recoveries {len(recovery_positions)}, previews {len(terminal_positions)}; max differences {max_error:.17g} Hz/{max_delta:.17g} codes",
    ), {"wrap_count": wraps, "comparisons": comparisons}


def analyze(
    run_dir: Path, *, build_manifest: Path, uf2: Path,
) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise RuntimeError("capture still in progress")
    manifest = load_manifest(run_dir)
    if manifest.stage != EXPECTED_STAGE or manifest.is_template:
        raise ValueError("run is not an instantiated Stage 6 dual-core proof")
    raw_log = run_dir / "raw" / "serial.log"
    counts = _rows_for(manifest, run_dir, "count_observations_v1")
    snapshots = _rows_for(manifest, run_dir, "pps_snapshots_v1")
    references = _rows_for(manifest, run_dir, "raw_events_v1")
    health = _rows_for(manifest, run_dir, "health_v1")
    dac = _rows_for(manifest, run_dir, "dac_steps_v1")
    estimates = _rows_for(manifest, run_dir, "estimates_v2")
    controls = _rows_for(manifest, run_dir, "control_previews_v1")
    active = _rows_for(manifest, run_dir, "active_transactions_v1")
    checks: list[Check] = []

    firmware = manifest.data["firmware"]
    build_ok = (
        firmware["git_commit"] == EXPECTED_COMMIT
        and firmware["source_sha256"] == EXPECTED_SOURCE
        and firmware["configuration_sha256"] == EXPECTED_CONFIG
        and firmware["uf2_sha256"] == EXPECTED_UF2
        and _sha256_file(build_manifest) == EXPECTED_BUILD_MANIFEST
        and _sha256_file(uf2) == EXPECTED_UF2
    )
    checks.append(Check("exact_clean_firmware_artifact", build_ok, f"commit {firmware['git_commit']}; UF2 {firmware['uf2_sha256']}"))
    continuity, count_by_seq = _check_continuity(counts, snapshots, references)
    checks.extend(Check(item.identifier, item.passed, item.evidence) for item in continuity)
    estimator_check, estimates_by_id = _estimator_parity(
        estimates, count_by_seq, manifest.data["selected_estimator"]["profile_sha256"]
    )
    checks.append(estimator_check)
    controller_check, parity = _controller_parity(controls, estimates_by_id)
    checks.append(controller_check)

    exact_dac = (
        len(dac) == 1 and dac[0]["event"] == "manual_apply"
        and int(dac[0]["dac_code_requested"]) == EXPECTED_CODE
        and int(dac[0]["dac_code_applied"]) == EXPECTED_CODE
        and int(dac[0]["dac_code_clamped"]) == 0 and int(dac[0]["flags"]) == 0
        and not active
    )
    checks.append(Check("no_feedback_actuation", exact_dac, f"{len(dac)} idempotent manual DAC row; {len(active)} active rows"))

    markers = _host_markers(raw_log)
    started = _one_marker(markers, "capture_started")
    stopped = _one_marker(markers, "capture_stopped")
    sent = [row["command"] for row in markers if row.get("event") == "host_command_sent"]
    expected_counts = {
        "CONFIG?": 61, "DAC SET 0xA82A": 1,
        "DUALCORE INVALIDATE_GNSS": 1, "DUALCORE RECOVER": 1, "DUALCORE?": 1,
    }
    commands_ok = len(sent) == sum(expected_counts.values()) and all(sent.count(command) == count for command, count in expected_counts.items())
    partial_line_drops = [
        row for row in markers if row.get("event") == "partial_line_dropped"
    ]
    duration = _utc_seconds(str(stopped["utc"])) - _utc_seconds(str(started["utc"]))
    transport_ok = (
        commands_ok
        and duration >= 4790
        and not partial_line_drops
        and all(
            int(stopped.get(key, -1)) == 0 for key in
            ("malformed_utf8", "parser_errors", "reconnect_count", "commands_rejected")
        )
    )
    checks.append(Check(
        "predetermined_schedule_and_transport",
        transport_ok,
        f"{len(sent)} exact commands; capture {duration:.0f} s; partial-line drops {len(partial_line_drops)}",
    ))

    latest = _latest_health(health)
    critical_reasons = {
        row["status_value"] for row in health
        if row["component"] in {"gnss_qualification", "cx317_preview"}
        and row["status_key"] == "critical_record"
    }
    required_reasons = {
        "controlled_fixture_invalidation", "receiver_metadata_requalified",
        "explicit_recovery_accepted_fresh_support_required",
    }
    queue_ok = (
        latest.get(("dual_core", "partition_fault")) == "none"
        and latest.get(("dual_core", "fail_static")) == "false"
        and int(latest.get(("dual_core", "observation_high_water"), "0")) > 0
        and int(latest.get(("dual_core", "critical_high_water"), "0")) > 0
        and latest.get(("cx317_preview", "active_live_update_codes")) == "0"
        and latest.get(("cx317_preview", "actuation_authorized")) == "false"
        and latest.get(("cx317_preview", "actionable")) == "false"
        and required_reasons <= critical_reasons
    )
    checks.append(Check("dual_core_queue_gnss_recovery_and_authority", queue_ok, f"critical reasons {sorted(critical_reasons)}; telemetry drops {latest.get(('dual_core', 'telemetry_dropped'))}"))

    latest_identity = {
        ("firmware", "version"): "CX317_DUAL_CORE_POST_CAMPAIGN_PREVIEW_V1",
        ("firmware", "config_id"): "cx317_pps_gated_i_only_preview",
        ("firmware", "git_commit"): EXPECTED_COMMIT,
        ("firmware", "source_hash"): EXPECTED_SOURCE,
        ("firmware", "config_hash"): EXPECTED_CONFIG,
        ("build", "profile_id"): "cx317_pps_gated_i_only_preview",
        ("build", "tcxo_counter_backend"): "pps_gated_ratio",
    }
    identity_ok = all(latest.get(key) == value for key, value in latest_identity.items())
    checks.append(Check("live_identity", identity_ok, f"{sum(latest.get(key) == value for key, value in latest_identity.items())}/{len(latest_identity)} fields exact"))

    passed = all(check.passed for check in checks)
    result = {
        "schema_version": 1, "status": "pass" if passed else "fail",
        "run_id": manifest.run_id, "tool": "cx317_stage6_dual_core_analyze_v1",
        "capture_duration_s": duration, "checks": [asdict(check) for check in checks],
        "controller_parity": parity,
        "authority": {"actionable": False, "actuation_authorized": False, "active_live_update_codes": 0},
        "artifact_hashes": {
            "policy": _sha256_file(POST_CAMPAIGN_POLICY),
            "build_manifest": _sha256_file(build_manifest), "uf2": _sha256_file(uf2),
            "raw_log": _sha256_file(raw_log),
        },
    }
    output = run_dir / "derived" / "stage6_dual_core_live_proof_v1.json"
    _write_atomic(output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    report = [
        "# Stage 6 dual-core live proof", "", f"Result: **{result['status'].upper()}**", "",
        f"Capture duration: {duration:.0f} s; controls: {len(controls)}; estimates: {len(estimates)}.", "",
        "| Gate | Result | Evidence |", "|---|---:|---|",
    ]
    report.extend(f"| {check.identifier} | {'PASS' if check.passed else 'FAIL'} | {check.evidence} |" for check in checks)
    _write_atomic(run_dir / "reports" / "STAGE6_DUAL_CORE_LIVE_PROOF.md", "\n".join(report) + "\n")
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output, result = analyze(args.run_dir, build_manifest=args.build_manifest, uf2=args.uf2)
    except (FileNotFoundError, KeyError, TypeError, ValueError, RuntimeError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
