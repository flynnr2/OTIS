from __future__ import annotations

from pathlib import Path


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def test_dac_presence_probe_does_not_claim_an_applied_code() -> None:
    driver = (FIRMWARE / "otis_dac_ad5693r.cpp").read_text(encoding="utf-8")
    begin_start = driver.index("bool otis_dac_ad5693r_begin(void)")
    begin_end = driver.index("bool otis_dac_ad5693r_reset(void)", begin_start)
    begin = driver[begin_start:begin_end]

    assert "dac_initialized = (result == 0u);" in begin
    assert "dac_last_write_ok = false;" in begin
    assert "dac_applied_code_known = false;" in begin
    assert "dac_last_write_ok = dac_initialized;" not in begin


def test_only_successful_explicit_code_write_establishes_applied_code() -> None:
    driver = (FIRMWARE / "otis_dac_ad5693r.cpp").read_text(encoding="utf-8")
    set_start = driver.index("bool otis_dac_ad5693r_set_raw(uint16_t code)")
    set_end = driver.index("bool otis_dac_ad5693r_is_enabled(void)", set_start)
    setter = driver[set_start:set_end]

    assignment = setter.index("dac_last_applied_code = clamped_code;")
    validity = setter.index("dac_applied_code_known = true;")
    assert assignment < validity
    assert setter[:assignment].rfind("if (dac_last_write_ok)") >= 0


def test_preview_and_status_fail_unavailable_before_explicit_write() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert sketch.count("applied_code_known &&") == 5
    assert "OtisCx317StaticCodeState cx317_static_code_state" in sketch
    assert 'emit_status(component, "applied_code_known"' in sketch
    assert 'emit_status(component, "last_applied_code", "unavailable"' in sketch


def test_manual_write_emits_structured_requested_applied_acknowledgement() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = sketch.index("void handle_dac_set(uint16_t requested_code)")
    end = sketch.index("#if OTIS_ENABLE_H1_DAC_SWEEP", start)
    handler = sketch[start:end]

    assert "otis_emit_dac_step(" in handler
    assert "requested_code," in handler
    assert "clamped, false" in handler
    assert 'ok ? "manual_apply" : "manual_write_failed"' in handler
    assert "OTIS_FLAG_SOURCE_HEALTH_SUSPECT" in handler
