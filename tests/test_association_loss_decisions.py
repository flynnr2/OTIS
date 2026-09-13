from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.contracts import (
    ASSOCIATION_LOSS_DECISION_V2_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.record_splitter import CsvRecordSplitter


def _row(
    *, classification: str = "timeout_no_snapshot", backlog: str = "0"
) -> dict[str, str]:
    return {
        "record_type": "ASL",
        "schema_version": "2",
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
        "snapshot_frozen": "true",
        "frozen_session": "1",
        "frozen_producer_ordinal": "1750",
        "frozen_consumer_ordinal": "1750",
        "frozen_backlog_depth": "0",
        "frozen_pio_fifo_depth": "0",
        "unassociated_front_word_present": "false",
        "unassociated_front_word": "0",
    }


def _write(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ASSOCIATION_LOSS_DECISION_V2_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def test_association_loss_decision_is_split_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "association.csv"
    row = _row()
    line = ",".join(row[field] for field in ASSOCIATION_LOSS_DECISION_V2_FIELDS)
    with CsvRecordSplitter({"association_loss_decisions_v2": path}) as splitter:
        assert splitter.process_line(line) == "association_loss_decisions_v2"

    result = validate_csv(
        path,
        CsvValidationContext(
            contract="association_loss_decisions_v2",
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
            contract="association_loss_decisions_v2",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert not result.ok
    assert any(
        "no-snapshot classification requires zero backlog" in error
        for error in result.errors
    )


def test_frozen_front_has_explicit_presence_and_independent_frontier(
    tmp_path: Path,
) -> None:
    # The DMA may finish a word after the decision saw an empty queue. This
    # overlap is legal, and a counter value of zero is not missing evidence.
    row = _row()
    row.update(
        frozen_producer_ordinal="1751",
        frozen_backlog_depth="1",
        unassociated_front_word_present="true",
        unassociated_front_word="0",
    )
    path = tmp_path / "association.csv"
    _write(path, row)
    context = CsvValidationContext(
        contract="association_loss_decisions_v2",
        known_channels=frozenset(),
        known_domains=frozenset(),
    )
    assert validate_csv(path, context).ok
    for changes, reason in (
        ({"snapshot_producer_ordinal": "1752"}, "must not move backward"),
        ({"snapshot_fault_latched": "true"}, "faulted decision"),
        ({"snapshot_fault_flags": "4"}, "faulted decision"),
        ({"snapshot_frozen": "false"}, "unavailable freeze"),
        ({"frozen_session": "2"}, "capture session"),
        (
            {"frozen_consumer_ordinal": "1751", "frozen_backlog_depth": "0"},
            "must not consume",
        ),
        (
            {"frozen_producer_ordinal": "1879", "frozen_backlog_depth": "129"},
            "non-overwritten slot",
        ),
        (
            {
                "unassociated_front_word_present": "false",
                "unassociated_front_word": "12",
            },
            "zero placeholder",
        ),
        ({"frozen_pio_fifo_depth": "9"}, "RX capacity"),
    ):
        _write(path, row | changes)
        result = validate_csv(path, context)
        assert not result.ok
        assert any(reason in error for error in result.errors), result.errors


def test_actual_firmware_loss_formatter_reaches_host_without_creating_snapshots(
    tmp_path: Path,
) -> None:
    import re
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[1]
    firmware = root / "firmware/arduino/otis_nano_rp2040_connect"
    sketch = (firmware / "otis_nano_rp2040_connect.ino").read_text()
    start = sketch.index("void publish_dual_core_association_loss_decision(")
    formatter = sketch[start : sketch.index("void emit_captured_edge(", start)]
    capacity = re.search(
        r"OTIS_EVIDENCE_FRAME_CAPACITY = (\d+)u",
        (firmware / "otis_dual_core_contract.h").read_text(),
    ).group(1)
    cpp = tmp_path / "formatter.cpp"
    cpp.write_text(
        r"""
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include "otis_pps_snapshot_backend.h"
#include "otis_pps_count_boundary.h"
struct Progress {
  uint32_t loop_sequence, last_snapshot_session, last_snapshot_sequence;
  int phase;
  uint64_t phase_enter_ticks, last_progress_ticks;
};
struct OtisDualCoreQueueStats { Progress timing_progress; };
struct Frame { uint32_t sequence; uint16_t length; char data[CAPACITY]; };
Frame dual_core_association_loss_scratch;
uint32_t dual_core_association_loss_decision_sequence = 0;
void otis_dual_core_get_stats(OtisDualCoreQueueStats *out) {
  out->timing_progress = {UINT32_MAX, UINT32_MAX, UINT32_MAX, 0, UINT64_MAX, UINT64_MAX};
}
const char *otis_timing_progress_phase_name(int) { return "loop_idle"; }
enum class OtisPartitionFault { EvidenceExhausted };
void otis_dual_core_latch_fault(OtisPartitionFault) { assert(false); }
void otis_dual_core_publish_evidence(Frame *frame) {
  assert(frame->length == strlen(frame->data));
  fwrite(frame->data, 1, frame->length, stdout);
}
""".replace("CAPACITY", capacity)
        + formatter
        + r"""
int main() {
  OtisPpsCountBoundaryObservation pending = {}, next = {};
  pending.reference_sequence = 814; pending.pps_timestamp_ticks = 816152754;
  next.reference_sequence = 815; next.pps_timestamp_ticks = 816250369;
  OtisPpsSnapshotBackendStats stats = {};
  stats.initialized = stats.running = true;
  stats.session = 1; stats.producer_ordinal = 815; stats.consumer_ordinal = 814;
  stats.backlog_depth = stats.backlog_high_water = 1;
  OtisPpsSnapshotFrozenDiagnostic frozen = {true, 1, 815, 814, 1, 0, true, 0};
  publish_dual_core_association_loss_decision("ref_without_snapshot", 816250605,
      pending, 97824, 1, 0, &next, stats, frozen);
  // An in-flight word may complete after the decision frontier. Empty at the
  // decision and present after stopping is a legal pair of observations.
  stats.producer_ordinal = stats.consumer_ordinal; stats.backlog_depth = 0;
  frozen.front_word = UINT32_MAX;
  publish_dual_core_association_loss_decision("snapshot_association_timeout", 817250605,
      pending, UINT32_MAX, 0, 0, nullptr, stats, frozen);
}
"""
    )
    compiler = shutil.which("c++")
    assert compiler, "native formatter regression requires c++"
    exe = tmp_path / "formatter"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(firmware),
            str(cpp),
            "-o",
            str(exe),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    emitted = subprocess.run(
        [str(exe)], check=True, capture_output=True, text=True
    ).stdout
    path = tmp_path / "association.csv"
    with CsvRecordSplitter({"association_loss_decisions_v2": path}) as splitter:
        for line in emitted.splitlines():
            assert splitter.process_line(line) == "association_loss_decisions_v2"
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["unassociated_front_word"] for row in rows] == ["0", str(2**32 - 1)]
    assert all(row["unassociated_front_word_present"] == "true" for row in rows)
    assert rows[0]["pending_reference_sequence"] == "814"
    assert rows[0]["frozen_consumer_ordinal"] == "814"
    assert rows[1]["snapshot_backlog_depth"] == "0"
    assert rows[1]["frozen_backlog_depth"] == "1"
    result = validate_csv(
        path,
        CsvValidationContext(
            contract="association_loss_decisions_v2",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert result.ok, result.errors
    assert result.row_count == 2
    assert not list(tmp_path.glob("*snapshots*.csv"))
