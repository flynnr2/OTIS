from pathlib import Path
import csv
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_live_owner_causal_hold_wrap_and_raw_span_identity(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("native compiler unavailable")
    executable = tmp_path / "acceptance_live"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    str(ROOT / "tests/cpp/reference_acceptance_live_harness.cpp"),
                    "-I", str(ROOT / "firmware/arduino/otis_nano_rp2040_connect"),
                    "-o", str(executable)], check=True)
    result = subprocess.run([str(executable)], capture_output=True, text=True, check=True)
    row, = list(csv.reader(result.stdout.splitlines()))
    assert len(row) == 19
    assert row[:2] == ["APS", "1"]
    assert row[4] == "250"
    assert row[14:18] == ["2", "10000000", "1", "1"]


def test_generated_policy_and_fixed_build_binding():
    from tools.generate_reference_acceptance_policy import HEADER, render_header
    assert HEADER.read_text() == render_header()
    import json
    manifest = json.loads((ROOT / "firmware/arduino/firmware_build_manifest.json").read_text())
    assert manifest["contract_bindings"]["reference_acceptance"] == "data_contracts/reference_acceptance_policy_v2.json"


def test_core0_execute_admits_exact_identity_before_write():
    """Physical execution uses the native-tested shared admission function."""
    firmware = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    sketch = (firmware / "otis_nano_rp2040_connect.ino").read_text()
    executor = sketch[sketch.index("void service_instrument_executor"):sketch.index("void note_observation_queue_service")]
    assert executor.index("otis_gnss_receiver_get_snapshot") < executor.index("otis_instrument_executor_admit")
    assert executor.index("otis_instrument_executor_admit") < executor.index("otis_dac_ad5693r_set_raw")
    assert executor.index("otis_dac_ad5693r_set_raw") < executor.index("otis_dual_core_publish_instrument_application")
