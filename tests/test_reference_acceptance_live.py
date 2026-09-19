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


def test_core0_execute_checks_the_retained_measurement_identity(tmp_path):
    """Compile the actual sole-writer release predicate, including modular spans."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("native compiler unavailable")
    firmware = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    sketch = (firmware / "otis_nano_rp2040_connect.ino").read_text()
    predicate = sketch.split("const bool exact_release =", 1)[1].split(";", 1)[0]
    release = sketch.index("if (!exact_release)")
    assert release < sketch.index("otis_regulation_actuator_apply_once(", release)
    source = tmp_path / "execute_identity.cpp"
    source.write_text('''
#include <cassert>
#include "otis_dual_core_contract.h"
#include "otis_adaptive_hybrid_regulation.h"
bool exact(const OtisCrossCoreActuatorRequest &request,
           const OtisCrossCoreActuatorRequest &pending) {
  return ''' + predicate + ''';
}
int main() {
  OtisCrossCoreActuatorRequest pending{};
  pending.session_id = 1;
  pending.source_acceptance_epoch = 1;
  pending.source_closing_accepted_boundary_ordinal = 600;
  assert(exact(pending, pending));
  auto request = pending;
  request.source_acceptance_epoch = 2;
  assert(!exact(request, pending));
  request = pending;
  request.session_id = 2;
  assert(!exact(request, pending));
  request = pending;
  ++request.source_opening_accepted_boundary_ordinal;
  ++request.source_closing_accepted_boundary_ordinal;
  assert(!exact(request, pending));
  pending.source_closing_accepted_boundary_ordinal = 599;
  assert(!exact(pending, pending));
  pending.source_closing_accepted_boundary_ordinal = 0;
  pending.source_opening_accepted_boundary_ordinal = UINT32_MAX - 599;
  assert(exact(pending, pending));
  request = pending;
  ++request.decision_reference_ticks;
  assert(!exact(request, pending));
  request = pending;
  ++request.monotonic_deadline_s;
  assert(!exact(request, pending));
  pending.source_acceptance_epoch = 0;
  assert(!exact(pending, pending));
}
''')
    executable = tmp_path / "execute_identity"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(firmware), str(source), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
