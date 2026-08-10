from __future__ import annotations

from pathlib import Path
import csv

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    ASSOCIATION_LOSS_DECISION_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)


def _row(*, classification: str = "timeout_no_snapshot", backlog: str = "0") -> dict[str, str]:
    return {
        "record_type": "ASL",
        "schema_version": "1",
        "decision_sequence": "0",
        "reason": "snapshot_association_timeout",
        "classification": classification,
        "decision_ticks": "1000",
        "pending_reference_sequence": "1750",
        "pending_reference_ticks": "900",
        "pending_age_ticks": "100",
        "boundary_depth": "0",
        "boundary_dropped_count": "0",
        "next_reference_present": "false",
        "next_reference_sequence": "0",
        "next_reference_ticks": "0",
        "snapshot_initialized": "true",
        "snapshot_running": "true",
        "snapshot_fault_latched": "false",
        "snapshot_fault_flags": "0",
        "snapshot_session": "1",
        "snapshot_producer_ordinal": "1750",
        "snapshot_consumer_ordinal": "1750",
        "snapshot_backlog_depth": backlog,
        "snapshot_backlog_high_water": "1",
        "snapshot_overwrite_count": "0",
        "snapshot_continuity_loss_count": "0",
        "snapshot_pio_rxstall_count": "0",
        "snapshot_dma_error_count": "0",
        "snapshot_dma_stopped_count": "0",
        "core1_loop_sequence": "1234",
        "core1_last_snapshot_session": "1",
        "core1_last_snapshot_sequence": "1749",
        "core1_phase": "BoundaryDrain",
        "core1_phase_enter_ticks": "990",
        "core1_last_progress_ticks": "999",
    }


def _write(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ASSOCIATION_LOSS_DECISION_V1_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def test_association_loss_decision_is_split_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "association.csv"
    row = _row()
    line = ",".join(row[field] for field in ASSOCIATION_LOSS_DECISION_V1_FIELDS)
    with CsvRecordSplitter({"association_loss_decisions_v1": path}) as splitter:
        assert splitter.process_line(line) == "association_loss_decisions_v1"

    result = validate_csv(
        path,
        CsvValidationContext(
            contract="association_loss_decisions_v1",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert result.ok, result.errors
    assert result.row_count == 1


def test_association_loss_decision_rejects_contradictory_snapshot_classification(
    tmp_path: Path,
) -> None:
    path = tmp_path / "association.csv"
    _write(path, _row(backlog="1"))
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="association_loss_decisions_v1",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert not result.ok
    assert any("no-snapshot classification requires zero backlog" in error for error in result.errors)
