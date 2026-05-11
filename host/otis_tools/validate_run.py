from __future__ import annotations

from pathlib import Path
import argparse
import sys

from .contracts import (
    COUNT_OBSERVATION_FIELDS,
    HEALTH_FIELDS,
    RAW_EVENT_FIELDS,
    validate_csv_header,
)
from .run_loader import load_manifest


FIELD_MAP = {
    "raw_events_v1": RAW_EVENT_FIELDS,
    "count_observations_v1": COUNT_OBSERVATION_FIELDS,
    "health_v1": HEALTH_FIELDS,
}


def validate_run(run_dir: Path) -> int:
    manifest = load_manifest(run_dir)
    failures: list[str] = []

    for file_entry in manifest.files:
        family = file_entry.get("contract")
        rel_path = file_entry.get("path")
        if family not in FIELD_MAP or not rel_path:
            continue
        result = validate_csv_header(run_dir / rel_path, FIELD_MAP[family])
        if result.ok:
            print(f"OK {rel_path}: {result.row_count} rows")
        else:
            for error in result.errors:
                failures.append(f"{rel_path}: {error}")

    for failure in failures:
        print(f"ERROR {failure}", file=sys.stderr)

    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an OTIS run directory.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    raise SystemExit(validate_run(args.run_dir))


if __name__ == "__main__":
    main()
