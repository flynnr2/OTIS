"""PPS arrival inside the production periodic publisher and real selector."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def function(source, name):
    start = source.index(name)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def test_periodic_publication_collision_preserves_first_accepted_span(tmp_path):
    source = (FW / "otis_nano_rp2040_connect.ino").read_text()
    signatures = [
        "void publish_dual_core_timing_status(const",
        "void publish_dual_core_timing_status_sink(",
        "void publish_dual_core_timing_status_u32(const char *component,\n                                         const char *key, uint32_t value,\n                                         const char *severity,\n                                         uint32_t flags) {",
        "void publish_forwarded_clock_monitor_status(void)",
        "void publish_dual_core_active_status_field(void",
        "bool publish_dual_core_active_status(uint32_t",
        "void publish_dual_core_timing_health(uint32_t",
    ]
    # Compile the actual production publisher bodies, not a synthetic copy of
    # their control flow. Native ports replace only hardware/state dependencies.
    (tmp_path / "publication.inc").write_text(
        "\n".join(function(source, s) for s in signatures)
    )
    compiler = shutil.which("c++")
    assert compiler
    stubs = tmp_path / "stubs"
    (stubs / "hardware/structs").mkdir(parents=True)
    (stubs / "Arduino.h").write_text(
        '#pragma once\n#include <stdint.h>\nclass Stream;\n'
        '#define D10 5\n#define D14 26\n#define D8 20\n#define D9 21\n'
        '#define D6 18\n#define PIN_SERIAL1_RX 1\n#define PIN_SERIAL1_TX 0\n'
        'uint32_t millis();\nuint32_t micros();\nuint64_t time_us_64();\n'
    )
    (stubs / "hardware/structs/timer.h").write_text(
        '#pragma once\n#include <stdint.h>\n'
        'struct mock_timer { uint32_t timerawl; };\nextern mock_timer *timer_hw;\n'
    )
    (stubs / "hardware/pio_instructions.h").write_text('#pragma once\n')
    options = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-Wno-unused-const-variable",
        "-fsanitize=undefined,address", "-fno-omit-frame-pointer",
        "-DARDUINO_ARCH_RP2040", "-I", str(stubs),
        "-I", str(ROOT / "tests/cpp/pps_snapshot_backend_stubs"),
        "-I", str(FW),
    ]
    count_object = tmp_path / "count.o"
    subprocess.run(
        [*options, "-Dotis_dual_core_publish_telemetry=publish_with_elapsed",
         "-c", str(FW / "otis_count_observation.cpp"), "-o", str(count_object)],
        check=True, capture_output=True, text=True,
    )
    executable = tmp_path / "collision"
    subprocess.run(
        [
            *options,
            '-DOTIS_BUILD_SOURCE_SHA256="native"',
            '-DOTIS_BUILD_CONFIG_SHA256="native"',
            "-I",
            str(tmp_path),
            str(ROOT / "tests/cpp/timing_status_capture_isolation_harness.cpp"),
            *(
                str(FW / name)
                for name in [
                    "otis_instrument.cpp",
                    "otis_adaptive_hybrid_regulation_live.cpp",
                    "otis_adaptive_hybrid_regulation.cpp",
                    "otis_adaptive_hybrid_wide.cpp",
                    "otis_regulation_transaction.cpp",
                    "otis_dual_core_partition.cpp",
                    "otis_oscillator_snapshot_estimator.cpp",
                    "otis_status_emit.cpp",
                ]
            ),
            str(count_object),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)


def test_retained_count_status_gap_keeps_all_original_qualification_losses(tmp_path):
    fixture = json.loads((ROOT / "tests/fixtures/timing_status/"
                          "periodic_count_status_gap_20261101.json").read_text())
    policy = json.loads((ROOT / "data_contracts/reference_acceptance_policy_v2.json").read_text())
    binary = tmp_path / "trace"
    compiler = shutil.which("c++")
    assert compiler
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
        str(ROOT / "tests/cpp/reference_acceptance_harness.cpp"),
        "-I", str(FW), "-o", str(binary),
    ], check=True, capture_output=True, text=True)
    commands = []
    for values in fixture["snapshots"]:
        row = dict(zip(fixture["columns"], values, strict=True))
        commands.append("O " + " ".join(map(str, (
            fixture["capture_session"], row["snapshot_sequence"],
            row["reference_sequence"], row["reference_timestamp_ticks"],
            row["cumulative_down_counter"], row["status"],
            fixture["reference_flags"], row["timestamp_uncertainty_ticks"],
        ))))
    result = subprocess.run([
        str(binary), *(str(policy[key]) for key in (
            "nominal_interval_ticks", "tolerance_ticks", "acquisition_intervals",
            "maximum_edge_rate_hz", "allowed_reference_flags",
            "maximum_excluded_candidates_per_span", "maximum_count_span_ticks",
        )),
    ], input="\n".join(commands) + "\n", capture_output=True, text=True, check=True)
    results = [json.loads(line) for line in result.stdout.splitlines()]
    losses = [r for r in results if r["disposition"] == "qualification_lost"]
    assert [r["candidate"]["snapshot_sequence"] for r in losses] == fixture[
        "expected_loss_snapshot_sequences"
    ]
    assert len(losses) == 130
    assert {r["reason"] for r in losses} == {"observation_age_ambiguous"}
    assert results[-1]["acceptance_epoch"] == fixture["expected_final_acceptance_epoch"]
    assert results[-1]["tracking"]


def test_status_refresh_does_not_renew_irq_credit_or_consume_state():
    source = (FW / "otis_pps_snapshot_backend.cpp").read_text()
    body = function(source, "void otis_pps_snapshot_backend_observe_empty(void)")
    assert "get_core_num() != 1u" in body
    assert "save_and_disable_interrupts()" in body
    assert "backend.running && !backend.fault_latched" in body
    assert "otis_pps_fifo_observe_empty" in body
    for forbidden in (
        "service_fifo(",
        "set_source_enabled(",
        "irq_entries_since_poll",
        "words_since_poll",
        "backend_pop(",
        "rearm(",
        "instrument_",
    ):
        assert forbidden not in body
