from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_core1_capture_drain_has_one_ring_budget() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    body = sketch[
        sketch.index("void drain_reference_snapshots(void)") :
        sketch.index("void emit_build_provenance_status(")
    ]
    assert "uint32_t budget = 128u;" in body
    assert "while (budget-- > 0u && otis_pps_snapshot_backend_pop(&snapshot))" in body
