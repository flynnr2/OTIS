from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import shutil
import sys
from typing import Callable

from .contracts import CONTRACT_FIELDS, CONTRACT_SCHEMA_VERSIONS
from .firmware_host_contract import (
    RECORD_TYPE_TO_CONTRACT,
    validate_record_wire_values,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, find_manifest_path


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

    def __enter__(self) -> "CsvRecordSplitter":
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
        clean = line.strip()
        if not clean:
            return None
        try:
            row = next(csv.reader([clean]))
        except csv.Error as exc:
            if self.on_parser_error is not None:
                self.on_parser_error(f"CSV parse error: {exc}")
            return None
        if not row:
            return None
        record_type = row[0]
        contract = RECORD_CONTRACTS.get(record_type)
        if contract is None:
            if record_type == "record_type" and tuple(row) in CONTRACT_HEADER_ROWS:
                return None
            if self.on_parser_error is not None:
                self.on_parser_error(
                    "unknown record type or mismatched contract header "
                    f"{record_type!r}"
                )
            return None
        handle = self.handle_by_record_type.get(record_type)
        if handle is None:
            handle = self.handle_by_contract.get(contract)
        if handle is None:
            return None
        expected_columns = len(CONTRACT_FIELDS[contract])
        if len(row) != expected_columns:
            if self.on_parser_error is not None:
                self.on_parser_error(f"{record_type} column count {len(row)} does not match {expected_columns}")
            return None
        expected_version = str(CONTRACT_SCHEMA_VERSIONS[contract])
        if row[1] != expected_version:
            if self.on_parser_error is not None:
                self.on_parser_error(
                    f"{record_type} schema_version {row[1]!r} does not match "
                    f"{expected_version}"
                )
            return None
        wire_errors = validate_record_wire_values(contract, row)
        if wire_errors:
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
                if self.on_parser_error is not None:
                    self.on_parser_error(
                        f"{record_type} must use channel_id={expected_channel}; "
                        f"got {row[channel_index]}"
                    )
                return None
        handle.write(clean + "\n")
        handle.flush()
        return contract


def _load_template(template_dir: Path, run_id: str) -> dict:
    manifest_path = find_manifest_path(template_dir)
    if manifest_path is None:
        raise FileNotFoundError(f"template manifest not found in {template_dir}")
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["run_id"] = run_id
    manifest["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest["template"] = False
    return manifest


def _split_targets_from_manifest(manifest: dict, run_dir: Path) -> tuple[dict[str, Path], dict[str, tuple[str, Path]]]:
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
    raw_entries = [entry for entry in manifest["files"] if entry.get("contract") == "raw_events_v1"]

    for entry in manifest["files"]:
        contract = entry["contract"]
        path = run_dir / entry["path"]
        if contract == "raw_events_v1" and len(raw_entries) > 1:
            record_type = entry.get("record_type")
            name = path.name.lower()
            if record_type == "EVT" or "external" in name or "evt" in name:
                file_by_record_type["EVT"] = (contract, path)
                continue
            if record_type == "REF" or "reference" in name or "ref" in name:
                file_by_record_type["REF"] = (contract, path)
                continue
        file_by_contract[contract] = path

    return file_by_contract, file_by_record_type


def capture_serial(run_dir: Path, template_dir: Path, run_id: str) -> int:
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    in_progress = run_dir / CAPTURE_IN_PROGRESS_FLAG
    in_progress.touch()

    manifest = _load_template(template_dir, run_id)
    if (template_dir / "README.md").exists():
        shutil.copyfile(template_dir / "README.md", run_dir / "README.md")
    with (run_dir / "run_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    file_by_contract, file_by_record_type = _split_targets_from_manifest(manifest, run_dir)
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "serial.log"
    try:
        with raw_path.open("x", encoding="utf-8", newline="") as raw_handle, CsvRecordSplitter(
            file_by_contract,
            file_by_record_type,
            append=False,
        ) as splitter:
            for line in sys.stdin:
                raw_handle.write(line)
                raw_handle.flush()
                splitter.process_line(line)
    finally:
        in_progress.unlink(missing_ok=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Split OTIS serial CSV records into a run directory.")
    parser.add_argument("--template", required=True, type=Path, help="Template run directory containing run_manifest.json.")
    parser.add_argument("--run-dir", required=True, type=Path, help="New run directory to create.")
    parser.add_argument("--run-id", required=True, help="Run identifier to write into run_manifest.json.")
    args = parser.parse_args()
    raise SystemExit(capture_serial(args.run_dir, args.template, args.run_id))


if __name__ == "__main__":
    main()
