from __future__ import annotations

from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CsvValidationContext, validate_csv


HEADER = (
    "record_type,schema_version,session,snapshot_sequence,"
    "cumulative_down_counter,reference_sequence,reference_timestamp_ticks,"
    "status,backend"
)


def _validate(path: Path):
    return validate_csv(
        path,
        CsvValidationContext(
            contract="pps_snapshots_v1",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )


def test_snapshot_contract_accepts_session_reset_and_u32_values(tmp_path: Path) -> None:
    path = tmp_path / "pps_snapshots.csv"
    path.write_text(
        "\n".join(
            [
                HEADER,
                "SNP,1,7,4294967295,0,4294967295,16,0,pio_wait_cumulative_snapshot_dma_v1",
                "SNP,1,8,0,4294967295,0,32,0,pio_wait_cumulative_snapshot_dma_v1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _validate(path)
    assert result.ok, result.errors


def test_snapshot_contract_rejects_out_of_range_or_unidentified_rows(tmp_path: Path) -> None:
    path = tmp_path / "pps_snapshots.csv"
    path.write_text(
        HEADER + "\nSNP,1,1,0,4294967296,1,16000000,0,\n",
        encoding="utf-8",
    )

    result = _validate(path)
    assert any("cumulative_down_counter must fit" in error for error in result.errors)
    assert any("backend must not be empty" in error for error in result.errors)


def test_splitter_routes_snapshot_as_a_separate_evidence_plane(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots.csv"
    counts = tmp_path / "counts.csv"
    with CsvRecordSplitter(
        {
            "pps_snapshots_v1": snapshots,
            "count_observations_v1": counts,
        }
    ) as splitter:
        assert splitter.process_line(
            "SNP,1,1,0,4294967295,7,16000000,0,pio_wait_cumulative_snapshot_dma_v1"
        ) == "pps_snapshots_v1"

    assert "SNP,1,1,0" in snapshots.read_text(encoding="utf-8")
    assert "SNP,1,1,0" not in counts.read_text(encoding="utf-8")
