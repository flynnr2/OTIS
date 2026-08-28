"""Deterministically classify the non-actuating D9/D6 readiness strata.

This module deliberately has no serial, flashing, or command capability.  It
reads retained capture evidence only.  In particular, D6 is compared with D8
only as D14-gated cumulative count evidence: it never supplies D9 waveform,
measurement-health, or control truth.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .time_domains import forward_progress


TOOL_ID = "otis_d9_d6_readiness_analyze_v1"
ANALYSIS_PATH = Path("reports/d9_d6_readiness_analysis_v1.json")
REPORT_PATH = Path("reports/D9_D6_READINESS.md")
SEAL_PATH = Path("reports/d9_d6_readiness_seal_v1.json")

CONTRACT_ID = "OTIS_D9_D6_READINESS_CONTRACT_V1"
UINT32_MASK = (1 << 32) - 1
MAX_EXPECTED_INTERVAL_COUNT = 12_000_000
PROFILE_BY_STRATUM = {
    "baseline": "d9_disabled_no_control_baseline",
    "output": "d9_forwarded_output_no_control",
    "monitor": "d9_d6_forwarded_output_no_control",
}
_REQUIRED_ENABLED_STATUS = {
    "contract_id": CONTRACT_ID,
    "source": "D8_GPIO20_GPIN0",
    "destination": "D9_GPIO21_GPOUT0",
    "integer_divider": "1",
    "fractional_divider": "0",
    "applied_auxsrc": "1",
    "applied_integer_divider": "1",
    "applied_fractional_divider": "0",
    "source_gpio_function": "8",
    "destination_gpio_function": "8",
    "inversion": "0",
    "drive_strength_ma": "2",
    "slew_rate": "slow",
    "nominal_frequency_hz": "10000000",
    "readback_valid": "true",
    "state": "configured_10mhz_forwarded_unqualified",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _manifest_file(manifest: Mapping[str, Any], contract: str) -> str | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    for item in files:
        if isinstance(item, Mapping) and item.get("contract") == contract:
            path = item.get("path")
            if isinstance(path, str):
                return path
    return None


def _rows_for_contract(run_dir: Path, manifest: Mapping[str, Any], contract: str, default: str) -> list[dict[str, str]]:
    relative = _manifest_file(manifest, contract) or default
    return _read_csv(run_dir / relative)


def _latest_status(rows: Iterable[Mapping[str, str]], component: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    result: dict[str, str] = {}
    history: list[dict[str, str]] = []
    for row in rows:
        if row.get("component") != component:
            continue
        key = row.get("status_key", "")
        value = row.get("status_value", "")
        if key:
            result[key] = value
            history.append({"key": key, "value": value, "timestamp_ticks": row.get("timestamp_ticks", "")})
    return result, history


def _as_uint(value: str, field: str, errors: list[str]) -> int | None:
    try:
        number = int(value, 10)
    except (TypeError, ValueError):
        errors.append(f"{field} is not an integer: {value!r}")
        return None
    if number < 0:
        errors.append(f"{field} is negative: {number}")
        return None
    return number


def _bind_manifest_identity(manifest: Mapping[str, Any], contract: Mapping[str, Any], stratum: str, errors: list[str]) -> dict[str, Any]:
    binding = manifest.get("d9_d6_readiness")
    if not isinstance(binding, Mapping):
        errors.append("run manifest lacks d9_d6_readiness identity binding")
        return {}
    nested = binding.get("contract")
    contract_binding = nested if isinstance(nested, Mapping) else binding
    expected_sha = contract.get("contract_semantic_sha256")
    if contract_binding.get("contract_id") != CONTRACT_ID:
        errors.append("manifest D9/D6 contract_id mismatch")
    if contract_binding.get("contract_semantic_sha256") != expected_sha:
        errors.append("manifest D9/D6 contract semantic SHA-256 mismatch")
    if binding.get("profile") != PROFILE_BY_STRATUM[stratum]:
        errors.append("manifest D9/D6 profile does not match requested stratum")
    if binding.get("physical_authority") is not False:
        errors.append("D9/D6 readiness manifest physical_authority must be false")
    return dict(binding)


def _snapshot_intervals(rows: list[dict[str, str]], *, label: str, errors: list[str]) -> list[dict[str, int]]:
    """Reconstruct down-counter intervals without making cross-session joins."""
    parsed: list[dict[str, int]] = []
    for row_number, row in enumerate(rows, start=2):
        required = ("session", "snapshot_sequence", "cumulative_down_counter", "reference_sequence", "reference_timestamp_ticks", "status")
        numeric: dict[str, int] = {}
        for name in required:
            value = _as_uint(row.get(name, ""), f"{label} row {row_number} {name}", errors)
            if value is None:
                break
            numeric[name] = value
        if len(numeric) != len(required):
            continue
        if numeric["cumulative_down_counter"] > UINT32_MASK:
            errors.append(f"{label} row {row_number} counter exceeds u32")
            continue
        parsed.append(numeric)

    intervals: list[dict[str, int]] = []
    previous_by_session: dict[int, dict[str, int]] = {}
    for current in parsed:
        previous = previous_by_session.get(current["session"])
        if previous is not None:
            continuous = True
            if current["snapshot_sequence"] != ((previous["snapshot_sequence"] + 1) & UINT32_MASK):
                errors.append(f"{label} session {current['session']} snapshot sequence discontinuity")
                continuous = False
            if current["reference_sequence"] != ((previous["reference_sequence"] + 1) & UINT32_MASK):
                errors.append(f"{label} session {current['session']} reference sequence discontinuity")
                continuous = False
            progress = forward_progress(
                previous["reference_timestamp_ticks"],
                current["reference_timestamp_ticks"],
                domain="rp2040_timer0",
                allow_equal=False,
            )
            if not progress.valid:
                errors.append(
                    f"{label} session {current['session']} reference timestamp "
                    f"progress is invalid: {progress.reason}"
                )
                continuous = False
            interval_count = (
                previous["cumulative_down_counter"]
                - current["cumulative_down_counter"]
            ) & UINT32_MASK
            if interval_count > MAX_EXPECTED_INTERVAL_COUNT:
                errors.append(
                    f"{label} session {current['session']} interval count is ambiguous"
                )
                continuous = False
            if not continuous:
                previous_by_session[current["session"]] = current
                continue
            intervals.append(
                {
                    "session": current["session"],
                    "opening_reference_sequence": previous["reference_sequence"],
                    "closing_reference_sequence": current["reference_sequence"],
                    "opening_ticks": previous["reference_timestamp_ticks"],
                    "closing_ticks": current["reference_timestamp_ticks"],
                    "counted_edges": interval_count,
                    "opening_status": previous["status"],
                    "closing_status": current["status"],
                }
            )
        previous_by_session[current["session"]] = current
    return intervals


def _d8_evidence(rows: list[dict[str, str]], first_valid_ticks: int | None, errors: list[str]) -> dict[str, Any]:
    intervals = _snapshot_intervals(rows, label="D8 snapshot", errors=errors)
    accepted = []
    activation_excluded = []
    for interval in intervals:
        if first_valid_ticks is not None and interval["opening_ticks"] < first_valid_ticks <= interval["closing_ticks"]:
            activation_excluded.append(interval)
            continue
        if interval["opening_status"] != 0 or interval["closing_status"] != 0:
            errors.append("D8 snapshot status is nonzero outside D9 activation window")
            continue
        accepted.append(interval)
    if not accepted:
        errors.append("no accepted D14-gated D8 intervals")
    return {"intervals": accepted, "activation_excluded_intervals": activation_excluded}


def _monitor_evidence(rows: list[dict[str, str]], d8: Mapping[str, Any], first_valid_ticks: int | None, tolerance: int, errors: list[str]) -> dict[str, Any]:
    # MNS v1 explicitly binds monitor session to authoritative reference_session;
    # a missing field is intentionally fatal rather than guessed from monitor
    # session.  The firmware's own monitor session is otherwise independent.
    for row_number, row in enumerate(rows, start=2):
        if "reference_session" not in row or row.get("reference_session", "") == "":
            errors.append(f"D6 MNS row {row_number} lacks reference_session")
        elif row.get("channel_id") != "3":
            errors.append(f"D6 MNS row {row_number} channel_id is not D6/channel 3")
        elif row.get("backend") != "pio_wait_cumulative_snapshot_cpu_v1":
            errors.append(
                f"D6 MNS row {row_number} backend identity is not the exact "
                "CPU-sidecar contract"
            )

    d8_by_reference = {
        (item["session"], item["closing_reference_sequence"]): item
        for item in d8["intervals"]
    }
    comparisons: list[dict[str, int]] = []
    activation_excluded: list[dict[str, int]] = []

    # Reconstruct monitor intervals again with the raw rows retained so that
    # the authoritative reference session is part of every comparison key.
    parsed_by_monitor_session: dict[int, list[tuple[dict[str, str], dict[str, int]]]] = {}
    for row in rows:
        local_errors: list[str] = []
        session = _as_uint(row.get("session", ""), "D6 session", local_errors)
        sequence = _as_uint(row.get("snapshot_sequence", ""), "D6 snapshot_sequence", local_errors)
        counter = _as_uint(row.get("cumulative_down_counter", ""), "D6 cumulative_down_counter", local_errors)
        reference_session = _as_uint(row.get("reference_session", ""), "D6 reference_session", local_errors)
        reference_sequence = _as_uint(row.get("reference_sequence", ""), "D6 reference_sequence", local_errors)
        ticks = _as_uint(row.get("reference_timestamp_ticks", ""), "D6 reference_timestamp_ticks", local_errors)
        status = _as_uint(row.get("status", ""), "D6 status", local_errors)
        if local_errors:
            errors.extend(local_errors)
            continue
        assert None not in (session, sequence, counter, reference_session, reference_sequence, ticks, status)
        parsed_by_monitor_session.setdefault(session, []).append((row, {"sequence": sequence, "counter": counter, "reference_session": reference_session, "reference_sequence": reference_sequence, "ticks": ticks, "status": status}))

    for monitor_session, stream in parsed_by_monitor_session.items():
        previous: dict[str, int] | None = None
        for _raw, current in stream:
            if previous is not None:
                continuous = True
                if current["sequence"] != ((previous["sequence"] + 1) & UINT32_MASK):
                    errors.append(f"D6 monitor session {monitor_session} snapshot sequence discontinuity")
                    continuous = False
                if current["reference_session"] != previous["reference_session"]:
                    errors.append("D6 monitor interval crosses authoritative reference session")
                    previous = current
                    continue
                if current["reference_sequence"] != ((previous["reference_sequence"] + 1) & UINT32_MASK):
                    errors.append(f"D6 monitor session {monitor_session} reference sequence discontinuity")
                    continuous = False
                progress = forward_progress(
                    previous["ticks"], current["ticks"],
                    domain="rp2040_timer0", allow_equal=False,
                )
                if not progress.valid:
                    errors.append(
                        f"D6 monitor session {monitor_session} reference timestamp "
                        f"progress is invalid: {progress.reason}"
                    )
                    continuous = False
                interval_count = (
                    previous["counter"] - current["counter"]
                ) & UINT32_MASK
                if interval_count > MAX_EXPECTED_INTERVAL_COUNT:
                    errors.append(
                        f"D6 monitor session {monitor_session} interval count is ambiguous"
                    )
                    continuous = False
                if not continuous:
                    previous = current
                    continue
                interval = {
                    "reference_session": current["reference_session"],
                    "opening_reference_sequence": previous["reference_sequence"],
                    "closing_reference_sequence": current["reference_sequence"],
                    "opening_ticks": previous["ticks"],
                    "closing_ticks": current["ticks"],
                    "counted_edges": interval_count,
                    "opening_status": previous["status"],
                    "closing_status": current["status"],
                }
                if first_valid_ticks is not None and interval["opening_ticks"] < first_valid_ticks <= interval["closing_ticks"]:
                    activation_excluded.append(interval)
                elif interval["opening_status"] != 0 or interval["closing_status"] != 0:
                    errors.append("D6 monitor status is nonzero outside D9 activation window")
                else:
                    d8_interval = d8_by_reference.get((interval["reference_session"], interval["closing_reference_sequence"]))
                    if d8_interval is None:
                        errors.append("D6 monitor interval has no same-session D8 interval")
                    elif d8_interval["opening_ticks"] != interval["opening_ticks"] or d8_interval["closing_ticks"] != interval["closing_ticks"]:
                        errors.append("D6 and D8 interval timestamp association differs")
                    else:
                        difference = abs(d8_interval["counted_edges"] - interval["counted_edges"])
                        comparison = {
                            "reference_session": interval["reference_session"],
                            "closing_reference_sequence": interval["closing_reference_sequence"],
                            "d8_counted_edges": d8_interval["counted_edges"],
                            "d6_counted_edges": interval["counted_edges"],
                            "absolute_difference_cycles": difference,
                        }
                        comparisons.append(comparison)
                        if difference > tolerance:
                            errors.append(f"D6:D8 absolute interval count difference {difference} exceeds {tolerance}")
            previous = current
    if not comparisons:
        errors.append("no accepted same-reference D8:D6 interval comparisons")
    return {"comparisons": comparisons, "activation_excluded_intervals": activation_excluded}


def _analyze_stratum(run_dir: Path, contract: Mapping[str, Any], stratum: str) -> dict[str, Any]:
    errors: list[str] = []
    manifest = _load_json(run_dir / "run_manifest.json")
    binding = _bind_manifest_identity(manifest, contract, stratum, errors)
    health_rows = _rows_for_contract(run_dir, manifest, "health_v1", "csv/health.csv")
    d8_rows = _rows_for_contract(run_dir, manifest, "pps_snapshots_v1", "csv/pps_snapshots.csv")
    monitor_rows = _rows_for_contract(run_dir, manifest, "forwarded_monitor_snapshots_v1", "csv/forwarded_monitor_snapshots.csv")
    output_status, output_history = _latest_status(health_rows, "forwarded_clock_output")
    boot_status, _ = _latest_status(health_rows, "boot_capabilities")
    if boot_status.get("selected_profile") != PROFILE_BY_STRATUM[stratum]:
        errors.append("boot status selected_profile does not match requested D9/D6 stratum")

    first_valid_ticks: int | None = None
    if stratum == "baseline":
        if output_status.get("state") != "disabled":
            errors.append("baseline profile did not retain D9 disabled")
        d9_terminal = "d9_output_disabled_profile_verified"
    else:
        for key, expected in _REQUIRED_ENABLED_STATUS.items():
            if output_status.get(key) != expected:
                errors.append(f"D9 output status {key!r} is not exactly {expected!r}")
        if output_status.get("contract_sha256") != contract.get("contract_semantic_sha256"):
            errors.append("D9 output status contract SHA-256 mismatch")
        first_valid_ticks = _as_uint(output_status.get("first_valid_ticks", ""), "D9 first_valid_ticks", errors)
        d9_terminal = "output_function_correct_but_waveform_evidence_incomplete"

    # A readiness profile has no actuator or active-control evidence.  This is
    # separate from D14/D8 health; a monitor fault cannot make these rows clean.
    for forbidden in ("dac_steps_v1", "active_transactions_v1", "active_hybrid_decisions_v1"):
        rows = _rows_for_contract(run_dir, manifest, forbidden, f"csv/{forbidden}.csv")
        if rows:
            errors.append(f"non-actuating readiness stratum contains {forbidden} rows")

    d8_errors: list[str] = []
    d8 = _d8_evidence(d8_rows, first_valid_ticks, d8_errors)
    acquisition_terminal = "d14_d8_acquisition_healthy" if not d8_errors else "d14_d8_acquisition_noninterference_failed"
    if stratum == "monitor":
        d6_errors: list[str] = []
        tolerance = int(contract["d6_monitor"]["count_semantics"]["maximum_absolute_interval_count_difference_cycles"])
        d6 = _monitor_evidence(monitor_rows, d8, first_valid_ticks, tolerance, d6_errors)
        if not d6_errors:
            d6_terminal = "d6_forwarded_clock_monitor_qualified_as_diagnostic_only"
        elif not monitor_rows:
            d6_terminal = "d6_monitor_unavailable_without_d9_claim_impact"
        else:
            d6_terminal = "d6_monitor_platform_defect"
    else:
        d6_errors = []
        d6 = {"comparisons": [], "activation_excluded_intervals": []}
        if monitor_rows:
            d6_errors.append("D6 monitor records present in a monitor-disabled stratum")
        d6_terminal = "d6_monitor_disabled_in_profile"

    # Identity errors invalidate the entire stratum. D6 errors are intentionally
    # retained as a local terminal and do not rewrite D9 or D14/D8 terminals.
    all_errors = [*errors, *d8_errors]
    ready = not all_errors
    return {
        "run_dir": str(run_dir),
        "profile": PROFILE_BY_STRATUM[stratum],
        "manifest_binding": binding,
        "identity_errors": errors,
        "d14_d8_errors": d8_errors,
        "d6_errors": d6_errors,
        "output_status_history": output_history,
        "d8": d8,
        "d6": d6,
        "terminals": {
            "d9_output": d9_terminal if ready else "d9_output_implementation_or_platform_fault",
            "d6_monitor": d6_terminal,
            "d14_d8_acquisition": acquisition_terminal,
        },
        "ready_without_d6_terminal": ready,
    }


def analyze_strata(run_dirs: Mapping[str, Path], *, contract_path: Path | None = None) -> dict[str, Any]:
    """Analyze baseline, D9-output, and D9+D6 profiles as separate strata."""
    if set(run_dirs) != set(PROFILE_BY_STRATUM):
        raise ValueError("run_dirs must contain exactly baseline, output, and monitor strata")
    if contract_path is None:
        contract_path = Path(__file__).resolve().parents[2] / "docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/d9_d6_readiness_contract_v1.json"
    contract = _load_json(contract_path)
    if contract.get("contract_id") != CONTRACT_ID:
        raise ValueError("unexpected D9/D6 readiness contract ID")
    expected_semantic = contract.get("contract_semantic_sha256")
    actual_semantic = _canonical_sha256({key: value for key, value in contract.items() if key != "contract_semantic_sha256"})
    if expected_semantic != actual_semantic:
        raise ValueError("D9/D6 readiness contract semantic SHA-256 is invalid")
    strata = {name: _analyze_stratum(Path(path).resolve(), contract, name) for name, path in run_dirs.items()}
    primary_errors = [error for result in strata.values() for error in [*result["identity_errors"], *result["d14_d8_errors"]]]
    programme_terminal = (
        "d9_d6_candidate_bundle_ready_for_physical_authority"
        if not primary_errors
        else "readiness_invalid_due_to_identity_or_verification_failure"
    )
    return {
        "schema_version": 1,
        "analyzer_id": TOOL_ID,
        "contract": {
            "contract_id": CONTRACT_ID,
            "contract_semantic_sha256": expected_semantic,
            "path": str(contract_path.resolve()),
        },
        "strata": strata,
        "terminals": {
            "programme": programme_terminal,
            "d9_waveform_claim": "output_function_correct_but_waveform_evidence_incomplete",
            "d9_waveform_reason": "no external scope or independently referenced frequency evidence is accepted by this analyzer",
        },
    }


def analyze(run_dir: Path) -> dict[str, Any]:
    """Analyze a candidate directory containing `strata/{baseline,output,monitor}`."""
    run_dir = run_dir.resolve()
    return analyze_strata({name: run_dir / "strata" / name for name in PROFILE_BY_STRATUM})


def report_markdown(analysis: Mapping[str, Any]) -> str:
    terminals = analysis["terminals"]
    lines = [
        "# D9/D6 readiness analysis",
        "",
        f"Programme terminal: `{terminals['programme']}`.",
        "",
        f"Waveform terminal: `{terminals['d9_waveform_claim']}` — {terminals['d9_waveform_reason']}.",
        "",
        "| Stratum | D9 output | D6 monitor | D14/D8 acquisition |",
        "| --- | --- | --- | --- |",
    ]
    for name in ("baseline", "output", "monitor"):
        current = analysis["strata"][name]["terminals"]
        lines.append(f"| {name} | `{current['d9_output']}` | `{current['d6_monitor']}` | `{current['d14_d8_acquisition']}` |")
    lines.extend([
        "",
        "D6 is diagnostic-only. Its local terminal does not establish D9 voltage, edge shape, load behavior, propagation delay, jitter, or waveform qualification.",
        "",
    ])
    return "\n".join(lines)


def seal(run_dir: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    """Write immutable analysis, human report, and a content-bound local seal."""
    run_dir = run_dir.resolve()
    for relative in (ANALYSIS_PATH, REPORT_PATH, SEAL_PATH):
        if (run_dir / relative).exists():
            raise FileExistsError(f"refusing to overwrite immutable readiness artifact: {relative}")
    analysis_path = run_dir / ANALYSIS_PATH
    report_path = run_dir / REPORT_PATH
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(report_markdown(analysis), encoding="utf-8")
    seal_value = {
        "schema_version": 1,
        "seal_type": "otis_d9_d6_readiness_seal_v1",
        "analyzer_id": TOOL_ID,
        "analysis_sha256": sha256(analysis_path.read_bytes()).hexdigest(),
        "report_sha256": sha256(report_path.read_bytes()).hexdigest(),
        "programme_terminal": analysis["terminals"]["programme"],
    }
    (run_dir / SEAL_PATH).write_text(json.dumps(seal_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return seal_value


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze non-actuating D9/D6 readiness strata.")
    parser.add_argument("run_dir", type=Path, help="Candidate directory containing strata/{baseline,output,monitor}")
    parser.add_argument("--seal", action="store_true", help="write immutable analysis/report/seal artifacts")
    args = parser.parse_args()
    result = analyze(args.run_dir)
    if args.seal:
        seal(args.run_dir, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
