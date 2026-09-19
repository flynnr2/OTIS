"""Decode optional LAT v1 diagnostics without promoting partial reports.

Raw input is retained. Completeness describes one seven-part statistics snapshot,
not complete capture or diagnostic coverage. This module has no control authority.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

UINT32_MAX = (1 << 32) - 1
HALF_RANGE = 1 << 31
HISTOGRAM_UPPER_US = (1, 4, 16, 64, 256, 1024, 4096, HALF_RANGE - 1)
BASE = {"v", "g", "c", "s", "p"}
PART_FIELDS = {
    0: {"e", "m", "a", "x", "d", "t", "sat", "hw"},
    1: {"hv", *(f"b{i}" for i in range(8))},
    **{p: {"have", "session", "seq", "start", "end", "u", "status", "domain"}
       for p in range(2, 7)},
}


def _parse(raw: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for item in raw.strip().split(",")[1:]:
        key, separator, value = item.partition("=")
        if not separator or key in values or not value.isascii() or not value.isdecimal():
            raise ValueError("malformed or duplicate field")
        number = int(value)
        if number > UINT32_MAX:
            raise ValueError("field outside uint32 domain")
        values[key] = number
    if not BASE <= values.keys():
        raise ValueError("missing report identity")
    if values["v"] != 1 or values["c"] not in (1, 2) or values["s"] > 4:
        raise ValueError("unknown version, channel or stage")
    part = values["p"]
    if part not in PART_FIELDS or values.keys() != BASE | PART_FIELDS[part]:
        raise ValueError("unknown part or incorrect fields")
    return values


def _validate(parts: dict[int, dict[str, int]]) -> list[str]:
    errors: list[str] = []
    if 0 in parts:
        counts = parts[0]
        if counts["sat"] not in (0, 1) or counts["hw"] != 0:
            errors.append("invalid saturation or unavailable hardware marker")
        if counts["x"] > counts["e"]:
            errors.append("threshold count exceeds eligible count")
    if 1 in parts and parts[1]["hv"] != 1:
        errors.append("unknown histogram version")
    if (0 in parts and 1 in parts and not parts[0]["sat"]
            and sum(parts[1][f"b{i}"] for i in range(8)) != parts[0]["e"]):
        errors.append("histogram count differs from eligible count")
    durations: dict[int, int] = {}
    for p in range(2, 6):
        if p not in parts:
            continue
        sample = parts[p]
        if sample["have"] not in (0, 1):
            errors.append(f"part {p}: invalid presence")
        elif sample["have"]:
            duration = (sample["end"] - sample["start"]) & UINT32_MAX
            if (sample["status"] != 0 or sample["domain"] != 1
                    or duration >= HALF_RANGE or sample["u"] != 0):
                errors.append(f"part {p}: ineligible retained sample")
            durations[p] = duration
        elif sample["status"] != 1 or sample["domain"] != 0:
            errors.append(f"part {p}: absent sample lacks explicit unavailable status")
        if 0 in parts:
            expected = parts[0]["e"] >= (2 if p == 5 else 1)
            if bool(sample["have"]) != expected:
                errors.append(f"part {p}: presence contradicts eligible count")
    if 2 in durations and 3 in durations and durations[2] > durations[3]:
        errors.append("minimum exceeds maximum")
    if 3 in durations and 4 in durations and durations[3] != durations[4]:
        errors.append("largest tail differs from maximum")
    if 4 in durations and 5 in durations and durations[4] < durations[5]:
        errors.append("tail order contradicts descending duration")
    if 6 in parts:
        sample = parts[6]
        if sample["have"] not in (0, 1):
            errors.append("part 6: invalid presence")
        elif sample["have"]:
            if sample["status"] not in (1, 2) or sample["domain"] not in (0, 1):
                errors.append("part 6: invalid noneligible sample")
            if 0 in parts and not (parts[0]["m"] or parts[0]["a"]):
                errors.append("part 6: noneligible sample without corresponding count")
        elif sample["status"] != 1 or sample["domain"] != 0:
            errors.append("part 6: absent sample lacks explicit unavailable status")
        elif 0 in parts and (parts[0]["m"] or parts[0]["a"]):
            errors.append("part 6: missing retained noneligible sample")
    return errors


def decode_reports(lines: Iterable[str]) -> list[dict[str, object]]:
    """Return reports with complete/missing/ambiguous status and retained rows.

    LAT generation is a report ordinal, not a capture or source sequence.
    Non-LAT records are ignored. A completely missing internal generation is
    surfaced as a gap; no leading/trailing coverage is invented.
    """
    groups: dict[tuple[int, int, int], dict[str, object]] = {}
    reports: list[dict[str, object]] = []
    generations: dict[int, tuple[int, int, int]] = {}
    last_generation: int | None = None
    for line_number, line in enumerate(lines, 1):
        raw = line.rstrip("\r\n")
        if not raw.startswith("LAT,"):
            continue
        try:
            row = _parse(raw)
        except ValueError as exc:
            reports.append({"status": "ambiguous", "errors": [str(exc)],
                            "line_numbers": [line_number], "raw_rows": [raw]})
            continue
        key = row["g"], row["c"], row["s"]
        if key not in groups:
            report: dict[str, object] = {
                "generation": key[0], "channel": key[1], "stage": key[2],
                "parts": {}, "errors": [], "raw_rows": [], "line_numbers": [],
            }
            groups[key] = report
            reports.append(report)
            if key[0] in generations and generations[key[0]] != key:
                report["errors"].append("generation has conflicting channel/stage")
                groups[generations[key[0]]]["errors"].append(
                    "generation has conflicting channel/stage")
            elif last_generation is not None:
                advance = (key[0] - last_generation) & UINT32_MAX
                if advance == 0 or advance >= HALF_RANGE:
                    report["errors"].append("generation duplicated or reordered")
                elif advance != 1:
                    reports.insert(len(reports) - 1, {
                        "status": "missing", "reason": "generation_gap",
                        "after_generation": last_generation,
                        "before_generation": key[0], "missing_generations": advance - 1,
                        "raw_rows": [],
                    })
            generations[key[0]] = key
            last_generation = key[0]
        report = groups[key]
        if key[0] != last_generation:
            report["errors"].append("late part after a later report generation")
        report["raw_rows"].append(raw)
        report["line_numbers"].append(line_number)
        parts = report["parts"]
        if row["p"] in parts:
            report["errors"].append(f"duplicate part {row['p']}")
        elif parts and row["p"] < max(parts):
            report["errors"].append("parts reordered")
        parts.setdefault(row["p"], row)
    for report in groups.values():
        parts = report["parts"]
        report["errors"].extend(_validate(parts))
        report["missing_parts"] = sorted(set(range(7)) - parts.keys())
        report["status"] = ("ambiguous" if report["errors"] else
                            "missing" if report["missing_parts"] else "complete")
        report["hardware_to_service_available"] = False
        report["histogram_upper_us"] = list(HISTOGRAM_UPPER_US)
        report["parts"] = {str(p): value for p, value in sorted(parts.items())}
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Raw firmware text log containing LAT rows")
    args = parser.parse_args()
    with args.log.open(encoding="utf-8", errors="replace") as source:
        print(json.dumps(decode_reports(source), indent=2))


if __name__ == "__main__":
    main()
