from __future__ import annotations

from pathlib import Path
import re


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def _function_body(source: str, signature: str, next_signature: str) -> str:
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def test_boot_diagnostics_are_captured_before_breadcrumb_registers_change() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    body = _function_body(
        source,
        "void boot_phase_reset_entry(void)",
        "void boot_phase_early_init(void)",
    )

    assert body.index("captureRp2040BootDiag();") < body.index(
        "otisBootBreadcrumbBegin"
    )


def test_protocol_banner_waits_for_serial_and_remains_one_shot() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    body = _function_body(
        source,
        "void emit_protocol_banner_if_serial_ready(void)",
        "void emit_periodic_status(void)",
    )

    assert "runtime_state.boot.protocol_banner_emitted" in body
    assert "!otis_transport_ready()" in body
    assert body.index('otis_transport_write_cstr("\\r\\n")') < body.index(
        "emit_boot_records_if_serial_ready()"
    )
    assert body.index("emitRp2040BootDiag(Serial)") < body.index(
        "otis_emit_csv_headers()"
    )
    assert body.index("otis_emit_csv_headers()") < body.index(
        "runtime_state.boot.protocol_banner_emitted = true"
    )
    loop_body = source[source.index("void loop()") :]
    assert loop_body.index("emit_protocol_banner_if_serial_ready()") < (
        loop_body.index("service_serial_commands()")
    )


def test_pio_edge_capture_claims_an_unused_state_machine() -> None:
    source = (FIRMWARE / "otis_capture_pio.cpp").read_text(encoding="utf-8")

    assert "pio_claim_unused_sm(pio_capture, false)" in source
    assert "constexpr uint pio_capture_sm" not in source


def test_phase5_ide_configuration_and_dormant_run_020_profile_are_exact() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")

    expected = {
        "OTIS_SW1_BRINGUP_MODE": "OTIS_SW1_MODE_H1_OCXO_OBSERVE",
        "OTIS_CAPTURE_BACKEND": "OTIS_CAPTURE_BACKEND_IRQ",
        "OTIS_TCXO_COUNTER_BACKEND":
            "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO",
        "OTIS_ENABLE_PPS_DUAL_OBSERVER": "1",
        "OTIS_H1_LONG_GATE_PERIOD_US": "300000000u",
        "OTIS_FC0_STARTUP_INHIBIT_MS": "600000u",
        "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS": "3u",
        "OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW": "0",
        "OTIS_ENABLE_DAC_AD5693R": "0",
        "OTIS_DAC_AD5693R_I2C_ADDRESS": "0x4Cu",
        "OTIS_DAC_MIN_CODE": "0x6000u",
        "OTIS_DAC_MAX_CODE": "0xFC00u",
        "OTIS_ENABLE_ENV_SENSORS": "0",
        "OTIS_ENABLE_H1_DAC_SWEEP": "0",
        "OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS": "2400000u",
        "OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS": "2400000u",
        "OTIS_H1_DAC_SWEEP_TINY_STEP_CODES": "0x0300u",
    }
    for name, value in expected.items():
        assert re.search(
            rf"^#define {re.escape(name)} {re.escape(value)}$",
            config,
            flags=re.MULTILINE,
        )
    assert "#define OTIS_FIRMWARE_CONFIG_ID OTIS_BUILD_PROFILE_ID" in config
    assert '#define OTIS_FIRMWARE_GIT_COMMIT OTIS_BUILD_GIT_COMMIT' in config
    assert not re.search(
        r'^#define OTIS_BUILD_GIT_COMMIT "[0-9a-f]{40}"$',
        config,
        re.MULTILINE,
    )

    # The disabled Run 020 profile remains available for an explicit future
    # characterization build and must retain its reviewed bounds.
    minimum = 0x6000
    maximum = 0xFC00
    center = (minimum + maximum) // 2
    step = 0x0300
    assert center == 0xAE00
    assert [
        center,
        center + step,
        center,
        center - step,
        center,
        center + 2 * step,
        center,
        center - 2 * step,
        center,
    ] == [
        0xAE00,
        0xB100,
        0xAE00,
        0xAB00,
        0xAE00,
        0xB400,
        0xAE00,
        0xA800,
        0xAE00,
    ]


def test_run_020_configuration_and_profile_plan_are_queryable_before_start() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    parser = (FIRMWARE / "otis_serial_command.cpp").read_text(encoding="utf-8")

    assert 'strcmp(command, "CONFIG?") == 0' in parser
    assert "OtisSerialCommandKind::ConfigQuery" in source
    assert '"config_id"' in source
    assert '"default_dwell_ms"' in source
    assert '"tiny_step_codes"' in source
    assert '"center_code"' in source
    assert '"profile_step"' in source
