"""Exercise the actual Q2 analyzer, evidence snapshot, seal and registration path."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .contracts import CONTRACT_FIELDS
from .evidence import create_evidence_snapshot
from .evidence_index import register_package
from .q2_transaction_analyze import (
    ANALYSIS_PATH,
    BUNDLE_PATH,
    FLASH_RECORD_PATH,
    OPERATOR_CONFIRMATION_PATH,
    REPORT_PATH,
    SEAL_PATH,
    SETUP_AUTHORITY_PATH,
    _canonical_sha256,
    analyze,
    expected_cases,
    report_markdown,
    seal,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _health_row(component: str, key: str, value: str, sequence: int) -> dict[str, str]:
    row = {field: "" for field in CONTRACT_FIELDS["health_v1"]}
    row.update(
        {
            "record_type": "STS",
            "schema_version": "1",
            "status_seq": str(sequence),
            "timestamp_ticks": str(sequence * 16000),
            "status_domain": "rp2040_timer0",
            "component": component,
            "status_key": key,
            "status_value": value,
            "severity": "INFO",
            "flags": "0",
        }
    )
    return row


def create_replay_fixture(run_dir: Path) -> dict[str, Any]:
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "csv").mkdir()
    (run_dir / "reports").mkdir()
    source_hash = "a" * 64
    config_hash = "b" * 64
    uf2_hash = "c" * 64
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": "cx319_q2_inhibited_transaction_bundle_v1",
        "gate": "Q2",
        "source_revision": "d" * 40,
        "firmware": {
            "profile_id": "cx319_q2_inhibited_transaction",
            "source_sha256": source_hash,
            "configuration_sha256": config_hash,
            "start_code": 0xA808,
            "uf2": {"sha256": uf2_hash},
            "build_manifest": {"sha256": "e" * 64},
        },
    }
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    _write_json(run_dir / BUNDLE_PATH, bundle)
    _write_json(
        run_dir / OPERATOR_CONFIRMATION_PATH,
        {
            "confirmed": True,
            "topology": "dac_analogue_output_disconnected_from_oscillator_efc_vctrl",
            "oscillator_powered": True,
            "dac_i2c_reachable": True,
        },
    )
    request = {
        "authorization_sequence": 1,
        "status_generation": 41,
        "query_nonce": 99,
    }
    _write_json(
        run_dir / SETUP_AUTHORITY_PATH,
        {
            "request": request,
            "snapshot": {
                "snapshot_generation_complete": "41",
                "query_nonce": "99",
            },
        },
    )
    _write_json(
        run_dir / FLASH_RECORD_PATH,
        {"status": "pass", "uf2_sha256": uf2_hash},
    )
    _write_json(
        run_dir / "reports/capture_device_state.json",
        {
            "capture_active": False,
            "parser_errors": 0,
            "commands_rejected": 0,
            "reconnect_count": 0,
        },
    )

    health: list[dict[str, str]] = []
    sequence = 1
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
        for key, value in values.items():
            health.append(_health_row("q2_transaction", key, value, sequence))
            sequence += 1
    for component, key, value in (
        ("firmware", "source_hash", source_hash),
        ("firmware", "config_hash", config_hash),
        ("build", "profile_id", "cx319_q2_inhibited_transaction"),
        ("dac", "enabled", "true"),
        ("dac", "initialized", "true"),
        ("dac", "i2c_address", "76"),
    ):
        health.append(_health_row(component, key, value, sequence))
        sequence += 1
    for phase in (
        "firmware_received",
        "core1_authorized",
        "core0_accepted",
        "core1_execution_released",
        "applied",
    ):
        for key, value in (
            ("phase", phase),
            ("authorization_sequence", "1"),
            ("status_generation", "41"),
            ("query_nonce", "99"),
        ):
            health.append(_health_row("cx317_setup", key, value, sequence))
            sequence += 1
    with (run_dir / "csv/health.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS["health_v1"])
        writer.writeheader()
        writer.writerows(health)
    dac = {field: "" for field in CONTRACT_FIELDS["dac_steps_v1"]}
    dac.update(
        {
            "record_type": "DAC",
            "schema_version": "1",
            "seq": "1",
            "elapsed_ms": "1000",
            "step_index": "9",
            "dac_code_requested": str(0xA808),
            "dac_code_applied": str(0xA808),
            "dac_code_clamped": "0",
            "dwell_ms": "0",
            "event": "manual_apply",
            "flags": "0",
        }
    )
    with (run_dir / "csv/dac_steps.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS["dac_steps_v1"])
        writer.writeheader()
        writer.writerow(dac)
    (run_dir / "raw/serial.log").write_text("# deterministic Q2 replay fixture\n", encoding="utf-8")
    _write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": 1,
            "run_id": run_dir.name,
            "template": False,
            "files": [
                {"path": "csv/health.csv", "contract": "health_v1"},
                {"path": "csv/dac_steps.csv", "contract": "dac_steps_v1"},
            ],
            "evidence_artifacts": [
                BUNDLE_PATH.as_posix(),
                OPERATOR_CONFIRMATION_PATH.as_posix(),
                SETUP_AUTHORITY_PATH.as_posix(),
                FLASH_RECORD_PATH.as_posix(),
                ANALYSIS_PATH.as_posix(),
                REPORT_PATH.as_posix(),
            ],
        },
    )
    return bundle


def run_operational_rehearsal(root: Path) -> dict[str, Any]:
    run_dir = root / "q2_operational_replay"
    index_path = root / "evidence_index_v1.json"
    bundle = create_replay_fixture(run_dir)
    analysis = analyze(run_dir)
    _write_json(run_dir / ANALYSIS_PATH, analysis)
    (run_dir / REPORT_PATH).write_text(report_markdown(analysis), encoding="utf-8")
    (run_dir / "COMPLETE").touch()
    create_evidence_snapshot(run_dir)
    seal_value = seal(run_dir, analysis)
    _write_json(run_dir / SEAL_PATH, seal_value)
    registered = register_package(
        index_path=index_path,
        package_path=run_dir,
        source_revision=bundle["source_revision"],
        build_identity=bundle["firmware"]["build_manifest"]["sha256"],
        profile_identity=bundle["firmware"]["profile_id"],
        attempt_classification="successful_rehearsal",
        result_or_failure_reason="Q2 deterministic operational-path replay passed",
        analyzer_identity=sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    return {
        "status": analysis["status"],
        "all_checks_passed": all(analysis["checks"].values()),
        "seal_sha256": seal_value["seal_sha256"],
        "registered_content_sha256": registered["content_sha256"],
    }
