from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_live_memory_budget_is_observed_on_each_execution_core() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    source = (FIRMWARE / "otis_memory_budget.cpp").read_text(encoding="utf-8")
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")

    assert sketch.count("otis_memory_budget_note_current_core();") == 4
    assert "otis_memory_budget_emit_status(&status_emit_context);" in sketch
    assert "rp2040.getFreeStack()" in source
    assert "rp2040.getFreeHeap()" in source
    assert '"live_observed_minimum_approximation"' in source
    assert "OTIS_MINIMUM_FREE_STACK_BYTES 1024u" in config
    assert "OTIS_MINIMUM_FREE_HEAP_BYTES 65536u" in config
