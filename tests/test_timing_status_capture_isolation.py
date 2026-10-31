"""PPS arrival inside the production periodic publisher and real selector."""

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
    executable = tmp_path / "collision"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-fsanitize=undefined,address",
            "-fno-omit-frame-pointer",
            '-DOTIS_BUILD_SOURCE_SHA256="native"',
            '-DOTIS_BUILD_CONFIG_SHA256="native"',
            "-I",
            str(FW),
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
                ]
            ),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)


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
