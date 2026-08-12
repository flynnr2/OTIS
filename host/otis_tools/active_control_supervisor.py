"""Current fail-static command and transport mechanics for active control.

The capture process remains the sole serial owner. Supervisors use the normal
command FIFO and the independent ABORT-only FIFO; this module contains only
the mechanics shared by the current CX319 control supervisors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import time
from typing import Any

from .active_transactions import ActiveTransactionSupervisor, _read_csv, _utc_now
from .serial_commands import send_timestamped_command_to_fifo
from .timebase import unwrap_ticks


ESTIMATES_CSV = Path("csv/estimates_v2.csv")
DAC_CSV = Path("csv/dac_steps.csv")
CAPTURE_TRANSPORT_STATE = Path("reports/capture_device_state.json")
CAPTURE_TRANSPORT_STATE_MAX_AGE_S = 15
NORMAL_COMMAND_ACK_TIMEOUT_S = 3.0
NORMAL_COMMAND_ACK_POLL_S = 0.02
RP2040_TIMER0_TICKS_PER_SECOND = 16_000_000


@dataclass(frozen=True)
class ControlTiming:
    selected_interval_s: int
    decision_cadence_s: int
    arm_progress_threshold: int
    qualification_timeout_s: int
    qualified_timeout_s: int
    service_load_queries: int
    service_query_period_s: float


def _parse_utc_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _latest_preview(path: Path) -> dict[str, str] | None:
    rows = _read_csv(path)
    return rows[-1] if rows else None


def _next_selected_interval_is_cadence_eligible(
    controls_path: Path,
    estimates_path: Path,
    *,
    selected_interval_s: int = 600,
    decision_cadence_s: int = 1800,
) -> bool:
    """Conservatively predict whether an arm can be consumed next interval."""
    del estimates_path
    rows = _read_csv(controls_path)
    if not rows:
        return False
    eligible = [row for row in rows if row.get("preview_available") == "true"]
    if not eligible:
        return True
    try:
        ticks, _ = unwrap_ticks(
            [int(row["decision_timestamp_ticks"]) for row in rows]
        )
        eligible_index = max(
            index
            for index, row in enumerate(rows)
            if row.get("preview_available") == "true"
        )
    except (KeyError, TypeError, ValueError):
        return False
    positive_spacings = [
        later - earlier
        for earlier, later in zip(ticks, ticks[1:])
        if later > earlier
    ]
    conservative_spacing = min(
        positive_spacings,
        default=selected_interval_s * RP2040_TIMER0_TICKS_PER_SECOND,
    )
    projected_next_s = (
        ticks[-1] + conservative_spacing
    ) // RP2040_TIMER0_TICKS_PER_SECOND
    last_eligible_s = ticks[eligible_index] // RP2040_TIMER0_TICKS_PER_SECOND
    return projected_next_s - last_eligible_s >= decision_cadence_s


class ControlSupervisorBase(ActiveTransactionSupervisor):
    """Shared current transport checks without retired campaign state modes."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(dual_core_transactions=True, **kwargs)
        self._last_arm_monotonic: float | None = None
        self._live_command_ack_required = False
        self._arm_progress_control_ref: str | None = None
        self._arm_progress_reset_seen = False
        self.state.setdefault("response_count", 0)
        self.state.setdefault("supervisor_started_utc", _utc_now())
        self.state.setdefault("qualification_started_utc", None)
        self.state.setdefault("arm_sent_at_utc", None)
        self._save()

    def _command(self, command: str) -> None:
        before = (
            self._check_capture_transport_state()
            if self._live_command_ack_required
            else None
        )
        send_timestamped_command_to_fifo(self.command_fifo, command)
        self._event("command_submitted", command=command)
        if before is None:
            return
        before_sent = int(before["commands_sent"])
        deadline = time.monotonic() + NORMAL_COMMAND_ACK_TIMEOUT_S
        while True:
            current = self._check_capture_transport_state()
            sent = int(current["commands_sent"])
            if sent == before_sent + 1:
                self._event("host_written", command=command, commands_sent=sent)
                return
            if sent != before_sent:
                raise ValueError(
                    "capture command acknowledgement sequence changed "
                    f"unexpectedly: before={before_sent} current={sent}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "capture did not acknowledge the fresh normal command "
                    f"within {NORMAL_COMMAND_ACK_TIMEOUT_S:.1f} s: {command}"
                )
            time.sleep(NORMAL_COMMAND_ACK_POLL_S)

    def _check_capture_transport_state(self) -> dict[str, Any]:
        path = self.run_dir / CAPTURE_TRANSPORT_STATE
        if not path.is_file():
            raise ValueError("capture transport state is missing")
        state = json.loads(path.read_text(encoding="utf-8"))
        age_s = time.time() - _parse_utc_epoch(str(state["updated_utc"]))
        if age_s < -1 or age_s > CAPTURE_TRANSPORT_STATE_MAX_AGE_S:
            raise ValueError(
                f"capture transport state is stale: age_s={age_s:.3f}"
            )
        exact = {
            "capture_active": True,
            "serial_open": True,
            "command_fifo_configured": True,
            "emergency_command_fifo_configured": True,
            "state_heartbeat_interval_s": 5.0,
            "normal_command_batch_limit": 1,
            "normal_command_max_age_s": 2.0,
            "write_timeout_s": 1.0,
        }
        for key, expected in exact.items():
            if state.get(key) != expected:
                raise ValueError(
                    "capture transport state mismatch: "
                    f"{key}={state.get(key)!r}, expected {expected!r}"
                )
        for key in (
            "malformed_utf8",
            "parser_errors",
            "reconnect_count",
            "commands_rejected",
            "emergency_aborts_sent",
        ):
            if int(state.get(key, -1)) != 0:
                raise ValueError(
                    f"capture transport counter {key} is {state.get(key)!r}"
                )
        return state

    def _arm_progress_epoch_ready(
        self, preview: dict[str, str] | None, progress: int
    ) -> bool:
        """Require a fresh estimator-progress reset after each control row."""
        control_ref = None
        if preview is not None:
            control_ref = preview.get("decision_id") or preview.get("control_seq")
        if control_ref != self._arm_progress_control_ref:
            self._arm_progress_control_ref = control_ref
            self._arm_progress_reset_seen = False
        if progress < self.timing.arm_progress_threshold:
            self._arm_progress_reset_seen = True
        return self._arm_progress_reset_seen

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        faults = {
            "dual_core_partition": health.get(("dual_core", "partition_fault")),
            "dual_core_fail_static": health.get(("dual_core", "fail_static")),
            "active_fail_static": health.get(("cx317_active", "fail_static")),
            "capture_dropped": health.get(("capture", "dropped_count")),
            "boundary_dropped": health.get(
                ("capture", "pps_count_boundary_dropped_count")
            ),
            "telemetry_dropped": health.get(("dual_core", "telemetry_dropped")),
        }
        if faults["dual_core_partition"] not in {None, "none"}:
            raise ValueError(
                "dual-core partition fault: "
                f"{faults['dual_core_partition']}"
            )
        for key in ("dual_core_fail_static", "active_fail_static"):
            if faults[key] == "true":
                raise ValueError(f"live {key} asserted")
        for key in ("capture_dropped", "boundary_dropped"):
            if faults[key] not in {None, "0"}:
                raise ValueError(f"live {key} is {faults[key]}")
        if not self._telemetry_drop_runtime_healthy(faults["telemetry_dropped"]):
            raise ValueError(
                f"live telemetry_dropped is {faults['telemetry_dropped']}"
            )
        if self.state["manual_start_sent"]:
            manual_rows = [
                row
                for row in _read_csv(self.run_dir / DAC_CSV)
                if row.get("event") in {"manual_apply", "manual_write_failed"}
            ]
            if manual_rows and manual_rows[-1]["event"] != "manual_apply":
                raise ValueError("one-shot manual start DAC write failed")

    def _telemetry_drop_runtime_healthy(self, observed: str | None) -> bool:
        return observed in {None, "0"}
