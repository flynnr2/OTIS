from __future__ import annotations

from pathlib import Path
import json

import pytest

from host.otis_tools.cx317_open_loop_executor import (
    HealthMonitor,
    UNIVERSAL_COUNTER_KEYS,
    dac_acknowledgements,
    require_gate_authorized,
    require_new_exact_ack,
    require_run_binding,
)
from host.otis_tools.cx317_open_loop_scheduler import load_plan


HEADER = (
    "record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,"
    "dac_code_applied,dac_code_clamped,dac_voltage_measured_v,"
    "ocxo_tune_voltage_measured_v,dwell_ms,event,flags\n"
)


def _write_ack(path: Path, row: str) -> None:
    path.write_text(HEADER + row + "\n", encoding="utf-8")


def _write_health_run(
    root: Path, agreement: str = "MATCHING"
) -> tuple[Path, Path, int]:
    run_dir = root / "run"
    (run_dir / "csv").mkdir(parents=True)
    (run_dir / "raw").mkdir()
    (run_dir / "capture_in_progress.flag").touch()
    header = "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags\n"
    rows = []
    sequence = 0
    for key in sorted(UNIVERSAL_COUNTER_KEYS):
        sequence += 1
        rows.append(
            f"STS,1,{sequence},{sequence},rp2040_timer0,pps_gate,{key},0,INFO,0"
        )
    sequence += 1
    rows.append(
        f"STS,1,{sequence},{sequence},rp2040_timer0,pps_dual_observer,agreement_state,{agreement},INFO,0"
    )
    health_path = run_dir / "csv" / "health.csv"
    health_path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    (run_dir / "raw" / "serial.log").write_text("", encoding="utf-8")
    return run_dir, health_path, sequence


def test_exact_manual_acknowledgement_is_required(tmp_path: Path) -> None:
    path = tmp_path / "dac_steps.csv"
    _write_ack(path, "DAC,1,7,100,-1,43344,43344,0,,,0,manual_apply,0")
    acknowledgement = require_new_exact_ack(path, 6, 43344)
    assert acknowledgement is not None
    assert acknowledgement.seq == 7
    assert acknowledgement.applied_code == 43344
    assert len(dac_acknowledgements(path)) == 1


@pytest.mark.parametrize(
    "row,message",
    [
        ("DAC,1,7,100,-1,43344,43345,0,,,0,manual_apply,0", "applied-code"),
        ("DAC,1,7,100,-1,43344,43344,1,,,0,manual_apply,0", "clamping"),
        ("DAC,1,7,100,-1,43344,43344,0,,,0,manual_write_failed,32", "event"),
        ("DAC,1,7,100,-1,43344,43344,0,,,0,manual_apply,32", "flag"),
    ],
)
def test_bad_acknowledgement_fails_closed(tmp_path: Path, row: str, message: str) -> None:
    path = tmp_path / "dac_steps.csv"
    _write_ack(path, row)
    with pytest.raises(RuntimeError, match=message):
        require_new_exact_ack(path, 6, 43344)


def test_physical_gate_must_explicitly_authorize(tmp_path: Path) -> None:
    path = tmp_path / "gate.json"
    path.write_text(
        json.dumps(
            {"decision": "not_ready", "hardware_execution_authorized": False}
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="not authorized"):
        require_gate_authorized(path)
    path.write_text(
        json.dumps({"decision": "pass", "hardware_execution_authorized": True}),
        encoding="utf-8",
    )
    assert require_gate_authorized(path)["decision"] == "pass"


def test_health_monitor_stops_on_counter_increase(tmp_path: Path) -> None:
    run_dir, health_path, sequence = _write_health_run(tmp_path)
    monitor = HealthMonitor.start(run_dir)
    monitor.check()
    with health_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"STS,1,{sequence + 1},{sequence + 1},rp2040_timer0,pps_gate,snapshot_dma_error_count,1,WARN,0\n"
        )
    with pytest.raises(RuntimeError, match="snapshot_dma_error_count"):
        monitor.check()


def test_general_auxiliary_input_is_not_implicitly_treated_as_pps(
    tmp_path: Path,
) -> None:
    run_dir, _, _ = _write_health_run(tmp_path, agreement="D14_EXCESS")
    monitor = HealthMonitor.start(
        run_dir, require_auxiliary_match_to_d14=False
    )
    monitor.check()


def test_run_declared_same_pps_auxiliary_input_requires_matching(
    tmp_path: Path,
) -> None:
    run_dir, _, _ = _write_health_run(tmp_path, agreement="D14_EXCESS")
    with pytest.raises(RuntimeError, match="not matching"):
        HealthMonitor.start(
            run_dir, require_auxiliary_match_to_d14=True
        )


def test_run_binding_requires_exact_campaign_firmware_and_estimator(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "stage5_open_loop_20260802T120000Z"
    run_dir.mkdir()
    template = json.loads(
        Path(
            "profiles/run_templates/cx317_pps_gated_open_loop_v1/manifest.json"
        ).read_text(encoding="utf-8")
    )
    template["template"] = False
    template["run_id"] = run_dir.name
    (run_dir / "run_manifest.json").write_text(
        json.dumps(template), encoding="utf-8"
    )
    plan = load_plan(
        Path("profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json")
    )

    dac, health, raw = require_run_binding(run_dir, plan)
    assert dac == run_dir / "csv" / "dac_steps.csv"
    assert health == run_dir / "csv" / "health.csv"
    assert raw == run_dir / "raw" / "serial.log"

    template["firmware"]["uf2_sha256"] = "0" * 64
    (run_dir / "run_manifest.json").write_text(
        json.dumps(template), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="UF2|uf2"):
        require_run_binding(run_dir, plan)


def test_run_binding_rejects_implicit_pps_semantics_for_general_input(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "stage5_open_loop_20260802T120000Z"
    run_dir.mkdir()
    template = json.loads(
        Path(
            "profiles/run_templates/cx317_pps_gated_open_loop_v1/manifest.json"
        ).read_text(encoding="utf-8")
    )
    template["template"] = False
    template["run_id"] = run_dir.name
    template["auxiliary_edge_input"]["current_connection"] = (
        "other_general_edge_source"
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps(template), encoding="utf-8"
    )
    plan = load_plan(
        Path("profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json")
    )
    with pytest.raises(RuntimeError, match="health policy"):
        require_run_binding(run_dir, plan)
