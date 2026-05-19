from __future__ import annotations

from pathlib import Path

from host.otis_tools.contracts import CsvValidationContext, validate_csv


HEADER = (
    "record_type,schema_version,env_seq,timestamp_ticks,observation_domain,"
    "source,role,temperature_c,relative_humidity_pct,pressure_pa,flags"
)


def _context() -> CsvValidationContext:
    return CsvValidationContext(
        contract="environment_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )


def _write(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")


def test_environment_contract_accepts_sht4x_and_bmp280_rows(tmp_path: Path) -> None:
    path = tmp_path / "environment.csv"
    _write(
        path,
        [
            "ENV,1,1,16000000,rp2040_timer0,sht4x,vcocxo_near,31.250,45.000,,0",
            "ENV,1,2,16001000,rp2040_timer0,bmp280,pressure_reference,31.500,,100812.250,0",
        ],
    )

    result = validate_csv(path, _context())

    assert result.ok
    assert result.row_count == 2


def test_environment_contract_rejects_non_monotonic_sequence(tmp_path: Path) -> None:
    path = tmp_path / "environment.csv"
    _write(
        path,
        [
            "ENV,1,2,16000000,rp2040_timer0,sht4x,vcocxo_near,31.250,45.000,,0",
            "ENV,1,2,16001000,rp2040_timer0,sht4x,vcocxo_near,31.300,45.100,,0",
        ],
    )

    result = validate_csv(path, _context())

    assert any("env_seq must be strictly increasing" in error for error in result.errors)


def test_environment_contract_rejects_empty_measurement(tmp_path: Path) -> None:
    path = tmp_path / "environment.csv"
    _write(path, ["ENV,1,1,16000000,rp2040_timer0,sht4x,vcocxo_near,,,,0"])

    result = validate_csv(path, _context())

    assert "row 1: at least one environmental measurement must be present" in result.errors


def test_environment_contract_rejects_bad_domain(tmp_path: Path) -> None:
    path = tmp_path / "environment.csv"
    _write(path, ["ENV,1,1,16000000,unknown_timer,sht4x,vcocxo_near,31.250,45.000,,0"])

    result = validate_csv(path, _context())

    assert "row 1: observation_domain 'unknown_timer' is not declared in manifest domains" in result.errors
