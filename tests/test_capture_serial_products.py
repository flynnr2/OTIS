from __future__ import annotations

from pathlib import Path

from host.otis_tools.record_splitter import CsvRecordSplitter, RECORD_CONTRACTS
from host.otis_tools.contracts import CONTRACT_FIELDS, CONTRACT_SCHEMA_VERSIONS
from host.otis_tools.firmware_host_contract import (
    RECORD_FIELD_WIRE_TYPES,
    WIRE_TYPES,
)
from host.otis_tools.run_paths import default_csv_files


def _canonical_wire_value(contract: str, field: str) -> str:
    wire_type = WIRE_TYPES[RECORD_FIELD_WIRE_TYPES[contract][field]]
    kind = wire_type["kind"]
    if kind == "optional":
        return ""
    if kind == "integer" or kind == "finite_decimal":
        return "0"
    if kind == "enum":
        return str(wire_type["values"][0])
    if kind == "escaped_atom":
        return "value"
    if kind == "lower_hex":
        return "0" * int(wire_type["length"])
    if kind == "lower_hex_or_literal":
        return str(wire_type["literal"])
    raise AssertionError(f"{contract}.{field} needs explicit fixed value")


def test_current_capture_inventory_matches_writer_backed_contract_registry() -> None:
    files = default_csv_files()
    assert len(files) == 17
    assert {entry["contract"] for entry in files} == set(CONTRACT_FIELDS)
    assert len({entry["path"] for entry in files}) == len(files)


def test_live_interpreted_products_are_split_without_touching_raw_evidence(
    tmp_path: Path,
) -> None:
    targets = {
        contract: tmp_path / f"{contract}.csv"
        for contract in (
            "accepted_pps_spans_v1",
            "estimates_v3",
            "control_previews_v1",
            "active_transactions_v3",
            "active_hybrid_decisions_v3",
            "active_hybrid_maintenance_v2",
            "relative_phase_observations_v2",
            "phase_estimator_outputs_v2",
            "tight_deadband_decisions_v1",
        )
    }
    record_types = {
        "accepted_pps_spans_v1": "APS",
        "estimates_v3": "EST",
        "control_previews_v1": "CTL",
        "active_transactions_v3": "ACT",
        "active_hybrid_decisions_v3": "AHY",
        "active_hybrid_maintenance_v2": "AHM",
        "relative_phase_observations_v2": "RPH",
        "phase_estimator_outputs_v2": "PHE",
        "tight_deadband_decisions_v1": "TDB",
    }
    with CsvRecordSplitter(targets) as splitter:
        for contract, record_type in record_types.items():
            fields = CONTRACT_FIELDS[contract]
            version = CONTRACT_SCHEMA_VERSIONS[contract]
            row = [record_type, str(version)]
            row.extend(
                _canonical_wire_value(contract, field) for field in fields[2:]
            )
            assert splitter.process_line(",".join(row)) == contract

    for contract, path in targets.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(CONTRACT_FIELDS[contract])
        assert lines[1].startswith(record_types[contract] + ",")


def test_retired_timing_only_wire_tags_are_not_routable(tmp_path: Path) -> None:
    retired = ("A" + "T2", "A" + "H2", "H" + "PR")
    assert all(record_type not in RECORD_CONTRACTS for record_type in retired)
    target = tmp_path / "active_transactions_v3.csv"
    with CsvRecordSplitter({"active_transactions_v3": target}) as splitter:
        for record_type in retired:
            assert splitter.process_line(record_type + ",2") is None
    assert target.read_text(encoding="utf-8").splitlines() == [
        ",".join(CONTRACT_FIELDS["active_transactions_v3"])
    ]
