from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.adaptive_hybrid_monitor import (
    TAIL_OBSERVATION_MAX_BYTES,
    _awaiting_expected_evidence,
    _bounded_contract_tail,
    _valid_header_without_rows,
)


FIELDS = ("record_type", "schema_version", "time_domain", "sequence", "payload")
EXPECTED = {
    "record_type": "ACT",
    "schema_version": "3",
    "time_domain": "rp2040_monotonic_us64",
}


def _row(sequence: int, payload: str = "") -> str:
    return f"ACT,3,rp2040_monotonic_us64,{sequence},{payload}\n"


def _observe(path: Path) -> dict[str, object]:
    return _bounded_contract_tail(
        path, FIELDS, now=100.0, expected=EXPECTED,
        summary_fields=("sequence", "time_domain"),
    )


def test_bounded_tail_observes_latest_complete_row_without_replaying_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large.csv"
    header = ",".join(FIELDS) + "\n"
    with path.open("wb") as stream:
        stream.write(header.encode())
        for sequence in range(20_000):
            stream.write(_row(sequence, "x" * 64).encode())
        stream.write(b"ACT,3,rp2040_monotonic_us64,20000,partial")
    observed = _observe(path)
    assert observed["latest"] == {
        "sequence": "19999",
        "time_domain": "rp2040_monotonic_us64",
    }
    assert observed["rows"] is None
    assert observed["observed_tail_only"] is True
    assert observed["mismatches"] == []
    assert observed["bytes_observed"] <= TAIL_OBSERVATION_MAX_BYTES + len(header)
    assert path.stat().st_size > TAIL_OBSERVATION_MAX_BYTES * 10


def test_bounded_tail_reports_missing_header_only_and_malformed_rows(tmp_path: Path) -> None:
    missing = _observe(tmp_path / "missing.csv")
    assert missing["unavailable"] is True

    header_only = tmp_path / "header_only.csv"
    header_only.write_text(",".join(FIELDS) + "\n", encoding="utf-8")
    observed = _observe(header_only)
    assert observed["latest"] is None
    assert observed["mismatches"] == []

    malformed = tmp_path / "malformed.csv"
    malformed.write_text("wrong,header\nACT,3,rp2040_monotonic_us64,1,x\n", encoding="utf-8")
    observed = _observe(malformed)
    assert observed["unavailable"] is True
    assert observed["mismatches"] == ["retained CSV header differs"]

    no_newline = tmp_path / "no_newline.csv"
    no_newline.write_text(",".join(FIELDS), encoding="utf-8")
    observed = _observe(no_newline)
    assert observed["unavailable"] is True
    assert observed["mismatches"] == ["retained CSV header is unavailable"]

    malformed_row = tmp_path / "malformed_row.csv"
    malformed_row.write_text(
        ",".join(FIELDS) + "\nACT,3,rp2040_monotonic_us64,1,\"unterminated\n",
        encoding="utf-8",
    )
    observed = _observe(malformed_row)
    assert observed["unavailable"] is True
    assert observed["mismatches"] == ["latest complete CSV row is malformed: unexpected end of data"]


def test_bounded_tail_rejects_wrong_clock_domain_on_the_observed_row(tmp_path: Path) -> None:
    path = tmp_path / "clock.csv"
    path.write_text(",".join(FIELDS) + "\nACT,3,controller_seconds,1,x\n", encoding="utf-8")
    observed = _observe(path)
    assert observed["observed_frontier_valid"] is False
    assert observed["mismatches"] == [
        "latest row time_domain differs: 'controller_seconds' != 'rp2040_monotonic_us64'"
    ]


def test_only_a_valid_header_without_rows_is_startup_absence() -> None:
    assert _valid_header_without_rows({
        "latest": None, "unavailable": False, "mismatches": [],
    })
    assert not _valid_header_without_rows({
        "latest": None, "unavailable": True, "mismatches": [],
    })
    assert not _valid_header_without_rows({
        "latest": None, "mismatches": ["retained CSV header differs"],
    })
    assert not _valid_header_without_rows({
        "latest": {"sequence": "1"}, "mismatches": [],
    })


def test_awaiting_expected_evidence_requires_all_valid_headers() -> None:
    empty = {"latest": None, "unavailable": False, "mismatches": []}
    exact = {"ACT": empty, "AHY": empty}
    assert _awaiting_expected_evidence(
        exact_lifecycle=exact,
        maintenance=empty,
    )
    assert not _awaiting_expected_evidence(
        exact_lifecycle={"ACT": empty, "AHY": {**empty, "unavailable": True}},
        maintenance=empty,
    )


@pytest.mark.parametrize("supervisor", [None, {"manual_start_sent": True, "setup_confirmed_utc": "2026-09-11T00:00:00Z"}])
def test_monitor_does_not_infer_record_delivery_from_host_startup_order(tmp_path, monkeypatch, supervisor):
    import json
    import os
    from host.otis_tools import adaptive_hybrid_monitor as monitor
    from host.otis_tools.adaptive_hybrid_contract import ADAPTIVE_HYBRID_PROGRAMME
    from host.otis_tools.contracts import ESTIMATE_V3_FIELDS, ACTIVE_TRANSACTION_V3_FIELDS, ACTIVE_HYBRID_DECISION_V3_FIELDS, ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS
    (tmp_path / "reports").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "csv").mkdir()
    (tmp_path / "raw/serial.log").write_text("retained raw evidence\n")
    (tmp_path / monitor.CAPTURE_STATE).write_text(json.dumps({
        "pid": os.getpid(), "capture_active": True, "serial_open": True}))
    if supervisor is not None:
        (tmp_path / monitor.SUPERVISOR_STATE).write_text(json.dumps(supervisor))
    for path, fields in ((monitor.ESTIMATES, ESTIMATE_V3_FIELDS),
                         (monitor.ACTIVE, ACTIVE_TRANSACTION_V3_FIELDS),
                         (monitor.HYBRID, ACTIVE_HYBRID_DECISION_V3_FIELDS),
                         (Path("csv/active_hybrid_maintenance_v2.csv"), ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS)):
        (tmp_path / path).write_text(",".join(fields) + "\n")
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda _: {os.getpid()})
    monkeypatch.setattr(monitor, "programme_from_mapping", lambda _: ADAPTIVE_HYBRID_PROGRAMME)
    manifest = {"host": {"serial_device": "/dev/unused"}, "firmware": {"build_identity": "fixture"},
                "run_id": "fixture", "bundle": {"bundle_sha256": "b" * 64}}
    sample = monitor.snapshot_validated(tmp_path, manifest)
    assert sample["status"] == "awaiting_expected_evidence"
    assert sample["diagnostic_review_hold"] is None
    assert sample["progress"]["maintenance_evidence"]["latest"] is None
    # A missing mandatory stream is a different observed fact, even at startup.
    (tmp_path / "csv/active_hybrid_maintenance_v2.csv").unlink()
    assert monitor.snapshot_validated(tmp_path, manifest)["status"] == "review_required"
