from __future__ import annotations

from pathlib import Path
import argparse
import sys

from .contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from .run_loader import load_manifest


def validate_run(run_dir: Path) -> int:
    manifest = load_manifest(run_dir)
    failures: list[str] = []

    for file_entry in manifest.files:
        contract = file_entry.get("contract")
        rel_path = file_entry.get("path")
        if not rel_path:
            failures.append("manifest file entry missing path")
            continue
        if contract not in CONTRACT_FIELDS:
            failures.append(f"{rel_path}: unsupported or missing contract {contract!r}")
            continue

        context = CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
        )
        result = validate_csv(run_dir / rel_path, context)
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
