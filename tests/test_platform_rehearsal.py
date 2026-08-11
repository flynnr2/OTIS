from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

import host.otis_tools.platform_rehearsal as rehearsal
from host.otis_tools.board_identity import EXPECTED_SERIAL
from host.otis_tools.contracts import CONTRACT_FIELDS


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "firmware/arduino/firmware_matrix.json"


def _write_csv(path: Path, contract: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = CONTRACT_FIELDS[contract]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            value = {field: "" for field in fields}
            value.update(row)
            writer.writerow(value)


def _fake_build(tmp_path: Path, matrix_path: Path) -> tuple[Path, Path]:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    profile = next(
        item for item in matrix["profiles"] if item["id"] == rehearsal.PROFILE_ID
    )
    uf2 = tmp_path / "firmware.uf2"
    uf2.write_bytes(b"fixed non-actuating firmware")
    build = {
        "schema_version": 1,
        "provenance": {
            "configuration": {
                "profile_id": rehearsal.PROFILE_ID,
                "defines": profile["defines"],
                "fqbn": matrix["target"]["fqbn"],
                "sha256": "c" * 64,
            },
            "source": {
                "git_commit": "1" * 40,
                "state": "dirty",
                "sha256": "s" * 64,
            },
            "invocation": {"id": "i" * 64},
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
                "size_bytes": uf2.stat().st_size,
            }
        ],
        "resource_budget": {
            "contract": "otis_firmware_resource_budget_v1",
            "status": "within_budget",
        },
    }
    manifest = tmp_path / "firmware_build_manifest.json"
    manifest.write_text(json.dumps(build), encoding="utf-8")
    return manifest, uf2


def test_validate_nonactuating_build_binds_current_exact_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_bytes(MATRIX.read_bytes())
    manifest, uf2 = _fake_build(tmp_path, matrix_path)
    monkeypatch.setattr(
        rehearsal, "_current_git_identity", lambda: ("1" * 40, "dirty")
    )
    monkeypatch.setattr(rehearsal, "source_input_hash", lambda **_kw: "s" * 64)
    monkeypatch.setattr(rehearsal, "configuration_hash", lambda *_a, **_kw: "c" * 64)

    result = rehearsal.validate_nonactuating_build(
        matrix_path=matrix_path,
        build_manifest_path=manifest,
        uf2_path=uf2,
    )

    assert result["profile_id"] == rehearsal.PROFILE_ID
    assert result["uf2_sha256"] == sha256(uf2.read_bytes()).hexdigest()
    assert result["resource_budget"]["status"] == "within_budget"


def test_validate_nonactuating_build_rejects_actuator_surface(
    tmp_path: Path,
) -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    profile = next(
        item for item in matrix["profiles"] if item["id"] == rehearsal.PROFILE_ID
    )
    profile["defines"]["OTIS_ENABLE_DAC_AD5693R"] = "1"
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
    manifest = tmp_path / "unused.json"
    uf2 = tmp_path / "unused.uf2"

    with pytest.raises(ValueError, match="actuation/preview authority"):
        rehearsal.validate_nonactuating_build(
            matrix_path=matrix_path,
            build_manifest_path=manifest,
            uf2_path=uf2,
        )


def test_platform_analyzer_passes_complete_priority_abort_rehearsal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    (run / "reports").mkdir(parents=True)
    (run / "raw").mkdir()
    transition = run / rehearsal.HANDOFF_TRANSITION_DIR
    (transition / "reports").mkdir(parents=True)
    binding = {
        "configuration_sha256": "c" * 64,
        "uf2_sha256": "u" * 64,
        "matrix_sha256": "m" * 64,
        "build_manifest_sha256": "b" * 64,
    }
    monkeypatch.setattr(
        rehearsal,
        "validate_nonactuating_build",
        lambda **_kwargs: binding,
    )
    bundle = {
        "schema_version": 1,
        "authority": {"actuation_compiled_out": True},
    }
    bundle["bundle_sha256"] = rehearsal._canonical_sha256(bundle)
    (run / rehearsal.BUNDLE_PATH).write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "firmware": {
                    "configuration_sha256": binding["configuration_sha256"],
                    "uf2_sha256": binding["uf2_sha256"],
                },
                "bundle": {
                    "sha256": rehearsal._sha256_file(
                        run / rehearsal.BUNDLE_PATH
                    )
                },
                "actuation_authorized": False,
                "closed_loop_control": False,
            }
        ),
        encoding="utf-8",
    )
    board = {"serial_number": EXPECTED_SERIAL}
    (run / rehearsal.FLASH_RECORD_PATH).write_text(
        json.dumps(
            {
                "status": "pass",
                "attempt_count": 1,
                "board_before": board,
                "board_after": board,
            }
        ),
        encoding="utf-8",
    )
    (run / rehearsal.TRANSPORT_REPORT_PATH).write_text(
        json.dumps(
            {
                "status": "pass",
                "capture_pid": 10,
                "serial_owner_pids": [10],
                "serial_owner_pids_after_resume": [10],
                "sole_serial_owner_verified": True,
                "sole_serial_owner_verified_after_resume": True,
                "owner_pid_unchanged_across_obstruction": True,
                "normal_fifo_saturated": True,
                "timestamped_config_queries_queued": 100,
                "owner_handoff": {
                    "status": "completed",
                    "pid": 10,
                    "serial_reopened": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (run / "reports/capture_device_state.json").write_text(
        json.dumps(
            {
                "capture_active": False,
                "serial_open": True,
                "logical_segment_closed": True,
                "malformed_utf8": 0,
                "parser_errors": 0,
                "reconnect_count": 0,
                "commands_rejected": 0,
                "emergency_aborts_sent": 1,
                "emergency_abort_latched": True,
                "normal_command_batch_limit": 1,
                "normal_command_max_age_s": 2.0,
                "write_timeout_s": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (run / "reports/capture_segment_closure_v1.json").write_text(
        json.dumps(
            {
                "closure_mode": "same_owner_logical_rotation",
                "owner_pid": 10,
                "physical_serial_open": True,
                "serial_reopened": False,
                "serial_owner_check": {
                    "performed": True,
                    "owner_pids": [10],
                },
            }
        ),
        encoding="utf-8",
    )
    (transition / "reports/capture_device_state.json").write_text(
        json.dumps(
            {
                "capture_active": False,
                "serial_open": False,
                "reconnect_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (transition / "reports/capture_segment_closure_v1.json").write_text(
        json.dumps(
            {
                "closure_mode": "physical_serial_close",
                "owner_pid": 10,
                "serial_reopened": False,
            }
        ),
        encoding="utf-8",
    )
    marker_rows = [
        {"event": "host_command_sent", "command": "CONFIG?"},
        {"event": "host_command_sent", "command": "DAC?"},
        {"event": "host_command_sent", "command": "FC0?"},
        {"event": "emergency_abort_latched"},
        {"event": "normal_command_ingress_revoked"},
        {"event": "host_command_accepted", "command": "ACTIVE ABORT"},
        {"event": "host_command_sent", "command": "ACTIVE ABORT"},
        {"event": "emergency_abort_sent"},
    ]
    (run / "raw/serial.log").write_text(
        "".join(
            rehearsal.HOST_MARKER_PREFIX + json.dumps(row) + "\n"
            for row in marker_rows
        ),
        encoding="utf-8",
    )
    health_values = {
        ("command", "config_snapshot"): "end",
        ("dac", "enabled"): "false",
        ("cx317_active", "command"): "rejected_disabled",
        ("resource_registry", "valid"): "true",
        ("resource_registry", "complete"): "true",
        ("resource_registry", "conflict_count"): "0",
        ("resource_registry", "binding_failure_count"): "0",
        ("memory_budget", "valid"): "true",
        ("memory_budget", "core0_minimum_free_stack_bytes"): "4096",
        ("memory_budget", "minimum_free_heap_bytes"): "100000",
        ("pps_gate", "snapshot_backlog_high_water"): "1",
        ("pps_gate", "snapshot_ring_capacity"): "128",
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
    }
    for key in (
        "snapshot_overwrite_count",
        "snapshot_continuity_loss_count",
        "snapshot_pio_rxstall_count",
        "snapshot_dma_error_count",
        "snapshot_dma_stopped_count",
    ):
        health_values[("pps_gate", key)] = "0"
    health_rows = []
    for sequence, ((component, key), value) in enumerate(
        health_values.items(), 1
    ):
        health_rows.append(
            {
                "record_type": "STS",
                "schema_version": "1",
                "status_seq": str(sequence),
                "timestamp_ticks": str(sequence),
                "status_domain": "rp2040_timer0",
                "component": component,
                "status_key": key,
                "status_value": value,
                "severity": "INFO",
                "flags": "0",
            }
        )
    _write_csv(run / "csv/health.csv", "health_v1", health_rows)
    _write_csv(
        run / "csv/count_observations.csv",
        "count_observations_v1",
        [
            {
                "record_type": "CNT",
                "schema_version": "1",
                "count_seq": str(index),
                "counted_edges": "10000000",
            }
            for index in range(1, 6)
        ],
    )
    _write_csv(
        run / "csv/pps_snapshots.csv",
        "pps_snapshots_v1",
        [
            {
                "record_type": "SNP",
                "schema_version": "1",
                "snapshot_sequence": str(index),
            }
            for index in range(1, 7)
        ],
    )
    _write_csv(run / "csv/dac_steps.csv", "dac_steps_v1", [])
    _write_csv(
        run / "csv/active_transactions_v1", "active_transactions_v1", []
    )
    matrix = tmp_path / "matrix.json"
    build = tmp_path / "build.json"
    uf2 = tmp_path / "firmware.uf2"
    matrix.write_text("{}", encoding="utf-8")
    build.write_text("{}", encoding="utf-8")
    uf2.write_bytes(b"x")

    result = rehearsal.analyze_rehearsal(
        run,
        matrix_path=matrix,
        build_manifest_path=build,
        uf2_path=uf2,
    )

    assert result["status"] == "pass"
    assert all(result["criteria"].values())
