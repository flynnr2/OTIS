from __future__ import annotations

import json
from pathlib import Path

from tools.verify_pio_snapshot import (
    verify_dma_ring_model,
    verify_fault_paths,
    verify_program_structure,
    verify_repository_installation,
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
        ROOT / "firmware/arduino/firmware_matrix.json",
    )
    assert installed["matrix_fqbn"].endswith(":freq=133")
    assert installed["in_base_gpio"] == 20
    assert installed["jmp_pin_gpio"] == 26
    assert installed["input_synchronizers"] == "enabled"


def test_stop_onset_full_fifo_startup_and_counter_wrap_fail_closed() -> None:
    faults = verify_fault_paths()
    stopped = faults["stopped_oscillator"]
    assert stopped["parked_wait_pps_snapshots"] == 0
    assert stopped["finite_tail_max_snapshots"] <= 1
    assert faults["full_fifo"].startswith("RXSTALL after 8 unread words")
    assert faults["startup_mid_high"] == "suppressed until low then next rise"
    transport = verify_dma_ring_model()
    assert transport["exact_capacity"] == "lossless"
    assert transport["overwrite_by_one"].startswith("detected")


def test_d14_and_d10_isrs_only_preserve_compact_events() -> None:
    capture = (FW / "otis_capture_irq.cpp").read_text(encoding="utf-8")
    d14 = _function_body(capture, "void handle_capture_edge(void)")
    d10_source = (FW / "otis_pps_dual_observer.cpp").read_text(
        encoding="utf-8"
    )
    d10 = _function_body(d10_source, "void handle_d10_witness_edge(void)")

    prohibited = (
        "Serial",
        "digitalRead",
        "delay(",
        "millis(",
        "otis_capture_ticks_now()",
        "otis_classify_pps_interval_ticks",
        "pio_sm_",
        "dma_",
        "float",
        "double",
    )
    for body in (d14, d10):
        assert not any(token in body for token in prohibited)
        assert "otis_capture_ticks_now_from_isr" in body
        assert "gpio_get" in body
    assert "otis_capture_ring_push_from_isr" in d14
    assert "push_d10_event_from_isr" in d10
    assert "d14_sampled_high_count" not in d14
    assert "d14_last_raw_timestamp" not in d14
    assert "d10_sampled_high_count" not in d10
    assert "d10_last_edge_timestamp" not in d10


def test_d14_isr_has_no_count_aperture_control() -> None:
    capture = (FW / "otis_capture_irq.cpp").read_text(encoding="utf-8")
    assert "pps_boundary_callback" not in capture
    assert "stop_h1_pio" not in capture
    assert "start_h1_pio" not in capture
    assert "sample_h1_pio" not in capture


def test_late_snapshot_cannot_be_paired_after_an_unmatched_reference() -> None:
    sketch = (FW / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    body = _function_body(sketch, "void drain_pps_count_boundary_ring(void)")
    assert "another_reference_waiting" in body
    assert "otis_pps_snapshot_backend_rearm()" in body
    assert "paired retroactively" in body
    assert "discard_first_recovery_snapshot" not in body
    assert "otis_pps_count_boundary_ring_reset()" in body
    assert body.index("another_reference_waiting") < body.index(
        "otis_pps_snapshot_backend_pop"
    )
    assert "otis_count_observation_note_association_loss" in body
    assert '"ref_without_snapshot"' in body

    count_source = (FW / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    association_loss = _function_body(
        count_source, "void otis_count_observation_note_association_loss("
    )
    assert 'association_state = "lost"' in association_loss
    assert "have_previous_observation = false" in association_loss
    assert "kCountReasonSnapshotAbsent" in association_loss
    assert "OTIS_FLAG_GATE_INCOMPLETE" in association_loss


def test_backend_candidate_remains_unqualified_and_old_isr_identity_is_gone() -> None:
    matrix = json.loads(
        (ROOT / "firmware/arduino/firmware_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    candidate_profiles = [
        profile
        for profile in matrix["profiles"]
        if profile["defines"].get("OTIS_TCXO_COUNTER_BACKEND")
        == "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
        and profile["expect"] == "pass"
    ]
    assert candidate_profiles
    assert all(
        profile["defines"]["OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED"] == "0"
        for profile in candidate_profiles
    )

    production_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FW.iterdir()
        if path.suffix in {".cpp", ".h", ".ino", ".pio"}
    )
    assert "pps_isr_stop_sample_restart_v1" not in production_sources
    assert "pio_wait_cumulative_snapshot_dma_v1" in production_sources


def test_counter_wrap_envelope_does_not_treat_nominal_frequency_as_a_maximum() -> None:
    config = (FW / "otis_config.h").read_text(encoding="utf-8")
    count_source = (FW / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )

    assert "OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ 133000000u" in config
    assert "OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ" in count_source
    assert '"declared_max_captured_edge_rate_hz"' in count_source
    assert '"declared_max_oscillator_hz"' not in count_source
