"""Execute one manifest-bound, non-actuating service-plane probe safely.

The helper never opens the serial device.  It sends only the exact command
declared by an active fixed-code run through the FIFO already owned by
``capture_device``.  Raw host-command markers are the authority for duplicate
prevention and the observed count-sequence boundaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import math
import stat
import tempfile
import time
from typing import Any, Callable

from .run_loader import CAPTURE_IN_PROGRESS_FLAG
from .pps_cumulative_span_estimator import _health_global_reasons
from .serial_commands import parse_serial_command, send_command_to_fifo


HOST_MARKER_PREFIX = "# OTIS_HOST "
PERMITTED_PROBE_COMMAND = "CONFIG?"
HOST_FAILURE_EVENTS = frozenset(
    {
        "host_command_rejected",
        "malformed_utf8",
        "oversize_line_dropped",
        "oversize_partial_line_dropped",
        "serial_disconnected",
    }
)
REQUIRED_LATEST_HEALTH = {
    ("pps_gate", "valid"): "true",
    ("pps_gate", "reference_validity"): "valid",
    ("pps_gate", "count_validity"): "valid",
    ("pps_gate", "boundary_validity"): "valid",
    ("pps_gate", "aperture_validity"): "valid",
    ("pps_gate", "fifo_continuity"): "continuous",
    ("pps_gate", "association_state"): "clean",
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _positive_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{label} must be a positive finite number")
    return float(value)


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class CommandMarker:
    command: str
    count_sequence: int | None
    utc: str | None


@dataclass(frozen=True)
class ProbeContract:
    command: str
    request_count: int
    cadence_period_s: float
    trigger_count_sequence: int
    basis: str


@dataclass(frozen=True)
class ProbeInspection:
    last_count_sequence: int | None
    sent_markers: tuple[CommandMarker, ...]
    host_failure_events: tuple[str, ...]

    def at_or_after(self, trigger_count_sequence: int) -> tuple[CommandMarker, ...]:
        return tuple(
            marker
            for marker in self.sent_markers
            if marker.count_sequence is not None
            and marker.count_sequence >= trigger_count_sequence
        )


def load_probe_contract(run_dir: Path) -> ProbeContract:
    manifest_path = run_dir / "run_manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("run manifest must be a JSON object")
    stage = manifest.get("stage")
    if stage == "CX317_FIXED_CODE_BASELINE":
        baseline = manifest.get("cx317_fixed_code_baseline")
        planned = (
            baseline.get("planned_service_plane_probe")
            if isinstance(baseline, dict)
            else None
        )
    elif stage == "CX317_PPS_GATED_I_ONLY_PREVIEW":
        preview = manifest.get("controller_preview")
        planned = (
            preview.get("planned_service_load")
            if isinstance(preview, dict)
            else None
        )
    else:
        raise ValueError(
            "service probe requires a declared CX317 fixed-code or Stage 6 preview run"
        )
    if not isinstance(planned, dict):
        raise ValueError("planned service-plane probe is unavailable")
    raw_command = planned.get("command")
    if not isinstance(raw_command, str):
        raise ValueError("planned service-plane command is unavailable")
    command = parse_serial_command(raw_command).normalized
    if command != PERMITTED_PROBE_COMMAND:
        raise ValueError("fixed-code service probe permits only CONFIG?")
    basis = planned.get("basis")
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError("planned service-plane provenance basis is unavailable")
    return ProbeContract(
        command=command,
        request_count=_positive_integer(
            planned.get("request_count"), "planned request count"
        ),
        cadence_period_s=_positive_number(
            planned.get("cadence_period_s"), "planned cadence period"
        ),
        trigger_count_sequence=_positive_integer(
            planned.get("planned_trigger_count_seq"),
            "planned trigger count sequence",
        ),
        basis=basis,
    )


def inspect_raw_log(raw_log: Path) -> ProbeInspection:
    current_count_sequence: int | None = None
    markers: list[CommandMarker] = []
    host_failure_events: set[str] = set()
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if line.startswith("CNT,"):
                fields = line.split(",", 4)
                try:
                    current_count_sequence = int(fields[2])
                except (IndexError, ValueError):
                    continue
                continue
            if not line.startswith(HOST_MARKER_PREFIX):
                continue
            try:
                marker = json.loads(line[len(HOST_MARKER_PREFIX) :])
            except json.JSONDecodeError:
                host_failure_events.add("host_marker_malformed")
                continue
            if not isinstance(marker, dict):
                host_failure_events.add("host_marker_malformed")
                continue
            event = str(marker.get("event"))
            if event in HOST_FAILURE_EVENTS:
                host_failure_events.add(event)
            if event == "host_command_sent":
                markers.append(
                    CommandMarker(
                        command=str(marker.get("command")),
                        count_sequence=current_count_sequence,
                        utc=(
                            str(marker["utc"])
                            if marker.get("utc") is not None
                            else None
                        ),
                    )
                )
    return ProbeInspection(
        current_count_sequence,
        tuple(markers),
        tuple(sorted(host_failure_events)),
    )


def _latest_health_reasons(path: Path) -> tuple[str, ...]:
    latest: dict[tuple[str, str], str] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            latest[(row["component"], row["status_key"])] = row[
                "status_value"
            ].strip()
    reasons: list[str] = []
    for key, expected in REQUIRED_LATEST_HEALTH.items():
        observed = latest.get(key)
        if observed != expected:
            reasons.append(
                f"latest_{key[0]}_{key[1]}={observed!r}_expected_{expected!r}"
            )
    return tuple(reasons)


def _require_clean_health(run_dir: Path, inspection: ProbeInspection) -> None:
    reasons = set(inspection.host_failure_events)
    health_path = run_dir / "csv" / "sts.csv"
    manifest_path = run_dir / "run_manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    for item in manifest.get("files", []):
        if item.get("contract") == "health_v1":
            health_path = run_dir / str(item["path"])
            break
    reasons.update(_health_global_reasons(health_path))
    reasons.update(_latest_health_reasons(health_path))
    if reasons:
        raise RuntimeError(
            "service-plane probe requires clean host/firmware health: "
            + ", ".join(sorted(reasons))
        )


def _require_live_fifo(run_dir: Path) -> Path:
    if not (run_dir / CAPTURE_IN_PROGRESS_FLAG).is_file():
        raise RuntimeError("capture-in-progress marker is absent")
    fifo = run_dir / "control.fifo"
    try:
        mode = fifo.stat().st_mode
    except FileNotFoundError as exc:
        raise RuntimeError("capture-owned control FIFO is absent") from exc
    if not stat.S_ISFIFO(mode):
        raise RuntimeError("capture-owned control path is not a FIFO")
    return fifo


def execute_probe(
    run_dir: Path,
    *,
    sender: Callable[[Path, str], int] = send_command_to_fifo,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    contract = load_probe_contract(run_dir)
    raw_log = run_dir / "raw" / "serial.log"
    before = inspect_raw_log(raw_log)
    after_trigger = before.at_or_after(contract.trigger_count_sequence)
    unexpected = [
        marker.command
        for marker in after_trigger
        if marker.command != contract.command
    ]
    if unexpected:
        raise RuntimeError(
            f"unexpected command markers at/after trigger: {unexpected}"
        )
    if len(after_trigger) > contract.request_count:
        raise RuntimeError("service-plane probe command count already exceeds plan")
    common = {
        "schema_version": 1,
        "command": contract.command,
        "planned_request_count": contract.request_count,
        "cadence_period_s": contract.cadence_period_s,
        "trigger_count_sequence": contract.trigger_count_sequence,
        "provenance_basis": contract.basis,
        "observed_preexisting_probe_commands": len(after_trigger),
        "observed_pre_count_sequence": before.last_count_sequence,
        "serial_device_opened_by_helper": False,
        "dac_command": False,
    }
    if len(after_trigger) == contract.request_count:
        return {
            **common,
            "status": "already_complete",
            "commands_sent_this_invocation": 0,
            "observed_post_count_sequence": before.last_count_sequence,
            "observed_total_probe_commands": len(after_trigger),
        }
    if (
        before.last_count_sequence is None
        or before.last_count_sequence < contract.trigger_count_sequence
    ):
        return {
            **common,
            "status": "not_due",
            "commands_sent_this_invocation": 0,
            "observed_post_count_sequence": before.last_count_sequence,
            "observed_total_probe_commands": len(after_trigger),
        }

    fifo = _require_live_fifo(run_dir)
    _require_clean_health(run_dir, before)
    remaining = contract.request_count - len(after_trigger)
    started_at_utc = _utc_now()
    for _ in range(remaining):
        _require_live_fifo(run_dir)
        sender(fifo, contract.command)
        sleep(contract.cadence_period_s)
    after = inspect_raw_log(raw_log)
    _require_clean_health(run_dir, after)
    final_markers = after.at_or_after(contract.trigger_count_sequence)
    unexpected = [
        marker.command
        for marker in final_markers
        if marker.command != contract.command
    ]
    if unexpected:
        raise RuntimeError(
            f"unexpected command markers at/after probe: {unexpected}"
        )
    status = (
        "complete"
        if len(final_markers) == contract.request_count
        else "incomplete_fail_closed"
    )
    return {
        **common,
        "status": status,
        "started_at_utc": started_at_utc,
        "finished_at_utc": _utc_now(),
        "commands_sent_this_invocation": remaining,
        "observed_post_count_sequence": after.last_count_sequence,
        "observed_total_probe_commands": len(final_markers),
        "first_probe_marker": (
            asdict(final_markers[0]) if final_markers else None
        ),
        "last_probe_marker": (
            asdict(final_markers[-1]) if final_markers else None
        ),
    }


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the exact manifest-bound non-actuating service-plane probe."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = execute_probe(args.run_dir)
        if args.output is not None:
            _write_result(args.output, result)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"complete", "already_complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
