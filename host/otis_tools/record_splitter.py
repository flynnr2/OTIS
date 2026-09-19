"""Route explicitly declared wire records; never create configuration or own I/O."""
from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

from .contracts import CONTRACT_FIELDS, CONTRACT_SCHEMA_VERSIONS
from .firmware_host_contract import (
    RAW_ONLY_DIAGNOSTIC_RECORD_TYPES,
    RECORD_TYPE_TO_CONTRACT,
    is_admissible_late_attach_fragment,
    validate_raw_only_diagnostic,
    validate_record_wire_values,
)

RECORD_CONTRACTS = dict(RECORD_TYPE_TO_CONTRACT)
CONTRACT_HEADER_ROWS = {
    tuple(fields): contract for contract, fields in CONTRACT_FIELDS.items()
}

# Hardware channel assignment is architectural, not caller-selected. EVT is
# optional D10 evidence on CH0; REF is the sole D14 reference on CH1.
RAW_EVENT_CHANNELS = {"EVT": "0", "REF": "1"}


class CsvRecordSplitter:
    def __init__(
        self,
        file_by_contract: dict[str, Path],
        file_by_record_type: dict[str, tuple[str, Path]] | None = None,
        append: bool = False,
        on_parser_error: Callable[[str], None] | None = None,
    ) -> None:
        self.file_by_contract = file_by_contract
        self.file_by_record_type = file_by_record_type or {}
        self.append = append
        self.on_parser_error = on_parser_error
        self.handles: dict[tuple[str, Path], object] = {}
        self.handle_by_contract: dict[str, object] = {}
        self.handle_by_record_type: dict[str, object] = {}
        self.recognized_protocol_line_seen = False
        self.late_attach_fragment_seen = False
        self.last_disposition: str | None = None
        self.last_record_type: str | None = None
        self.last_diagnostic_errors: tuple[str, ...] = ()

    def __enter__(self) -> CsvRecordSplitter:
        targets: list[tuple[str, Path]] = list(self.file_by_contract.items())
        targets.extend((contract, path) for contract, path in self.file_by_record_type.values())
        for contract, path in targets:
            key = (contract, path)
            if key in self.handles:
                continue
            fields = CONTRACT_FIELDS[contract]
            path.parent.mkdir(parents=True, exist_ok=True)
            needs_header = not self.append or not path.exists() or path.stat().st_size == 0
            handle = path.open("a" if self.append else "w", encoding="utf-8", newline="")
            if needs_header:
                handle.write(",".join(fields) + "\n")
                handle.flush()
            self.handles[key] = handle
        for contract, path in self.file_by_contract.items():
            self.handle_by_contract[contract] = self.handles[(contract, path)]
        for record_type, (contract, path) in self.file_by_record_type.items():
            self.handle_by_record_type[record_type] = self.handles[(contract, path)]
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for handle in self.handles.values():
            handle.close()

    def process_line(self, line: str) -> str | None:
        self.last_disposition = None
        self.last_record_type = None
        self.last_diagnostic_errors = ()
        clean = line.strip()
        if not clean:
            self.last_disposition = "empty"
            return None
        try:
            row = next(csv.reader([clean]))
        except csv.Error as exc:
            if clean.startswith("LAT,"):
                self.last_record_type = "LAT"
                self.last_disposition = "raw_only_diagnostic_invalid"
                self.last_diagnostic_errors = (f"CSV parse error: {exc}",)
                return None
            self.last_disposition = "error"
            if self.on_parser_error is not None:
                self.on_parser_error(f"CSV parse error: {exc}")
            return None
        if not row:
            self.last_disposition = "empty"
            return None
        record_type = row[0]
        self.last_record_type = record_type
        if record_type in RAW_ONLY_DIAGNOSTIC_RECORD_TYPES:
            self.recognized_protocol_line_seen = True
            wire_errors = validate_raw_only_diagnostic(row)
            if wire_errors:
                if record_type == "LAT":
                    self.last_disposition = "raw_only_diagnostic_invalid"
                    self.last_diagnostic_errors = tuple(wire_errors)
                    return None
                self.last_disposition = "error"
                if self.on_parser_error is not None:
                    self.on_parser_error(
                        f"{record_type} raw-only diagnostic mismatch: "
                        + "; ".join(wire_errors)
                    )
                return None
            self.last_disposition = "raw_only_diagnostic"
            return None
        contract = RECORD_CONTRACTS.get(record_type)
        if contract is None:
            if record_type == "record_type" and tuple(row) in CONTRACT_HEADER_ROWS:
                self.recognized_protocol_line_seen = True
                self.last_disposition = "contract_header"
                return None
            if is_admissible_late_attach_fragment(
                clean,
                recognized_protocol_line_seen=self.recognized_protocol_line_seen,
                prior_fragment_seen=self.late_attach_fragment_seen,
            ):
                self.late_attach_fragment_seen = True
                self.last_disposition = "late_attach_boot_fragment"
                return None
            self.last_disposition = "error"
            if self.on_parser_error is not None:
                self.on_parser_error(
                    "unknown record type or mismatched contract header "
                    f"{record_type!r}"
                )
            return None
        self.recognized_protocol_line_seen = True
        handle = self.handle_by_record_type.get(record_type)
        if handle is None:
            handle = self.handle_by_contract.get(contract)
        if handle is None:
            self.last_disposition = "unselected_contract"
            return None
        expected_columns = len(CONTRACT_FIELDS[contract])
        if len(row) != expected_columns:
            self.last_disposition = "error"
            if self.on_parser_error is not None:
                self.on_parser_error(f"{record_type} column count {len(row)} does not match {expected_columns}")
            return None
        expected_version = str(CONTRACT_SCHEMA_VERSIONS[contract])
        if row[1] != expected_version:
            self.last_disposition = "error"
            if self.on_parser_error is not None:
                self.on_parser_error(
                    f"{record_type} schema_version {row[1]!r} does not match "
                    f"{expected_version}"
                )
            return None
        wire_errors = validate_record_wire_values(contract, row)
        if wire_errors:
            self.last_disposition = "error"
            if self.on_parser_error is not None:
                self.on_parser_error(
                    f"{record_type} current wire contract mismatch: "
                    + "; ".join(wire_errors)
                )
            return None
        expected_channel = RAW_EVENT_CHANNELS.get(record_type)
        if expected_channel is not None:
            channel_index = CONTRACT_FIELDS[contract].index("channel_id")
            if row[channel_index] != expected_channel:
                self.last_disposition = "error"
                if self.on_parser_error is not None:
                    self.on_parser_error(
                        f"{record_type} must use channel_id={expected_channel}; "
                        f"got {row[channel_index]}"
                    )
                return None
        handle.write(clean + "\n")
        handle.flush()
        self.last_disposition = "contract_record"
        return contract


def split_targets(manifest: dict, run_dir: Path) -> tuple[dict[str, Path], dict[str, tuple[str, Path]]]:
    channels = {
        int(item["channel_id"]): item
        for item in manifest.get("channels", [])
        if isinstance(item, dict) and "channel_id" in item
    }
    expected_channels = {
        0: {"pin": "D10", "role": "external_event", "record_type": "EVT"},
        1: {"pin": "D14", "role": "authoritative_pps_reference", "record_type": "REF"},
    }
    for channel_id, expected in expected_channels.items():
        observed = channels.get(channel_id)
        if observed is None or any(observed.get(key) != value for key, value in expected.items()):
            raise ValueError(
                f"manifest channel CH{channel_id} must declare {expected}; got {observed}"
            )
    d10 = channels[0]
    if (
        d10.get("control_authority") is not False
        or d10.get("terminal_authority") is not False
        or d10.get("authority") != "evidence_only"
    ):
        raise ValueError("D10/CH0 must remain optional zero-authority evidence")
    file_by_contract: dict[str, Path] = {}
    file_by_record_type: dict[str, tuple[str, Path]] = {}
    for entry in manifest["files"]:
        contract = entry["contract"]
        path = run_dir / entry["path"]
        if contract == "raw_events_v1":
            record_type = entry.get("record_type")
            if record_type not in RAW_EVENT_CHANNELS or record_type in file_by_record_type:
                raise ValueError("raw event files require distinct explicit EVT and REF record types")
            file_by_record_type[record_type] = (contract, path)
        else:
            if contract in file_by_contract:
                raise ValueError(f"multiple output paths for {contract}")
            file_by_contract[contract] = path
    if set(file_by_record_type) != set(RAW_EVENT_CHANNELS):
        raise ValueError("manifest must declare separate EVT and REF outputs")
    return file_by_contract, file_by_record_type
