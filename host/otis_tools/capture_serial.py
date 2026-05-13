from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import shutil
import sys
from typing import Callable

from .contracts import CONTRACT_FIELDS
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, find_manifest_path


RECORD_CONTRACTS = {
    "EVT": "raw_events_v1",
    "REF": "raw_events_v1",
    "CNT": "count_observations_v1",
    "STS": "health_v1",
}


class CsvRecordSplitter:
    def __init__(
        self,
        file_by_contract: dict[str, Path],
        append: bool = False,
        on_parser_error: Callable[[str], None] | None = None,
    ) -> None:
        self.file_by_contract = file_by_contract
        self.append = append
        self.on_parser_error = on_parser_error
        self.handles = {}

    def __enter__(self) -> "CsvRecordSplitter":
        for contract, path in self.file_by_contract.items():
            fields = CONTRACT_FIELDS[contract]
            path.parent.mkdir(parents=True, exist_ok=True)
            needs_header = not self.append or not path.exists() or path.stat().st_size == 0
            handle = path.open("a" if self.append else "w", encoding="utf-8", newline="")
            if needs_header:
                handle.write(",".join(fields) + "\n")
                handle.flush()
            self.handles[contract] = handle
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
            return None
        handle = self.handles.get(contract)
        if handle is None:
            return None
        expected_columns = len(CONTRACT_FIELDS[contract])
        if len(row) != expected_columns and self.on_parser_error is not None:
            self.on_parser_error(f"{record_type} column count {len(row)} does not match {expected_columns}")
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

    file_by_contract = {entry["contract"]: run_dir / entry["path"] for entry in manifest["files"]}
    try:
        with CsvRecordSplitter(file_by_contract, append=False) as splitter:
            for line in sys.stdin:
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
