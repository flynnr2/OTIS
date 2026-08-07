from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from host.otis_tools.contracts import HEALTH_FIELDS
from host.otis_tools.cx317_stage7_manifest import create_stage7_manifest
from host.otis_tools.cx317_stage7_transport_rehearsal_analyze import analyze


def _build(tmp_path: Path) -> tuple[Path, Path]:
    uf2 = tmp_path / "candidate.uf2"
    uf2.write_bytes(b"transport-rehearsal")
    source_sha = "a" * 64
    config_sha = "b" * 64
    build = {
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "sha256": source_sha,
                "state": "clean",
            },
            "configuration": {
                "profile_id": "cx317_dual_core_active_rehearsal",
                "sha256": config_sha,
                "defines": {
                    "OTIS_CX317_ACTIVE_START_CODE": "0xA800u",
                    "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "2u",
                    "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "42u",
                    "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
                    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
                    "OTIS_GNSS_UART_TX_ENABLED": "0",
                    "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG": "120u",
                    "OTIS_FC0_STARTUP_INHIBIT_MS": "60000u",
                    "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS": "3u",
                    "OTIS_CX317_STARTUP_WARMUP_S": "60u",
                    "OTIS_CX317_SETTLING_EXCLUSION_S": "60u",
                    "OTIS_CX317_FULL_HISTORY_RESET_S": "180u",
                    "OTIS_CX317_RECOVERY_FRESH_SUPPORT_S": "120u",
                    "OTIS_CX317_DECISION_CADENCE_S": "240u",
                    "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "240u",
                },
            },
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
                "size_bytes": uf2.stat().st_size,
            }
        ],
    }
    manifest = tmp_path / "firmware_build_manifest.json"
    manifest.write_text(json.dumps(build), encoding="utf-8")
    return manifest, uf2


def _write_health(run: Path) -> None:
    path = run / "csv/health.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for sequence, (key, value) in enumerate(
        (
            ("state", "ABORTED"),
            ("evidence_phase", "evidence_clear"),
            ("correction_count", "0"),
        ),
        1,
    ):
        row = {field: "" for field in HEALTH_FIELDS}
        row.update(
            {
                "record_type": "STS",
                "schema_version": "1",
                "status_seq": str(sequence),
                "timestamp_ticks": str(sequence),
                "status_domain": "rp2040_timer0",
                "component": "cx317_active",
                "status_key": key,
                "status_value": value,
                "severity": "INFO",
                "flags": "0",
            }
        )
        rows.append(row)
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEALTH_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_transport_rehearsal_analyzer_passes_exact_priority_abort(
    tmp_path: Path,
) -> None:
    build_manifest, uf2 = _build(tmp_path)
    run = tmp_path / "transport_run"
    create_stage7_manifest(
        part="rehearsal",
        start_code=0xA800,
        run_dir=run,
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.test",
        rehearsal_kind="transport_fault",
    )
    _write_health(run)
    (run / "reports").mkdir(parents=True, exist_ok=True)
    (run / "reports/capture_device.log").write_text(
        "file-backed\n", encoding="utf-8"
    )
    (run / "reports/capture_device_state.json").write_text(
        json.dumps(
            {
                "capture_active": False,
                "serial_open": False,
                "normal_command_batch_limit": 1,
                "normal_command_max_age_s": 2.0,
                "write_timeout_s": 1.0,
                "emergency_aborts_sent": 1,
            }
        ),
        encoding="utf-8",
    )
    (run / "reports/cx317_active_supervisor_state.json").write_text(
        json.dumps(
            {
                "terminal": {
                    "result": "aborted",
                    "reason": (
                        "stage7_supervisor_fault:[Errno 35] Resource "
                        "temporarily unavailable"
                    ),
                }
            }
        ),
        encoding="utf-8",
    )
    events = [
        {
            "event": "stage7_supervisor_fault",
            "error": "[Errno 35] Resource temporarily unavailable",
        },
        {
            "event": "emergency_device_abort_submitted",
            "reason": "stage7_supervisor_fault",
        },
    ]
    (run / "reports/cx317_active_supervisor_events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events),
        encoding="utf-8",
    )
    (run / "raw").mkdir(parents=True, exist_ok=True)
    markers = [
        {"event": "command_ingress_opened", "path": "normal", "batch_limit": 1, "normal_command_max_age_s": 2.0},
        {"event": "emergency_command_ingress_opened", "path": "emergency"},
        {"event": "emergency_abort_latched"},
        {"event": "normal_command_ingress_revoked", "buffered_bytes_discarded": 0},
        {"event": "host_command_accepted", "command": "ACTIVE ABORT"},
        {"event": "host_command_sent", "command": "ACTIVE ABORT", "bytes_written": 13},
        {"event": "emergency_abort_sent"},
        {
            "event": "capture_stopped",
            "malformed_utf8": 0,
            "parser_errors": 0,
            "reconnect_count": 0,
            "commands_rejected": 0,
            "emergency_aborts_sent": 1,
            "emergency_abort_latched": True,
        },
    ]
    (run / "raw/serial.log").write_text(
        "".join("# OTIS_HOST " + json.dumps(row) + "\n" for row in markers),
        encoding="utf-8",
    )
    saturation = run / "reports/transport_fault_injection.json"
    saturation.write_text(
        json.dumps(
            {
                "status": "pass",
                "normal_fifo_saturated": True,
                "timestamped_config_queries_queued": 100,
                "capture_resumed": True,
                "capture_pid": 1234,
                "serial_owner_pids": [1234],
                "sole_serial_owner_verified": True,
            }
        ),
        encoding="utf-8",
    )

    _, result = analyze(
        run,
        build_manifest=build_manifest,
        uf2=uf2,
        saturation_report=saturation,
    )

    assert result["status"] == "pass"
    assert all(result["criteria"].values())
