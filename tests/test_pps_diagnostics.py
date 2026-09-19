from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"
HARNESS = ROOT / "tests" / "cpp" / "pps_diagnostics_harness.cpp"
HEADER = FIRMWARE / "otis_pps_diagnostics.h"
COUNT_OBSERVATION = FIRMWARE / "otis_count_observation.cpp"


def test_pps_diagnostics_state_machine(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")

    binary = tmp_path / "pps_diagnostics_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(FIRMWARE),
            str(HARNESS),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_pps_diagnostics_core_has_no_service_plane_dependencies() -> None:
    source = HEADER.read_text(encoding="utf-8")
    for prohibited in (
        "Arduino.h",
        "Serial",
        "snprintf",
        "printf(",
        "malloc(",
        "calloc(",
        "realloc(",
        "operator new",
        "otis_emit_",
        "otis_transport_",
    ):
        assert prohibited not in source

    assert "otis_monotonic_us32_interval" in source
    assert "latest_capture_service" in source
    assert "latest_snapshot_produced" in source
    assert "latest_snapshot_drained" in source
    assert "latest_measurement_reconstructed" in source
    assert "latest_telemetry_emitted" in source
    assert "latest_control_observed" in source


def test_capture_watchdog_samples_now_after_backend_service_coordinate() -> None:
    source = COUNT_OBSERVATION.read_text(encoding="utf-8")
    backend = source[source.index("bool otis_count_observation_service") :]

    mailbox_copy = backend.index("otis_pps_snapshot_backend_get_stats")
    mailbox_note = backend.index("otis_pps_diagnostics_note_capture_service")
    now_sample = backend.index("uint64_t now_ticks = otis_monotonic_us32_now();")
    watchdog_poll = backend.index("otis_pps_diagnostics_poll")

    assert mailbox_copy < mailbox_note < now_sample < watchdog_poll
    assert "reports stale FIFO service only" in backend


def test_count_control_eligibility_comes_only_from_common_acceptance() -> None:
    source = COUNT_OBSERVATION.read_text(encoding="utf-8")

    assert "otis_capture_irq" not in source
    assert "update_control_gate" not in source
    predicate = """runtime_state->tcxo.valid_for_control =
      !runtime_state->tcxo.startup_inhibit_active &&
      accepted_reference_status.tracking &&
      accepted_reference_status.anchor_current;"""
    assert source.count(predicate) == 2
    assert "accepted_reference_status.anchor_current &&" not in source
    assert '"capture_state"' in source
    assert 'capture_state = counter_ok ? "clean" : "lost"' in source
    assert '"capture_loss_count"' in source
    assert '"capture_loss_reason"' in source
    assert '"snapshot_producer_ordinal"' in source
    assert '"snapshot_consumer_ordinal"' in source
    assert '"snapshot_producer_sequence"' not in source
    assert '"snapshot_consumer_sequence"' not in source
    assert "association_" not in source
    assert "snapshot_dma" not in source
