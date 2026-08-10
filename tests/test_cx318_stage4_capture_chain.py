from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.capture_serial import RECORD_CONTRACTS
from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.cx318_stage4_capture_chain import (
    HANDOFF_REPORT_PATH,
    REPORT_PATH,
    compose_capture_chain,
)


CONTRACTS = (
    "count_observations_v1",
    "pps_snapshots_v1",
    "health_v1",
    "dac_steps_v1",
    "active_transactions_v1",
    "relative_phase_observations_v1",
    "phase_estimator_outputs_v1",
    "hybrid_preview_decisions_v1",
)


def _row(contract: str, **values: str) -> list[str]:
    defaults = {field: "" for field in CONTRACT_FIELDS[contract]}
    defaults.update(values)
    return [defaults[field] for field in CONTRACT_FIELDS[contract]]


def _stage_rows(snapshot: int, *, phase_observation: int | None) -> list[list[str]]:
    rows = [
        _row(
            "pps_snapshots_v1", record_type="SNP", schema_version="1", session="1",
            snapshot_sequence=str(snapshot), cumulative_down_counter=str(1000 - snapshot),
            reference_sequence=str(snapshot), reference_timestamp_ticks=str(snapshot * 16_000_000),
            status="0", backend="pio_wait_cumulative_snapshot_dma_v1",
        ),
        _row(
            "health_v1", record_type="STS", schema_version="1", status_seq=str(snapshot),
            timestamp_ticks=str(snapshot * 16_000_000), status_domain="rp2040_timer0",
            component="capture", status_key="dropped_count", status_value="0", severity="info", flags="0",
        ),
        _row(
            "health_v1", record_type="STS", schema_version="1", status_seq=str(snapshot * 10 + 1),
            timestamp_ticks=str(snapshot * 16_000_000), status_domain="rp2040_timer0",
            component="capture", status_key="pps_count_boundary_dropped_count", status_value="0", severity="info", flags="0",
        ),
        _row(
            "health_v1", record_type="STS", schema_version="1", status_seq=str(snapshot * 10 + 2),
            timestamp_ticks=str(snapshot * 16_000_000), status_domain="rp2040_timer0",
            component="dual_core", status_key="partition_fault", status_value="none", severity="info", flags="0",
        ),
        _row(
            "health_v1", record_type="STS", schema_version="1", status_seq=str(snapshot * 10 + 3),
            timestamp_ticks=str(snapshot * 16_000_000), status_domain="rp2040_timer0",
            component="dual_core", status_key="fail_static", status_value="false", severity="info", flags="0",
        ),
    ]
    if snapshot > 1:
        rows.append(
            _row(
                "count_observations_v1", record_type="CNT", schema_version="1", count_seq=str(snapshot - 1),
                channel_id="2", gate_open_ticks=str((snapshot - 1) * 16_000_000),
                gate_close_ticks=str(snapshot * 16_000_000), gate_domain="rp2040_timer0",
                counted_edges="10000000", source_edge="rising", source_domain="h0_tcxo_16mhz", flags="16",
            )
        )
    if phase_observation is not None:
        identity = f"RPH:1:{phase_observation}"
        estimate = f"PHE:1:{phase_observation}"
        rows.extend([
            _row(
                "relative_phase_observations_v1", record_type="RPH", schema_version="1", phase_epoch="1",
                observation_sequence=str(phase_observation), capture_session="1",
                opening_snapshot_sequence=str(snapshot - 1), closing_snapshot_sequence=str(snapshot),
                opening_reference_sequence=str(snapshot - 1), closing_reference_sequence=str(snapshot), dac_epoch="1",
                source_backend="pio_wait_cumulative_snapshot_dma_v1", source_file_sha256="live_stream_unsealed",
                method_id="CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1", configuration_sha256="a" * 64,
                interval_edges="10000000", edge_error_cycles="0", relative_phase_cycles="0",
                relative_phase_time_ns="0", qualification_state="qualified", observation_age_s="0",
                discontinuity_reason="", calibrated_uncertainty_status="unavailable",
            ),
            _row(
                "phase_estimator_outputs_v1", record_type="PHE", schema_version="1", phase_epoch="1",
                observation_sequence=str(phase_observation), source_relative_phase_observation=identity,
                raw_relative_phase_cycles="0", raw_relative_phase_time_ns="0", filtered_relative_phase_cycles="0",
                estimated_frequency_error_hz="", estimator_id="CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
                configuration_sha256="a" * 64, estimate_age_s="", qualification_state="initializing",
                uncertainty_status="unavailable", reason_codes="initializing",
            ),
            _row(
                "hybrid_preview_decisions_v1", record_type="HPR", schema_version="1",
                preview_sequence=str(phase_observation), candidate_id="candidate", candidate_configuration_sha256="b" * 64,
                phase_estimator_id="CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
                phase_estimator_configuration_sha256="a" * 64,
                frequency_estimator_id="cx317_selected_600s_nonoverlap_v1",
                frequency_estimator_configuration_sha256="c" * 64, configuration_sha256="b" * 64,
                phase_epoch="1", observation_sequence=str(phase_observation), dac_epoch="1",
                decision_timestamp_ticks=str(snapshot * 16_000_000), time_domain="rp2040_timer0",
                source_phase_estimate=estimate, source_frequency_estimate="unavailable", raw_relative_phase_cycles="0",
                modeled_relative_phase_cycles="", observed_frequency_error_hz="", modeled_frequency_error_hz="",
                frequency_term_hz="", phase_bias_hz="", combined_frequency_error_hz="", actual_applied_code="43048",
                shadow_code_before="43048", shadow_code_after="43048", band_state_before="INSIDE", band_state_after="INSIDE",
                preview_state="INITIALIZING_PREVIEW", decision_reason="initializing", frequency_observation_event="false",
                counterfactual_decision="false", counterfactual_correction="false", raw_counterfactual_delta_codes="",
                counterfactual_delta_codes="", counterfactual_code="43048", step_limited="false", range_clamped="false",
                correction_count="0", cumulative_movement_codes="0", alternating_correction_count="0",
                modeled_not_observed_after_divergence="false", uncertainty_status="unavailable", actionable="false",
                actuation_authorized="false", authorization_consumed="false",
            ),
        ])
    return rows


def _write_run(path: Path, rows: list[list[str]], *, pid: int, prior: Path | None = None) -> Path:
    files = [
        {"contract": contract, "path": f"csv/{contract}.csv"}
        for contract in CONTRACTS
    ]
    path.mkdir(parents=True)
    proof = path / "bindings/static_code_proof.json"
    proof.parent.mkdir()
    proof.write_text("{}\n", encoding="utf-8")
    (path / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "template": False, "run_id": path.name,
        "host": {"serial_device": "/dev/cu.usbmodem14601"}, "files": files,
        "evidence_artifacts": ["bindings/static_code_proof.json"],
        "stage4_live_preview": {"static_code_evidence": {
            "path": "bindings/static_code_proof.json", "sha256": sha256(proof.read_bytes()).hexdigest(),
        }},
    }), encoding="utf-8")
    by_contract = {contract: [] for contract in CONTRACTS}
    raw = [b'# OTIS_HOST {"event": "serial_opened"}\n', b"BOOT,1\n"]
    for row in rows:
        contract = RECORD_CONTRACTS[row[0]]
        by_contract[contract].append(row)
        raw.append((",".join(row) + "\n").encode())
    raw_path = path / "raw/serial.log"
    raw_path.parent.mkdir()
    raw_path.write_bytes(b"".join(raw))
    for contract, listed in by_contract.items():
        csv_path = path / f"csv/{contract}.csv"
        csv_path.parent.mkdir(exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(CONTRACT_FIELDS[contract])
            writer.writerows(listed)
    state = {"pid": pid, "capture_active": False, "serial_open": False, "parser_errors": 0,
             "malformed_utf8": 0, "reconnect_count": 0, "commands_rejected": 0,
             "emergency_aborts_sent": 0, "emergency_abort_latched": False, "commands_sent": 0}
    state_path = path / "reports/capture_device_state.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if prior is not None:
        report_path = path / HANDOFF_REPORT_PATH
        report_path.write_text(json.dumps({
            "tool": "cx318_capture_handoff_v1", "status": "passed", "source_run": str(prior.resolve()),
            "target_run": str(path.resolve()), "serial_device": "/dev/cu.usbmodem14601",
            "source_pid": json.loads((prior / "reports/capture_device_state.json").read_text())["pid"],
            "target_pid": pid, "commands_sent": 0, "elapsed_s": 0.2, "maximum_gap_s": 5.0,
        }), encoding="utf-8")
    return path


def test_composer_slices_reset_anchor_and_proves_chain(tmp_path: Path) -> None:
    first = _write_run(tmp_path / "first", _stage_rows(1, phase_observation=None) + _stage_rows(2, phase_observation=1), pid=10)
    second = _write_run(tmp_path / "second", _stage_rows(3, phase_observation=2), pid=20, prior=first)

    report = compose_capture_chain(
        source_runs=[first, second], first_source_start_line=1, output_run=tmp_path / "derived",
    )

    assert report["status"] == "passed"
    assert report["continuity"] == {"snp": 3, "cnt": 2, "rph": 2, "phe": 2, "hpr": 2, "session": 1, "phase_epoch": 1}
    assert report["handoffs"][0]["elapsed_s"] == 0.2
    assert (tmp_path / "derived" / REPORT_PATH).is_file()
    with (tmp_path / "derived/raw/serial.log").open("rb") as handle:
        assert handle.readlines()[0] == b'# OTIS_HOST {"event": "serial_opened"}\n'
    with (tmp_path / "derived/csv/pps_snapshots_v1.csv").open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.reader(handle))) == 4  # one header, three SNP rows


def test_composer_rejects_authority_record_without_creating_output(tmp_path: Path) -> None:
    first = _write_run(tmp_path / "first", _stage_rows(1, phase_observation=None), pid=10)
    dac = _row("dac_steps_v1", record_type="DAC", schema_version="1", seq="1")
    raw_path = first / "raw/serial.log"
    raw_path.write_bytes(raw_path.read_bytes() + (",".join(dac) + "\n").encode())
    with (first / "csv/dac_steps_v1.csv").open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerow(dac)

    with pytest.raises(ValueError, match="forbidden DAC"):
        compose_capture_chain(source_runs=[first], first_source_start_line=1, output_run=tmp_path / "derived")
    assert not (tmp_path / "derived").exists()


def test_composer_rejects_unbounded_handoff(tmp_path: Path) -> None:
    first = _write_run(tmp_path / "first", _stage_rows(1, phase_observation=None) + _stage_rows(2, phase_observation=1), pid=10)
    second = _write_run(tmp_path / "second", _stage_rows(3, phase_observation=2), pid=20, prior=first)
    report_path = second / HANDOFF_REPORT_PATH
    report = json.loads(report_path.read_text())
    report["maximum_gap_s"] = 5.1
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="bounded_gap"):
        compose_capture_chain(source_runs=[first, second], first_source_start_line=1, output_run=tmp_path / "derived")
