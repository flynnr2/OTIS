from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json
import sys

from .capture_serial import capture_serial
from .contracts import CsvValidationContext, validate_csv
from .run_loader import load_manifest
from .validate_run import _validate_count_sanity, _validate_manifest


DEFAULT_TEMPLATE = Path("runs/h1_open_loop/dac_manual_sweep/_template")
DEFAULT_RUN_DIR = Path("runs/h1_open_loop/dac_manual_sweep/run_001")
DEFAULT_RUN_ID = "h1_dac_manual_001"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _has_status(rows: list[dict[str, str]], component: str, key: str, value: str | None = None) -> bool:
    for row in rows:
        if row["component"] == component and row["status_key"] == key:
            if value is None or row["status_value"] == value:
                return True
    return False


def _status_values(rows: list[dict[str, str]], component: str, key: str) -> list[str]:
    return [
        row["status_value"]
        for row in rows
        if row["component"] == component and row["status_key"] == key
    ]


def _hex_code(value: int) -> str:
    return f"0x{value:04X}"


def _verify_h1_telemetry(
    run_dir: Path,
    allow_dac_init_fail: bool,
    skip_initial_pps_intervals: int,
) -> tuple[int, int, int, list[int]]:
    sts = _read_csv(run_dir / "csv" / "sts.csv")
    cnt = _read_csv(run_dir / "csv" / "cnt.csv")
    ref = _read_csv(run_dir / "csv" / "ref.csv")

    required = [
        ("system", "mode", "H1_OCXO_OBSERVE_OPEN_LOOP"),
        ("system", "h1_open_loop", "true"),
        ("control", "gpsdo_steering", "not_implemented"),
        ("build", "enable_dac_ad5693r", "1"),
        ("dac", "enabled", "true"),
        ("capture", "tcxo_counter_backend", "rp2040_fc0_gpin0"),
    ]
    if not allow_dac_init_fail:
        required.extend(
            [
                ("dac", "initialized", "true"),
                ("dac", "init", "ok"),
            ]
        )

    missing = [item for item in required if not _has_status(sts, *item)]
    if missing:
        raise ValueError(f"missing required STS rows: {missing}")

    if not cnt:
        raise ValueError("no CNT rows found")
    if any(row["channel_id"] != "2" for row in cnt):
        raise ValueError("CNT rows are not on CH2")
    if any(int(row["counted_edges"]) == 0 and int(row["flags"]) == 0 for row in cnt):
        raise ValueError("zero counted_edges without diagnostic flag")
    if not any(row["source_domain"] == "h1_ocxo_open_loop" for row in cnt):
        raise ValueError("no H1 OCXO source_domain CNT rows found")

    skipped_pps_intervals: list[int] = []
    if len(ref) >= 2:
        ticks = [
            int(row["timestamp_ticks"])
            for row in ref
            if row["record_type"] == "REF" and row["channel_id"] == "1"
        ]
        intervals = [end - start for start, end in zip(ticks, ticks[1:])]
        skipped_pps_intervals = intervals[:skip_initial_pps_intervals]
        bad = [
            interval
            for interval in intervals[skip_initial_pps_intervals:]
            if not (12_800_000 <= interval <= 19_200_000)
        ]
        if bad:
            raise ValueError(f"PPS intervals outside 0.8-1.2 s at 16 MHz ticks: {bad[:5]}")

    return len(sts), len(cnt), len(ref), skipped_pps_intervals


def _verify_h1_commands(
    run_dir: Path,
    expected_min_code: int,
    expected_max_code: int,
    allow_dac_init_fail: bool,
) -> None:
    sts = _read_csv(run_dir / "csv" / "sts.csv")
    accepted = _status_values(sts, "dac", "accepted_code")
    rejected = _status_values(sts, "dac", "rejected_code")
    requested = _status_values(sts, "dac", "requested_code")
    set_status = _status_values(sts, "dac", "set")

    mid_code = (expected_min_code + expected_max_code) // 2
    checks = {
        "HELP response": bool(_status_values(sts, "command", "h1_help")),
        "DAC limits min": _hex_code(expected_min_code) in _status_values(sts, "dac", "min_code"),
        "DAC limits max": _hex_code(expected_max_code) in _status_values(sts, "dac", "max_code"),
        "FC0 query responded": bool(_status_values(sts, "fc0", "valid")),
    }
    if allow_dac_init_fail and "rejected_not_initialized" in set_status:
        checks.update(
            {
                "DAC SET/MID requested": _hex_code(mid_code) in requested,
                "DAC ZERO requested": _hex_code(expected_min_code) in requested,
                "low clamp request observed": "0x0000" in requested,
                "high clamp request observed": "0xFFFF" in requested,
                "not-initialized rejection": "rejected_not_initialized" in set_status,
            }
        )
    else:
        checks.update(
            {
                "DAC SET/MID accepted": _hex_code(mid_code) in accepted,
                "DAC ZERO accepted": _hex_code(expected_min_code) in accepted,
                "low clamp rejected": "0x0000" in rejected,
                "high clamp rejected": "0xFFFF" in rejected,
                "outside clamps status": "rejected_outside_clamps" in set_status,
            }
        )

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError(f"failed command checks: {failed}")


def _validate_h1_structure(run_dir: Path) -> int:
    try:
        manifest = load_manifest(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {run_dir}: {exc}", file=sys.stderr)
        return 1

    failures = _validate_manifest(run_dir, manifest)
    for file_entry in manifest.files:
        contract = file_entry.get("contract")
        rel_path = file_entry.get("path")
        if not contract or not rel_path:
            failures.append("manifest file entry missing contract or path")
            continue
        path = run_dir / rel_path
        context = CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            template=manifest.is_template,
        )
        result = validate_csv(path, context)
        if result.ok:
            print(f"OK {rel_path}: {result.row_count} rows")
        else:
            failures.extend(f"{rel_path}: {error}" for error in result.errors)
        for warning in result.warnings:
            print(f"WARN {rel_path}: {warning}", file=sys.stderr)

    count_rows = _read_csv(run_dir / "csv" / "cnt.csv")
    failures.extend(_validate_count_sanity(count_rows, manifest, manifest.is_template))
    for failure in failures:
        print(f"ERROR {failure}", file=sys.stderr)
    return 1 if failures else 0


class _StdinSwap:
    def __init__(self, replacement) -> None:
        self.replacement = replacement
        self.original = None

    def __enter__(self) -> None:
        self.original = sys.stdin
        sys.stdin = self.replacement

    def __exit__(self, exc_type, exc, tb) -> None:
        sys.stdin = self.original


def verify_h1_manual_log(
    raw_log: Path,
    run_dir: Path,
    run_id: str,
    template: Path,
    expected_min_code: int,
    expected_max_code: int,
    allow_dac_init_fail: bool,
    skip_initial_pps_intervals: int,
) -> int:
    if not raw_log.exists():
        print(f"ERROR raw log does not exist: {raw_log}", file=sys.stderr)
        return 1
    if run_dir.exists():
        print(f"ERROR run directory already exists: {run_dir}", file=sys.stderr)
        return 1

    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        with _StdinSwap(handle):
            capture_serial(run_dir, template, run_id)

    structural_status = _validate_h1_structure(run_dir)
    if structural_status != 0:
        return structural_status

    try:
        sts_count, cnt_count, ref_count, skipped_pps_intervals = _verify_h1_telemetry(
            run_dir,
            allow_dac_init_fail,
            skip_initial_pps_intervals,
        )
        _verify_h1_commands(run_dir, expected_min_code, expected_max_code, allow_dac_init_fail)
    except ValueError as exc:
        print(f"ERROR H1 verification: {exc}", file=sys.stderr)
        return 1

    print(f"OK H1 telemetry: {sts_count} STS rows, {cnt_count} CNT rows, {ref_count} REF rows")
    if skipped_pps_intervals:
        print(f"INFO skipped initial PPS intervals ticks: {skipped_pps_intervals}")
    print("OK H1 manual command checks")
    print(f"OK H1 run directory: {run_dir}")
    return 0


def _parse_code(text: str) -> int:
    value = int(text, 0)
    if not (0 <= value <= 0xFFFF):
        raise argparse.ArgumentTypeError(f"{text!r} is not a 16-bit code")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify an H1 open-loop manual DAC raw serial log.")
    parser.add_argument("raw_log", type=Path, help="Raw OTIS serial logfile to split and verify.")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--expected-min-code", type=_parse_code, default=0x7000)
    parser.add_argument("--expected-max-code", type=_parse_code, default=0x9000)
    parser.add_argument(
        "--allow-dac-init-fail",
        action="store_true",
        help="Allow runs captured intentionally without the AD5693R present.",
    )
    parser.add_argument(
        "--skip-initial-pps-intervals",
        type=int,
        default=1,
        help="Ignore this many initial PPS intervals before cadence validation; H1 defaults to 1.",
    )
    args = parser.parse_args()

    raise SystemExit(
        verify_h1_manual_log(
            args.raw_log,
            args.run_dir,
            args.run_id,
            args.template,
            args.expected_min_code,
            args.expected_max_code,
            args.allow_dac_init_fail,
            args.skip_initial_pps_intervals,
        )
    )


if __name__ == "__main__":
    main()
