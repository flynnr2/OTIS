from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv

from .run_loader import load_manifest


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _int(value: str) -> int:
    return int(value, 10)


def _summarize_pps(raw_rows: list[dict[str, str]], nominal_hz_by_domain: dict[str, float]) -> list[str]:
    lines: list[str] = []
    by_domain: dict[str, list[int]] = defaultdict(list)
    for row in raw_rows:
        if row.get("record_type") == "REF" and row.get("edge") == "R":
            by_domain[row["capture_domain"]].append(_int(row["timestamp_ticks"]))

    for domain, ticks in sorted(by_domain.items()):
        if len(ticks) < 2:
            lines.append(f"- PPS {domain}: {len(ticks)} reference edge(s); not enough intervals")
            continue
        intervals = [b - a for a, b in zip(ticks, ticks[1:])]
        mean_ticks = sum(intervals) / len(intervals)
        hz = nominal_hz_by_domain.get(domain)
        if hz:
            mean_seconds = mean_ticks / hz
            lines.append(f"- PPS {domain}: {len(intervals)} interval(s), mean {mean_ticks:.3f} ticks ({mean_seconds:.9f} s)")
        else:
            lines.append(f"- PPS {domain}: {len(intervals)} interval(s), mean {mean_ticks:.3f} ticks")
    return lines


def render_report(run_dir: Path) -> str:
    manifest = load_manifest(run_dir)
    files_by_contract = {entry["contract"]: run_dir / entry["path"] for entry in manifest.files}
    nominal_hz_by_domain = {
        str(domain["name"]): float(domain["nominal_hz"])
        for domain in manifest.data.get("domains", [])
        if "name" in domain and "nominal_hz" in domain
    }

    raw_rows = _read_csv(files_by_contract.get("raw_events_v1", Path("__missing__")))
    count_rows = _read_csv(files_by_contract.get("count_observations_v1", Path("__missing__")))
    health_rows = _read_csv(files_by_contract.get("health_v1", Path("__missing__")))

    lines: list[str] = []
    lines.append(f"Run: {manifest.run_id}")
    lines.append("")
    lines.append("Contracts:")

    for file_entry in manifest.files:
        lines.append(f"- {file_entry['contract']}: {file_entry['path']}")

    lines.append("")
    lines.append("Rows:")
    lines.append(f"- raw_events_v1: {len(raw_rows)}")
    lines.append(f"- count_observations_v1: {len(count_rows)}")
    lines.append(f"- health_v1: {len(health_rows)}")

    pps_lines = _summarize_pps(raw_rows, nominal_hz_by_domain)
    if pps_lines:
        lines.append("")
        lines.append("Reference intervals:")
        lines.extend(pps_lines)

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Render a compact OTIS run report.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(render_report(args.run_dir))


if __name__ == "__main__":
    main()
