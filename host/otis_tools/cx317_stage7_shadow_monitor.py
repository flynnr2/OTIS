"""Read-only Stage 7 authoritative-observation and shadow recorder.

This process never opens the serial device, command FIFO or abort FIFO.  It
derives a durable context row whenever a new qualified selected 600 s estimate
appears, then exactly replays every frozen non-actionable shadow candidate.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import argparse
import csv
import os
import tempfile
import time

from .cx317_active_campaign import _latest_health, _read_csv
from .cx317_stage7_shadow import (
    CONTRACT_SHA256,
    ShadowObservation,
    load_contract,
    run_shadow,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG


ESTIMATES = Path("csv/estimates_v2.csv")
ACTIVE = Path("csv/active_transactions_v1.csv")
ENVIRONMENT = Path("csv/environment.csv")
HEALTH = Path("csv/health.csv")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
AUTHORITATIVE = Path("reports/stage7_authoritative_observations_v1.csv")
SHADOW = Path("reports/stage7_shadow_decisions_v1.csv")
SELECTED_ESTIMATOR = "cx317_selected_600s_nonoverlap_v1"
SELECTED_HASH = "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c"
AUTHORITATIVE_DEADBAND_HZ = 0.006249995628992717

AUTHORITATIVE_FIELDS = (
    "record_type",
    "schema_version",
    "part",
    "observation_sequence",
    "estimate_id",
    "estimate_seq",
    "estimator_timestamp_ticks",
    "timestamp_s",
    "source_reference_first_seq",
    "source_reference_last_seq",
    "frequency_error_hz",
    "actual_applied_code",
    "actual_dac_epoch",
    "elapsed_since_actual_dac_s",
    "authoritative_deadband_state",
    "preceding_actual_correction_direction",
    "gnss_qualification",
    "service_load_state",
    "environment_source_seq",
    "temperature_c",
    "relative_humidity_pct",
    "pressure_pa",
    "service_queue_depth",
    "service_queue_high_water",
    "observation_queue_depth",
    "observation_queue_high_water",
    "critical_queue_depth",
    "critical_queue_high_water",
    "evidence_queue_depth",
    "evidence_queue_high_water",
    "telemetry_queue_depth",
    "telemetry_queue_high_water",
    "telemetry_dropped",
    "selected_estimator_sha256",
    "shadow_contract_sha256",
    "preserved_while_capture_active",
    "eligible",
)

SHADOW_FIELDS = (
    "record_type",
    "schema_version",
    "part",
    "shadow_contract_sha256",
    "candidate_id",
    "observation_sequence",
    "estimate_id",
    "timestamp_s",
    "observed_error_hz",
    "counterfactual_error_hz",
    "actual_applied_code",
    "shadow_code_before",
    "shadow_code_after",
    "band_state_before",
    "band_state_after",
    "state_before",
    "state_after",
    "transition",
    "entry_consecutive_count",
    "release_consecutive_count",
    "integrator_before_codes",
    "raw_delta_codes",
    "limited_delta_codes",
    "proposed_code",
    "step_limited",
    "range_clamped",
    "counterfactual_write",
    "correction_count",
    "path_codes",
    "net_movement_codes",
    "alternating_correction_count",
    "decision_reason",
    "actionable",
    "actuation_authorized",
    "authorization_consumed",
)


def _atomic_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        "true"
                        if value is True
                        else "false"
                        if value is False
                        else ""
                        if value is None
                        else value
                    )
                    for key, value in row.items()
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _selected_rows(path: Path) -> list[dict[str, str]]:
    return [
        row
        for row in _read_csv(path)
        if row.get("estimator_version") == SELECTED_ESTIMATOR
        and row.get("config_hash") == SELECTED_HASH
        and row.get("observation_validity") == "valid"
        and row.get("reference_validity") == "valid"
        and row.get("count_validity") == "valid"
        and row.get("diagnostic_health") == "healthy"
        and row.get("preview_eligibility") == "true"
        and row.get("frequency_error_hz") not in {None, ""}
    ]


def _actual_state(
    active: list[dict[str, str]], timestamp_s: int, start_code: int
) -> tuple[int, int, int, str]:
    code = start_code
    epoch = 0
    last_application_s = 0
    direction = "none"
    for row in active:
        if row.get("event") != "application":
            continue
        applied_s = int(row["application_timestamp_s"])
        if applied_s > timestamp_s:
            break
        code = int(row["applied_code"])
        epoch = int(row["dac_epoch"])
        last_application_s = applied_s
        delta = int(row["requested_delta_codes"])
        direction = "positive" if delta > 0 else "negative"
    return code, epoch, max(0, timestamp_s - last_application_s), direction


def _service_state(run_dir: Path) -> str:
    path = run_dir / SUPERVISOR_STATE
    if not path.exists():
        return "unavailable"
    import json

    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("stage7_part") == "part_a":
        sent = int(state.get("part_a_service_load_sent", 0))
        if state.get("part_a_service_load_complete"):
            return "part_a_load_complete"
        return "part_a_load_active" if sent else "normal"
    burst = state.get("part_b_service_burst_index")
    return f"part_b_burst_{burst}_active" if burst is not None else "normal"


def _context_row(
    *,
    run_dir: Path,
    part: str,
    start_code: int,
    observation_sequence: int,
    estimate: dict[str, str],
) -> dict:
    timestamp_s = int(estimate["source_reference_last_seq"])
    code, epoch, elapsed, direction = _actual_state(
        _read_csv(run_dir / ACTIVE), timestamp_s, start_code
    )
    environment = _read_csv(run_dir / ENVIRONMENT)
    env = environment[-1] if environment else {}
    health = _latest_health(run_dir / HEALTH)

    def status(component: str, key: str) -> str:
        return health.get((component, key), "unavailable")

    error = float(estimate["frequency_error_hz"])
    gnss = (
        "qualified"
        if status("gnss_receiver", "control_eligible") == "true"
        else "unqualified"
    )
    return {
        "record_type": "S7O",
        "schema_version": 1,
        "part": part,
        "observation_sequence": observation_sequence,
        "estimate_id": estimate["estimate_id"],
        "estimate_seq": estimate["estimate_seq"],
        "estimator_timestamp_ticks": estimate["estimator_timestamp_ticks"],
        "timestamp_s": timestamp_s,
        "source_reference_first_seq": estimate["source_reference_first_seq"],
        "source_reference_last_seq": estimate["source_reference_last_seq"],
        "frequency_error_hz": f"{error:.12f}",
        "actual_applied_code": code,
        "actual_dac_epoch": epoch,
        "elapsed_since_actual_dac_s": elapsed,
        "authoritative_deadband_state": (
            "inside" if abs(error) <= AUTHORITATIVE_DEADBAND_HZ else "outside"
        ),
        "preceding_actual_correction_direction": direction,
        "gnss_qualification": gnss,
        "service_load_state": _service_state(run_dir),
        "environment_source_seq": env.get("env_seq", "unavailable"),
        "temperature_c": env.get("temperature_c", "unavailable"),
        "relative_humidity_pct": env.get(
            "relative_humidity_pct", "unavailable"
        ),
        "pressure_pa": env.get("pressure_pa", "unavailable"),
        "service_queue_depth": status("dual_core", "service_to_timing_depth"),
        "service_queue_high_water": status(
            "dual_core", "service_to_timing_high_water"
        ),
        "observation_queue_depth": status("dual_core", "observation_depth"),
        "observation_queue_high_water": status(
            "dual_core", "observation_high_water"
        ),
        "critical_queue_depth": status("dual_core", "critical_depth"),
        "critical_queue_high_water": status(
            "dual_core", "critical_high_water"
        ),
        "evidence_queue_depth": status("dual_core", "evidence_depth"),
        "evidence_queue_high_water": status(
            "dual_core", "evidence_high_water"
        ),
        "telemetry_queue_depth": status("dual_core", "telemetry_depth"),
        "telemetry_queue_high_water": status(
            "dual_core", "telemetry_high_water"
        ),
        "telemetry_dropped": status("dual_core", "telemetry_dropped"),
        "selected_estimator_sha256": SELECTED_HASH,
        "shadow_contract_sha256": CONTRACT_SHA256,
        "preserved_while_capture_active": (
            run_dir / CAPTURE_IN_PROGRESS_FLAG
        ).exists(),
        "eligible": True,
    }


def refresh(run_dir: Path, *, part: str, start_code: int) -> tuple[int, int]:
    contract = load_contract()
    authoritative_path = run_dir / AUTHORITATIVE
    existing = _read_csv(authoritative_path)
    known = {row["estimate_id"] for row in existing}
    selected = _selected_rows(run_dir / ESTIMATES)
    for estimate in selected:
        if estimate["estimate_id"] in known:
            continue
        existing.append(
            _context_row(
                run_dir=run_dir,
                part=part,
                start_code=start_code,
                observation_sequence=len(existing) + 1,
                estimate=estimate,
            )
        )
        known.add(estimate["estimate_id"])
    _atomic_csv(authoritative_path, AUTHORITATIVE_FIELDS, existing)

    observations = [
        ShadowObservation(
            observation_sequence=int(row["observation_sequence"]),
            estimate_id=row["estimate_id"],
            timestamp_s=int(row["timestamp_s"]),
            frequency_error_hz=float(row["frequency_error_hz"]),
            actual_applied_code=int(row["actual_applied_code"]),
            actual_dac_epoch=int(row["actual_dac_epoch"]),
            eligible=row["eligible"] in {True, "true"},
        )
        for row in existing
    ]
    decisions = run_shadow(
        observations, contract=contract, part=part, start_code=start_code
    )
    shadow_rows = [
        {
            **asdict(decision),
            "part": part,
            "shadow_contract_sha256": CONTRACT_SHA256,
        }
        for decision in decisions
    ]
    _atomic_csv(run_dir / SHADOW, SHADOW_FIELDS, shadow_rows)
    return len(existing), len(shadow_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("part_a", "part_b"), required=True)
    parser.add_argument("--start-code", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--poll-s", type=float, default=1.0)
    args = parser.parse_args(argv)
    while True:
        observations, decisions = refresh(
            args.run_dir, part=args.part, start_code=args.start_code
        )
        if not args.follow or not (
            args.run_dir / CAPTURE_IN_PROGRESS_FLAG
        ).exists():
            print(
                f"authoritative_observations={observations} "
                f"shadow_decisions={decisions}"
            )
            return 0
        time.sleep(max(0.1, args.poll_s))


if __name__ == "__main__":
    raise SystemExit(main())
