"""Fail-static live executor for the predetermined CX317 Stage 5 campaign.

This module is intentionally separate from estimator/control code.  It sends
only the codes in the reviewed campaign plan, never reads frequency error, and
never restores a code on failure or abort.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import math
import signal
import tempfile
import time
from typing import Any

from .cx317_abort_path import AbortFifo
from .cx317_open_loop_scheduler import CampaignPlan, load_plan
from .run_loader import RunManifest, load_manifest
from .serial_commands import send_command_to_fifo


TOOL_VERSION = "cx317_open_loop_executor_v1"
UNIVERSAL_COUNTER_KEYS = frozenset(
    {
        "dropped_count",
        "pps_count_boundary_dropped_count",
        "error_flags",
        "boundary_ring_dropped_count",
        "snapshot_overwrite_count",
        "snapshot_continuity_loss_count",
        "snapshot_pio_rxstall_count",
        "snapshot_dma_error_count",
        "snapshot_dma_stopped_count",
        "association_loss_count",
        "counter_snapshot_invalid_count",
        "count_saturated_count",
        "boundary_sequence_gap_count",
        "boundary_sequence_duplicate_count",
        "missing_pps_count",
        "pps_interval_anomaly_count",
        "physical_pps_missing_count",
    }
)
HOST_FAULT_MARKERS = (
    '"event": "serial_disconnected"',
    '"event": "parser_error"',
    '"event": "malformed_utf8"',
    '"event": "host_command_rejected"',
)


class CampaignAbort(RuntimeError):
    pass


@dataclass(frozen=True)
class DacAcknowledgement:
    seq: int
    requested_code: int
    applied_code: int
    clamped: bool
    event: str
    flags: int


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _integer(text: str | None, label: str) -> int:
    if text is None or text == "":
        raise ValueError(f"DAC acknowledgement {label} is missing")
    try:
        return int(text, 0)
    except ValueError as exc:
        raise ValueError(f"DAC acknowledgement {label} is not an integer") from exc


def dac_acknowledgements(path: Path) -> list[DacAcknowledgement]:
    if not path.exists():
        return []
    output: list[DacAcknowledgement] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                output.append(
                    DacAcknowledgement(
                        seq=_integer(row.get("seq"), "sequence"),
                        requested_code=_integer(
                            row.get("dac_code_requested"), "requested code"
                        ),
                        applied_code=_integer(
                            row.get("dac_code_applied"), "applied code"
                        ),
                        clamped=_integer(row.get("dac_code_clamped"), "clamp flag")
                        != 0,
                        event=str(row.get("event") or ""),
                        flags=_integer(row.get("flags"), "flags"),
                    )
                )
            except ValueError:
                # A concurrently written final line is not an acknowledgement
                # until it is complete. Earlier malformed rows fail below when
                # their sequence becomes visible through a complete row.
                continue
    return output


def require_new_exact_ack(
    path: Path, after_seq: int, requested_code: int
) -> DacAcknowledgement | None:
    new_rows = [item for item in dac_acknowledgements(path) if item.seq > after_seq]
    if not new_rows:
        return None
    acknowledgement = min(new_rows, key=lambda item: item.seq)
    if acknowledgement.requested_code != requested_code:
        raise RuntimeError("DAC acknowledgement requested-code mismatch")
    if acknowledgement.applied_code != requested_code:
        raise RuntimeError("DAC acknowledgement applied-code mismatch")
    if acknowledgement.clamped:
        raise RuntimeError("DAC acknowledgement unexpectedly reports clamping")
    if acknowledgement.event != "manual_apply":
        raise RuntimeError(
            f"DAC acknowledgement event is {acknowledgement.event!r}, not manual_apply"
        )
    if acknowledgement.flags != 0:
        raise RuntimeError("DAC acknowledgement carries a suspect/error flag")
    if len(new_rows) != 1:
        raise RuntimeError("multiple DAC acknowledgement rows followed one request")
    return acknowledgement


def _latest_health_values(path: Path) -> tuple[dict[str, int], str | None]:
    counters: dict[str, int] = {}
    agreement: str | None = None
    if not path.exists():
        return counters, agreement
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = row.get("status_key")
            if key in UNIVERSAL_COUNTER_KEYS:
                try:
                    counters[str(key)] = int(str(row.get("status_value")), 0)
                except ValueError:
                    continue
            if (
                row.get("component") == "pps_dual_observer"
                and key == "agreement_state"
            ):
                agreement = row.get("status_value")
    return counters, agreement


def _host_fault_counts(raw_log: Path) -> dict[str, int]:
    if not raw_log.exists():
        return {marker: 0 for marker in HOST_FAULT_MARKERS}
    text = raw_log.read_text(encoding="utf-8", errors="replace")
    return {marker: text.count(marker) for marker in HOST_FAULT_MARKERS}


@dataclass
class HealthMonitor:
    run_dir: Path
    health_path: Path
    raw_log_path: Path
    baseline_counters: dict[str, int]
    baseline_host_faults: dict[str, int]
    require_auxiliary_match_to_d14: bool

    @classmethod
    def start(
        cls,
        run_dir: Path,
        health_path: Path | None = None,
        raw_log_path: Path | None = None,
        require_auxiliary_match_to_d14: bool = False,
    ) -> "HealthMonitor":
        health_path = health_path or run_dir / "csv" / "health.csv"
        raw_log_path = raw_log_path or run_dir / "raw" / "serial.log"
        counters, agreement = _latest_health_values(health_path)
        missing = sorted(UNIVERSAL_COUNTER_KEYS - set(counters))
        if missing:
            raise RuntimeError(f"capture health is missing required counters: {missing}")
        if require_auxiliary_match_to_d14 and agreement != "MATCHING":
            raise RuntimeError("D14/D10 observers are not matching at scheduler start")
        return cls(
            run_dir=run_dir,
            health_path=health_path,
            raw_log_path=raw_log_path,
            baseline_counters=counters,
            baseline_host_faults=_host_fault_counts(raw_log_path),
            require_auxiliary_match_to_d14=require_auxiliary_match_to_d14,
        )

    def check(self) -> None:
        if not (self.run_dir / "capture_in_progress.flag").exists():
            raise RuntimeError("capture_in_progress.flag was lost")
        counters, agreement = _latest_health_values(self.health_path)
        if self.require_auxiliary_match_to_d14 and agreement != "MATCHING":
            raise RuntimeError(
                "run-declared D14/general-auxiliary-input agreement was lost"
            )
        for key, baseline in self.baseline_counters.items():
            current = counters.get(key)
            if current is None:
                raise RuntimeError(f"capture health counter disappeared: {key}")
            if current > baseline:
                raise RuntimeError(
                    f"capture health counter increased: {key} {baseline}->{current}"
                )
        current_faults = _host_fault_counts(self.raw_log_path)
        for marker, baseline in self.baseline_host_faults.items():
            if current_faults[marker] > baseline:
                raise RuntimeError(f"host capture fault marker increased: {marker}")


def require_gate_authorized(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("physical gate evaluation must be an object")
    if value.get("decision") != "pass" or value.get(
        "hardware_execution_authorized"
    ) is not True:
        raise RuntimeError("Stage 5 physical gate is not authorized")
    return value


def _single_contract_path(manifest: RunManifest, contract: str) -> Path:
    matches = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"run manifest must expose exactly one {contract} file; got {len(matches)}"
        )
    return matches[0]


def require_run_binding(
    run_dir: Path, plan: CampaignPlan
) -> tuple[Path, Path, Path]:
    manifest = load_manifest(run_dir)
    value = manifest.data
    if manifest.is_template or manifest.run_id != run_dir.name:
        raise RuntimeError("run manifest identity is not instantiated for this run")
    required_scalars = {
        "stage": "CX317_PPS_GATED_OPEN_LOOP",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "predetermined_open_loop_characterization",
        "closed_loop_control": False,
        "actionable": False,
        "actuation_authorized": False,
    }
    for field, expected in required_scalars.items():
        if value.get(field) != expected:
            raise RuntimeError(f"run manifest {field} binding mismatch")
    firmware = value.get("firmware")
    if not isinstance(firmware, dict):
        raise RuntimeError("run manifest firmware binding is missing")
    expected_firmware = {
        "config_id": plan.firmware_profile,
        "configuration_sha256": plan.firmware_configuration_sha256,
        "uf2_sha256": plan.firmware_uf2_sha256,
    }
    for field, expected in expected_firmware.items():
        if firmware.get(field) != expected:
            raise RuntimeError(f"run manifest firmware {field} binding mismatch")
    backend = value.get("phase5_pps_backend_qualification")
    if (
        not isinstance(backend, dict)
        or backend.get("measurement_backend") != plan.measurement_backend
        or backend.get("nominal_reference_interval_s") != 1.0
    ):
        raise RuntimeError("run manifest PPS-gated backend binding mismatch")
    campaign = value.get("plant_campaign")
    if (
        not isinstance(campaign, dict)
        or campaign.get("plan_id") != plan.plan_id
        or campaign.get("config_sha256") != plan.config_hash
        or campaign.get("frequency_error_used_for_commands") is not False
        or campaign.get("automatic_restore") is not False
        or campaign.get("final_safe_code") != plan.final_safe_code
    ):
        raise RuntimeError("run manifest predetermined campaign binding mismatch")
    estimator = value.get("selected_estimator")
    if (
        not isinstance(estimator, dict)
        or estimator.get("method_id") != plan.estimator_method_id
        or estimator.get("profile_sha256")
        != plan.selected_estimator_config_sha256
        or estimator.get("authoritative_span_s")
        != plan.selected_authoritative_span_s
    ):
        raise RuntimeError("run manifest selected estimator binding mismatch")
    dac_path = _single_contract_path(manifest, "dac_steps_v1")
    health_path = _single_contract_path(manifest, "health_v1")
    for contract in (
        "raw_events_v1",
        "count_observations_v1",
        "pps_snapshots_v1",
        "environment_v1",
    ):
        _single_contract_path(manifest, contract)
    require_auxiliary_edge_health_policy(run_dir)
    return dac_path, health_path, run_dir / "raw" / "serial.log"


def require_auxiliary_edge_health_policy(run_dir: Path) -> bool:
    """Return whether this run explicitly wires the general input to D14 PPS.

    D10 is not architecturally a PPS witness.  Agreement is meaningful only
    for a manifest that declares the current physical connection and opts into
    that run-specific comparison.
    """

    manifest = load_manifest(run_dir)
    auxiliary = manifest.data.get("auxiliary_edge_input")
    if not isinstance(auxiliary, dict):
        raise RuntimeError("run manifest auxiliary edge-input binding is missing")
    if (
        auxiliary.get("pin") != "D10"
        or auxiliary.get("architectural_role") != "general_edge_timestamp_input"
    ):
        raise RuntimeError("run manifest general auxiliary input identity mismatch")
    connection = auxiliary.get("current_connection")
    policy = auxiliary.get("current_run_health_policy")
    if connection == "same_gps_pps_as_d14_for_current_run":
        if policy != "require_match_to_d14":
            raise RuntimeError(
                "same-PPS auxiliary connection must require run-specific matching"
            )
        return True
    if policy == "not_applicable_to_d14":
        return False
    raise RuntimeError("run manifest auxiliary edge-input health policy mismatch")


def _write_result(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _event(events: list[dict[str, Any]], name: str, **values: Any) -> None:
    events.append({"event": name, "utc": _utc_now(), **values})


def _wait_monotonic(
    duration_s: float,
    abort: AbortFifo,
    health: HealthMonitor,
    signal_stop: dict[str, bool],
) -> None:
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        if signal_stop["requested"] or abort.poll():
            raise CampaignAbort("independent abort requested")
        health.check()
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _wait_for_ack(
    dac_csv: Path,
    requested_code: int,
    after_seq: int,
    deadline_s: float,
    abort: AbortFifo,
    health: HealthMonitor,
    signal_stop: dict[str, bool],
) -> tuple[DacAcknowledgement, float]:
    started = time.monotonic()
    deadline = started + deadline_s
    while time.monotonic() < deadline:
        if signal_stop["requested"] or abort.poll():
            raise CampaignAbort("independent abort requested during DAC acknowledgement")
        health.check()
        acknowledgement = require_new_exact_ack(
            dac_csv, after_seq, requested_code
        )
        if acknowledgement is not None:
            return acknowledgement, time.monotonic() - started
        time.sleep(0.01)
    raise TimeoutError(
        f"DAC acknowledgement deadline missed for 0x{requested_code:04X}"
    )


def execute_campaign(
    plan: CampaignPlan,
    gate_path: Path,
    run_dir: Path,
    command_fifo: Path,
    abort_fifo: Path,
    result_path: Path,
) -> Path:
    plan.require_hardware_binding()
    require_gate_authorized(gate_path)
    assert plan.ack_deadline_s is not None
    dac_csv, health_csv, raw_log = require_run_binding(run_dir, plan)
    if not dac_csv.exists():
        raise RuntimeError("run does not expose csv/dac_steps.csv")
    health = HealthMonitor.start(
        run_dir,
        health_csv,
        raw_log,
        require_auxiliary_match_to_d14=require_auxiliary_edge_health_policy(
            run_dir
        ),
    )
    events: list[dict[str, Any]] = []
    acknowledgements: list[dict[str, Any]] = []
    signal_stop = {"requested": False}
    previous_handlers = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }

    def request_stop(_signum, _frame) -> None:
        signal_stop["requested"] = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    status = "failed"
    reason = "unavailable"
    last_verified_code: int | None = None
    started_at_utc = _utc_now()
    try:
        with AbortFifo(abort_fifo) as abort:
            _event(events, "warmup_start", duration_s=plan.initial_warmup_s)
            _wait_monotonic(
                plan.initial_warmup_s, abort, health, signal_stop
            )
            _event(events, "warmup_complete")
            for index, step in enumerate(plan.sequence):
                if abort.poll() or signal_stop["requested"]:
                    raise CampaignAbort("independent abort requested before transition")
                health.check()
                existing = dac_acknowledgements(dac_csv)
                after_seq = max((item.seq for item in existing), default=-1)
                command = f"DAC SET 0x{step.code:04X}"
                _event(
                    events,
                    "transition_request",
                    step_index=index,
                    label=step.label,
                    code=step.code,
                )
                send_command_to_fifo(command_fifo, command)
                acknowledgement, latency_s = _wait_for_ack(
                    dac_csv,
                    step.code,
                    after_seq,
                    plan.ack_deadline_s,
                    abort,
                    health,
                    signal_stop,
                )
                slack_s = plan.ack_deadline_s - latency_s
                if not math.isfinite(slack_s) or slack_s <= 0:
                    raise RuntimeError("DAC acknowledgement has no positive deadline slack")
                last_verified_code = step.code
                acknowledgements.append(
                    {
                        **asdict(acknowledgement),
                        "latency_s": latency_s,
                        "deadline_s": plan.ack_deadline_s,
                        "slack_s": slack_s,
                    }
                )
                _event(
                    events,
                    "transition_ack",
                    step_index=index,
                    code=step.code,
                    latency_s=latency_s,
                    slack_s=slack_s,
                )
                _wait_monotonic(
                    plan.settling_exclusion_s, abort, health, signal_stop
                )
                _event(
                    events,
                    "settling_exclusion_complete",
                    step_index=index,
                    code=step.code,
                )
                _wait_monotonic(
                    plan.dwell_s - plan.settling_exclusion_s,
                    abort,
                    health,
                    signal_stop,
                )
                _event(
                    events,
                    "dwell_complete",
                    step_index=index,
                    code=step.code,
                )
            if last_verified_code != plan.final_safe_code:
                raise RuntimeError("campaign did not finish at the reviewed final safe code")
            status = "complete_fail_static"
            reason = "planned_sequence_complete"
    except CampaignAbort as exc:
        status = "aborted_fail_static"
        reason = str(exc)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        status = "failed_fail_static"
        reason = str(exc)
        raise
    finally:
        signal.signal(signal.SIGINT, previous_handlers[signal.SIGINT])
        signal.signal(signal.SIGTERM, previous_handlers[signal.SIGTERM])
        _write_result(
            result_path,
            {
                "schema_version": 1,
                "tool_version": TOOL_VERSION,
                "plan_id": plan.plan_id,
                "started_at_utc": started_at_utc,
                "ended_at_utc": _utc_now(),
                "status": status,
                "reason": reason,
                "last_verified_code": last_verified_code,
                "automatic_restore": False,
                "feedback_derived_commands": False,
                "events": events,
                "acknowledgements": acknowledgements,
            },
        )
    return result_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the authorized predetermined CX317 Stage 5 campaign fail-static.")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--gate-evaluation", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--abort-fifo", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(
            execute_campaign(
                load_plan(args.plan),
                args.gate_evaluation,
                args.run_dir,
                args.command_fifo,
                args.abort_fifo,
                args.result,
            )
        )
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
