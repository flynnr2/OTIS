from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import argparse
import csv
import json
import math
import sys

from .contracts import CsvValidationContext, validate_csv
from .run_loader import RunManifest, load_manifest
from .validate_run import _validate_count_sanity, _validate_manifest, _validate_pps_cadence


RAW_CONTRACT = "raw_events_v1"
COUNT_CONTRACT = "count_observations_v1"
HEALTH_CONTRACT = "health_v1"


@dataclass(frozen=True)
class CsvReadResult:
    path: Path
    contract: str
    fieldnames: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    malformed_rows: tuple[str, ...]
    exists: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _read_csv(path: Path, contract: str) -> CsvReadResult:
    if not path.exists():
        return CsvReadResult(path=path, contract=contract, fieldnames=(), rows=(), malformed_rows=(), exists=False)

    malformed_rows: list[str] = []
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        for row_number, row in enumerate(reader, start=1):
            if None in row:
                malformed_rows.append(f"{path.name}: row {row_number} has too many columns")
            rows.append({str(key): value for key, value in row.items() if key is not None})

    return CsvReadResult(
        path=path,
        contract=contract,
        fieldnames=fieldnames,
        rows=tuple(rows),
        malformed_rows=tuple(malformed_rows),
        exists=True,
    )


def _parse_int(value: str | None) -> int | None:
    try:
        return int(str(value), 10)
    except (TypeError, ValueError):
        return None


def _parse_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _fmt_number(value: float | int | None, digits: int = 6) -> str:
    if value is None:
        return "not computed"
    if isinstance(value, int):
        return str(value)
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        return f"{value:.3f}"
    return f"{value:.{digits}g}"


def _fmt_ppm(value: float | None) -> str:
    if value is None:
        return "not computed"
    return f"{value:.3f} ppm"


def _ticks_to_seconds(ticks: int, domain: str, nominal_hz_by_domain: dict[str, float]) -> float | None:
    nominal_hz = nominal_hz_by_domain.get(domain)
    if not nominal_hz:
        return None
    return ticks / nominal_hz


def _domain_hz(manifest: RunManifest) -> dict[str, float]:
    domains: dict[str, float] = {}
    for domain in manifest.data.get("domains", []):
        if not isinstance(domain, dict) or "name" not in domain:
            continue
        nominal_hz = _parse_float(domain.get("nominal_hz"))
        if nominal_hz:
            domains[str(domain["name"])] = nominal_hz
    return domains


def _validation_findings(
    manifest: RunManifest,
    reads: list[CsvReadResult],
    nominal_hz_by_domain: dict[str, float],
) -> list[str]:
    findings: list[str] = _validate_manifest(manifest.root, manifest)
    for read in reads:
        context = CsvValidationContext(
            contract=read.contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            template=manifest.is_template,
        )
        result = validate_csv(read.path, context)
        findings.extend(f"{read.path.relative_to(manifest.root)}: {error}" for error in result.errors)
    raw_rows = [row for read in reads if read.contract == RAW_CONTRACT for row in read.rows]
    count_rows = [row for read in reads if read.contract == COUNT_CONTRACT for row in read.rows]
    findings.extend(_validate_pps_cadence(raw_rows, nominal_hz_by_domain, manifest.is_template))
    findings.extend(_validate_count_sanity(count_rows, manifest.is_template))
    return findings


def _monotonic(values: list[int], strict: bool = False) -> bool:
    if len(values) < 2:
        return True
    if strict:
        return all(current > previous for previous, current in zip(values, values[1:]))
    return all(current >= previous for previous, current in zip(values, values[1:]))


def _sequence_gaps(values: list[int]) -> list[int]:
    if len(values) < 2:
        return []
    return [current - previous for previous, current in zip(values, values[1:]) if current - previous != 1]


def _interval_stats(values: list[int]) -> dict[str, float | int | None]:
    if len(values) < 2:
        return {"count": 0, "min": None, "max": None, "mean": None, "stddev": None}
    intervals = [float(current - previous) for previous, current in zip(values, values[1:])]
    return {
        "count": len(intervals),
        "min": min(intervals),
        "max": max(intervals),
        "mean": _mean(intervals),
        "stddev": _stddev(intervals),
    }


def _summarize_raw(reads: list[CsvReadResult], nominal_hz_by_domain: dict[str, float]) -> tuple[dict, list[str]]:
    rows = [row for read in reads for row in read.rows]
    anomalies: list[str] = []
    timestamps = [_parse_int(row.get("timestamp_ticks")) for row in rows]
    timestamps_int = [value for value in timestamps if value is not None]
    event_seq = [_parse_int(row.get("event_seq")) for row in rows]
    event_seq_int = [value for value in event_seq if value is not None]

    if len(timestamps_int) != len(rows):
        anomalies.append("raw_events_v1: one or more timestamp_ticks values are missing or non-integer")
    if not _monotonic(timestamps_int):
        anomalies.append("raw_events_v1: timestamp_ticks are not monotonic in manifest file order")
    if not _monotonic(event_seq_int, strict=True):
        anomalies.append("raw_events_v1: event_seq is not strictly increasing in manifest file order")

    by_channel_type: dict[str, int] = dict(
        sorted(Counter(f"CH{row.get('channel_id', '?')} {row.get('record_type', '?')}" for row in rows).items())
    )
    duplicate_timestamps = sum(count - 1 for count in Counter(timestamps_int).values() if count > 1)

    interval_by_channel: dict[str, dict] = {}
    ticks_by_channel: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        timestamp = _parse_int(row.get("timestamp_ticks"))
        if timestamp is not None:
            ticks_by_channel[str(row.get("channel_id", "?"))].append(timestamp)
    for channel, ticks in sorted(ticks_by_channel.items()):
        interval_by_channel[channel] = _interval_stats(ticks)

    duration_ticks = None
    duration_seconds = None
    domain_note = "not computed: no rows"
    if timestamps_int:
        duration_ticks = max(timestamps_int) - min(timestamps_int)
        domains = {str(row.get("capture_domain", "")) for row in rows if row.get("capture_domain")}
        if len(domains) == 1:
            domain = next(iter(domains))
            duration_seconds = _ticks_to_seconds(duration_ticks, domain, nominal_hz_by_domain)
            domain_note = f"using {domain} nominal_hz" if duration_seconds is not None else f"not computed: no nominal_hz for {domain}"
        else:
            domain_note = f"not computed: mixed or ambiguous capture_domain values {sorted(domains)}"

    return (
        {
            "row_count": len(rows),
            "record_type_counts": dict(sorted(Counter(row.get("record_type", "") for row in rows).items())),
            "channel_type_counts": by_channel_type,
            "first_timestamp_ticks": min(timestamps_int) if timestamps_int else None,
            "last_timestamp_ticks": max(timestamps_int) if timestamps_int else None,
            "duration_ticks": duration_ticks,
            "duration_seconds": duration_seconds,
            "duration_note": domain_note,
            "timestamp_monotonic": _monotonic(timestamps_int),
            "duplicate_timestamp_count": duplicate_timestamps,
            "event_seq_monotonic": _monotonic(event_seq_int, strict=True),
            "event_seq_gap_count": len(_sequence_gaps(event_seq_int)),
            "intervals_by_channel_ticks": interval_by_channel,
        },
        anomalies,
    )


def _summarize_reference(reads: list[CsvReadResult], nominal_hz_by_domain: dict[str, float]) -> tuple[dict, list[str]]:
    rows = [row for read in reads for row in read.rows if row.get("record_type") == "REF" and row.get("edge") == "R"]
    anomalies: list[str] = []
    by_domain: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        timestamp = _parse_int(row.get("timestamp_ticks"))
        if timestamp is not None:
            by_domain[str(row.get("capture_domain", ""))].append(timestamp)

    domains: dict[str, dict] = {}
    for domain, ticks in sorted(by_domain.items()):
        intervals = [end - start for start, end in zip(ticks, ticks[1:])]
        seconds = [_ticks_to_seconds(interval, domain, nominal_hz_by_domain) for interval in intervals]
        seconds_float = [value for value in seconds if value is not None]
        mean_seconds = _mean(seconds_float)
        ppm_error = ((mean_seconds - 1.0) * 1_000_000) if mean_seconds is not None else None
        suspicious = 0
        for interval_seconds in seconds_float:
            if not (0.8 <= interval_seconds <= 1.2):
                suspicious += 1
        if suspicious:
            anomalies.append(f"raw_events_v1: {suspicious} PPS/reference interval(s) in {domain} outside 0.8-1.2 s")
        domains[domain] = {
            "edge_count": len(ticks),
            "interval_count": len(intervals),
            "mean_interval_ticks": _mean([float(value) for value in intervals]),
            "min_interval_ticks": min(intervals) if intervals else None,
            "max_interval_ticks": max(intervals) if intervals else None,
            "stddev_interval_ticks": _stddev([float(value) for value in intervals]),
            "mean_interval_seconds": mean_seconds,
            "min_interval_seconds": min(seconds_float) if seconds_float else None,
            "max_interval_seconds": max(seconds_float) if seconds_float else None,
            "stddev_interval_seconds": _stddev(seconds_float),
            "ppm_error_vs_1s": ppm_error,
            "timing_note": "using manifest nominal_hz" if seconds_float else "not computed: units ambiguous or not enough edges",
        }
    return {"edge_count": len(rows), "domains": domains}, anomalies


def _summarize_counts(reads: list[CsvReadResult], nominal_hz_by_domain: dict[str, float]) -> tuple[dict, list[str]]:
    rows = [row for read in reads for row in read.rows]
    anomalies: list[str] = []
    frequencies: list[float] = []
    windows_seconds: list[float] = []
    source_domains = sorted({str(row.get("source_domain", "")) for row in rows if row.get("source_domain")})

    for index, row in enumerate(rows, start=1):
        gate_open = _parse_int(row.get("gate_open_ticks"))
        gate_close = _parse_int(row.get("gate_close_ticks"))
        counted_edges = _parse_int(row.get("counted_edges"))
        gate_domain = str(row.get("gate_domain", ""))
        if gate_open is None or gate_close is None or counted_edges is None:
            anomalies.append(f"count_observations_v1: row {index} has missing or non-integer count/window fields")
            continue
        window_ticks = gate_close - gate_open
        if window_ticks <= 0:
            anomalies.append(f"count_observations_v1: row {index} has non-positive gate window")
            continue
        window_seconds = _ticks_to_seconds(window_ticks, gate_domain, nominal_hz_by_domain)
        if window_seconds is None:
            continue
        windows_seconds.append(window_seconds)
        frequencies.append(counted_edges / window_seconds)

    nominal_source_hz = None
    if len(source_domains) == 1:
        nominal_source_hz = nominal_hz_by_domain.get(source_domains[0])
    mean_frequency = _mean(frequencies)
    ppm_error = None
    if mean_frequency is not None and nominal_source_hz:
        ppm_error = ((mean_frequency - nominal_source_hz) / nominal_source_hz) * 1_000_000

    return (
        {
            "row_count": len(rows),
            "mean_observed_frequency_hz": mean_frequency,
            "min_observed_frequency_hz": min(frequencies) if frequencies else None,
            "max_observed_frequency_hz": max(frequencies) if frequencies else None,
            "stddev_observed_frequency_hz": _stddev(frequencies),
            "ppm_error_vs_nominal": ppm_error,
            "mean_window_seconds": _mean(windows_seconds),
            "min_window_seconds": min(windows_seconds) if windows_seconds else None,
            "max_window_seconds": max(windows_seconds) if windows_seconds else None,
            "frequency_note": (
                f"nominal source frequency from {source_domains[0]}"
                if nominal_source_hz
                else f"source nominal not computed: source_domain values {source_domains} not declared with nominal_hz"
            ),
        },
        anomalies,
    )


def _summarize_health(reads: list[CsvReadResult]) -> tuple[dict, list[str]]:
    rows = [row for read in reads for row in read.rows]
    anomalies: list[str] = []
    severity_counts = dict(sorted(Counter(row.get("severity", "") for row in rows).items()))
    status_counts = dict(sorted(Counter(row.get("status_key", "") for row in rows).items()))
    status_values: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        value = _parse_int(row.get("status_value"))
        if value is not None:
            status_values[str(row.get("status_key", ""))].append(value)

    counter_summaries: dict[str, dict[str, int]] = {}
    interesting = ("drop", "malformed", "truncated", "error", "ring", "water", "reset", "boot")
    for key, values in sorted(status_values.items()):
        if any(token in key.lower() for token in interesting):
            counter_summaries[key] = {"first": values[0], "last": values[-1], "max": max(values), "delta": values[-1] - values[0]}
            if any(token in key.lower() for token in ("drop", "malformed", "truncated", "error")) and values[-1] > values[0]:
                anomalies.append(f"health_v1: {key} increased by {values[-1] - values[0]}")

    return (
        {
            "row_count": len(rows),
            "severity_counts": severity_counts,
            "status_key_counts": status_counts,
            "counter_summaries": counter_summaries,
        },
        anomalies,
    )


def build_summary(run_dir: Path) -> dict:
    manifest = load_manifest(run_dir)
    nominal_hz_by_domain = _domain_hz(manifest)
    manifest_files = []
    reads: list[CsvReadResult] = []
    for entry in manifest.files:
        rel_path = str(entry.get("path", ""))
        contract = str(entry.get("contract", ""))
        path = run_dir / rel_path
        read = _read_csv(path, contract)
        reads.append(read)
        manifest_files.append(
            {
                "path": rel_path,
                "contract": contract,
                "present": read.exists,
                "row_count": read.row_count,
                "headers": list(read.fieldnames),
            }
        )

    reads_by_contract: dict[str, list[CsvReadResult]] = defaultdict(list)
    for read in reads:
        reads_by_contract[read.contract].append(read)

    validation_findings = _validation_findings(manifest, reads, nominal_hz_by_domain)
    malformed = [message for read in reads for message in read.malformed_rows]
    raw_summary, raw_anomalies = _summarize_raw(reads_by_contract.get(RAW_CONTRACT, []), nominal_hz_by_domain)
    ref_summary, ref_anomalies = _summarize_reference(reads_by_contract.get(RAW_CONTRACT, []), nominal_hz_by_domain)
    count_summary, count_anomalies = _summarize_counts(reads_by_contract.get(COUNT_CONTRACT, []), nominal_hz_by_domain)
    health_summary, health_anomalies = _summarize_health(reads_by_contract.get(HEALTH_CONTRACT, []))
    anomalies = malformed + raw_anomalies + ref_anomalies + count_anomalies + health_anomalies

    missing_files = [file_entry["path"] for file_entry in manifest_files if not file_entry["present"]]
    useful = not missing_files and not validation_findings and (raw_summary["row_count"] > 0 or manifest.is_template)
    return {
        "run_identity": {
            "run_id": manifest.run_id,
            "bringup_mode": manifest.bringup_mode,
            "template": manifest.is_template,
            "profile": manifest.data.get("profile"),
            "started_at_utc": manifest.data.get("started_at_utc") or manifest.data.get("created_utc"),
            "ended_at_utc": manifest.data.get("ended_at_utc"),
            "domains": manifest.data.get("domains", []),
            "channels": manifest.data.get("channels", []),
        },
        "artifact_inventory": manifest_files,
        "row_counts": {
            contract: sum(read.row_count for read in contract_reads)
            for contract, contract_reads in sorted(reads_by_contract.items())
        },
        "raw_event_summary": raw_summary,
        "reference_pps_summary": ref_summary,
        "count_observation_summary": count_summary,
        "health_status_summary": health_summary,
        "validation_findings": validation_findings,
        "anomalies": anomalies,
        "development_usefulness": {
            "keep_as_fixture": useful,
            "reason": (
                "template run with valid listed artifacts"
                if useful and manifest.is_template
                else "valid run with parseable listed artifacts"
                if useful
                else "not fixture-ready: resolve missing files, validation findings, or missing raw rows"
            ),
        },
    }


def _append_key_values(lines: list[str], values: dict[str, object]) -> None:
    for key, value in values.items():
        lines.append(f"- {key}: {value if value not in (None, '') else 'not present'}")


def render_report(run_dir: Path) -> str:
    summary = build_summary(run_dir)
    identity = summary["run_identity"]
    lines: list[str] = ["# OTIS Run Report", "", "## Run Identity"]
    _append_key_values(
        lines,
        {
            "run_id": identity["run_id"],
            "bringup_mode": identity["bringup_mode"],
            "template": identity["template"],
            "profile": identity["profile"],
            "started_at_utc": identity["started_at_utc"],
            "ended_at_utc": identity["ended_at_utc"],
        },
    )

    lines.extend(["", "## Artifact Inventory"])
    for file_entry in summary["artifact_inventory"]:
        state = "present" if file_entry["present"] else "missing"
        headers = ", ".join(file_entry["headers"]) if file_entry["headers"] else "not present"
        lines.append(f"- {file_entry['path']} ({file_entry['contract']}): {state}, {file_entry['row_count']} rows, headers: {headers}")

    lines.extend(["", "## Row Counts"])
    if summary["row_counts"]:
        for contract, count in summary["row_counts"].items():
            lines.append(f"- {contract}: {count}")
    else:
        lines.append("- not present")

    raw = summary["raw_event_summary"]
    lines.extend(["", "## Raw Event Summary"])
    if raw["row_count"]:
        _append_key_values(
            lines,
            {
                "row_count": raw["row_count"],
                "record_type_counts": raw["record_type_counts"],
                "channel_type_counts": raw["channel_type_counts"],
                "first_timestamp_ticks": raw["first_timestamp_ticks"],
                "last_timestamp_ticks": raw["last_timestamp_ticks"],
                "duration_ticks": raw["duration_ticks"],
                "duration_seconds": _fmt_number(raw["duration_seconds"]),
                "duration_note": raw["duration_note"],
                "timestamp_monotonic": raw["timestamp_monotonic"],
                "duplicate_timestamp_count": raw["duplicate_timestamp_count"],
                "event_seq_monotonic": raw["event_seq_monotonic"],
                "event_seq_gap_count": raw["event_seq_gap_count"],
            },
        )
        for channel, stats in raw["intervals_by_channel_ticks"].items():
            lines.append(
                f"- CH{channel} intervals ticks: count={stats['count']}, min={_fmt_number(stats['min'])}, "
                f"max={_fmt_number(stats['max'])}, mean={_fmt_number(stats['mean'])}, stddev={_fmt_number(stats['stddev'])}"
            )
    else:
        lines.append("- not present")

    ref = summary["reference_pps_summary"]
    lines.extend(["", "## Reference / PPS Summary"])
    if ref["edge_count"]:
        lines.append(f"- reference edge count: {ref['edge_count']}")
        for domain, stats in ref["domains"].items():
            lines.append(
                f"- {domain}: intervals={stats['interval_count']}, mean={_fmt_number(stats['mean_interval_ticks'])} ticks / "
                f"{_fmt_number(stats['mean_interval_seconds'])} s, min={_fmt_number(stats['min_interval_seconds'])} s, "
                f"max={_fmt_number(stats['max_interval_seconds'])} s, stddev={_fmt_number(stats['stddev_interval_seconds'])} s, "
                f"ppm_error_vs_1s={_fmt_ppm(stats['ppm_error_vs_1s'])}; {stats['timing_note']}"
            )
    else:
        lines.append("- not present")

    count = summary["count_observation_summary"]
    lines.extend(["", "## Count Observation Summary"])
    if count["row_count"]:
        _append_key_values(
            lines,
            {
                "row_count": count["row_count"],
                "mean_observed_frequency_hz": _fmt_number(count["mean_observed_frequency_hz"]),
                "min_observed_frequency_hz": _fmt_number(count["min_observed_frequency_hz"]),
                "max_observed_frequency_hz": _fmt_number(count["max_observed_frequency_hz"]),
                "stddev_observed_frequency_hz": _fmt_number(count["stddev_observed_frequency_hz"]),
                "ppm_error_vs_nominal": _fmt_ppm(count["ppm_error_vs_nominal"]),
                "mean_window_seconds": _fmt_number(count["mean_window_seconds"]),
                "min_window_seconds": _fmt_number(count["min_window_seconds"]),
                "max_window_seconds": _fmt_number(count["max_window_seconds"]),
                "frequency_note": count["frequency_note"],
            },
        )
    else:
        lines.append("- not present")

    health = summary["health_status_summary"]
    lines.extend(["", "## Health / Status Summary"])
    if health["row_count"]:
        _append_key_values(
            lines,
            {
                "row_count": health["row_count"],
                "severity_counts": health["severity_counts"],
                "status_key_counts": health["status_key_counts"],
                "counter_summaries": health["counter_summaries"] or "not present",
            },
        )
    else:
        lines.append("- not present")

    lines.extend(["", "## Validation Findings"])
    if summary["validation_findings"]:
        lines.extend(f"- {finding}" for finding in summary["validation_findings"])
    else:
        lines.append("- none")

    lines.extend(["", "## Anomalies"])
    if summary["anomalies"]:
        lines.extend(f"- {anomaly}" for anomaly in summary["anomalies"])
    else:
        lines.append("- none")

    usefulness = summary["development_usefulness"]
    lines.extend(["", "## Development Usefulness"])
    lines.append(f"- keep_as_fixture: {usefulness['keep_as_fixture']}")
    lines.append(f"- reason: {usefulness['reason']}")

    lines.extend(
        [
            "",
            "## Reproduction Commands",
            f"- `python3 -m host.otis_tools.validate_run {run_dir}`",
            f"- `python3 -m host.otis_tools.report_run {run_dir}`",
            f"- `python3 -m host.otis_tools.report_run {run_dir} --json {run_dir / 'reports' / 'summary.json'}`",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Markdown OTIS run report.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, help="Write Markdown report to this path instead of stdout.")
    parser.add_argument("--json", type=Path, help="Write machine-readable JSON summary to this path.")
    args = parser.parse_args()

    try:
        report = render_report(args.run_dir)
        if args.json:
            summary = build_summary(args.run_dir)
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
        else:
            print(report, end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR report_run: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
