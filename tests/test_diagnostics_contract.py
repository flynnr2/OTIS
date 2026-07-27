from __future__ import annotations

from pathlib import Path

from host.otis_tools.contracts import CsvValidationContext, validate_csv


HEADER = (
    "record_type,schema_version,diagnostic_seq,diagnostic_id,subsystem,severity,"
    "state,transition,diagnostic_confidence,reason_code,first_seen_ticks,last_seen_ticks,"
    "time_domain,evidence_refs,algorithm_version,config_version,control_effect,control_eligibility"
)


def _context() -> CsvValidationContext:
    return CsvValidationContext(
        contract="diagnostics_draft_v0",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )


def _write(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")


def test_diagnostics_contract_accepts_reference_and_actuator_fixtures() -> None:
    for path in (
        Path("tests/fixtures/diagnostics/pps_reference_anomaly_diagnostics_v0.csv"),
        Path("tests/fixtures/diagnostics/actuator_diagnostics_v0.csv"),
    ):
        result = validate_csv(path, _context())

        assert result.ok
        assert result.row_count >= 2


def test_diagnostics_contract_accepts_unknown_confidence_without_zeroing(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(
        path,
        [
            "DIAG,0,1,diag.plant.unknown_gain,actuator,WARN,active,raised,unknown,"
            "plant_model_unknown_gain,100,100,rp2040_timer0,profiles/plant_models:missing,"
            "plant_diag_v0,fixture:unknown_gain,inhibit_actuation,not_eligible",
        ],
    )

    result = validate_csv(path, _context())

    assert result.ok


def test_diagnostics_contract_rejects_collapsed_or_unstable_finding(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(
        path,
        [
            "DIAG,0,1,diag.bad,reference,WARN,active,raised,1.200,,"
            "100,90,rp2040_timer0,,diag_v0,fixture,inhibit_actuation,not_eligible",
        ],
    )

    result = validate_csv(path, _context())

    assert "row 1: diagnostic_confidence must be between 0.0 and 1.0 or 'unknown'" in result.errors
    assert "row 1: last_seen_ticks must be greater than or equal to first_seen_ticks" in result.errors
    assert "row 1: reason_code must not be empty" in result.errors
    assert "row 1: evidence_refs must not be empty" in result.errors


def test_diagnostics_contract_rejects_service_plane_as_timing_truth(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(
        path,
        [
            "DIAG,0,1,diag.service.drop,service_plane,DEGRADED,active,raised,0.800,"
            "service_plane_telemetry_drop,100,100,rp2040_timer0,health.csv:STS:drop_count,"
            "service_diag_v0,fixture,enter_holdover,not_eligible",
        ],
    )

    result = validate_csv(path, _context())

    assert "row 1: service-plane telemetry diagnostics must not directly enter holdover or fail static" in result.errors
