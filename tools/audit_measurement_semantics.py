from __future__ import annotations

from pathlib import Path
import argparse
import csv
import io
import re


OUTPUT = Path("derived/measurement_semantics_usage_inventory.csv")
TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".ino",
    ".json",
    ".md",
    ".py",
    ".schema",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "tmp",
}
TERMS = (
    ("uncertainty", re.compile(r"uncertaint", re.IGNORECASE)),
    ("dispersion", re.compile(r"\bdispersion\b", re.IGNORECASE)),
    ("standard_deviation", re.compile(
        r"\bstddev\b|\bstandard deviation\b", re.IGNORECASE
    )),
    ("confidence", re.compile(r"\bconfidence\b", re.IGNORECASE)),
    ("error_bound", re.compile(r"\berror bounds?\b", re.IGNORECASE)),
    ("coverage_factor", re.compile(r"\bcoverage factor\b", re.IGNORECASE)),
)


def _classification(path: Path, line: str, matched: list[str]) -> str:
    if "frequency_uncertainty_hz" in line and (
        "estimates_v1" in path.as_posix()
        or "ESTIMATE_V1_FIELDS" in line
        or "historical" in line.lower()
        or "legacy" in line.lower()
    ):
        return "legacy_v1_dispersion_label"
    if "uncertainty" in matched:
        return "measurement_uncertainty_semantics"
    if "dispersion" in matched or "standard_deviation" in matched:
        return "sample_dispersion_or_repeatability"
    if "confidence" in matched:
        return "confidence_semantics"
    if "error_bound" in matched:
        return "error_bound_semantics"
    return "coverage_semantics"


def inventory_bytes(root: Path) -> bytes:
    rows: list[dict[str, str]] = []
    output_path = root / OUTPUT
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path == output_path
            or any(part in SKIP_PARTS for part in path.relative_to(root).parts)
            or path.suffix.lower() not in TEXT_SUFFIXES
        ):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            matched = [name for name, pattern in TERMS if pattern.search(line)]
            if not matched:
                continue
            rows.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "line": str(line_number),
                    "matched_terms": ";".join(matched),
                    "classification": _classification(path, line, matched),
                    "source_text": line.strip(),
                }
            )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=(
            "path",
            "line",
            "matched_terms",
            "classification",
            "source_text",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify the repository-wide metrology usage inventory."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    expected = inventory_bytes(root)
    output = root / OUTPUT
    if args.check:
        if not output.exists() or output.read_bytes() != expected:
            print(
                "measurement semantics inventory is stale; run "
                "tools/audit_measurement_semantics.py"
            )
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(expected)
    print(f"wrote {output.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
