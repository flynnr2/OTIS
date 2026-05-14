from __future__ import annotations

from pathlib import Path

from tools.otis_wire_validate import validate_text


GOLDEN = Path("firmware/arduino/validation/golden")


def _validate_fixture(name: str, profile: str):
    path = GOLDEN / name
    return validate_text(
        source=str(path),
        text=path.read_text(encoding="utf-8"),
        profile=profile,
        require_headers=True,
        max_boot_records=1,
    )


def _errors(report) -> list[str]:
    return [finding.message for finding in report.findings if finding.severity == "error"]


def test_wire_validator_accepts_golden_snippets() -> None:
    cases = [
        ("synthetic_sw1_excerpt.txt", "synthetic"),
        ("gpio_loopback_sw1_excerpt.txt", "gpio_loopback"),
        ("gpin0_observe_sw1_excerpt.txt", "gpin0_observe"),
    ]

    for filename, profile in cases:
        report = _validate_fixture(filename, profile)
        assert _errors(report) == []


def test_wire_validator_rejects_field_order_change() -> None:
    path = GOLDEN / "synthetic_sw1_excerpt.txt"
    text = path.read_text(encoding="utf-8").replace(
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
        "record_type,schema_version,channel_id,event_seq,edge,timestamp_ticks,capture_domain,flags",
    )

    report = validate_text(
        source=str(path),
        text=text,
        profile="synthetic",
        require_headers=True,
        max_boot_records=1,
    )

    assert "raw_events header/schema record is missing" in _errors(report)


def test_wire_validator_rejects_unparseable_numeric_field() -> None:
    path = GOLDEN / "synthetic_sw1_excerpt.txt"
    text = path.read_text(encoding="utf-8").replace(
        "EVT,1,1000,0,R,1600001234,rp2040_timer0,0",
        "EVT,1,not-a-number,0,R,1600001234,rp2040_timer0,0",
    )

    report = validate_text(
        source=str(path),
        text=text,
        profile="synthetic",
        require_headers=True,
        max_boot_records=1,
    )

    assert "EVT.event_seq is not parseable as an integer: 'not-a-number'" in _errors(report)


def test_wire_validator_rejects_counter_regression() -> None:
    path = GOLDEN / "gpio_loopback_sw1_excerpt.txt"
    text = path.read_text(encoding="utf-8").replace(
        "EVT,1,1002,0,R,100048048,rp2040_timer0,16",
        "EVT,1,999,0,R,100048048,rp2040_timer0,16",
    )

    report = validate_text(
        source=str(path),
        text=text,
        profile="gpio_loopback",
        require_headers=True,
        max_boot_records=1,
    )

    assert any("event_seq decreases" in message for message in _errors(report))


def test_wire_validator_checks_pio_overflow_fields_when_applicable() -> None:
    path = GOLDEN / "gpio_loopback_sw1_excerpt.txt"
    text = path.read_text(encoding="utf-8").replace(
        "STS,1,7,24106000,rp2040_timer0,capture,mode,irq_reconstructed,INFO,32768",
        "STS,1,7,24106000,rp2040_timer0,capture,mode,pio_fifo_cpu_timestamped,INFO,32768",
    )

    report = validate_text(
        source=str(path),
        text=text,
        profile="gpio_loopback",
        require_headers=True,
        max_boot_records=1,
    )

    assert "PIO capture status field capture,pio_fifo_overflow_drop_count is missing" in _errors(report)


def test_wire_validator_reports_older_committed_capture_metadata_gaps() -> None:
    path = Path("runs/h0_sw1/synthetic_usb/run_001/serial_raw.log")
    report = validate_text(
        source=str(path),
        text=path.read_text(encoding="utf-8"),
        profile="synthetic",
        require_headers=False,
        max_boot_records=1,
    )

    assert "required STS firmware,version is missing" in _errors(report)
    assert "required STS protocol,schema_version is missing" in _errors(report)
