from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from host.otis_tools.active_status_live_state import ActiveStatusLiveReducer
from host.otis_tools.contracts import HEALTH_FIELDS


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_production_dual_core_active_status_uses_bounded_contract_component() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = sketch.index("void publish_dual_core_active_status_field")
    end = sketch.index("\nbool publish_dual_core_active_status", start)
    production_sink = sketch[start:end]
    assert "OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT" in production_sink
    assert '"adaptive_hybrid_regulation"' not in production_sink


def test_adaptive_hybrid_status_getter_preserves_application_and_checkpoint(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "adaptive_hybrid_active_status"
    dead_strip = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-variable",
            "-Wno-unused-function",
            "-ffunction-sections",
            "-fdata-sections",
            str(ROOT / "tests/cpp/adaptive_hybrid_active_status_harness.cpp"),
            str(FIRMWARE / "otis_regulation_transaction.cpp"),
            str(FIRMWARE / "otis_active_hybrid_decision_types.cpp"),
            str(FIRMWARE / "otis_active_hybrid_decision_format.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_regulation.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_maintenance_format.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_maintenance_record.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_wide.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            *dead_strip,
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    completed = subprocess.run(
        [str(executable)], cwd=ROOT, check=True, capture_output=True, text=True
    )
    reducer = ActiveStatusLiveReducer()
    updates: list[dict[str, object]] = []
    rows = list(csv.reader(completed.stdout.splitlines()))
    assert rows
    for values in rows:
        assert len(values) == len(HEALTH_FIELDS)
        row = dict(zip(HEALTH_FIELDS, values, strict=True))
        assert row["component"] == "adaptive_hybrid"
        update = reducer.observe(row)
        if update is not None:
            updates.append(update)
    complete_updates = [
        update for update in updates if update["state"] == "complete"
    ]
    assert len(complete_updates) == 2
    pre_setup = {
        (record["component"], record["status_key"]): record["status_value"]
        for record in complete_updates[0]["records"]
    }
    assert pre_setup[("adaptive_hybrid", "state")] == "DISARMED"
    assert pre_setup[("adaptive_hybrid", "reason")] == "initialized_disarmed"
    assert pre_setup[("adaptive_hybrid", "hybrid_state")] == "SETUP_PENDING"
    assert (
        pre_setup[("adaptive_hybrid", "hybrid_reason")]
        == "setup_consumers_pending"
    )
    assert pre_setup[("adaptive_hybrid", "manual_start_confirmed")] == "false"
    assert (
        pre_setup[("adaptive_hybrid", "confirmed_applied_code_known")] == "false"
    )
    assert pre_setup[("adaptive_hybrid", "fail_static")] == "false"
    assert pre_setup[("adaptive_hybrid", "correction_count")] == "0"
    assert pre_setup[("adaptive_hybrid", "cumulative_movement_codes")] == "0"
    assert pre_setup[("adaptive_hybrid", "dac_epoch")] == "0"
    assert updates[-1]["state"] == "complete"
    assert updates[-1]["reason"] == "snapshot_generation_complete"
