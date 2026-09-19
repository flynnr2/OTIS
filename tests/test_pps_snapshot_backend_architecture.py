from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_pio_snapshot import (
    run_phase_sweep,
    verify_fault_paths,
    verify_program_structure,
    verify_repository_installation,
    verify_sampled_recognition_bound,
    verify_timing_paths,
)

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    raise AssertionError(f"unterminated function {signature}")


def test_checked_in_pio_program_and_installed_configuration_match_proof() -> None:
    verify_program_structure()
    assert verify_timing_paths() == 4
    installed = verify_repository_installation(
        FW / "otis_pps_snapshot_backend.cpp",
        FW / "otis_pps_snapshot.pio.h",
        ROOT / "firmware/arduino/firmware_build_manifest.json",
    )
    assert installed["manifest_fqbn"].endswith(":freq=133")
    assert installed["image_id"] == "adaptive_hybrid_regulation"
    assert installed["in_base_gpio"] == 20
    assert installed["jmp_pin_gpio"] == 26
    assert installed["input_synchronizers"] == "enabled"


@pytest.mark.parametrize("oscillator_hz", [16_000_000, 10_000_000])
def test_boundary_quantisation_does_not_accumulate_across_clean_spans(oscillator_hz: int) -> None:
    sweep = run_phase_sweep(oscillator_hz=oscillator_hz)
    assert sweep["maximum_tested_span_intervals"] == 7
    assert set(sweep["multi_interval_boundary_error_edges"]) <= {-1, 0, 1}


def test_current_dwell_bound_covers_every_armed_state_and_depends_on_d8() -> None:
    bound = verify_sampled_recognition_bound()
    assert bound["armed_states"] == 50
    assert bound["sampled_d14_to_recognition_max_clocks"] == 9
    assert bound["sampled_d14_to_snapshot_max_clocks"] == 10
    assert bound["recognition_to_snapshot_clocks"] == 1
    slower = verify_sampled_recognition_bound(maximum_dwell=18)
    assert slower["sampled_d14_to_snapshot_max_clocks"] > 10


def test_stop_onset_full_fifo_startup_and_counter_wrap_fail_closed() -> None:
    faults = verify_fault_paths()
    stopped = faults["stopped_oscillator"]
    assert stopped["parked_wait_pps_snapshots"] == 0
    assert stopped["finite_tail_max_snapshots"] <= 1
    assert faults["full_fifo"].startswith("RXSTALL after 8 unread words")
    assert faults["startup_mid_high"] == "suppressed until low then next rise"


def test_single_owner_has_no_gpio_or_dma_pairing_runtime():
    sketch = (FW / "otis_nano_rp2040_connect.ino").read_text()
    backend = (FW / "otis_pps_snapshot_backend.cpp").read_text()
    assert "attachInterrupt" not in sketch
    assert "hardware/dma.h" not in backend
    assert "otis_pps_snapshot_backend_rearm" not in sketch
    for retired in ("otis_capture_irq.cpp", "otis_capture_ring.cpp", "otis_pps_count_boundary_ring.cpp"):
        assert not (FW / retired).exists()


def test_fixed_image_uses_the_qualified_pps_gated_snapshot_backend() -> None:
    config = (FW / "otis_config.h").read_text(encoding="utf-8")
    assert "OTIS_TCXO_COUNTER_BACKEND" not in config
    assert "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED" not in config
    production_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FW.iterdir()
        if path.suffix in {".cpp", ".h", ".ino", ".pio"}
    )
    assert "pps_isr_stop_sample_restart_v1" not in production_sources
    assert "pio_wait_cumulative_snapshot_fifo_irq_v2" in production_sources
    assert "otis_pps_snapshot_backend_begin" in production_sources


def test_counter_wrap_envelope_does_not_treat_nominal_frequency_as_a_maximum() -> None:
    config = (FW / "otis_config.h").read_text(encoding="utf-8")
    count_source = (FW / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )

    assert "OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ 133000000u" in config
    assert "OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ" in count_source
    assert '"declared_max_captured_edge_rate_hz"' in count_source
    assert '"declared_max_oscillator_hz"' not in count_source
