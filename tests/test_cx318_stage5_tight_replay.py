from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    CONTRACT_FIELDS,
    CsvValidationContext,
    TIGHT_DEADBAND_POLICY_SHA256,
    validate_csv,
)
from host.otis_tools.cx318_stage5_tight_replay import replay_tight_deadband


CONTRACT = "tight_deadband_decisions_v1"


def _row(sequence: int, counts: int, **overrides: str) -> dict[str, str]:
    absolute = abs(counts)
    row = {
        "record_type": "TDB",
        "schema_version": "1",
        "decision_sequence": str(sequence),
        "estimate_id": f"est:cx317:selected600:{sequence:06d}",
        "decision_timestamp_ticks": str(1_000 + sequence),
        "time_domain": "rp2040_timer0",
        "capture_session": "7",
        "dac_epoch": "2",
        "integer_edge_error_counts": str(counts),
        "absolute_edge_error_counts": str(absolute),
        "state_before": "OUTSIDE",
        "state_after": "OUTSIDE",
        "entry_counter": "0",
        "release_counter": "0",
        "transition": "false",
        "frequency_controller_eligible": "false",
        "requalified": "false",
        "requalification_reason": "",
        "historical_v2_inside": str(absolute <= 3).lower(),
        "symmetric_two_count_inside": str(absolute <= 2).lower(),
        "policy_id": "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
        "policy_sha256": TIGHT_DEADBAND_POLICY_SHA256,
        "actionable": "false",
        "actuation_authorized": "false",
        "authorization_consumed": "false",
        "reason_codes": "three_count_outside_hold",
    }
    row.update(overrides)
    return row


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[CONTRACT])
        writer.writeheader()
        writer.writerows(rows)


def _exact_rows() -> list[dict[str, str]]:
    return [
        _row(0, 2, state_before="REQUALIFY_OUTSIDE", entry_counter="1", transition="true", reason_codes="tight_entry_pending"),
        _row(1, -2, state_before="OUTSIDE", state_after="TIGHT_INSIDE", transition="true", reason_codes="tight_entry_confirmed"),
        _row(2, 3, state_before="TIGHT_INSIDE", state_after="TIGHT_INSIDE", reason_codes="three_count_inside_hold"),
        _row(3, 4, state_before="TIGHT_INSIDE", state_after="TIGHT_INSIDE", release_counter="1", reason_codes="loose_release_pending"),
        _row(4, -4, state_before="TIGHT_INSIDE", transition="true", frequency_controller_eligible="true", reason_codes="loose_release_confirmed"),
    ]


def test_tdb_contract_and_replay_cover_active_and_both_zero_authority_shadows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tight_deadband_decisions_v1.csv"
    _write(path, _exact_rows())

    validation = validate_csv(
        path,
        CsvValidationContext(CONTRACT, frozenset(), frozenset()),
    )
    replay = replay_tight_deadband(path)

    assert validation.ok
    assert replay.exact
    assert len(replay.comparisons) == 5
    assert all(item["pass"] for item in replay.comparisons)


def test_tdb_contract_rejects_noninteger_counts_bad_shadows_and_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tight_deadband_decisions_v1.csv"
    row = _exact_rows()[0]
    row.update(
        integer_edge_error_counts="2.0",
        absolute_edge_error_counts="9",
        historical_v2_inside="false",
        actionable="true",
    )
    _write(path, [row])

    result = validate_csv(path, CsvValidationContext(CONTRACT, frozenset(), frozenset()))

    assert not result.ok
    assert any("integer_edge_error_counts is not an integer" in error for error in result.errors)
    assert any("actionable must remain false" in error for error in result.errors)


def test_tdb_replay_reports_exact_field_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "tight_deadband_decisions_v1.csv"
    rows = _exact_rows()
    rows[2]["symmetric_two_count_inside"] = "true"
    _write(path, rows)

    replay = replay_tight_deadband(path)

    assert not replay.exact
    assert any("symmetric_two_count_inside" in error for error in replay.errors)


def test_tdb_capture_route_writes_only_exact_26_column_frames(tmp_path: Path) -> None:
    path = tmp_path / "tight_deadband_decisions_v1.csv"
    row = _exact_rows()[0]
    frame = ",".join(row[field] for field in CONTRACT_FIELDS[CONTRACT])
    with CsvRecordSplitter({CONTRACT: path}) as splitter:
        assert splitter.process_line(frame) == CONTRACT
        assert splitter.process_line(frame + ",unexpected") is None

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == [",".join(CONTRACT_FIELDS[CONTRACT]), frame]
