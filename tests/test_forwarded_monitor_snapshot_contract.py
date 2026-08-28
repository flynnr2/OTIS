from __future__ import annotations

from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CsvValidationContext, validate_csv


CONTRACT = "forwarded_monitor_snapshots_v1"
HEADER = (
    "record_type,schema_version,session,reference_session,snapshot_sequence,"
    "cumulative_down_counter,reference_sequence,reference_timestamp_ticks,"
    "status,backend,channel_id"
)
ROW = "MNS,1,7,3,0,4294967295,11,16000000,0,pio_wait_cumulative_snapshot_cpu_v1,3"


def _validate(path: Path, *, known_channels: frozenset[int] = frozenset({3})):
    return validate_csv(
        path,
        CsvValidationContext(
            contract=CONTRACT,
            known_channels=known_channels,
            known_domains=frozenset({"rp2040_timer0"}),
        ),
    )


def test_forwarded_monitor_snapshot_accepts_d6_channel_and_session_reset(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forwarded_monitor_snapshots.csv"
    path.write_text(
        "\n".join(
            [
                HEADER,
                ROW,
                "MNS,1,8,4,0,0,12,32000000,0,pio_wait_cumulative_snapshot_cpu_v1,3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _validate(path)

    assert result.ok, result.errors


def test_forwarded_monitor_snapshot_rejects_non_d6_channel_and_unidentified_backend(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forwarded_monitor_snapshots.csv"
    path.write_text(
        HEADER + "\nMNS,1,7,3,0,1,11,16000000,0,,2\n",
        encoding="utf-8",
    )

    result = _validate(path, known_channels=frozenset({2, 3}))

    assert any("backend must be pio_wait_cumulative_snapshot_cpu_v1" in error for error in result.errors)
    assert any("channel_id must be 3 (D6)" in error for error in result.errors)


def test_splitter_routes_monitor_records_separately_from_authoritative_snapshots(
    tmp_path: Path,
) -> None:
    monitor = tmp_path / "forwarded_monitor_snapshots.csv"
    snapshots = tmp_path / "pps_snapshots.csv"
    with CsvRecordSplitter(
        {
            CONTRACT: monitor,
            "pps_snapshots_v1": snapshots,
        }
    ) as splitter:
        assert splitter.process_line(ROW) == CONTRACT
        assert splitter.process_line(
            "SNP,1,1,0,4294967295,7,16000000,0,"
            "pio_wait_cumulative_snapshot_dma_v1"
        ) == "pps_snapshots_v1"

    assert ROW in monitor.read_text(encoding="utf-8")
    assert ROW not in snapshots.read_text(encoding="utf-8")
