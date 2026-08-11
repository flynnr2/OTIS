from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def test_all_versioned_profiles_and_cycle_encoding(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "pseudo_pps_schedule"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            f"-I{FIRMWARE}",
            "tests/cpp/pseudo_pps_schedule_harness.cpp",
            str(FIRMWARE / "otis_pseudo_pps_schedule.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_generator_has_one_hardware_edge_owner_and_low_stall() -> None:
    source = (FIRMWARE / "otis_pseudo_pps.cpp").read_text(encoding="utf-8")
    pio = (FIRMWARE / "otis_pseudo_pps.pio").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(encoding="utf-8")

    assert source.count("pio_claim_unused_sm") == 1
    assert "dma_claim_unused_channel" in source
    assert "attachInterrupt" not in source
    assert "delay(" not in source
    assert "delayMicroseconds(" not in source
    assert pio.index("set pins, 0") < pio.index("pull block")
    assert pio.count(".program") == 1
    assert "irq set 7" in pio
    assert "gpio_set_dir(OTIS_PIN_PSEUDO_PPS_OUTPUT, GPIO_IN)" in source
    assert "gpio_get(OTIS_PIN_PSEUDO_PPS_OUTPUT)" in source
    assert "gpio_get(OTIS_PIN_PPS_REFERENCE)" in source
    assert "diagnostic witnesses only" in source
    assert "pio_sm_restart(generator.pio, sm)" in source
    assert "pio_encode_jmp(static_cast<uint>(generator.program_offset))" in source
    assert source.index("pio_sm_restart(generator.pio, sm)") < source.index(
        "pio_encode_jmp(static_cast<uint>(generator.program_offset))"
    )
    assert sketch.index("otis_pseudo_pps_service();") < sketch.index(
        "drain_capture_ring();"
    )
    assert '"output_high_sample_count"' in sketch
    assert '"reference_high_sample_count"' in sketch


def test_generator_is_disabled_except_explicit_loopback_profile() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    assert "#define OTIS_ENABLE_PSEUDO_PPS_GENERATOR 0" in config
    matrix = json.loads(Path("firmware/arduino/firmware_matrix.json").read_text())
    enabled_pass_profiles = [
        profile["id"]
        for profile in matrix["profiles"]
        if profile["defines"]["OTIS_ENABLE_PSEUDO_PPS_GENERATOR"] == "1"
        and profile["expect"] == "pass"
    ]
    assert enabled_pass_profiles == ["pseudo_pps_loopback"]
    profile = next(
        p for p in matrix["profiles"] if p["id"] == enabled_pass_profiles[0]
    )
    assert profile["defines"]["OTIS_ENABLE_PPS_DUAL_OBSERVER"] == "0"
    assert profile["defines"]["OTIS_ENABLE_DAC_AD5693R"] == "0"
    assert profile["defines"]["OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW"] == "0"
    assert profile["defines"]["OTIS_PPS_GATE_MIN_INTERVAL_US"] == "999500"
    assert profile["defines"]["OTIS_PPS_GATE_MAX_INTERVAL_US"] == "1000500"


def test_test_only_gate_band_does_not_relax_phase4_hash_guard() -> None:
    source = (FIRMWARE / "otis_observe_only_discipline_live.cpp").read_text(
        encoding="utf-8"
    )
    assertion = source.index(
        '"reference-quality thresholds changed; regenerate its configuration hash"'
    )
    guard = source.rfind("#if OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW", 0, assertion)
    end = source.index("#endif", assertion)

    assert guard != -1
    assert guard < assertion < end


def test_central_registry_claims_all_generator_resources() -> None:
    registry = (FIRMWARE / "otis_resource_registry.cpp").read_text(
        encoding="utf-8"
    )
    assert "OTIS_PIN_PSEUDO_PPS_OUTPUT" in registry
    assert "kPseudoPpsPioProgramLength" in registry
    assert "OtisResourceType::PioIrqFlag" in registry
    assert '"finite_schedule_transport"' in registry
    assert registry.count("OTIS_OWNER_PSEUDO_PPS") >= 4


def test_commands_preserve_bounded_existing_framing() -> None:
    parser = (FIRMWARE / "otis_serial_command.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    for command in (
        "PPSGEN PROFILES?",
        "PPSGEN ARM ",
        "PPSGEN START",
        "PPSGEN STOP",
        "PPSGEN?",
    ):
        assert command in parser
    service = sketch[sketch.index("void service_serial_commands(void)") :]
    assert "uint8_t byte_budget = 32u" in service
    assert "return;" in service


def test_truth_is_separate_from_detected_reference_records() -> None:
    protocol = (FIRMWARE / "otis_protocol.h").read_text(encoding="utf-8")
    emit = (FIRMWARE / "otis_emit.cpp").read_text(encoding="utf-8")
    assert '#define OTIS_RECORD_PGT "PGT"' in protocol
    assert "otis_emit_pseudo_pps_truth" in emit
    assert "OTIS_RECORD_REF" not in emit[
        emit.index("void otis_emit_pseudo_pps_truth") : emit.index(
            "void otis_emit_pps_snapshot"
        )
    ]
