from __future__ import annotations

from pathlib import Path


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
    assert "otis_transport_row_free_slots()==0" in body
    assert "emitOtisBootSummary(diagnostic_rows" in body
    assert body.index("emitRp2040BootDiag(diagnostic_rows)") < body.index(
        "runtime_state.boot.protocol_banner_emitted=true"
    )
    assert "Serial" not in body
    loop_body = source[source.index("void loop()") :]
    assert loop_body.index("emit_protocol_banner_if_serial_ready()") < (
        loop_body.index("service_serial_commands()")
    )
