from __future__ import annotations

from pathlib import Path
import csv
import shutil
import subprocess

import pytest

from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.firmware_host_contract import validate_record_wire_values


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_phase_preview_binds_only_after_confirmed_application(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "phase_preview_binding"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/phase_preview_binding_harness.cpp"),
            str(FIRMWARE / "otis_phase_preview_live.cpp"),
            str(FIRMWARE / "otis_selected_phase_frequency_preview_engine.cpp"),
            str(FIRMWARE / "otis_phase_preview_format.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    completed = subprocess.run([str(executable)], cwd=ROOT, check=True, capture_output=True, text=True)
    rows = list(csv.reader(completed.stdout.splitlines()))
    assert rows and len(rows) % 2 == 0
    for rph_values, phe_values in zip(rows[::2], rows[1::2], strict=True):
        assert validate_record_wire_values("relative_phase_observations_v2", rph_values) == ()
        assert validate_record_wire_values("phase_estimator_outputs_v2", phe_values) == ()
        rph = dict(zip(CONTRACT_FIELDS["relative_phase_observations_v2"], rph_values, strict=True))
        phe = dict(zip(CONTRACT_FIELDS["phase_estimator_outputs_v2"], phe_values, strict=True))
        for field in ("phase_epoch", "observation_sequence", "capture_session", "acceptance_epoch", "accepted_boundary_ordinal"):
            assert rph[field] == phe[field]
        if rph["qualification_state"] == "qualified":
            assert rph["source_accepted_span_ref"] == (
                f"live:APS:{rph['capture_session']}:{rph['acceptance_epoch']}:{rph['accepted_boundary_ordinal']}"
            )
        else:
            assert rph["source_accepted_span_ref"] == ""


def test_sketch_does_not_fabricate_a_pre_setup_code() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    frequency_live = (FIRMWARE / "otis_frequency_regulation_live.cpp").read_text(
        encoding="utf-8"
    )
    start = sketch.index("OtisRegulationStaticCodeState regulation_static_code_state")
    end = sketch.index("\nvoid ", start)
    static_state = sketch[start:end]

    assert "return dual_core_static_code;" in static_state
    assert "if (!dual_core_static_code.available)" not in static_state
    assert "TIGHT_DEADBAND_INITIAL" not in config
    assert "otis_phase_preview_live_begin();" in sketch
    assert '"applied_code_bound"' in sketch
    assert '"static_code"' not in sketch
    assert 'char current_code[16] = "";' in frequency_live
    assert '"%u", code->applied_code' in frequency_live
