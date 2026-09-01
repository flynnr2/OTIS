from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.contracts import CsvValidationContext, validate_csv
from host.otis_tools.time_domains import (
    RP2040_TIMER0_MICROS_WRAP_TICKS,
    canonical_domain_declaration,
    forward_progress,
    time_domain,
    unwrap_domain_ticks,
    validate_domain_declarations,
)


def test_rp2040_progression_no_wrap_boundary_wrap_and_multiple_records() -> None:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    ordinary = forward_progress(10, 20, domain="rp2040_timer0")
    boundary = forward_progress(modulus - 1, 0, domain="rp2040_timer0")
    values, wraps = unwrap_domain_ticks(
        [modulus - 2, modulus - 1, 0, 1], domain="rp2040_timer0"
    )

    assert (ordinary.valid, ordinary.distance_ticks, ordinary.rollover_count) == (
        True,
        10,
        0,
    )
    assert (boundary.valid, boundary.distance_ticks, boundary.rollover_count) == (
        True,
        1,
        1,
    )
    assert values == [modulus - 2, modulus - 1, modulus, modulus + 1]
    assert wraps == 1


def test_backward_ambiguous_duplicate_and_unknown_domain_fail_closed() -> None:
    backward = forward_progress(1000, 900, domain="rp2040_timer0")
    ambiguous = forward_progress(
        0,
        RP2040_TIMER0_MICROS_WRAP_TICKS // 2,
        domain="rp2040_timer0",
    )
    duplicate = forward_progress(
        10, 10, domain="rp2040_timer0", allow_equal=False
    )
    strict = forward_progress(1000, 900, domain="h1_cx317_ocxo_10mhz")

    assert (backward.valid, backward.reason) == (
        False,
        "illegal_or_ambiguous_wrap",
    )
    assert (ambiguous.valid, ambiguous.reason) == (
        False,
        "excessive_ambiguous_gap",
    )
    assert (duplicate.valid, duplicate.reason) == (False, "duplicate_timestamp")
    assert (strict.valid, strict.reason) == (False, "illegal_backward_movement")
    with pytest.raises(ValueError, match="unsupported timestamp domain"):
        forward_progress(1, 2, domain="invented")


def test_extended_timer0_is_strict_nonwrapping_and_accepts_long_progress() -> None:
    long_progress = forward_progress(
        3_902 * 16_000_000,
        6_302 * 16_000_000,
        domain="rp2040_timer0_extended",
    )
    backward = forward_progress(
        6_302 * 16_000_000,
        3_902 * 16_000_000,
        domain="rp2040_timer0_extended",
    )

    assert long_progress.valid is True
    assert long_progress.distance_ticks == 2_400 * 16_000_000
    assert (backward.valid, backward.reason) == (
        False,
        "illegal_backward_movement",
    )


def test_manifest_domain_declarations_reject_absent_unknown_and_contradictory() -> None:
    assert validate_domain_declarations(None)
    assert validate_domain_declarations(
        [{"name": "invented", "nominal_hz": 1}]
    )
    errors = validate_domain_declarations(
        [
            {
                "name": "rp2040_timer0",
                "nominal_hz": 1,
                "rollover": "strict_nonwrapping",
            }
        ]
    )
    assert any("nominal_hz" in error for error in errors)
    assert any("rollover" in error for error in errors)
    assert not validate_domain_declarations(
        [{"name": "rp2040_timer0", "nominal_hz": 16_000_000}]
    )
    assert not validate_domain_declarations(
        [
            {
                "name": "rp2040_timer0_extended",
                "nominal_hz": 16_000_000,
            }
        ]
    )


def test_timer0_domains_declare_encoded_scale_and_actual_quantum() -> None:
    raw = time_domain("rp2040_timer0")
    extended = time_domain("rp2040_timer0_extended")

    for domain in (raw, extended):
        assert domain.nominal_hz == 16_000_000
        assert domain.source_counter_hz == 1_000_000
        assert domain.encoding_scale == 16
        assert domain.quantum_ticks == 16
        assert domain.quantum_ns == 1_000
        assert domain.coordinate_semantics == "projected_local_non_metrological"
    assert raw.provenance == (
        "rp2040_timerawl_or_arduino_micros_1mhz_encoded_x16"
    )
    assert extended.provenance == (
        "session_bound_wrap_reconstruction_of_rp2040_timer0"
    )


def test_current_timer0_declaration_is_complete_but_legacy_minimal_remains_valid(
) -> None:
    current = canonical_domain_declaration("rp2040_timer0")

    assert not validate_domain_declarations([current], require_complete=True)
    assert not validate_domain_declarations(
        [{"name": "rp2040_timer0", "nominal_hz": 16_000_000}]
    )
    missing = dict(current)
    del missing["quantum_ns"]
    assert any(
        "lacks canonical quantum_ns" in error
        for error in validate_domain_declarations([missing], require_complete=True)
    )


@pytest.mark.parametrize(
    ("field", "contradiction"),
    [
        ("source_counter_hz", 16_000_000),
        ("encoding_scale", 1),
        ("quantum_ticks", 1),
        ("quantum_ns", 62.5),
        ("coordinate_semantics", "metrological_capture"),
        ("provenance", "native_16mhz_counter"),
    ],
)
def test_timer0_declaration_rejects_contradictory_quantum_or_provenance(
    field: str,
    contradiction: object,
) -> None:
    declaration = canonical_domain_declaration("rp2040_timer0")
    declaration[field] = contradiction

    errors = validate_domain_declarations([declaration])
    assert any(
        field in error and "contradicts canonical" in error for error in errors
    )


def test_csv_validator_derives_wrap_from_row_domain_and_rejects_reorder(
    tmp_path: Path,
) -> None:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    path = tmp_path / "raw_events.csv"
    header = (
        "record_type,schema_version,event_seq,channel_id,edge,"
        "timestamp_ticks,capture_domain,flags\n"
    )
    path.write_text(
        header
        + f"REF,1,1,1,R,{modulus - 10},rp2040_timer0,0\n"
        + "REF,1,2,1,R,5,rp2040_timer0,0\n",
        encoding="utf-8",
    )
    context = CsvValidationContext(
        contract="raw_events_v1",
        known_channels=frozenset({1}),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(path, context).ok

    path.write_text(
        header
        + "REF,1,1,1,R,1000,rp2040_timer0,0\n"
        + "REF,1,2,1,R,900,rp2040_timer0,0\n",
        encoding="utf-8",
    )
    result = validate_csv(path, context)
    assert not result.ok
    assert any("illegal_or_ambiguous_wrap" in error for error in result.errors)


def test_session_transition_near_wrap_does_not_bridge_domains(tmp_path: Path) -> None:
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    path = tmp_path / "pps_snapshots.csv"
    path.write_text(
        "record_type,schema_version,session,snapshot_sequence,"
        "cumulative_down_counter,reference_sequence,"
        "reference_timestamp_ticks,status,backend\n"
        f"SNP,1,1,1,1000,1,{modulus - 10},0,pio_wait_cumulative_snapshot_dma_v1\n"
        "SNP,1,2,0,900,0,5,0,pio_wait_cumulative_snapshot_dma_v1\n",
        encoding="utf-8",
    )
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="pps_snapshots_v1",
            known_channels=frozenset(),
            known_domains=frozenset({"rp2040_timer0"}),
        ),
    )
    assert result.ok


def test_run_confirmed_segment_reset_restarts_domain_progression(
    tmp_path: Path,
) -> None:
    path = tmp_path / "health.csv"
    path.write_text(
        "record_type,schema_version,status_seq,timestamp_ticks,status_domain,"
        "component,status_key,status_value,severity,flags\n"
        "STS,1,26,1632000026,rp2040_timer0,firmware,a,b,INFO,0\n"
        "STS,1,10,1632000010,rp2040_timer0,firmware,a,c,INFO,0\n",
        encoding="utf-8",
    )
    result = validate_csv(
        path,
        CsvValidationContext(
            "health_v1",
            frozenset(),
            frozenset({"rp2040_timer0"}),
            segmented_capture=True,
        ),
    )
    assert any("status_seq must be strictly increasing" in error for error in result.errors)
    assert not any("progression" in error for error in result.errors)
