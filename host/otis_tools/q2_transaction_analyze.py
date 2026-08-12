"""Independently replay the bounded Q2 transaction evidence."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


TOOL_ID = "cx319_q2_transaction_analyzer_v2"
BUNDLE_PATH = Path("cx319_q2_exact_bundle_v1.json")
OPERATOR_CONFIRMATION_PATH = Path("reports/q2_operator_inhibition_confirmation_v1.json")
SETUP_AUTHORITY_PATH = Path("reports/q2_setup_authority_input_v1.json")
FLASH_RECORD_PATH = Path("reports/q2_exact_flash_v1.json")
ANALYSIS_PATH = Path("reports/cx319_q2_transaction_analysis_v1.json")
REPORT_PATH = Path("reports/cx319_q2_transaction_analysis_v1.md")
SEAL_PATH = Path("reports/cx319_q2_transaction_seal_v1.json")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def expected_cases() -> dict[int, dict[str, object]]:
    names = [
        "initial_status_generation_mismatch",
        "initial_query_nonce_mismatch",
        "initial_session_mismatch",
        "initial_expired_authority",
        "initial_requested_code_mismatch",
        "initial_one_shot_ordinal_mismatch",
        "initial_configuration_mismatch",
        "initial_capture_lease_absent",
        "initial_gnss_ineligible",
        "initial_reference_ineligible",
        "initial_partition_unhealthy",
        "initial_active_not_disarmed",
        "initial_setup_already_applied",
    ]
    cases: dict[int, dict[str, object]] = {}
    for case_id, name in enumerate(names, start=1):
        cases[case_id] = {
            "case_name": name,
            "transaction": "setup",
            "disposition": "rejected_before_authorization",
            "phase_mask": 1,
            "setup_i2c_attempts": 0,
            "automatic_i2c_attempts": 0,
            "retry_rejected": False,
        }
    names = [
        "stale_status_generation",
        "stale_query_nonce",
        "stale_session",
        "stale_expiry",
        "stale_expected_code",
        "stale_configuration",
        "stale_capture_lease",
        "stale_gnss_eligibility",
        "stale_reference_eligibility",
        "stale_partition_health",
        "stale_active_state",
        "stale_setup_applied_state",
    ]
    for case_id, name in enumerate(names, start=14):
        cases[case_id] = {
            "case_name": name,
            "transaction": "setup",
            "disposition": "rejected_before_release",
            "phase_mask": 71,
            "setup_i2c_attempts": 0,
            "automatic_i2c_attempts": 0,
            "retry_rejected": True,
        }
    names = [
        "execution_expired",
        "execution_expected_code_changed",
        "execution_configuration_changed",
        "execution_partition_unhealthy",
        "execution_actuator_unready",
    ]
    for case_id, name in enumerate(names, start=26):
        cases[case_id] = {
            "case_name": name,
            "transaction": "setup",
            "disposition": "rejected_before_i2c",
            "phase_mask": 79,
            "setup_i2c_attempts": 0,
            "automatic_i2c_attempts": 0,
            "retry_rejected": True,
        }
    interruption_masks = [0, 1, 3, 7, 15, 31]
    interruption_names = [
        "interrupt_before_receive",
        "interrupt_after_receive",
        "interrupt_after_authorization",
        "interrupt_after_core0_acceptance",
        "interrupt_after_release",
        "interrupt_after_consumption_before_i2c",
    ]
    for offset, (name, mask) in enumerate(
        zip(interruption_names, interruption_masks), start=31
    ):
        cases[offset] = {
            "case_name": name,
            "transaction": "setup",
            "disposition": "interrupted_fail_static",
            "phase_mask": mask,
            "setup_i2c_attempts": 0,
            "automatic_i2c_attempts": 0,
            "retry_rejected": offset == 36,
        }
    cases[37] = {
        "case_name": "setup_i2c_failure_terminal_then_recovery_ready",
        "transaction": "setup",
        "disposition": "failed_once_no_retry_recovery_new_guard",
        "phase_mask": 223,
        "setup_i2c_attempts": 1,
        "automatic_i2c_attempts": 0,
        "retry_rejected": True,
    }
    cases[38] = {
        "case_name": "automatic_ambiguous_application_terminal_then_recovery_ready",
        "transaction": "automatic",
        "disposition": "ambiguous_once_fault_no_retry_recovery_new_transaction",
        "phase_mask": 219,
        "setup_i2c_attempts": 0,
        "automatic_i2c_attempts": 1,
        "retry_rejected": True,
    }
    return cases


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _q2_case_evidence(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    completed: dict[int, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for row in rows:
        if row.get("component") != "q2_transaction":
            continue
        key = row.get("status_key", "")
        value = row.get("status_value", "")
        if key == "case_begin":
            if current is not None:
                raise ValueError("Q2 case began before the prior case completed")
            current = {"case_begin": value}
            continue
        if current is None:
            continue
        if key in current:
            raise ValueError(f"duplicate Q2 case field: {key}")
        current[key] = value
        if key == "case_complete":
            case_id = int(value)
            if case_id in completed:
                raise ValueError(f"duplicate completed Q2 case {case_id}")
            completed[case_id] = current
            current = None
    if current is not None:
        raise ValueError("final Q2 case is incomplete")
    return completed


def _case_checks(rows: list[dict[str, str]]) -> tuple[dict[str, bool], dict[str, Any]]:
    observed = _q2_case_evidence(rows)
    expected = expected_cases()
    details: dict[str, Any] = {}
    checks: dict[str, bool] = {"all_38_cases_present_once": set(observed) == set(expected)}
    nonces: set[int] = set()
    for case_id, contract in expected.items():
        row = observed.get(case_id, {})
        try:
            nonce = int(row.get("query_nonce", "0"))
            phase_mask = int(row.get("phase_mask", "-1"))
            setup_attempts = int(row.get("setup_i2c_attempts", "-1"))
            automatic_attempts = int(row.get("automatic_i2c_attempts", "-1"))
        except ValueError:
            nonce = 0
            phase_mask = setup_attempts = automatic_attempts = -1
        if nonce:
            nonces.add(nonce)
        exact = (
            row.get("case_begin") == str(case_id)
            and row.get("case_id") == str(case_id)
            and row.get("case_complete") == str(case_id)
            and row.get("case_name") == contract["case_name"]
            and row.get("transaction") == contract["transaction"]
            and row.get("disposition") == contract["disposition"]
            and phase_mask == contract["phase_mask"]
            and setup_attempts == contract["setup_i2c_attempts"]
            and automatic_attempts == contract["automatic_i2c_attempts"]
            and (row.get("retry_rejected") == "true")
            is contract["retry_rejected"]
            and row.get("case_pass") == "true"
            and nonce > 0
        )
        checks[f"case_{case_id:02d}_{contract['case_name']}"] = exact
        details[str(case_id)] = {"expected": contract, "observed": row}
    checks["nonce_bound_unique_cases"] = len(nonces) == len(expected)
    checks["one_injected_setup_failure_attempt"] = sum(
        int(row.get("setup_i2c_attempts", "0")) for row in observed.values()
    ) == 1
    checks["one_injected_automatic_ambiguous_attempt"] = sum(
        int(row.get("automatic_i2c_attempts", "0")) for row in observed.values()
    ) == 1
    return checks, details


def _setup_evidence(
    rows: list[dict[str, str]], authority: dict[str, Any]
) -> tuple[list[str], list[str]]:
    request = authority["request"]
    phases: list[str] = []
    critical_records: list[str] = []
    active = False
    matching: dict[str, str] = {}
    for row in rows:
        if row.get("component") != "cx317_setup":
            continue
        key = row.get("status_key", "")
        value = row.get("status_value", "")
        if key == "phase":
            if active and all(
                matching.get(name) == str(request[name])
                for name in (
                    "authorization_sequence",
                    "status_generation",
                    "query_nonce",
                )
            ):
                phases.append(matching["phase"])
                critical = matching.get("critical_record")
                if critical:
                    critical_records.append(critical)
            matching = {"phase": value}
            active = True
        elif active:
            matching[key] = value
    if active and all(
        matching.get(name) == str(request[name])
        for name in ("authorization_sequence", "status_generation", "query_nonce")
    ):
        phases.append(matching["phase"])
        critical = matching.get("critical_record")
        if critical:
            critical_records.append(critical)
    return phases, critical_records


def _setup_acknowledgement_complete(
    phases: list[str], critical_records: list[str]
) -> bool:
    required_phases = {
        "firmware_received",
        "core1_authorized",
        "core0_accepted",
        "core1_execution_released",
        "applied",
    }
    required_critical_records = {
        "core1_current_setup_authority_accepted",
        "core1_execution_released_after_current_recheck",
    }
    # Cross-core producers can reach the USB serializer in a different order
    # from their causal state transitions. Identity-bound phase/critical sets
    # plus the separately checked single physical DAC row are the contract.
    return (
        bool(phases)
        and phases[0] == "firmware_received"
        and required_phases.issubset(phases)
        and required_critical_records.issubset(critical_records)
        and not ({"failed", "rejected"} & set(phases))
    )


def analyze(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    bundle = json.loads((run_dir / BUNDLE_PATH).read_text(encoding="utf-8"))
    confirmation = json.loads(
        (run_dir / OPERATOR_CONFIRMATION_PATH).read_text(encoding="utf-8")
    )
    authority = json.loads(
        (run_dir / SETUP_AUTHORITY_PATH).read_text(encoding="utf-8")
    )
    flash = json.loads((run_dir / FLASH_RECORD_PATH).read_text(encoding="utf-8"))
    capture = json.loads(
        (run_dir / "reports/capture_device_state.json").read_text(encoding="utf-8")
    )
    health = _read_csv(run_dir / "csv/health.csv")
    dac = _read_csv(run_dir / "csv/dac_steps.csv")
    latest_status = {
        (row.get("component", ""), row.get("status_key", "")): row.get(
            "status_value", ""
        )
        for row in health
    }
    case_checks, case_details = _case_checks(health)
    phases, critical_records = _setup_evidence(health, authority)
    setup_rows = [row for row in dac if row.get("event") == "manual_apply"]
    expected_setup_code = int(bundle["firmware"]["start_code"])
    checks = {
        "bundle_digest_exact": bundle.get("bundle_sha256")
        == _canonical_sha256(
            {key: value for key, value in bundle.items() if key != "bundle_sha256"}
        ),
        "operator_confirmed_oscillator_control_input_isolated": (
            confirmation.get("confirmed") is True
            and confirmation.get("topology")
            == "dac_analogue_output_disconnected_from_oscillator_efc_vctrl"
            and confirmation.get("oscillator_powered") is True
            and confirmation.get("dac_i2c_reachable") is True
        ),
        "exact_q2_flash_passed": (
            flash.get("status") == "pass"
            and flash.get("uf2_sha256") == bundle["firmware"]["uf2"]["sha256"]
        ),
        "emitted_firmware_identity_exact": (
            latest_status.get(("firmware", "source_hash"))
            == bundle["firmware"]["source_sha256"]
            and latest_status.get(("firmware", "config_hash"))
            == bundle["firmware"]["configuration_sha256"]
            and latest_status.get(("build", "profile_id"))
            == bundle["firmware"]["profile_id"]
        ),
        "physical_dac_reachable_before_transaction": (
            latest_status.get(("dac", "enabled")) == "true"
            and latest_status.get(("dac", "initialized")) == "true"
            and latest_status.get(("dac", "i2c_address")) == "76"
        ),
        "capture_closed_cleanly": (
            capture.get("capture_active") is False
            and capture.get("parser_errors") == 0
            and capture.get("commands_rejected") == 0
            and capture.get("reconnect_count") == 0
        ),
        **case_checks,
        "production_setup_exact_acknowledgement_path": (
            _setup_acknowledgement_complete(phases, critical_records)
        ),
        "one_physical_inhibited_setup_write": (
            len(setup_rows) == 1
            and setup_rows[0].get("dac_code_requested") == str(expected_setup_code)
            and setup_rows[0].get("dac_code_applied") == str(expected_setup_code)
        ),
        "zero_automatic_physical_writes": len(dac) == len(setup_rows) == 1,
        "setup_authority_bound_to_complete_snapshot": (
            int(authority["request"]["status_generation"]) > 0
            and int(authority["request"]["query_nonce"]) > 0
            and authority.get("snapshot", {}).get("snapshot_generation_complete")
            == str(authority["request"]["status_generation"])
            and authority.get("snapshot", {}).get("query_nonce")
            == str(authority["request"]["query_nonce"])
        ),
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "pass" if all(checks.values()) else "fail",
        "run_id": run_dir.name,
        "checks": checks,
        "case_replay": case_details,
        "production_setup_phases": phases,
        "production_setup_critical_records": critical_records,
        "physical_dac_rows": dac,
        "claims_boundary": (
            "Q2 proves the finite transaction and acknowledgement cases with "
            "one electrically inhibited physical setup write; it grants no "
            "live oscillator-control or Q4 authority"
        ),
    }
    result["analysis_sha256"] = _canonical_sha256(result)
    return result


def report_markdown(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# CX319 Q2 Inhibited Transaction Rehearsal",
            "",
            f"Status: **{result['status'].upper()}**",
            "",
            *[
                f"- {'PASS' if passed else 'FAIL'} — `{name}`"
                for name, passed in result["checks"].items()
            ],
            "",
            result["claims_boundary"] + ".",
            "",
        ]
    )


def seal(run_dir: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    if analysis.get("status") != "pass":
        raise ValueError("cannot seal a failed Q2 analysis")
    evidence_path = run_dir / "evidence_manifest.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    bundle = json.loads((run_dir / BUNDLE_PATH).read_text(encoding="utf-8"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": "cx319_q2_inhibited_transaction_seal_v1",
        "tool": TOOL_ID,
        "status": "pass",
        "run_id": run_dir.name,
        "analysis_sha256": _sha256_file(run_dir / ANALYSIS_PATH),
        "evidence_snapshot_sha256": _sha256_file(evidence_path),
        "evidence_snapshot_digest": evidence["snapshot_digest"],
        "bundle_sha256": bundle["bundle_sha256"],
        "uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "physical_setup_writes": 1,
        "physical_automatic_writes": 0,
        "physical_oscillator_movement_possible": False,
        "live_authority_granted": False,
    }
    payload["seal_sha256"] = _canonical_sha256(payload)
    return payload
