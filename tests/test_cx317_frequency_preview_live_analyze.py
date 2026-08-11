from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import csv
from hashlib import sha256
import json

import pytest

from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.cx317_i_only_preview_replay import load_policy
from host.otis_tools.cx317_frequency_preview_live_analyze import (
    AUTHORITY_KEYS,
    REQUIRED_ZERO_HEALTH,
    _controller_parity,
    analyze,
)
from host.otis_tools.service_plane_probe import REQUIRED_LATEST_HEALTH
from host.otis_tools.timebase import RP2040_TIMER0_MICROS_WRAP_TICKS


def _write_csv(path: Path, contract: str, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = CONTRACT_FIELDS[contract]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for values in rows:
            row = {field: "" for field in fields}
            row.update(values)
            writer.writerow(row)


def _estimate(
    sequence: int,
    *,
    first: int,
    last: int,
    selected: bool,
    estimator_hash: str,
) -> dict[str, object]:
    span = 600 if selected else 60
    kind = "selected600" if selected else "diagnostic60"
    return {
        "record_type": "EST",
        "schema_version": 2,
        "estimate_seq": sequence,
        "estimate_id": f"est:cx317:{kind}:{sequence:06d}",
        "estimator_timestamp_ticks": (1800 + span) * 16_000_000,
        "time_domain": "rp2040_timer0",
        "source_count_seq": last,
        "source_count_ref": f"live:CNT:{last}",
        "source_reference_first_seq": first,
        "source_reference_last_seq": last,
        "source_status_refs": "live:STS:pps_gate",
        "source_dac_ref": "live:DAC:static",
        "manifest_ref": "firmware_config:cx317_pps_gated_i_only_preview",
        "estimator_version": (
            "cx317_selected_600s_nonoverlap_v1"
            if selected else "cx317_diagnostic_60s_overlap_v1"
        ),
        "config_hash": estimator_hash,
        "observation_validity": "valid",
        "observation_reason_codes": "contiguous_snapshot_span",
        "reference_validity": "valid",
        "reference_age_s": 0,
        "reference_continuity": "true",
        "count_validity": "valid",
        "count_age_s": 0,
        "count_continuity": "true",
        "diagnostic_health": "healthy",
        "diagnostic_reason_codes": "diagnostic_healthy",
        "frequency_observation_hz": "10000000.000000000000",
        "accepted_sample_count": span,
        "estimator_confidence": "unavailable",
        "frequency_estimate_hz": "10000000.000000000000",
        "frequency_error_hz": "0.000000000000",
        "dispersion_hz": "",
        "uncertainty_status": "unavailable",
        "uncertainty_reason_codes": "counter_aperture_uncertainty_unavailable;reference_uncertainty_unavailable;calibration_uncertainty_unavailable",
        "correlation_policy": "not_combined_missing_components",
        "uncertainty_model_ref": "unavailable:combined_uncertainty",
        "drift_enabled": "false",
        "drift_hz_per_s": "",
        "preview_eligibility": "true" if selected else "false",
        "eligibility_reason_codes": (
            "preview_input_observe_only" if selected else "diagnostic_non_authoritative"
        ),
    }


def _control(
    sequence: int,
    *,
    tick_s: int,
    estimate_ref: str,
    state: str,
    previous: str,
    reason: str,
    preview: bool,
    policy_hash: str,
    model_hash: str,
    policy_id: str,
    gain: float,
) -> dict[str, object]:
    return {
        "record_type": "CTL",
        "schema_version": 1,
        "control_seq": sequence,
        "decision_id": f"ctl:cx317:{sequence:06d}",
        "decision_timestamp_ticks": tick_s * 16_000_000,
        "time_domain": "rp2040_timer0",
        "est_input_ref": estimate_ref,
        "plant_model_ref": "profile:plant_models/cx317_pps_gated_v1.json",
        "plant_model_id": "cx317_pps_gated_bench",
        "plant_model_version": 1,
        "plant_model_hash": model_hash,
        "policy_version": policy_id,
        "config_hash": policy_hash,
        "control_state": state,
        "previous_control_state": previous,
        "state_transition": "true",
        "transition_reason_code": reason,
        "preview_eligibility": "true" if preview else "false",
        "eligibility_reason_codes": "preview_available_observe_only" if preview else reason,
        "diagnostic_health": "healthy",
        "model_applicability": "applicable",
        "model_reason_codes": "model_applicable_observe_only",
        "current_dac_code": 43344,
        "frequency_error_hz": "0.000000000000" if preview else "",
        "hz_per_code": format(gain, ".15g"),
        "raw_delta_codes": "0.000000000000" if preview else "",
        "limited_delta_codes": 0 if preview else "",
        "proposed_dac_code": 43344 if preview else "",
        "step_limited": "false",
        "range_clamped": "false",
        "preview_available": "true" if preview else "false",
        "preview_only": "true",
        "actuation_authorized": "false",
        "actionable": "false",
        "decision_reason_code": reason,
    }


def _run(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    run = tmp_path / "stage6"
    policy = load_policy()
    estimator_hash = "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c"
    files = [
        ("csv/ref.csv", "raw_events_v1"),
        ("csv/cnt.csv", "count_observations_v1"),
        ("csv/snp.csv", "pps_snapshots_v1"),
        ("csv/health.csv", "health_v1"),
        ("csv/dac_steps.csv", "dac_steps_v1"),
        ("csv/environment.csv", "environment_v1"),
        ("csv/estimates_v2.csv", "estimates_v2"),
        ("csv/control_previews_v1.csv", "control_previews_v1"),
    ]
    source_hash = "1" * 64
    configuration_hash = "2" * 64
    git_commit = "4" * 40
    uf2_bytes = b"synthetic-stage6-matrix-uf2"
    uf2_hash = sha256(uf2_bytes).hexdigest()
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": "stage6_fixture",
        "stage": "CX317_PPS_GATED_I_ONLY_PREVIEW",
        "h_phase": "H1",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "i_only_observe_only_preview",
        "closed_loop_control": False,
        "actionable": False,
        "actuation_authorized": False,
        "board": "arduino_nano_rp2040_connect",
        "started_at_utc": "2026-08-01T23:50:10Z",
        "ended_at_utc": "2026-08-02T06:00:10Z",
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "version": "CX317_PPS_GATED_I_ONLY_PREVIEW_V1",
            "config_id": "cx317_pps_gated_i_only_preview",
            "git_commit": git_commit,
            "source_state": "dirty",
            "source_sha256": source_hash,
            "configuration_sha256": configuration_hash,
            "uf2_sha256": uf2_hash,
            "uf2_size_bytes": len(uf2_bytes),
        },
        "oscillator": {"nominal_frequency_hz": 10_000_000},
        "selected_estimator": {
            "method_id": "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1",
            "profile_sha256": estimator_hash,
        },
        "controller_preview": {
            "policy_sha256": policy.config_hash,
            "plant_model_sha256": policy.plant_model_hash,
            "minimum_declared_duration_s": 21_600,
            "planned_capture_duration_s": 22_200,
            "preflight_identity_query": {
                "command": "CONFIG?",
                "request_count": 1,
                "timing": "after capture opens and before A950",
                "basis": "synthetic live identity provenance",
            },
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 1, "role": "authoritative_pps_reference", "record_family": "raw_events_v1"},
            {"channel_id": 2, "role": "pps_gated_oscillator_count", "record_family": "count_observations_v1"},
        ],
        "files": [{"path": path, "contract": contract} for path, contract in files],
    }
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    references: list[dict[str, object]] = []
    counts: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    counter = 2_000_000_000
    for offset, sequence in enumerate(range(13_000, 13_601)):
        tick = (1800 + offset) * 16_000_000
        if offset:
            counter = (counter - 10_000_000) & 0xFFFFFFFF
        references.append({
            "record_type": "REF", "schema_version": 1,
            "event_seq": sequence + 1000, "channel_id": 1, "edge": "R",
            "timestamp_ticks": tick, "capture_domain": "rp2040_timer0", "flags": 16,
        })
        counts.append({
            "record_type": "CNT", "schema_version": 1,
            "count_seq": sequence, "channel_id": 2,
            "gate_open_ticks": tick - 16_000_000,
            "gate_close_ticks": tick, "gate_domain": "rp2040_timer0",
            "counted_edges": 10_000_000, "source_edge": "R",
            "source_domain": "h0_tcxo_16mhz", "flags": 16,
        })
        snapshots.append({
            "record_type": "SNP", "schema_version": 1, "session": 1,
            "snapshot_sequence": sequence, "cumulative_down_counter": counter,
            "reference_sequence": sequence, "reference_timestamp_ticks": tick,
            "status": 0, "backend": "pio_wait_cumulative_snapshot_dma_v1",
        })
    _write_csv(run / "csv/ref.csv", "raw_events_v1", references)
    _write_csv(run / "csv/cnt.csv", "count_observations_v1", counts)
    _write_csv(run / "csv/snp.csv", "pps_snapshots_v1", snapshots)

    health_values = {**REQUIRED_LATEST_HEALTH}
    health_values.update({key: "0" for key in REQUIRED_ZERO_HEALTH})
    health_values.update({("cx317_preview", key): "false" for key in AUTHORITY_KEYS})
    health_values[("cx317_preview", "active_live_update_codes")] = "0"
    health_values[("pps_dual_observer", "d14_raw_minus_d10_raw")] = "0"
    health_values.update({
        ("firmware", "version"): "CX317_PPS_GATED_I_ONLY_PREVIEW_V1",
        ("firmware", "config_id"): "cx317_pps_gated_i_only_preview",
        ("firmware", "git_commit"): git_commit,
        ("firmware", "source_state"): "dirty",
        ("firmware", "source_hash"): source_hash,
        ("firmware", "config_hash"): configuration_hash,
        ("build", "profile_id"): "cx317_pps_gated_i_only_preview",
        ("build", "invocation_id"): "synthetic-stage6-build",
        ("build", "tcxo_counter_backend"): "pps_gated_ratio",
        ("pps_gate", "boundary_owner"): "pio_state_machine",
        ("pps_gate", "aperture_backend"): "pio_wait_cumulative_snapshot_dma_v1",
        ("pps_gate", "backend_qualified"): "true",
    })
    health_rows = [
        {
            "record_type": "STS", "schema_version": 1, "status_seq": index,
            "timestamp_ticks": (2401 + index) * 16_000_000,
            "status_domain": "rp2040_timer0", "component": component,
            "status_key": key, "status_value": value,
            "severity": "INFO", "flags": 0,
        }
        for index, ((component, key), value) in enumerate(health_values.items(), 1)
    ]
    _write_csv(run / "csv/health.csv", "health_v1", health_rows)
    _write_csv(run / "csv/dac_steps.csv", "dac_steps_v1", [{
        "record_type": "DAC", "schema_version": 1, "seq": 1,
        "elapsed_ms": 10_000, "step_index": -1,
        "dac_code_requested": 43344, "dac_code_applied": 43344,
        "dac_code_clamped": 0, "dwell_ms": 0,
        "event": "manual_apply", "flags": 0,
    }])
    _write_csv(run / "csv/environment.csv", "environment_v1", [{
        "record_type": "ENV", "schema_version": 1, "env_seq": 1,
        "timestamp_ticks": 1799 * 16_000_000,
        "observation_domain": "rp2040_timer0", "source": "sht4x",
        "role": "vcocxo_near", "temperature_c": "29.000",
        "relative_humidity_pct": "40.000", "flags": 0,
    }])
    estimates = [
        _estimate(0, first=13_000, last=13_060, selected=False, estimator_hash=estimator_hash),
        _estimate(1, first=13_000, last=13_600, selected=True, estimator_hash=estimator_hash),
    ]
    _write_csv(run / "csv/estimates_v2.csv", "estimates_v2", estimates)
    controls = [
        _control(
            0, tick_s=1800, estimate_ref="est:cx317:selected600:000000",
            state="QUALIFYING", previous="WARMUP_INHIBIT",
            reason="fresh_estimator_support", preview=False,
            policy_hash=policy.config_hash, model_hash=policy.plant_model_hash,
            policy_id=policy.policy_id, gain=policy.gain_nominal,
        ),
        _control(
            1, tick_s=2400, estimate_ref="est:cx317:selected600:000001",
            state="LOCKED_PREVIEW", previous="QUALIFYING",
            reason="inside_evidence_deadband", preview=True,
            policy_hash=policy.config_hash, model_hash=policy.plant_model_hash,
            policy_id=policy.policy_id, gain=policy.gain_nominal,
        ),
    ]
    _write_csv(run / "csv/control_previews_v1.csv", "control_previews_v1", controls)

    raw = run / "raw/serial.log"
    raw.parent.mkdir()
    lines = [
        '# OTIS_HOST {"event":"capture_started","utc":"2026-08-01T23:50:10Z"}',
        '# OTIS_HOST {"event":"serial_opened","utc":"2026-08-01T23:50:10Z"}',
        "CNT,1,13000,2,0,1,rp2040_timer0,10000000,R,h0_tcxo_16mhz,16",
        '# OTIS_HOST {"command":"CONFIG?","event":"host_command_accepted","utc":"2026-08-02T00:00:00Z"}',
        '# OTIS_HOST {"command":"CONFIG?","event":"host_command_sent","utc":"2026-08-02T00:00:00Z"}',
        '# OTIS_HOST {"command":"DAC SET 0xA950","event":"host_command_accepted","utc":"2026-08-02T00:00:10Z"}',
        '# OTIS_HOST {"command":"DAC SET 0xA950","event":"host_command_sent","utc":"2026-08-02T00:00:10Z"}',
        "DAC,1,1,10000,-1,43344,43344,0,,,0,manual_apply,0",
        "CNT,1,13001,2,1,2,rp2040_timer0,10000000,R,h0_tcxo_16mhz,16",
    ]
    for second in range(60):
        utc = f"2026-08-02T05:00:{second:02d}Z"
        lines.extend([
            f'# OTIS_HOST {{"command":"CONFIG?","event":"host_command_accepted","utc":"{utc}"}}',
            f'# OTIS_HOST {{"command":"CONFIG?","event":"host_command_sent","utc":"{utc}"}}',
        ])
    lines.extend([
        "CNT,1,13600,2,2,3,rp2040_timer0,10000000,R,h0_tcxo_16mhz,16",
        '# OTIS_HOST {"duration_s":22200.0,"event":"planned_duration_complete","utc":"2026-08-02T06:00:10Z"}',
        '# OTIS_HOST {"bytes_written":1,"commands_rejected":0,"commands_sent":62,"event":"capture_stopped","lines_parsed":1,"lines_seen":1,"malformed_utf8":0,"parser_errors":0,"reconnect_count":0,"utc":"2026-08-02T06:00:10Z"}',
    ])
    raw.write_text("\n".join(lines) + "\n", encoding="utf-8")

    service_path = tmp_path / "service.json"
    service_path.write_text(json.dumps({
        "schema_version": 1,
        "status": "complete",
        "command": "CONFIG?",
        "planned_request_count": 60,
        "cadence_period_s": 1.0,
        "trigger_count_sequence": 13001,
        "observed_total_probe_commands": 60,
        "commands_sent_this_invocation": 60,
        "dac_command": False,
        "first_probe_marker": {"command": "CONFIG?", "count_sequence": 13001, "utc": "2026-08-02T05:00:00Z"},
        "last_probe_marker": {"command": "CONFIG?", "count_sequence": 13001, "utc": "2026-08-02T05:00:59Z"},
    }), encoding="utf-8")
    uf2_path = tmp_path / "otis_nano_rp2040_connect.ino.uf2"
    uf2_path.write_bytes(uf2_bytes)
    build_manifest_path = tmp_path / "firmware_build_manifest.json"
    build_manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "artifacts": [{
            "name": uf2_path.name,
            "sha256": uf2_hash,
            "size_bytes": len(uf2_bytes),
        }],
        "provenance": {
            "configuration": {
                "profile_id": "cx317_pps_gated_i_only_preview",
                "sha256": configuration_hash,
            },
            "source": {
                "git_commit": git_commit,
                "state": "dirty",
                "sha256": source_hash,
            },
            "invocation": {"id": "synthetic-stage6-build"},
        },
    }), encoding="utf-8")
    return run, service_path, build_manifest_path, uf2_path


def test_stage6_live_analyzer_recomputes_estimator_and_controller(tmp_path: Path) -> None:
    run, service, build_manifest, uf2 = _run(tmp_path)
    output, result = analyze(
        run,
        service,
        firmware_build_manifest_path=build_manifest,
        firmware_uf2_path=uf2,
    )

    assert output.is_file()
    assert result["exit_gate"] == "pass_observe_only"
    assert result["capture"]["static_duration_s"] == 21_600
    assert result["estimator_parity"]["selected_row_count"] == 1
    assert result["controller_parity"]["preview_available_count"] == 1
    assert all(item["passed"] for item in result["checks"])
    report = (run / "reports/STAGE6_LIVE_PREVIEW.md").read_text(encoding="utf-8")
    assert "## Tolerance provenance" in report
    assert "| Parameter and units" in report


def test_stage6_live_analyzer_fails_closed_on_numeric_mismatch(tmp_path: Path) -> None:
    run, service, build_manifest, uf2 = _run(tmp_path)
    path = run / "csv/estimates_v2.csv"
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    rows[-1]["frequency_estimate_hz"] = "10000000.000000000001"
    _write_csv(path, "estimates_v2", rows)

    _, result = analyze(
        run,
        service,
        firmware_build_manifest_path=build_manifest,
        firmware_uf2_path=uf2,
    )

    assert result["exit_gate"] == "fail_closed"
    parity = next(item for item in result["checks"] if item["identifier"] == "estimator_host_firmware_numeric_parity")
    assert parity["passed"] is False


def test_stage6_live_analyzer_refuses_healthy_active_capture(tmp_path: Path) -> None:
    run, service, build_manifest, uf2 = _run(tmp_path)
    (run / "capture_in_progress.flag").touch()

    with pytest.raises(RuntimeError, match="still in progress"):
        analyze(
            run,
            service,
            firmware_build_manifest_path=build_manifest,
            firmware_uf2_path=uf2,
        )


def test_stage6_live_analyzer_requires_exact_build_evidence_for_pass(
    tmp_path: Path,
) -> None:
    run, service, _, _ = _run(tmp_path)

    _, result = analyze(run, service)

    assert result["exit_gate"] == "fail_closed"
    binding = next(
        item for item in result["checks"]
        if item["identifier"] == "exact_firmware_build_binding"
    )
    assert binding["passed"] is False
    assert result["firmware_build_binding"]["status"] == "unavailable"


def test_stage6_live_analyzer_reports_shortened_legacy_run_fail_closed(
    tmp_path: Path,
) -> None:
    run, service, _, _ = _run(tmp_path)
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["controller_preview"]["preflight_identity_query"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _write_csv(run / "csv/estimates_v2.csv", "estimates_v2", [])
    raw_path = run / "raw/serial.log"
    raw_path.write_text(
        "\n".join(
            line for line in raw_path.read_text(encoding="utf-8").splitlines()
            if '"event":"planned_duration_complete"' not in line
        ) + "\n",
        encoding="utf-8",
    )
    service_result = json.loads(service.read_text(encoding="utf-8"))
    service_result["status"] = "not_tested_run_closed_before_trigger"
    service.write_text(json.dumps(service_result), encoding="utf-8")

    output, result = analyze(run, service)

    assert output.is_file()
    assert result["exit_gate"] == "fail_closed"
    assert result["capture"]["planned_duration_complete_observed"] is False
    assert result["preflight_identity_query"]["expected_count"] is None
    checks = {item["identifier"]: item for item in result["checks"]}
    assert checks["minimum_static_duration"]["passed"] is False
    assert checks["estimator_host_firmware_numeric_parity"]["passed"] is False
    assert checks["preflight_live_identity_query"]["passed"] is False
    assert checks["bounded_service_load_integrity"]["passed"] is False
    assert (run / "reports/STAGE6_LIVE_PREVIEW.md").is_file()


def test_stage6_live_analyzer_rejects_uf2_different_from_build_manifest(
    tmp_path: Path,
) -> None:
    run, service, build_manifest, uf2 = _run(tmp_path)
    uf2.write_bytes(b"different-uf2")

    _, result = analyze(
        run,
        service,
        firmware_build_manifest_path=build_manifest,
        firmware_uf2_path=uf2,
    )

    assert result["exit_gate"] == "fail_closed"
    assert result["firmware_build_binding"]["status"] == "fail"
    assert result["firmware_build_binding"]["comparisons"][
        "actual_uf2_sha256"
    ] is False


@pytest.mark.parametrize(
    ("raw_delta_offset", "expected_parity"),
    [
        (Decimal("0.000000001000"), True),
        (Decimal("0.000000002000"), False),
    ],
)
def test_controller_raw_delta_parity_propagates_serialized_input_bound(
    tmp_path: Path,
    raw_delta_offset: Decimal,
    expected_parity: bool,
) -> None:
    run, service, build_manifest, uf2 = _run(tmp_path)
    controls_path = run / "csv/control_previews_v1.csv"
    controls = list(csv.DictReader(controls_path.open(newline="", encoding="utf-8")))
    controls[-1]["raw_delta_codes"] = str(
        Decimal(controls[-1]["raw_delta_codes"]) + raw_delta_offset
    )
    _write_csv(controls_path, "control_previews_v1", controls)

    _, result = analyze(
        run,
        service,
        firmware_build_manifest_path=build_manifest,
        firmware_uf2_path=uf2,
    )

    check = next(
        item for item in result["checks"]
        if item["identifier"] == "controller_host_firmware_parity"
    )
    assert check["passed"] is expected_parity
    assert result["controller_parity"][
        "raw_delta_numeric_tolerance_codes"
    ] == pytest.approx(1.4427513853232258e-9, rel=0, abs=1e-24)


def test_controller_parity_unwraps_long_run_timer_and_environment_ticks() -> None:
    policy = load_policy()
    times_s = [1800, 2400, 3000, 3600, 4200, 4800]
    controls: list[dict[str, str]] = []
    estimates: dict[str, dict[str, str]] = {}
    for sequence, timestamp_s in enumerate(times_s):
        preview = sequence > 0
        estimate_ref = (
            f"est:cx317:selected600:{sequence:06d}"
            if preview else "est:cx317:selected600:000000"
        )
        if preview:
            estimates[estimate_ref] = {"frequency_error_hz": "0.000000000000"}
        row = _control(
            sequence,
            tick_s=timestamp_s,
            estimate_ref=estimate_ref,
            state="LOCKED_PREVIEW" if preview else "QUALIFYING",
            previous=(
                "WARMUP_INHIBIT" if sequence == 0 else
                "QUALIFYING" if sequence == 1 else
                "LOCKED_PREVIEW"
            ),
            reason="inside_evidence_deadband" if preview else "fresh_estimator_support",
            preview=preview,
            policy_hash=policy.config_hash,
            model_hash=policy.plant_model_hash,
            policy_id=policy.policy_id,
            gain=policy.gain_nominal,
        )
        row["decision_timestamp_ticks"] = (
            timestamp_s * 16_000_000
        ) % RP2040_TIMER0_MICROS_WRAP_TICKS
        if sequence >= 2:
            row["state_transition"] = "false"
        controls.append({key: str(value) for key, value in row.items()})

    environment = [
        {
            "timestamp_ticks": str(
                timestamp_s * 16_000_000
                % RP2040_TIMER0_MICROS_WRAP_TICKS
            ),
            "source": "sht4x",
            "role": "vcocxo_near",
            "temperature_c": temperature,
        }
        for timestamp_s, temperature in (
            (1799, "29.000"), (4200, "29.050"), (4500, "29.100")
        )
    ]

    checks, result = _controller_parity(
        controls, estimates, environment, policy
    )

    parity = next(
        item for item in checks
        if item.identifier == "controller_host_firmware_parity"
    )
    assert parity.passed is True
    assert result["decision_timestamp_wrap_count"] == 1
    assert result["environment_timestamp_wrap_count"] == 1
    assert result["comparisons"][-1]["timestamp_s"] == 4800
    assert result["comparisons"][-1]["temperature_c"] == 29.1
