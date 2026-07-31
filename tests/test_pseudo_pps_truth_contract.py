from __future__ import annotations

from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CsvValidationContext, validate_csv


HEADER = (
    "record_type,schema_version,truth_seq,generator_session,profile_id,"
    "profile_version,generator_sequence,event,intended_class,"
    "scheduled_offset_us,scheduled_interval_us,pulse_width_us,flags"
)


def test_truth_contract_accepts_schedule_omission_and_markers(tmp_path: Path) -> None:
    path = tmp_path / "pseudo_pps_truth.csv"
    path.write_text(
        "\n".join(
            [
                HEADER,
                "PGT,1,1,7,COMPOSITE,1,0,start,marker,0,0,0,0",
                "PGT,1,2,7,COMPOSITE,1,1,schedule,clean,1000000,1000000,100000,0",
                "PGT,1,3,7,COMPOSITE,1,2,schedule,omission,2000000,1000000,0,0",
                "PGT,1,4,7,COMPOSITE,1,0,completion,marker,0,0,0,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="pseudo_pps_truth_v1",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert result.ok, result.errors


def test_truth_contract_rejects_marker_with_schedule_values(tmp_path: Path) -> None:
    path = tmp_path / "pseudo_pps_truth.csv"
    path.write_text(
        HEADER
        + "\nPGT,1,1,1,CLEAN_NOMINAL,1,1,start,marker,100,100,10,0\n",
        encoding="utf-8",
    )
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="pseudo_pps_truth_v1",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert any("marker generator_sequence must be zero" in error for error in result.errors)


def test_splitter_routes_pgt_without_treating_it_as_ref(tmp_path: Path) -> None:
    truth = tmp_path / "truth.csv"
    raw = tmp_path / "raw.csv"
    with CsvRecordSplitter(
        {
            "pseudo_pps_truth_v1": truth,
            "raw_events_v1": raw,
        }
    ) as splitter:
        assert (
            splitter.process_line(
                "PGT,1,1,1,CLEAN_NOMINAL,1,0,start,marker,0,0,0,0"
            )
            == "pseudo_pps_truth_v1"
        )
    assert "PGT,1,1" in truth.read_text(encoding="utf-8")
    assert "PGT,1,1" not in raw.read_text(encoding="utf-8")
