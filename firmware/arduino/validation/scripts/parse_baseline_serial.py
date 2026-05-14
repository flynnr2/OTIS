#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.report_run import build_summary, render_report
from host.otis_tools.validate_run import validate_run


CONTRACT_TO_TAG = {
    "raw_events_v1": "raw_events",
    "count_observations_v1": "count_observations",
    "health_v1": "health",
}

MODE_TO_TEMPLATE = {
    "synthetic": "examples/h0_usb_synthetic",
    "gpio_loopback": "examples/h0_gpio_loopback",
    "gps_pps": "examples/h0_gps_pps",
    "tcxo_observe": "examples/h0_pps_tcxo_real",
}

MODE_TO_FIRMWARE_MODE = {
    "synthetic": "SW1_SYNTHETIC_USB",
    "gpio_loopback": "SW1_GPIO_LOOPBACK",
    "gps_pps": "SW1_GPS_PPS",
    "tcxo_observe": "SW1_TCXO_OBSERVE",
}

BASELINE_DIR = SCRIPT_PATH.parents[1] / "baselines"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _latest_status_int(health_rows: list[dict[str, str]], component: str, key: str) -> int | None:
    for row in reversed(health_rows):
        if row.get("component") == component and row.get("status_key") == key:
            try:
                return int(str(row.get("status_value", "")), 10)
            except ValueError:
                return None
    return None


def _status_values(health_rows: list[dict[str, str]], component: str, key: str) -> set[str]:
    return {
        str(row.get("status_value", ""))
        for row in health_rows
        if row.get("component") == component and row.get("status_key") == key
    }


def _has_header(raw_lines: list[str], header_prefix: str) -> bool:
    return any(line.strip().startswith(header_prefix) for line in raw_lines)


def _split_raw(raw_path: Path, mode: str, baseline_dir: Path) -> dict[str, Path]:
    csv_dir = baseline_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    file_by_contract = {
        contract: csv_dir / f"{mode}_{tag}.csv"
        for contract, tag in CONTRACT_TO_TAG.items()
    }

    parser_errors: list[str] = []
    with CsvRecordSplitter(
        file_by_contract,
        append=False,
        on_parser_error=parser_errors.append,
    ) as splitter:
        with raw_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                splitter.process_line(line)

    if parser_errors:
        (baseline_dir / "reports").mkdir(parents=True, exist_ok=True)
        error_path = baseline_dir / "reports" / f"{mode}_parser_errors.txt"
        error_path.write_text("\n".join(parser_errors) + "\n", encoding="utf-8")

    return file_by_contract


def _stage_run_dir(mode: str, file_by_contract: dict[str, Path], tmp_root: Path) -> Path:
    template_dir = REPO_ROOT / MODE_TO_TEMPLATE[mode]
    run_dir = tmp_root / f"{mode}_baseline_run"
    shutil.copytree(template_dir, run_dir)

    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = f"{mode}_R0_BASELINE"
    manifest["template"] = False
    manifest["created_utc"] = None
    manifest["expected_artifacts"] = [entry["path"] for entry in manifest["files"]]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for entry in manifest["files"]:
        source = file_by_contract[entry["contract"]]
        shutil.copyfile(source, run_dir / entry["path"])
    (run_dir / "COMPLETE").touch()
    return run_dir


def _mode_capture_check(mode: str, raw_rows: list[dict[str, str]], count_rows: list[dict[str, str]]) -> Check:
    if mode == "synthetic":
        have_evt = any(row.get("record_type") == "EVT" for row in raw_rows)
        have_ref = any(row.get("record_type") == "REF" for row in raw_rows)
        have_cnt = bool(count_rows)
        return Check(
            "expected synthetic capture records",
            have_evt and have_ref and have_cnt,
            f"EVT={have_evt}, REF={have_ref}, CNT={have_cnt}",
        )
    if mode == "gpio_loopback":
        count = sum(1 for row in raw_rows if row.get("record_type") == "EVT" and row.get("channel_id") == "0")
        return Check("expected GPIO loopback EVT records", count > 0, f"CH0 EVT rows={count}")
    if mode == "gps_pps":
        count = sum(1 for row in raw_rows if row.get("record_type") == "REF" and row.get("channel_id") == "1")
        return Check("expected GPS PPS REF records", count >= 2, f"CH1 REF rows={count}")

    count = sum(1 for row in count_rows if row.get("record_type") == "CNT" and row.get("channel_id") == "2")
    refs = sum(1 for row in raw_rows if row.get("record_type") == "REF" and row.get("channel_id") == "1")
    return Check("expected TCXO observe CNT records", count > 0, f"CH2 CNT rows={count}, CH1 REF rows={refs}")


def _baseline_checks(
    mode: str,
    raw_lines: list[str],
    raw_rows: list[dict[str, str]],
    count_rows: list[dict[str, str]],
    health_rows: list[dict[str, str]],
    validate_rc: int,
) -> list[Check]:
    boot_lines = [line for line in raw_lines if line.startswith("BOOT,v=1")]
    fatal_lines = [line for line in raw_lines if line.startswith("BOOT_FATAL")]
    dropped_count = _latest_status_int(health_rows, "capture", "dropped_count")
    pio_overflow = _latest_status_int(health_rows, "capture", "pio_fifo_overflow_drop_count")
    expected_mode = MODE_TO_FIRMWARE_MODE[mode]
    modes = _status_values(health_rows, "system", "mode")
    schema_versions = _status_values(health_rows, "protocol", "schema_version")

    checks = [
        Check("existing host validation passes", validate_rc == 0, f"validate_run exit={validate_rc}"),
        Check("BOOT record appears", bool(boot_lines), f"BOOT rows={len(boot_lines)}"),
        Check("no BOOT_FATAL record appears", not fatal_lines, f"BOOT_FATAL rows={len(fatal_lines)}"),
        Check("no unexpected reset loop", len(boot_lines) <= 1, f"BOOT rows={len(boot_lines)}"),
        Check(
            "raw event header appears",
            _has_header(raw_lines, "record_type,schema_version,event_seq,"),
            "EVT/REF header present",
        ),
        Check(
            "count observation header appears",
            _has_header(raw_lines, "record_type,schema_version,count_seq,"),
            "CNT header present",
        ),
        Check(
            "health header appears",
            _has_header(raw_lines, "record_type,schema_version,status_seq,"),
            "STS header present",
        ),
        Check("schema_version STS is present", "1" in schema_versions, f"schema_version values={sorted(schema_versions)}"),
        Check("expected firmware mode STS is present", expected_mode in modes, f"mode values={sorted(modes)}"),
        _mode_capture_check(mode, raw_rows, count_rows),
        Check(
            "no capture ring overflow",
            dropped_count == 0,
            "latest capture,dropped_count=" + ("missing" if dropped_count is None else str(dropped_count)),
        ),
    ]

    if pio_overflow is not None:
        checks.append(
            Check(
                "no PIO FIFO overflow",
                pio_overflow == 0,
                f"latest capture,pio_fifo_overflow_drop_count={pio_overflow}",
            )
        )

    return checks


def _render_validation_report(mode: str, report: str, checks: list[Check], artifacts: dict[str, str]) -> str:
    lines = [
        f"# OTIS Arduino R0 Baseline Validation: {mode}",
        "",
        "## Baseline Checks",
    ]
    for check in checks:
        state = "PASS" if check.ok else "FAIL"
        lines.append(f"- {state}: {check.name} ({check.detail})")

    lines.extend(["", "## Generated Artifacts"])
    for label, path in artifacts.items():
        lines.append(f"- {label}: `{path}`")

    lines.extend(["", "## Host Tool Report", "", report.rstrip(), ""])
    return "\n".join(lines)


def parse_baseline(mode: str, raw_path: Path, baseline_dir: Path) -> int:
    if mode not in MODE_TO_TEMPLATE:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODE_TO_TEMPLATE)}")
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)

    raw_dir = baseline_dir / "raw"
    reports_dir = baseline_dir / "reports"
    raw_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    copied_raw = raw_dir / f"{mode}_raw_serial.txt"
    if raw_path.resolve() != copied_raw.resolve():
        shutil.copyfile(raw_path, copied_raw)

    file_by_contract = _split_raw(copied_raw, mode, baseline_dir)
    raw_rows = _read_csv(file_by_contract["raw_events_v1"])
    count_rows = _read_csv(file_by_contract["count_observations_v1"])
    health_rows = _read_csv(file_by_contract["health_v1"])
    raw_lines = copied_raw.read_text(encoding="utf-8", errors="replace").splitlines()

    with tempfile.TemporaryDirectory(prefix="otis_r0_baseline_") as tmp:
        run_dir = _stage_run_dir(mode, file_by_contract, Path(tmp))
        validate_rc = validate_run(run_dir)
        summary = build_summary(run_dir)
        report = render_report(run_dir)

    checks = _baseline_checks(mode, raw_lines, raw_rows, count_rows, health_rows, validate_rc)
    artifacts = {
        "raw serial": str(copied_raw.relative_to(baseline_dir)),
        "raw events csv": str(file_by_contract["raw_events_v1"].relative_to(baseline_dir)),
        "count observations csv": str(file_by_contract["count_observations_v1"].relative_to(baseline_dir)),
        "health csv": str(file_by_contract["health_v1"].relative_to(baseline_dir)),
        "validation report": f"reports/{mode}_validation.md",
        "summary json": f"reports/{mode}_summary.json",
    }
    summary["baseline_checks"] = [
        {"name": check.name, "ok": check.ok, "detail": check.detail}
        for check in checks
    ]
    summary["baseline_artifacts"] = artifacts

    validation_path = reports_dir / f"{mode}_validation.md"
    summary_path = reports_dir / f"{mode}_summary.json"
    validation_path.write_text(_render_validation_report(mode, report, checks, artifacts), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for check in checks:
        state = "PASS" if check.ok else "FAIL"
        print(f"{state} {check.name}: {check.detail}")

    print(f"Wrote {validation_path}")
    print(f"Wrote {summary_path}")
    return 0 if all(check.ok for check in checks) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse and validate an OTIS Arduino R0 raw serial baseline.")
    parser.add_argument("--mode", required=True, choices=sorted(MODE_TO_TEMPLATE))
    parser.add_argument("--raw", required=True, type=Path, help="Raw serial text captured from arduino-cli monitor.")
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=BASELINE_DIR,
        help="Baseline output directory. Defaults to firmware/arduino/validation/baselines.",
    )
    args = parser.parse_args()
    raise SystemExit(parse_baseline(args.mode, args.raw, args.baseline_dir))


if __name__ == "__main__":
    main()
