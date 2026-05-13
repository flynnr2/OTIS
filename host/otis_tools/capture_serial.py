from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import shutil
import sys

from .contracts import CONTRACT_FIELDS
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, find_manifest_path


RECORD_CONTRACTS = {
    "EVT": "raw_events_v1",
    "REF": "raw_events_v1",
    "CNT": "count_observations_v1",
    "STS": "health_v1",
}


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
    handles = {}
    try:
        for contract, path in file_by_contract.items():
            fields = CONTRACT_FIELDS[contract]
            handle = path.open("w", encoding="utf-8", newline="")
            handle.write(",".join(fields) + "\n")
            handles[contract] = handle

        for line in sys.stdin:
            clean = line.strip()
            if not clean:
                continue
            record_type = clean.split(",", 1)[0]
            contract = RECORD_CONTRACTS.get(record_type)
            if contract is None:
                continue
            if contract in handles:
                handles[contract].write(clean + "\n")
                handles[contract].flush()
    finally:
        for handle in handles.values():
            handle.close()

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
