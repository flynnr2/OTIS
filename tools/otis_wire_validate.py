#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "1"

HEADER_FIELDS = {
    "raw_events": [
        "record_type",
        "schema_version",
        "event_seq",
        "channel_id",
        "edge",
        "timestamp_ticks",
        "capture_domain",
        "flags",
    ],
    "count_observations": [
        "record_type",
        "schema_version",
        "count_seq",
        "channel_id",
        "gate_open_ticks",
        "gate_close_ticks",
        "gate_domain",
        "counted_edges",
        "source_edge",
        "source_domain",
        "flags",
    ],
    "health": [
        "record_type",
        "schema_version",
        "status_seq",
        "timestamp_ticks",
        "status_domain",
        "component",
        "status_key",
        "status_value",
        "severity",
        "flags",
    ],
}

FIELDS_BY_TAG = {
    "EVT": HEADER_FIELDS["raw_events"],
    "REF": HEADER_FIELDS["raw_events"],
    "CNT": HEADER_FIELDS["count_observations"],
    "STS": HEADER_FIELDS["health"],
}

NUMERIC_FIELDS = {
    "EVT": {"schema_version", "event_seq", "channel_id", "timestamp_ticks", "flags"},
    "REF": {"schema_version", "event_seq", "channel_id", "timestamp_ticks", "flags"},
    "CNT": {
        "schema_version",
        "count_seq",
        "channel_id",
        "gate_open_ticks",
        "gate_close_ticks",
        "counted_edges",
        "flags",
    },
    "STS": {"schema_version", "status_seq", "timestamp_ticks", "flags"},
}

BOOT_TAGS = {"BOOT", "BOOT_WARN", "BOOT_FATAL", "BOOTDIAG"}
KNOWN_TAGS = set(FIELDS_BY_TAG) | BOOT_TAGS
SEVERITIES = {"INFO", "WARN", "ERROR", "FATAL"}
EDGES = {"R", "F", "B"}

BOOT_REQUIRED_KEYS = {
    "BOOT": {
        "v",
        "boot_count",
        "phase",
        "reset_reason",
        "watchdog",
        "failure_count",
        "safe_mode",
    },
    "BOOT_WARN": {"v", "key"},
    "BOOT_FATAL": {"v", "fatal", "phase"},
    "BOOTDIAG": {"v", "wd_reason", "resets_reset", "resets_done", "chip_id"},
}

PROFILE_CAPTURE_REQUIREMENTS = {
    "generic": set(),
    "synthetic": {"EVT", "REF", "CNT"},
    "gpio_loopback": {"EVT"},
    "gpin0_observe": {"CNT"},
    "gps_pps": {"REF"},
    "tcxo_observe": {"CNT"},
}


@dataclass(frozen=True)
class Finding:
    severity: str
    line: int | None
    message: str


@dataclass
class WireRecord:
    tag: str
    line: int
    fields: dict[str, str]


@dataclass
class WireReport:
    source: str
    profile: str
    total_lines: int = 0
    header_counts: dict[str, int] = field(default_factory=lambda: {name: 0 for name in HEADER_FIELDS})
    tag_counts: dict[str, int] = field(default_factory=dict)
    boot_counts: dict[str, int] = field(default_factory=dict)
    sts_by_key: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    records: list[WireRecord] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, line: int | None, message: str) -> None:
        self.findings.append(Finding(severity, line, message))


def _is_int(text: str) -> bool:
    try:
        int(text, 10)
    except ValueError:
        return False
    return True


def _parse_csv_line(text: str) -> list[str] | None:
    try:
        return next(csv.reader([text]))
    except csv.Error:
        return None


def _parse_kv_boot(tag: str, row: list[str], line_no: int, report: WireReport) -> None:
    pairs: dict[str, str] = {}
    malformed: list[str] = []
    for cell in row[1:]:
        if "=" not in cell:
            malformed.append(cell)
            continue
        key, value = cell.split("=", 1)
        pairs[key] = value

    report.boot_counts[tag] = report.boot_counts.get(tag, 0) + 1
    missing = sorted(BOOT_REQUIRED_KEYS[tag] - set(pairs))
    if missing:
        report.add("error", line_no, f"{tag} missing required keys: {', '.join(missing)}")
    if malformed:
        report.add("error", line_no, f"{tag} has malformed key/value cells: {', '.join(malformed)}")
    if pairs.get("v") != SCHEMA_VERSION:
        report.add("error", line_no, f"{tag} version is {pairs.get('v')!r}, expected {SCHEMA_VERSION}")


def _parse_record(tag: str, row: list[str], line_no: int, report: WireReport) -> None:
    fields = FIELDS_BY_TAG[tag]
    if len(row) != len(fields):
        report.add("error", line_no, f"{tag} column count {len(row)} does not match {len(fields)}")
        return

    record = dict(zip(fields, row))
    report.tag_counts[tag] = report.tag_counts.get(tag, 0) + 1
    report.records.append(WireRecord(tag=tag, line=line_no, fields=record))

    if record["schema_version"] != SCHEMA_VERSION:
        report.add("error", line_no, f"{tag} schema_version is {record['schema_version']!r}, expected {SCHEMA_VERSION}")

    for name in NUMERIC_FIELDS[tag]:
        if not _is_int(record[name]):
            report.add("error", line_no, f"{tag}.{name} is not parseable as an integer: {record[name]!r}")

    if tag in {"EVT", "REF"} and record["edge"] not in EDGES:
        report.add("error", line_no, f"{tag}.edge is {record['edge']!r}, expected one of {sorted(EDGES)}")
    if tag == "CNT" and record["source_edge"] not in EDGES:
        report.add("error", line_no, f"CNT.source_edge is {record['source_edge']!r}, expected one of {sorted(EDGES)}")
    if tag == "CNT" and _is_int(record["gate_open_ticks"]) and _is_int(record["gate_close_ticks"]):
        if int(record["gate_close_ticks"]) < int(record["gate_open_ticks"]):
            report.add("error", line_no, "CNT gate_close_ticks is before gate_open_ticks")
    if tag == "STS":
        if record["severity"] not in SEVERITIES:
            report.add("error", line_no, f"STS.severity is {record['severity']!r}, expected one of {sorted(SEVERITIES)}")
        report.sts_by_key.setdefault((record["component"], record["status_key"]), []).append(record["status_value"])


def _consume_line(text: str, line_no: int, report: WireReport) -> None:
    clean = text.strip()
    if not clean:
        return
    row = _parse_csv_line(clean)
    if row is None or not row:
        report.add("error", line_no, "line is not parseable as CSV")
        return

    for header_name, fields in HEADER_FIELDS.items():
        if row == fields:
            report.header_counts[header_name] += 1
            return

    tag = row[0]
    if tag in FIELDS_BY_TAG:
        _parse_record(tag, row, line_no, report)
        return
    if tag in BOOT_TAGS:
        _parse_kv_boot(tag, row, line_no, report)
        return

    report.add("error", line_no, f"unknown record tag or header: {tag!r}")


def _monotonic_check(report: WireReport, tags: Iterable[str], field_name: str) -> None:
    previous: int | None = None
    previous_line: int | None = None
    for record in report.records:
        if record.tag not in tags:
            continue
        value = record.fields[field_name]
        if not _is_int(value):
            continue
        parsed = int(value, 10)
        if previous is not None and parsed < previous:
            report.add(
                "error",
                record.line,
                f"{field_name} decreases from {previous} on line {previous_line} to {parsed}",
            )
        previous = parsed
        previous_line = record.line


def _latest_int_status(report: WireReport, component: str, key: str) -> int | None:
    values = report.sts_by_key.get((component, key), [])
    for value in reversed(values):
        if _is_int(value):
            return int(value, 10)
    return None


def _post_validate(report: WireReport, require_headers: bool, max_boot_records: int) -> None:
    if report.boot_counts.get("BOOT", 0) == 0:
        report.add("error", None, "BOOT record is missing")
    if report.boot_counts.get("BOOTDIAG", 0) == 0:
        report.add("error", None, "BOOTDIAG reset diagnostic record is missing")
    if report.boot_counts.get("BOOT_FATAL", 0) > 0:
        report.add("error", None, "BOOT_FATAL record is present")
    if report.boot_counts.get("BOOT", 0) > max_boot_records:
        report.add("error", None, f"BOOT record count {report.boot_counts.get('BOOT', 0)} exceeds {max_boot_records}")

    if require_headers:
        for header_name, count in report.header_counts.items():
            if count == 0:
                report.add("error", None, f"{header_name} header/schema record is missing")
            elif count > 1:
                report.add("warning", None, f"{header_name} header appears {count} times")

    required_capture_tags = PROFILE_CAPTURE_REQUIREMENTS[report.profile]
    for tag in sorted(required_capture_tags):
        if report.tag_counts.get(tag, 0) == 0:
            report.add("error", None, f"{report.profile} profile requires at least one {tag} record")
    if sum(report.tag_counts.get(tag, 0) for tag in ("EVT", "REF", "CNT")) == 0:
        report.add("error", None, "no capture records are present")
    if report.tag_counts.get("STS", 0) == 0:
        report.add("error", None, "no status records are present")

    required_sts = {
        ("system", "boot"),
        ("protocol", "schema_version"),
        ("firmware", "name"),
        ("firmware", "version"),
        ("firmware", "git_commit"),
        ("system", "mode"),
        ("capture", "mode"),
        ("capture", "dropped_count"),
        ("capture", "error_flags"),
    }
    for component, key in sorted(required_sts):
        if (component, key) not in report.sts_by_key:
            report.add("error", None, f"required STS {component},{key} is missing")

    schema_values = set(report.sts_by_key.get(("protocol", "schema_version"), []))
    if schema_values and SCHEMA_VERSION not in schema_values:
        report.add("error", None, f"protocol,schema_version STS values do not include {SCHEMA_VERSION}: {sorted(schema_values)}")

    dropped_count = _latest_int_status(report, "capture", "dropped_count")
    if dropped_count is not None and dropped_count != 0:
        report.add("error", None, f"latest capture,dropped_count is {dropped_count}, expected 0")

    error_flags = _latest_int_status(report, "capture", "error_flags")
    if error_flags is not None and error_flags != 0:
        report.add("error", None, f"latest capture,error_flags is {error_flags}, expected 0")

    capture_modes = set(report.sts_by_key.get(("capture", "mode"), []))
    backends = set(report.sts_by_key.get(("build", "capture_backend"), []))
    pio_applicable = (
        "pio_fifo_cpu_timestamped" in capture_modes
        or "pio_fifo" in backends
        or any(component == "capture" and key.startswith("pio_fifo_") for component, key in report.sts_by_key)
    )
    if pio_applicable:
        for key in (
            "pio_fifo_drained_event_count",
            "pio_fifo_empty_count",
            "pio_fifo_overflow_drop_count",
            "pio_fifo_max_drain_batch",
        ):
            if ("capture", key) not in report.sts_by_key:
                report.add("error", None, f"PIO capture status field capture,{key} is missing")
        overflow_count = _latest_int_status(report, "capture", "pio_fifo_overflow_drop_count")
        if overflow_count is not None and overflow_count != 0:
            report.add("error", None, f"latest capture,pio_fifo_overflow_drop_count is {overflow_count}, expected 0")

    _monotonic_check(report, ("EVT", "REF"), "event_seq")
    _monotonic_check(report, ("CNT",), "count_seq")
    _monotonic_check(report, ("STS",), "status_seq")


def validate_text(source: str, text: str, profile: str, require_headers: bool, max_boot_records: int) -> WireReport:
    report = WireReport(source=source, profile=profile)
    for line_no, line in enumerate(text.splitlines(), start=1):
        report.total_lines += 1
        _consume_line(line, line_no, report)
    _post_validate(report, require_headers=require_headers, max_boot_records=max_boot_records)
    return report


def _summary_dict(report: WireReport) -> dict:
    errors = [finding for finding in report.findings if finding.severity == "error"]
    warnings = [finding for finding in report.findings if finding.severity == "warning"]
    return {
        "source": report.source,
        "profile": report.profile,
        "ok": not errors,
        "total_lines": report.total_lines,
        "headers": report.header_counts,
        "records": {tag: report.tag_counts.get(tag, 0) for tag in sorted(FIELDS_BY_TAG)},
        "boot_records": {tag: report.boot_counts.get(tag, 0) for tag in sorted(BOOT_TAGS)},
        "status_keys": [f"{component},{key}" for component, key in sorted(report.sts_by_key)],
        "errors": [
            {"line": finding.line, "message": finding.message}
            for finding in errors
        ],
        "warnings": [
            {"line": finding.line, "message": finding.message}
            for finding in warnings
        ],
    }


def _render_markdown(report: WireReport) -> str:
    summary = _summary_dict(report)
    lines = [
        f"# OTIS Wire Validation: {Path(report.source).name}",
        "",
        f"- profile: {report.profile}",
        f"- result: {'PASS' if summary['ok'] else 'FAIL'}",
        f"- total_lines: {report.total_lines}",
        "",
        "## Record Counts",
    ]
    for tag, count in summary["boot_records"].items():
        lines.append(f"- {tag}: {count}")
    for tag, count in summary["records"].items():
        lines.append(f"- {tag}: {count}")
    lines.extend(["", "## Headers"])
    for name, count in summary["headers"].items():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Findings"])
    if not report.findings:
        lines.append("- none")
    else:
        for finding in report.findings:
            location = f"line {finding.line}: " if finding.line is not None else ""
            lines.append(f"- {finding.severity.upper()}: {location}{finding.message}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate OTIS Arduino raw serial wire-format invariants.")
    parser.add_argument("raw", type=Path, help="Raw serial text file to validate.")
    parser.add_argument("--profile", choices=sorted(PROFILE_CAPTURE_REQUIREMENTS), default="generic")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Optional report output path.")
    parser.add_argument("--no-require-headers", action="store_true", help="Allow captures that start after the CSV headers.")
    parser.add_argument("--max-boot-records", type=int, default=1, help="Maximum BOOT records before treating the log as a reset loop.")
    args = parser.parse_args(argv)

    text = args.raw.read_text(encoding="utf-8", errors="replace")
    report = validate_text(
        source=str(args.raw),
        text=text,
        profile=args.profile,
        require_headers=not args.no_require_headers,
        max_boot_records=args.max_boot_records,
    )
    if args.format == "json":
        rendered = json.dumps(_summary_dict(report), indent=2, sort_keys=True) + "\n"
    else:
        rendered = _render_markdown(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    return 0 if _summary_dict(report)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
