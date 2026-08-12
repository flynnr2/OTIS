from __future__ import annotations

import csv
import json

from host.otis_tools.q2_transaction_analyze import (
    BUNDLE_PATH,
    FLASH_RECORD_PATH,
    OPERATOR_CONFIRMATION_PATH,
    SETUP_AUTHORITY_PATH,
    _canonical_sha256,
    _case_checks,
    analyze,
    expected_cases,
)


def _rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for case_id, contract in expected_cases().items():
        values = {
            "case_begin": str(case_id),
            "query_nonce": str(0x51A20000 + case_id),
            "case_id": str(case_id),
            "case_name": str(contract["case_name"]),
            "transaction": str(contract["transaction"]),
            "disposition": str(contract["disposition"]),
            "phase_mask": str(contract["phase_mask"]),
            "setup_i2c_attempts": str(contract["setup_i2c_attempts"]),
            "automatic_i2c_attempts": str(contract["automatic_i2c_attempts"]),
            "retry_rejected": str(contract["retry_rejected"]).lower(),
            "case_pass": "true",
            "case_complete": str(case_id),
        }
        rows.extend(
            {
                "component": "q2_transaction",
                "status_key": key,
                "status_value": value,
            }
            for key, value in values.items()
        )
    return rows


def test_independent_q2_case_replay_accepts_exact_matrix() -> None:
    checks, details = _case_checks(_rows())
    assert all(checks.values())
    assert len(details) == 38


def test_independent_q2_case_replay_rejects_one_changed_disposition() -> None:
    rows = _rows()
    changed = next(
        row
        for row in rows
        if row["status_key"] == "disposition"
        and row["status_value"] == "ambiguous_once_fault_no_retry_recovery_new_transaction"
    )
    changed["status_value"] = "applied"
    checks, _ = _case_checks(rows)
    assert checks["case_38_automatic_ambiguous_application_terminal_then_recovery_ready"] is False


def test_full_q2_analyzer_replays_fixture(tmp_path) -> None:
    run_dir = tmp_path / "q2_fixture"
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "csv").mkdir()
    bundle = {
        "schema_version": 1,
        "firmware": {
            "profile_id": "cx319_q2_inhibited_transaction",
            "source_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "start_code": 0xA808,
            "uf2": {"sha256": "c" * 64},
        },
    }
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    (run_dir / BUNDLE_PATH).write_text(json.dumps(bundle), encoding="utf-8")
    (run_dir / OPERATOR_CONFIRMATION_PATH).write_text(
        json.dumps(
            {
                "confirmed": True,
                "topology": "dac_analogue_output_disconnected_from_oscillator_efc_vctrl",
                "oscillator_powered": True,
                "dac_i2c_reachable": True,
            }
        ),
        encoding="utf-8",
    )
    request = {
        "authorization_sequence": 1,
        "status_generation": 41,
        "query_nonce": 99,
    }
    (run_dir / SETUP_AUTHORITY_PATH).write_text(
        json.dumps(
            {
                "request": request,
                "snapshot": {
                    "snapshot_generation_complete": "41",
                    "query_nonce": "99",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / FLASH_RECORD_PATH).write_text(
        json.dumps({"status": "pass", "uf2_sha256": "c" * 64}),
        encoding="utf-8",
    )
    (run_dir / "reports/capture_device_state.json").write_text(
        json.dumps(
            {
                "capture_active": False,
                "parser_errors": 0,
                "commands_rejected": 0,
                "reconnect_count": 0,
            }
        ),
        encoding="utf-8",
    )
    health_rows = _rows()
    for component, key, value in (
        ("firmware", "source_hash", "a" * 64),
        ("firmware", "config_hash", "b" * 64),
        ("build", "profile_id", "cx319_q2_inhibited_transaction"),
        ("dac", "enabled", "true"),
        ("dac", "initialized", "true"),
        ("dac", "i2c_address", "76"),
    ):
        health_rows.append(
            {"component": component, "status_key": key, "status_value": value}
        )
    for phase in (
        "firmware_received",
        "core1_authorized",
        "core0_accepted",
        "core1_execution_released",
        "applied",
    ):
        health_rows.extend(
            [
                {"component": "cx317_setup", "status_key": "phase", "status_value": phase},
                {"component": "cx317_setup", "status_key": "authorization_sequence", "status_value": "1"},
                {"component": "cx317_setup", "status_key": "status_generation", "status_value": "41"},
                {"component": "cx317_setup", "status_key": "query_nonce", "status_value": "99"},
            ]
        )
    with (run_dir / "csv/health.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["component", "status_key", "status_value"])
        writer.writeheader()
        writer.writerows(health_rows)
    with (run_dir / "csv/dac_steps.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["event", "dac_code_requested", "dac_code_applied"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "event": "manual_apply",
                "dac_code_requested": str(0xA808),
                "dac_code_applied": str(0xA808),
            }
        )
    result = analyze(run_dir)
    assert result["status"] == "pass"
    assert all(result["checks"].values())
