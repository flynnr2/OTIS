from __future__ import annotations

from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CONTRACT_FIELDS


def test_live_interpreted_products_are_split_without_touching_raw_evidence(
    tmp_path: Path,
) -> None:
    targets = {
        contract: tmp_path / f"{contract}.csv"
        for contract in (
            "reference_observations_v1",
            "diagnostics_v1",
            "estimates_v2",
            "control_previews_v1",
            "active_transactions_v1",
        )
    }
    record_types = {
        "reference_observations_v1": "RFO",
        "diagnostics_v1": "DIAG",
        "estimates_v2": "EST",
        "control_previews_v1": "CTL",
        "active_transactions_v1": "ACT",
    }
    with CsvRecordSplitter(targets) as splitter:
        for contract, record_type in record_types.items():
            fields = CONTRACT_FIELDS[contract]
            row = [record_type, str(1 if contract != "estimates_v2" else 2)]
            row.extend("" for _ in fields[2:])
            assert splitter.process_line(",".join(row)) == contract

    for contract, path in targets.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(CONTRACT_FIELDS[contract])
        assert lines[1].startswith(record_types[contract] + ",")
