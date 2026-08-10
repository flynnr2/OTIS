from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import csv
import json
from types import SimpleNamespace

import pytest

import host.otis_tools.cx318_stage4_manifest as stage4_manifest
import host.otis_tools.cx318_stage4_static_code_preflight as preflight
import host.otis_tools.cx318_stage4_flash as stage4_flash
import host.otis_tools.cx318_stage4_premise_flash as premise_flash
import host.otis_tools.cx318_stage4_premise_command as premise_command
from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.cx318_stage4_manifest import (
    LIVE_STAGE,
    create_live_manifest,
    create_setup_manifest,
)
from host.otis_tools.cx318_stage4_rebound_matrix import derive_rebound_matrix
from host.otis_tools.evidence import create_evidence_snapshot
from tools.firmware_matrix import CONFIG_HEADER, configuration_payload, source_input_hash


def _write_csv(path: Path, contract: str, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[contract])
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CONTRACT_FIELDS[contract]})


def _premise_artifacts(run: Path) -> tuple[dict[str, object], dict[str, str]]:
    firmware = run / "firmware/premise"
    firmware.mkdir(parents=True)
    matrix_path = firmware / "firmware_matrix.json"
    matrix_path.write_bytes(Path("firmware/arduino/firmware_matrix.json").read_bytes())
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    profile = next(item for item in matrix["profiles"] if item["id"] == premise_flash.PROFILE_ID)
    config = configuration_payload(matrix, profile)
    config["sha256"] = sha256(json.dumps(
        config, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()
    uf2_path = firmware / "otis_nano_rp2040_connect.ino.uf2"
    uf2_path.write_bytes(b"premise-uf2")
    build = {
        "schema_version": 1,
        "provenance": {
            "source": {"git_commit": "a" * 40, "state": "clean", "sha256": "b" * 64},
            "configuration": config,
            "invocation": {"id": "d" * 64},
        },
        "artifacts": [{
            "name": uf2_path.name,
            "sha256": sha256(uf2_path.read_bytes()).hexdigest(),
            "size_bytes": uf2_path.stat().st_size,
        }],
    }
    build_path = firmware / "firmware_build_manifest.json"
    build_path.write_text(json.dumps(build), encoding="utf-8")
    binding = premise_flash.validate_premise_build_artifacts(
        matrix_path=matrix_path, build_manifest_path=build_path, uf2_path=uf2_path,
    )
    board = {
        "address": "/dev/cu.test",
        "hardware_id": "503533748A919118",
        "serial_number": "503533748A919118",
        "vid": "0x2341",
        "pid": "0x005E",
        "product": "Nano RP2040 Connect",
        "board_name": "Arduino Nano RP2040 Connect",
        "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
    }
    record = {
        "schema_version": 1,
        "tool": premise_flash.TOOL_ID,
        "status": "passed",
        "attempt_count": 1,
        "artifact_binding": binding,
        "board_before": board,
        "board_after": board,
        "command": ["arduino-cli", "upload", "--input-file", str(uf2_path.resolve())],
    }
    record_path = run / "reports/premise_flash_record.json"
    record_path.parent.mkdir(exist_ok=True)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    paths = {
        "matrix": matrix_path.relative_to(run).as_posix(),
        "build_manifest": build_path.relative_to(run).as_posix(),
        "uf2": uf2_path.relative_to(run).as_posix(),
        "flash_record": record_path.relative_to(run).as_posix(),
    }
    lineage = {
        "profile_id": premise_flash.PROFILE_ID,
        "matrix": {"path": paths["matrix"], "sha256": sha256(matrix_path.read_bytes()).hexdigest()},
        "build_manifest": {"path": paths["build_manifest"], "sha256": sha256(build_path.read_bytes()).hexdigest()},
        "uf2": {
            "path": paths["uf2"], "sha256": sha256(uf2_path.read_bytes()).hexdigest(),
            "size_bytes": uf2_path.stat().st_size,
        },
        "flash_record": {"path": paths["flash_record"], "sha256": sha256(record_path.read_bytes()).hexdigest()},
        "artifact_binding": binding,
    }
    return lineage, paths


def _setup_run(root: Path, *, duplicate_write: bool = False) -> Path:
    campaign = root / "runs/cx318"
    campaign.mkdir(parents=True)
    (campaign / "PROGRAMME_STATE.md").write_text("# Test campaign\n", encoding="utf-8")
    run = campaign / "setup"
    (run / "raw").mkdir(parents=True)
    (run / "reports").mkdir()
    premise_lineage, premise_paths = _premise_artifacts(run)
    files = {
        "pps_snapshots_v1": "csv/pps_snapshots.csv",
        "count_observations_v1": "csv/count_observations.csv",
        "health_v1": "csv/health.csv",
        "dac_steps_v1": "csv/dac_steps.csv",
        "environment_v1": "csv/environment.csv",
        "active_transactions_v1": "csv/active_transactions.csv",
    }
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run.name,
        "stage": preflight.EXPECTED_STAGE,
        "stage4_static_setup": {
            "premise_amendment": "operator_authorized_single_setup_write",
            "authorized_code": "0xA828",
            "maximum_setup_attempts": 1,
            "maximum_setup_writes": 1,
            "retry_after_failure": False,
            "opening_dac_epoch": 0,
            "resulting_dac_epoch": 1,
            "automatic_authority": False,
            "phase_hybrid_authority": False,
            "gps_transmit_authorized": False,
        },
        "premise_firmware": premise_lineage,
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 2, "role": "pps_gated_oscillator_count", "record_family": "count_observations_v1"}
        ],
        "files": [
            {"path": path, "contract": contract}
            for contract, path in files.items()
        ],
        "evidence_artifacts": [
            *premise_paths.values(),
            premise_command.LATCH_PATH.as_posix(),
        ],
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_csv(run / files["pps_snapshots_v1"], "pps_snapshots_v1", [
        {"record_type": "SNP", "schema_version": 1, "session": 7,
         "snapshot_sequence": sequence, "cumulative_down_counter": 4_000_000_000 - sequence * 10_000_000,
         "reference_sequence": sequence, "reference_timestamp_ticks": sequence * 16_000_000,
         "status": 0, "backend": "pio_wait_cumulative_snapshot_dma_v1"}
        for sequence in (10, 11)
    ])
    _write_csv(run / files["count_observations_v1"], "count_observations_v1", [
        {"record_type": "CNT", "schema_version": 1, "count_seq": sequence,
         "channel_id": 2, "gate_open_ticks": sequence * 16_000_000,
         "gate_close_ticks": (sequence + 1) * 16_000_000,
         "gate_domain": "rp2040_timer0", "counted_edges": 10_000_000,
         "source_edge": "R", "source_domain": "h0_tcxo_16mhz", "flags": 16}
        for sequence in (10, 11)
    ])
    health_values = [
        ("firmware", "git_commit", premise_lineage["artifact_binding"]["git_commit"]),
        ("firmware", "source_state", "clean"),
        ("firmware", "source_hash", premise_lineage["artifact_binding"]["source_sha256"]),
        ("firmware", "config_hash", premise_lineage["artifact_binding"]["configuration_sha256"]),
        ("build", "profile_id", premise_flash.PROFILE_ID),
        ("build", "enable_cx318_stage4_premise_setup", "1"),
        ("build", "enable_cx318_stage4_preview", "0"),
        ("build", "enable_cx317_i_only_preview", "0"),
        ("build", "enable_cx317_bounded_active", "0"),
        ("build", "enable_dac_ad5693r", "1"),
        ("cx318_premise", "allowed_code", "0xA828"),
        ("cx318_premise", "write_consumed", "true"),
        ("cx318_premise", "actionable", "false"),
        ("cx318_premise", "actuation_authorized", "false"),
        ("cx318_premise", "automatic_authority", "false"),
        ("dual_core", "partition_fault", "none"),
        ("dual_core", "fail_static", "false"),
        ("dual_core", "telemetry_dropped", "0"),
        ("capture", "dropped_count", "0"),
        ("active", "manual_start_confirmed", "false"),
        ("active", "arm_eligible", "false"),
        ("dac", "applied_code_known", "false"),
        ("dac", "applied_code_known", "true"),
        ("dac", "last_write_ok", "true"),
        ("dac", "last_requested_code", "0xA828"),
        ("dac", "last_applied_code", "0xA828"),
    ]
    _write_csv(run / files["health_v1"], "health_v1", [
        {"record_type": "STS", "schema_version": 1, "status_seq": index,
         "timestamp_ticks": index * 16_000_000, "status_domain": "rp2040_timer0",
         "component": component, "status_key": key, "status_value": value,
         "severity": "INFO", "flags": 0}
        for index, (component, key, value) in enumerate(health_values, start=1)
    ])
    dac_rows = [
        {"record_type": "DAC", "schema_version": 1, "seq": 1,
         "elapsed_ms": 10_000, "step_index": -1,
         "dac_code_requested": 0xA828, "dac_code_applied": 0xA828,
         "dac_code_clamped": 0, "dwell_ms": 0, "event": "manual_apply", "flags": 0}
    ]
    if duplicate_write:
        dac_rows.append({**dac_rows[0], "seq": 2, "elapsed_ms": 11_000})
    _write_csv(run / files["dac_steps_v1"], "dac_steps_v1", dac_rows)
    _write_csv(run / files["environment_v1"], "environment_v1", [
        {"record_type": "ENV", "schema_version": 1, "env_seq": index,
         "timestamp_ticks": index * 16_000_000, "observation_domain": "rp2040_timer0",
         "source": source, "role": role, "temperature_c": "29.0",
         "relative_humidity_pct": "40.0" if source == "sht4x" else "",
         "pressure_pa": "101325" if source == "bmp280" else "", "flags": 0}
        for index, (source, role) in enumerate(
            (("sht4x", "vcocxo_near"), ("bmp280", "pressure_reference")), start=1
        )
    ])
    _write_csv(run / files["active_transactions_v1"], "active_transactions_v1", [])
    commands = list(preflight.EXPECTED_COMMANDS)
    raw_lines = ['# OTIS_HOST {"event":"capture_started"}']
    def raw_status(sequence: int, key: str, value: str) -> str:
        record = {
            "record_type": "STS", "schema_version": 1,
            "status_seq": sequence, "timestamp_ticks": sequence * 16_000_000,
            "status_domain": "rp2040_timer0", "component": "dac",
            "status_key": key, "status_value": value,
            "severity": "INFO", "flags": 0,
        }
        return ",".join(str(record.get(field, "")) for field in CONTRACT_FIELDS["health_v1"])

    for command_index, command in enumerate(commands):
        raw_lines.extend([
            f'# OTIS_HOST {json.dumps({"event": "host_command_accepted", "command": command}, sort_keys=True)}',
            f'# OTIS_HOST {json.dumps({"event": "host_command_sent", "command": command}, sort_keys=True)}',
        ])
        if command_index == 2:
            raw_lines.extend([
                raw_status(101, "applied_code_known", "false"),
                raw_status(102, "last_write_ok", "false"),
                raw_status(103, "last_requested_code", "0x0000"),
                raw_status(104, "last_applied_code", "unavailable"),
            ])
        elif command_index == 3:
            raw_lines.extend(
                ",".join(str(row.get(field, "")) for field in CONTRACT_FIELDS["dac_steps_v1"])
                for row in dac_rows
            )
        elif command_index == 4:
            raw_lines.extend([
                raw_status(105, "applied_code_known", "true"),
                raw_status(106, "last_write_ok", "true"),
                raw_status(107, "last_requested_code", "0xA828"),
                raw_status(108, "last_applied_code", "0xA828"),
            ])
    raw_lines.append('# OTIS_HOST {"event":"capture_stopped"}')
    (run / "raw/serial.log").write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    latch_path = run / premise_command.LATCH_PATH
    latch_path.parent.mkdir(parents=True, exist_ok=True)
    latch = {
        "schema_version": 1,
        "tool": premise_command.TOOL_ID,
        "status": "attempt_latched_before_enqueue",
        "created_utc": "2026-08-09T20:00:00Z",
        "run_id": run.name,
        "command": premise_command.COMMAND,
        "maximum_attempts": 1,
        "retry_authorized": False,
        "capture_pid": 123,
        "precommand_sequence": list(preflight.EXPECTED_COMMANDS[:3]),
        "campaign_id": campaign.name,
        "campaign_latch_path": premise_command.CAMPAIGN_LATCH_PATH.as_posix(),
    }
    latch_path.write_text(json.dumps(latch), encoding="utf-8")
    (campaign / premise_command.CAMPAIGN_LATCH_PATH).write_text(json.dumps({
        **latch,
        "run_latch_path": latch_path.relative_to(campaign).as_posix(),
    }), encoding="utf-8")
    (run / "reports/capture_device_state.json").write_text(json.dumps({
        "capture_active": False, "serial_open": False, "parser_errors": 0,
        "malformed_utf8": 0, "reconnect_count": 0, "commands_rejected": 0,
        "commands_sent": len(commands), "pid": 123,
    }), encoding="utf-8")
    (run / "COMPLETE").write_text("\n", encoding="utf-8")
    create_evidence_snapshot(run)
    return run


def _identity_run(root: Path, flash_record: dict[str, object]) -> Path:
    run = root / "runs/cx318/identity"
    (run / "raw").mkdir(parents=True)
    (run / "reports").mkdir()
    flash_path = run / "reports/flash_record.json"
    flash_path.write_text(json.dumps(flash_record), encoding="utf-8")
    usb_path = run / "reports/usb_board_identity.json"
    usb_path.write_text(json.dumps({
        "schema_version": 1,
        "tool": "cx318_stage4_post_flash_usb_identity_v1",
        "device": "/dev/cu.test",
        "identity": flash_record["board_after"],
        "flash_record_sha256": sha256(flash_path.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    files = {
        "pps_snapshots_v1": "csv/pps_snapshots.csv",
        "count_observations_v1": "csv/count_observations.csv",
        "health_v1": "csv/health.csv",
        "dac_steps_v1": "csv/dac_steps.csv",
        "environment_v1": "csv/environment.csv",
        "active_transactions_v1": "csv/active_transactions.csv",
    }
    firmware = {
        "git_commit": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
    }
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run.name,
        "stage": preflight.EXPECTED_IDENTITY_STAGE,
        "firmware": firmware,
        "host": {"serial_device": "/dev/cu.test"},
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 2, "role": "pps_gated_oscillator_count", "record_family": "count_observations_v1"}
        ],
        "files": [{"path": path, "contract": contract} for contract, path in files.items()],
        "post_flash_identity": {
            "flash_record": {
                "path": "reports/flash_record.json",
                "sha256": sha256(flash_path.read_bytes()).hexdigest(),
            },
            "usb_board_identity": {
                "path": "reports/usb_board_identity.json",
                "sha256": sha256(usb_path.read_bytes()).hexdigest(),
            },
        },
        "evidence_artifacts": [
            "reports/flash_record.json",
            "reports/usb_board_identity.json",
        ],
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_csv(run / files["pps_snapshots_v1"], "pps_snapshots_v1", [
        {"record_type": "SNP", "schema_version": 1, "session": 1,
         "snapshot_sequence": sequence, "cumulative_down_counter": 4_000_000_000 - sequence * 10_000_000,
         "reference_sequence": sequence, "reference_timestamp_ticks": sequence * 16_000_000,
         "status": 0, "backend": "pio_wait_cumulative_snapshot_dma_v1"}
        for sequence in (1, 2)
    ])
    _write_csv(run / files["count_observations_v1"], "count_observations_v1", [
        {"record_type": "CNT", "schema_version": 1, "count_seq": sequence,
         "channel_id": 2, "gate_open_ticks": sequence * 16_000_000,
         "gate_close_ticks": (sequence + 1) * 16_000_000,
         "gate_domain": "rp2040_timer0", "counted_edges": 10_000_000,
         "source_edge": "R", "source_domain": "h0_tcxo_16mhz", "flags": 16}
        for sequence in (1, 2)
    ])
    values = {
        ("firmware", "git_commit"): firmware["git_commit"],
        ("firmware", "source_state"): firmware["source_state"],
        ("firmware", "source_hash"): firmware["source_sha256"],
        ("firmware", "config_hash"): firmware["configuration_sha256"],
        ("build", "profile_id"): "cx318_stage4_nonactuating_preview",
        ("build", "enable_cx318_stage4_preview"): "1",
        ("build", "enable_dac_ad5693r"): "0",
        ("build", "enable_cx317_i_only_preview"): "0",
        ("build", "enable_cx317_bounded_active"): "0",
        ("cx318_preview", "confirmed_static_code"): "0xA828",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "1",
        ("cx318_preview", "actionable"): "false",
        ("cx318_preview", "actuation_authorized"): "false",
        ("cx318_preview", "authorization_consumed"): "false",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "telemetry_dropped"): "0",
    }
    _write_csv(run / files["health_v1"], "health_v1", [
        {"record_type": "STS", "schema_version": 1, "status_seq": index,
         "timestamp_ticks": index * 16_000_000, "status_domain": "rp2040_timer0",
         "component": component, "status_key": key, "status_value": value,
         "severity": "INFO", "flags": 0}
        for index, ((component, key), value) in enumerate(values.items(), start=1)
    ])
    _write_csv(run / files["dac_steps_v1"], "dac_steps_v1", [])
    _write_csv(run / files["active_transactions_v1"], "active_transactions_v1", [])
    _write_csv(run / files["environment_v1"], "environment_v1", [
        {"record_type": "ENV", "schema_version": 1, "env_seq": index,
         "timestamp_ticks": index * 16_000_000, "observation_domain": "rp2040_timer0",
         "source": source, "role": role, "temperature_c": "29.0",
         "relative_humidity_pct": "40.0" if source == "sht4x" else "",
         "pressure_pa": "101325" if source == "bmp280" else "", "flags": 0}
        for index, (source, role) in enumerate(
            (("sht4x", "vcocxo_near"), ("bmp280", "pressure_reference")), start=1
        )
    ])
    raw = ['# OTIS_HOST {"event":"capture_started"}']
    for command in ("CONFIG?", "DUALCORE?"):
        raw.extend([
            f'# OTIS_HOST {json.dumps({"event": "host_command_accepted", "command": command}, sort_keys=True)}',
            f'# OTIS_HOST {json.dumps({"event": "host_command_sent", "command": command}, sort_keys=True)}',
        ])
    raw.append('# OTIS_HOST {"event":"capture_stopped"}')
    (run / "raw/serial.log").write_text("\n".join(raw) + "\n", encoding="utf-8")
    (run / "reports/capture_device_state.json").write_text(json.dumps({
        "capture_active": False, "serial_open": False, "parser_errors": 0,
        "malformed_utf8": 0, "reconnect_count": 0, "commands_rejected": 0,
        "commands_sent": 2,
    }), encoding="utf-8")
    (run / "COMPLETE").write_text("\n", encoding="utf-8")
    create_evidence_snapshot(run)
    return run


def _lineage_artifacts(root: Path, setup: Path):
    live = root / "runs/cx318/live"
    base = json.loads(Path("firmware/arduino/firmware_matrix.json").read_text(encoding="utf-8"))
    base_path = root / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    matrix_path, _, _ = derive_rebound_matrix(
        setup_run_dir=setup,
        output_path=live / "firmware/rebound_matrix.json",
        base_matrix_path=base_path,
    )
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    profile = next(item for item in matrix["profiles"] if item["id"] == "cx318_stage4_nonactuating_preview")
    uf2_path = live / "firmware/build/artifacts/otis_nano_rp2040_connect.ino.uf2"
    uf2_path.parent.mkdir(parents=True)
    uf2_path.write_bytes(b"stage4-uf2")
    build = {
        "schema_version": 1,
        "provenance": {
            "source": {"git_commit": "a" * 40, "state": "clean", "sha256": "b" * 64},
            "configuration": {
                "profile_id": profile["id"], "defines": profile["defines"], "sha256": "c" * 64,
            },
        },
        "artifacts": [{
            "name": uf2_path.name,
            "sha256": sha256(uf2_path.read_bytes()).hexdigest(),
            "size_bytes": uf2_path.stat().st_size,
        }],
    }
    build_path = uf2_path.with_name("firmware_build_manifest.json")
    build_path.write_text(json.dumps(build), encoding="utf-8")
    binding = {
        "matrix_sha256": sha256(matrix_path.read_bytes()).hexdigest(),
        "build_manifest_sha256": sha256(build_path.read_bytes()).hexdigest(),
        "uf2_sha256": sha256(uf2_path.read_bytes()).hexdigest(),
        "uf2_size_bytes": uf2_path.stat().st_size,
        "git_commit": "a" * 40,
        "source_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
        "fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133",
        "build_invocation_id": "d" * 64,
    }
    board = {
        "address": "/dev/cu.test",
        "hardware_id": "503533748A919118",
        "serial_number": "503533748A919118",
        "vid": "0x2341",
        "pid": "0x005E",
        "product": "Nano RP2040 Connect",
        "board_name": "Arduino Nano RP2040 Connect",
        "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
    }
    record = {
        "schema_version": 1,
        "tool": "cx318_stage4_exact_flash_v1",
        "status": "passed",
        "attempt_count": 1,
        "completed_utc": "2026-08-09T22:00:00Z",
        "artifact_binding": binding,
        "board_before": board,
        "board_after": board,
        "command": ["arduino-cli", "upload", "--input-file", str(uf2_path.resolve())],
    }
    identity = _identity_run(root, record)
    flash_path = identity / "reports/flash_record.json"
    return live, matrix_path, build_path, uf2_path, flash_path, identity, binding


def test_setup_evidence_and_proof_bind_exact_single_a828_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    run = _setup_run(tmp_path)
    evidence = preflight.validate_setup_run(run)
    assert evidence.confirmed_code == 0xA828
    assert evidence.dac_epoch == 1
    live, matrix, build, uf2, flash, identity, binding = _lineage_artifacts(tmp_path, run)
    monkeypatch.setattr(preflight, "validate_build_inputs", lambda **_kwargs: binding)
    output = live / "bindings/static_code_proof.json"
    _, proof = preflight.create_static_proof(
        setup_run_dir=run,
        identity_run_dir=identity,
        rebound_matrix_path=matrix,
        build_manifest_path=build,
        uf2_path=uf2,
        flash_record_path=flash,
        output_path=output,
    )
    assert preflight.validate_static_proof(proof) == evidence


def test_setup_evidence_rejects_a_second_dac_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    run = _setup_run(tmp_path, duplicate_write=True)
    with pytest.raises(ValueError, match="exactly one DAC row"):
        preflight.validate_setup_run(run)


def test_premise_build_and_flash_lineage_is_exact_and_one_attempt(tmp_path: Path) -> None:
    run = tmp_path / "premise"
    (run / "reports").mkdir(parents=True)
    lineage, paths = _premise_artifacts(run)
    matrix = run / paths["matrix"]
    build = run / paths["build_manifest"]
    uf2 = run / paths["uf2"]
    record_path = run / paths["flash_record"]
    record = json.loads(record_path.read_text(encoding="utf-8"))

    binding = premise_flash.validate_premise_build_artifacts(
        matrix_path=matrix, build_manifest_path=build, uf2_path=uf2,
    )
    assert binding == lineage["artifact_binding"]
    assert premise_flash.validate_premise_flash_record(
        record, matrix_path=matrix, build_manifest_path=build, uf2_path=uf2,
    ) == binding

    record["attempt_count"] = 2
    with pytest.raises(ValueError, match="one successful attempt"):
        premise_flash.validate_premise_flash_record(
            record, matrix_path=matrix, build_manifest_path=build, uf2_path=uf2,
        )


def test_rebound_matrix_changes_only_static_code_and_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    run = _setup_run(tmp_path)
    base = json.loads(Path("firmware/arduino/firmware_matrix.json").read_text(encoding="utf-8"))
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    output, code, epoch = derive_rebound_matrix(
        setup_run_dir=run, output_path=tmp_path / "derived.json",
        base_matrix_path=base_path,
    )
    derived = json.loads(output.read_text(encoding="utf-8"))
    before = next(item for item in base["profiles"] if item["id"] == "cx318_stage4_nonactuating_preview")
    after = next(item for item in derived["profiles"] if item["id"] == "cx318_stage4_nonactuating_preview")
    changed = {key for key in before["defines"] if before["defines"][key] != after["defines"][key]}
    assert changed == {"OTIS_CX318_STAGE4_STATIC_CODE", "OTIS_CX318_STAGE4_DAC_EPOCH"}
    assert (code, epoch) == (0xA828, 1)
    assert derived["cx318_stage4_rebound_derivation"]["base_matrix_sha256"] == sha256(base_path.read_bytes()).hexdigest()


def test_rebound_matrix_rejects_modified_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    run = _setup_run(tmp_path)
    base = json.loads(Path("firmware/arduino/firmware_matrix.json").read_text(encoding="utf-8"))
    base["profiles"][0]["purpose"] += " altered"
    base_path = tmp_path / "altered.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="exact tracked"):
        derive_rebound_matrix(
            setup_run_dir=run,
            output_path=tmp_path / "derived.json",
            base_matrix_path=base_path,
        )


def test_flash_preflight_requires_exact_complete_rebound_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    setup = _setup_run(tmp_path)
    matrix_path, _, _ = derive_rebound_matrix(
        setup_run_dir=setup,
        output_path=tmp_path / "rebound.json",
    )
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    profile = next(item for item in matrix["profiles"] if item["id"] == "cx318_stage4_nonactuating_preview")
    config = configuration_payload(
        matrix,
        profile,
        config_source_sha256=sha256(CONFIG_HEADER.read_bytes()).hexdigest(),
    )
    config["sha256"] = sha256(
        json.dumps(config, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    uf2 = tmp_path / "firmware.uf2"
    uf2.write_bytes(b"exact-stage4")
    build = {
        "provenance": {
            "source": {
                "git_commit": "a" * 40,
                "state": "clean",
                "sha256": source_input_hash(matrix_path=matrix_path),
            },
            "configuration": config,
            "invocation": {"id": "d" * 64},
        },
        "artifacts": [{
            "name": uf2.name,
            "sha256": sha256(uf2.read_bytes()).hexdigest(),
            "size_bytes": uf2.stat().st_size,
        }],
    }
    build_path = tmp_path / "build.json"
    build_path.write_text(json.dumps(build), encoding="utf-8")

    def fake_run(command, **_kwargs):
        output = "a" * 40 + "\n" if command[1:3] == ["rev-parse", "HEAD"] else ""
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    monkeypatch.setattr(stage4_flash.subprocess, "run", fake_run)
    binding = stage4_flash.validate_build_inputs(
        rebound_matrix_path=matrix_path,
        build_manifest_path=build_path,
        uf2_path=uf2,
    )
    assert binding["uf2_sha256"] == sha256(uf2.read_bytes()).hexdigest()
    build["provenance"]["configuration"]["defines"]["OTIS_ENABLE_DAC_AD5693R"] = "1"
    build_path.write_text(json.dumps(build), encoding="utf-8")
    with pytest.raises(ValueError, match="exact clean rebound"):
        stage4_flash.validate_build_inputs(
            rebound_matrix_path=matrix_path,
            build_manifest_path=build_path,
            uf2_path=uf2,
        )


def test_exact_setup_and_live_manifests_preserve_zero_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    setup = _setup_run(tmp_path)
    generated_setup = tmp_path / "runs/cx318/generated_setup"
    _, premise_paths = _premise_artifacts(generated_setup)
    setup_manifest_path = create_setup_manifest(
        run_dir=generated_setup,
        serial_device="/dev/cu.test",
        premise_matrix_path=generated_setup / premise_paths["matrix"],
        premise_build_manifest_path=generated_setup / premise_paths["build_manifest"],
        premise_uf2_path=generated_setup / premise_paths["uf2"],
        premise_flash_record_path=generated_setup / premise_paths["flash_record"],
    )
    setup_manifest = json.loads(setup_manifest_path.read_text(encoding="utf-8"))
    assert setup_manifest["stage4_static_setup"]["exact_command_sequence"] == list(
        preflight.EXPECTED_COMMANDS
    )
    assert setup_manifest["stage4_static_setup"]["maximum_setup_writes"] == 1
    assert setup_manifest["stage4_static_setup"]["maximum_setup_attempts"] == 1
    assert setup_manifest["stage4_static_setup"]["retry_after_failure"] is False
    assert setup_manifest["premise_firmware"]["profile_id"] == premise_flash.PROFILE_ID
    assert setup_manifest["phase_hybrid_authority"] is False

    live, matrix_path, build_path, uf2_path, flash_path, identity, binding = _lineage_artifacts(tmp_path, setup)
    monkeypatch.setattr(preflight, "validate_build_inputs", lambda **_kwargs: binding)
    monkeypatch.setattr(stage4_manifest, "validate_build_inputs", lambda **_kwargs: binding)
    proof_path, _ = preflight.create_static_proof(
        setup_run_dir=setup,
        identity_run_dir=identity,
        rebound_matrix_path=matrix_path,
        build_manifest_path=build_path,
        uf2_path=uf2_path,
        flash_record_path=flash_path,
        output_path=live / "bindings/static_code_proof.json",
    )
    live_manifest_path = create_live_manifest(
        run_dir=live,
        build_manifest_path=build_path,
        uf2_path=uf2_path,
        static_proof_path=proof_path,
        rebound_matrix_path=matrix_path,
        serial_device="/dev/cu.test",
    )
    live_manifest = json.loads(live_manifest_path.read_text(encoding="utf-8"))
    assert live_manifest["stage"] == LIVE_STAGE
    assert live_manifest["stage4_live_preview"]["static_code"] == "0xA828"
    assert live_manifest["stage4_live_preview"]["dac_rows_permitted"] == 0
    assert live_manifest["stage4_live_preview"]["active_rows_permitted"] == 0
    assert live_manifest["firmware"]["source_state"] == "clean"


def test_rehearsal_manifest_requires_one_full_frequency_window_before_long_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    setup = _setup_run(tmp_path)
    rehearsal, matrix, build, uf2, flash, identity, binding = _lineage_artifacts(tmp_path, setup)
    monkeypatch.setattr(preflight, "validate_build_inputs", lambda **_kwargs: binding)
    monkeypatch.setattr(stage4_manifest, "validate_build_inputs", lambda **_kwargs: binding)
    proof, _ = preflight.create_static_proof(
        setup_run_dir=setup,
        identity_run_dir=identity,
        rebound_matrix_path=matrix,
        build_manifest_path=build,
        uf2_path=uf2,
        flash_record_path=flash,
        output_path=rehearsal / "bindings/static_code_proof.json",
    )
    path = stage4_manifest.create_rehearsal_manifest(
        run_dir=rehearsal,
        build_manifest_path=build,
        uf2_path=uf2,
        static_proof_path=proof,
        rebound_matrix_path=matrix,
        serial_device="/dev/cu.test",
        duration_s=720,
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["stage"] == stage4_manifest.REHEARSAL_STAGE
    assert manifest["diagnostic_rehearsal"] is True
    assert manifest["stage4_progression_authority"] is False
    assert manifest["stage4_live_preview"]["minimum_authoritative_frequency_estimates"] == 1
    assert manifest["stage4_live_preview"]["minimum_duration_s"] == 600
