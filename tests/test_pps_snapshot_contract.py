from __future__ import annotations

from pathlib import Path

from host.otis_tools.record_splitter import CsvRecordSplitter
from host.otis_tools.contracts import CsvValidationContext, validate_csv


HEADER = (
    "record_type,schema_version,session,snapshot_sequence,"
    "cumulative_down_counter,reference_sequence,reference_timestamp_ticks,"
    "timestamp_uncertainty_ticks,status,backend"
)
BACKEND = "pio_wait_cumulative_snapshot_fifo_irq_v2"


def _validate(path: Path):
    return validate_csv(
        path,
        CsvValidationContext(
            contract="pps_snapshots_v2",
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
                f"SNP,2,7,4294967295,0,4294967295,16,1,0,{BACKEND}",
                f"SNP,2,8,0,4294967295,0,32,1,0,{BACKEND}",
                f"SNP,2,8,1,4294967294,1,33,4294967295,2,{BACKEND}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _validate(path)
    assert result.ok, result.errors


def test_snapshot_contract_rejects_identity_backend_status_and_uncertainty_disagreement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pps_snapshots.csv"
    path.write_text(
        "\n".join([
            HEADER,
            "SNP,2,1,0,4294967296,1,16000000,1,0,wrong",
            f"SNP,2,1,1,1,2,16000001,4294967295,0,{BACKEND}",
            f"SNP,2,1,2,0,2,16000002,1,32,{BACKEND}",
        ]) + "\n",
        encoding="utf-8",
    )

    result = _validate(path)
    assert any("cumulative_down_counter must fit" in error for error in result.errors)
    assert any("backend must be" in error for error in result.errors)
    assert any("reference_sequence must equal" in error for error in result.errors)
    assert any("UINT32_MAX uncertainty" in error for error in result.errors)
    assert any("unknown SNP v2 bits" in error for error in result.errors)


def test_splitter_routes_snapshot_as_a_separate_evidence_plane(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots.csv"
    counts = tmp_path / "counts.csv"
    with CsvRecordSplitter(
        {
            "pps_snapshots_v2": snapshots,
            "count_observations_v1": counts,
        }
    ) as splitter:
        assert splitter.process_line(
            f"SNP,2,1,0,4294967295,0,16000000,1,0,{BACKEND}"
        ) == "pps_snapshots_v2"

    assert "SNP,2,1,0" in snapshots.read_text(encoding="utf-8")
    assert "SNP,2,1,0" not in counts.read_text(encoding="utf-8")
