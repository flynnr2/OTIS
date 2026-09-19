"""Bounded command transport between the foreground owner and capture worker."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .adaptive_hybrid_contract import NORMAL_COMMAND_ACK_TIMEOUT_S
from .adaptive_hybrid_transactions import (
    LEASE_PERIOD_S,
    AdaptiveHybridTransactionSupervisor,
    _read_csv,
    _utc_now,
)
from .run_spec import CAPTURE_CONFIG
from .serial_commands import send_timestamped_command_to_fifo

ESTIMATES_CSV = Path("csv/estimates_v3.csv")
DAC_CSV = Path("csv/dac_steps.csv")
CAPTURE_TRANSPORT_STATE = Path("reports/capture_device_state.json")
CAPTURE_TRANSPORT_STATE_MAX_AGE_S = 15
NORMAL_COMMAND_ACK_POLL_S = 0.02
RP2040_MONOTONIC_US_PER_SECOND = 1_000_000


class ExplicitSupervisorAbort(BaseException):
    """Unwind a bounded wait after the explicit operator abort was submitted."""


def _parse_utc_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def read_capture_transport_state(
    run_dir: Path,
    *,
    expected_pid: int | None = None,
    allow_priority_abort: bool = False,
    require_clean: bool = True,
    now_monotonic_ns: int | None = None,
) -> dict[str, Any]:
    """Validate one fresh snapshot from the sole capture worker."""
    path = run_dir / CAPTURE_TRANSPORT_STATE
    if not path.is_file():
        raise ValueError("capture transport state is missing")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("capture transport state root is malformed")
    if expected_pid is not None and state.get("pid") != expected_pid:
        raise ValueError("capture transport state belongs to another process")
    updated_ns = state.get("updated_monotonic_ns")
    if type(updated_ns) is not int or updated_ns <= 0:
        raise ValueError("capture transport state updated_monotonic_ns is malformed")
    now_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    age_ns = now_ns - updated_ns
    if age_ns < 0:
        raise ValueError("capture transport state is from the future")
    if age_ns > CAPTURE_TRANSPORT_STATE_MAX_AGE_S * 1_000_000_000:
        raise ValueError(
            f"capture transport state is stale: age_s={age_ns / 1_000_000_000:.3f}"
        )
    exact = {
        "capture_active": True,
        "serial_open": True,
        "command_fifo_configured": True,
        "emergency_command_fifo_configured": True,
        "state_heartbeat_interval_s": CAPTURE_CONFIG["status_interval_s"],
        "normal_command_batch_limit": CAPTURE_CONFIG["normal_command_batch_limit"],
        "normal_command_max_age_s": CAPTURE_CONFIG["normal_command_max_age_s"],
        "write_timeout_s": CAPTURE_CONFIG["write_timeout_s"],
    }
    for key, expected in exact.items():
        if state.get(key) != expected:
            raise ValueError(
                f"capture transport state mismatch: {key}={state.get(key)!r}, "
                f"expected {expected!r}"
            )
    if require_clean:
        for key in ("malformed_utf8", "parser_errors", "reconnect_count", "commands_rejected"):
            if int(state.get(key, -1)) != 0:
                raise ValueError(f"capture transport counter {key} is {state.get(key)!r}")
    abort_latched = state.get("emergency_abort_latched")
    aborts_sent = int(state.get("emergency_aborts_sent", -1))
    if type(abort_latched) is not bool or aborts_sent not in {0, 1}:
        raise ValueError("capture priority-abort state is malformed")
    if not allow_priority_abort and (abort_latched or aborts_sent):
        raise ValueError("capture priority-abort ingress is already latched")
    return state

class ControlSupervisorBase(AdaptiveHybridTransactionSupervisor):
    """Shared current transport checks without retired campaign state modes."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._last_arm_monotonic: float | None = None
        self._live_command_ack_required = False
        self._arm_progress_control_ref: str | None = None
        self._arm_progress_reset_seen = False
        self.state.setdefault("response_count", 0)
        self.state.setdefault("supervisor_started_utc", _utc_now())
        self.state.setdefault("qualification_started_utc", None)
        self.state.setdefault("arm_sent_at_utc", None)
        self._save()

    @contextmanager
    def _causal_observation(self, timeout_s: float, *, deadline_ns: int | None = None):
        previous = getattr(self, "_causal_deadline_ns", None)
        deadline = time.monotonic_ns() + int(timeout_s * 1_000_000_000)
        if deadline_ns is not None:
            if type(deadline_ns) is not int or deadline_ns <= 0:
                raise ValueError("causal observation deadline is malformed")
            deadline = min(deadline, deadline_ns)
        if previous is not None:
            deadline = min(deadline, previous)
        self._causal_deadline_ns = deadline
        try:
            self._check_wait_deadline()
            yield deadline
            self._check_wait_deadline()
        finally:
            self._causal_deadline_ns = previous

    def _check_wait_deadline(self, deadline_ns: int | None = None) -> None:
        active = getattr(self, "_causal_deadline_ns", None)
        if active is not None:
            deadline_ns = active if deadline_ns is None else min(active, deadline_ns)
        if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
            raise TimeoutError("causal observation deadline expired")

    def _poll_wait_abort(self) -> None:
        if (
            not self._live_command_ack_required
            or getattr(self, "expected_capture_pid", None) is None
        ):
            return
        state = read_capture_transport_state(
            self.run_dir,
            expected_pid=getattr(self, "expected_capture_pid", None),
            allow_priority_abort=True,
            require_clean=False,
        )
        if (
            state.get("emergency_abort_latched") is True
            or int(state.get("emergency_aborts_sent", 0)) != 0
        ):
            self._observe_explicit_capture_abort(state)
            raise ExplicitSupervisorAbort()

    def _observe_explicit_capture_abort(self, state: dict[str, Any]) -> None:
        """Concrete owner records the externally submitted priority abort."""
        del state
        raise NotImplementedError

    def _wait_slice(self, seconds: float, *, allow_lease: bool = False,
                    deadline_ns: int | None = None) -> None:
        self._poll_wait_abort()
        self._check_wait_deadline(deadline_ns)
        last_lease = getattr(self, "_last_lease_monotonic_ns", None)
        if (allow_lease and last_lease is not None
            and not getattr(self, "_normal_command_ack_pending", False)
            and self._startup_census_admitted()
            and time.monotonic_ns() - last_lease >= int(LEASE_PERIOD_S * 1_000_000_000)):
            self._renew_lease()
        self._check_wait_deadline(deadline_ns)
        active = getattr(self, "_causal_deadline_ns", None)
        bounds = [value for value in (active, deadline_ns) if value is not None]
        if bounds:
            seconds = min(seconds, (min(bounds) - time.monotonic_ns()) / 1_000_000_000)
        time.sleep(max(0.0, seconds))
        self._poll_wait_abort()
        self._check_wait_deadline(deadline_ns)

    def _command(self, command: str) -> None:
        self._poll_wait_abort()
        self._check_wait_deadline()
        if getattr(self, "_normal_command_ack_pending", False):
            raise ValueError("normal command acknowledgement is unresolved")
        before = (
            self._check_capture_transport_state()
            if self._live_command_ack_required
            else None
        )
        deadline_ns = time.monotonic_ns() + int(NORMAL_COMMAND_ACK_TIMEOUT_S * 1_000_000_000)
        self._normal_command_ack_pending = before is not None
        send_timestamped_command_to_fifo(self.command_fifo, command)
        self._event("command_submitted", command=command)
        if before is None:
            return
        before_sent = int(before["commands_sent"])
        while True:
            self._poll_wait_abort()
            self._check_wait_deadline(deadline_ns)
            current = self._check_capture_transport_state()
            sent = int(current["commands_sent"])
            if sent == before_sent + 1:
                self._normal_command_ack_pending = False
                self._event("host_written", command=command, commands_sent=sent)
                return
            if sent != before_sent:
                raise ValueError(
                    "capture command acknowledgement sequence changed "
                    f"unexpectedly: before={before_sent} current={sent}"
                )
            # A timed-out/contradictory ACK stays unresolved. Do not insert a
            # lease or another normal command into that counter frontier.
            self._wait_slice(NORMAL_COMMAND_ACK_POLL_S, deadline_ns=deadline_ns)

    def _read_capture_transport_state(self) -> dict[str, Any]:
        return read_capture_transport_state(
            self.run_dir,
            expected_pid=getattr(self, "expected_capture_pid", None),
            allow_priority_abort=True,
        )

    def _check_capture_transport_state(self) -> dict[str, Any]:
        state = self._read_capture_transport_state()
        if (
            state.get("emergency_abort_latched") is True
            or int(state.get("emergency_aborts_sent", 0)) != 0
        ):
            self._observe_explicit_capture_abort(state)
            raise ExplicitSupervisorAbort()
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
        if progress < self.arm_progress_threshold:
            self._arm_progress_reset_seen = True
        return self._arm_progress_reset_seen

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        faults = {
            "dual_core_partition": health.get(("dual_core", "partition_fault")),
            "dual_core_fail_static": health.get(("dual_core", "fail_static")),
            "active_fail_static": health.get(("adaptive_hybrid", "fail_static")),
            "capture_faults": health.get(("capture", "error_flags")),
            "snapshot_ring_full": health.get(("capture", "snapshot_ring_full_count")),
            "irq_budget_exhausted": health.get(("capture", "irq_budget_exhausted_count")),
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
        for key in ("capture_faults", "snapshot_ring_full", "irq_budget_exhausted"):
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
