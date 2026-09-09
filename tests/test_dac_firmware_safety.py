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
