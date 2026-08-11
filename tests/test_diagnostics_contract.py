from __future__ import annotations

from pathlib import Path

from host.otis_tools.contracts import CsvValidationContext, validate_csv


HEADER = (
    "record_type,schema_version,diagnostic_seq,diagnostic_id,episode_id,"
    "subsystem,severity,state,transition,diagnostic_confidence,reason_code,"
    "clear_reason_code,first_seen_ticks,last_seen_ticks,time_domain,"
    "occurrence_count,persistence_state,first_evidence_refs,latest_evidence_refs,"
    "algorithm_version,config_hash,observation_effect,reference_effect,"
    "model_effect,control_effect"
)


def _context() -> CsvValidationContext:
    return CsvValidationContext(
        contract="diagnostics_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )


def _write(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")


def test_diagnostics_contract_accepts_unknown_confidence_without_zeroing(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(
        path,
        [
            "DIAG,1,1,diag.plant.unknown_gain,episode-1,actuator,WARN,active,"
            "raised,unknown,plant_model_unknown_gain,,100,100,rp2040_timer0,1,"
            "confirmed,profiles/plant_models:missing,profiles/plant_models:missing,"
            f"plant_diag_v1,{'a' * 64},none,none,mark_unavailable,inhibit",
        ],
    )

    result = validate_csv(path, _context())

    assert result.ok


def test_diagnostics_contract_rejects_collapsed_or_unstable_finding(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(
        path,
        [
            "DIAG,1,1,diag.bad,episode-1,reference,WARN,active,raised,1.200,,"
            ",100,90,rp2040_timer0,1,confirmed,,,diag_v1,"
            f"{'b' * 64},invalidate,invalidate,unknown,inhibit",
        ],
    )

    result = validate_csv(path, _context())

    assert "row 1: diagnostic_confidence must be between 0.0 and 1.0 or 'unknown'" in result.errors
    assert "row 1: last_seen_ticks must be greater than or equal to first_seen_ticks" in result.errors
    assert "row 1: reason_code must not be empty" in result.errors
    assert "row 1: first_evidence_refs must not be empty" in result.errors
    assert "row 1: latest_evidence_refs must not be empty" in result.errors


def test_diagnostics_contract_rejects_service_plane_as_timing_truth(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(
        path,
        [
            "DIAG,1,1,diag.service.drop,episode-1,service_plane,DEGRADED,active,"
            "raised,0.800,service_plane_telemetry_drop,,100,100,rp2040_timer0,1,"
            "confirmed,health.csv:STS:drop_count,health.csv:STS:drop_count,"
            f"service_diag_v1,{'c' * 64},reduce_trust,invalidate,none,inhibit",
        ],
    )

    result = validate_csv(path, _context())

    assert "row 1: service-plane diagnostics must not redefine reference truth" in result.errors


def test_retired_draft_contract_is_not_accepted(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics.csv"
    _write(path, [])

    context = CsvValidationContext(
        contract="diagnostics_draft_v0",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    result = validate_csv(path, context)

    assert result.ok is False
    assert "unsupported contract 'diagnostics_draft_v0'" in result.errors
