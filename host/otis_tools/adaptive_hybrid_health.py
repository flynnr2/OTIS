"""Shared health and setup mechanics for the current adaptive-hybrid supervisor.

The capture process remains the sole serial owner.  This module contains the
small live-only seam shared with :class:`AdaptiveHybridSupervisor`: exact
prewrite health, immutable setup authority, live snapshot selection, and the
setup-result deadline.  Controller policy, transaction interpretation, and
terminal decisions belong to the concrete supervisor.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from .active_status_live_state import LIVE_STATE_PATH, read_live_health_state
from .adaptive_hybrid_contract import ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S
from .adaptive_hybrid_transactions import (
    ACTIVE_CSV,
    QUERY_PERIOD_S,
    _read_csv,
    _utc_now,
)
from .adaptive_hybrid_transport import (
    ControlSupervisorBase,
)
from .prewrite_readiness_contract import (
    PrewriteReadiness,
    evaluate_health_integrity,
)

SETUP_AUTHORITY_CONTRACT = "adaptive_hybrid_setup_authority_v1"
SETUP_AUTHORITY_PATH = Path("reports/adaptive_hybrid_setup_authority_v1.json")
SETUP_AUTHORITY_LIFETIME_S = 30

CONTROL_CSV = Path("csv/control_previews_v1.csv")
DAC_CSV = Path("csv/dac_steps.csv")

QUALIFICATION_DEADLINE_S = 5400
SELECTED_INTERVAL_S = 600
ARM_PROGRESS_THRESHOLD = 520
ARM_LIFETIME_S = 110
PREWRITE_CONTRACT_STARTUP_GRACE_S = 30
SETUP_RESULT_GRACE_S = QUERY_PERIOD_S

# Snapshot completion is a bounded diagnostic wait, not a control-authority or
# USB pending-frame deadline. Waiting carries no actuator authority, while an
# atomic complete snapshot and every health gate remain mandatory before setup.
ACTIVE_SNAPSHOT_COMPLETION_POLL_S = 0.02
ACTIVE_STATUS_COMPLETE_MAX_AGE_S = QUERY_PERIOD_S + 2.0


def canonical_health(
    health: Mapping[tuple[str, str], str],
) -> list[dict[str, str]]:
    return [
        {"component": component, "key": key, "value": value}
        for (component, key), value in sorted(health.items())
    ]


def write_setup_authority_input(path: Path, value: dict[str, object]) -> None:
    """Durably publish one immutable setup-authority record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = dict(value)
    unsigned.pop("record_sha256", None)
    record_hash = sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    retained = {**unsigned, "record_sha256": record_hash}
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(retained, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class AdaptiveHybridSupervisorBase(ControlSupervisorBase):
    """Live-only setup and health seam for the adaptive-hybrid supervisor."""

    def __init__(
        self,
        *,
        prewrite_contract_startup_grace_s: float = (
            PREWRITE_CONTRACT_STARTUP_GRACE_S
        ),
        **kwargs: object,
    ) -> None:
        if prewrite_contract_startup_grace_s <= 0:
            raise ValueError("pre-write startup grace must be positive")
        super().__init__(**kwargs)
        self.prewrite_contract_startup_grace_s = float(
            prewrite_contract_startup_grace_s
        )
        self.arm_progress_threshold = ARM_PROGRESS_THRESHOLD
        self.state.setdefault("setup_confirmed_utc", None)
        self.state.setdefault("prewrite_contract_ready_utc", None)
        self.state.setdefault("latest_prewrite_readiness", None)
        self.state.setdefault("terminal_event_emitted", False)
        self.state.setdefault("host_attach_query_nonce", secrets.randbits(32) or 1)
        self.state.setdefault("setup_authorization_sequence", 0)
        self.state.setdefault("setup_authority_path", None)
        self.state.setdefault("setup_requested_utc", None)
        self._save()

    def _check_prewrite_contract(
        self,
        health: dict[tuple[str, str], str],
        elapsed_monotonic_s: float,
    ) -> PrewriteReadiness | None:
        if not self.control_authority_enabled:
            return None
        # After the one setup stimulus, the transaction and terminal gates own
        # the remaining run. The prewrite contract cannot authorize a retry.
        if self.state["manual_start_sent"]:
            return None
        readiness = self._prewrite_readiness(health)
        value = readiness.as_dict()
        if self.state.get("latest_prewrite_readiness") != value:
            self.state["latest_prewrite_readiness"] = value
            self._save()
        if readiness.ready:
            if self.state["prewrite_contract_ready_utc"] is None:
                self.state["prewrite_contract_ready_utc"] = _utc_now()
                self._save()
                self._event(
                    "adaptive_hybrid_prewrite_runtime_contract_ready",
                    contract_id=readiness.contract_id,
                    planned_live_stimulus=readiness.planned_live_stimulus_code,
                )
            return readiness
        if (
            self.state["prewrite_contract_ready_utc"] is not None
            or elapsed_monotonic_s >= self.prewrite_contract_startup_grace_s
        ):
            raise ValueError(
                "adaptive-hybrid pre-write runtime contract failed: "
                + readiness.diagnostic()
            )
        return readiness

    def _runtime_health_integrity(
        self, health: dict[tuple[str, str], str]
    ):  # type: ignore[no-untyped-def]
        return evaluate_health_integrity(health)

    def _current_health(
        self, *, required_query_nonce: int | None = None
    ) -> dict[tuple[str, str], str]:
        with self._causal_observation(ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S):
            if required_query_nonce is None:
                required_query_nonce = int(self.state["host_attach_query_nonce"])
            while True:
                selection = read_live_health_state(
                    self.run_dir / LIVE_STATE_PATH,
                    required_query_nonce=required_query_nonce,
                )
                if selection.state in {"absent", "unmatched"}:
                    return {}
                if selection.state == "invalid":
                    raise ValueError(
                        "active live-health handoff is invalid: " + selection.diagnostic
                    )
                if selection.observed_monotonic_ns is None:
                    raise ValueError("active live-health handoff has no host clock")
                age_s = (
                    time.monotonic_ns() - selection.observed_monotonic_ns
                ) / 1_000_000_000
                if age_s < -0.001:
                    raise ValueError("active live-health handoff is from the future")
                if selection.state == "complete":
                    if age_s > ACTIVE_STATUS_COMPLETE_MAX_AGE_S:
                        raise ValueError(
                            "active live-health handoff is stale: "
                            f"age_s={age_s:.6f} limit_s="
                            f"{ACTIVE_STATUS_COMPLETE_MAX_AGE_S:.6f}"
                        )
                    return selection.health
                remaining_s = ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S - age_s
                if remaining_s <= 0:
                    raise ValueError(
                        "active live-health snapshot did not complete within "
                        f"{ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S:.3f} s: "
                        f"generation={selection.generation}"
                    )
                self._wait_slice(min(ACTIVE_SNAPSHOT_COMPLETION_POLL_S, remaining_s), allow_lease=True)

    def _setup_command(
        self, health: dict[tuple[str, str], str]
    ) -> tuple[str, dict[str, object]]:
        configuration_identity = self.expected_build_identity.split(":", 1)[1]
        if len(configuration_identity) != 64:
            raise ValueError("setup configuration identity is not SHA-256")
        self.state["setup_authorization_sequence"] = (
            int(self.state["setup_authorization_sequence"]) + 1
        )
        request: dict[str, object] = {
            "authorization_sequence": self.state["setup_authorization_sequence"],
            "status_generation": int(
                health[("adaptive_hybrid", "snapshot_generation_complete")]
            ),
            "query_nonce": int(health[("adaptive_hybrid", "query_nonce")]),
            "expires_s": int(health[("adaptive_hybrid", "uptime_s")])
            + SETUP_AUTHORITY_LIFETIME_S,
            "session_id": int(health[("adaptive_hybrid", "session_id")]),
            "requested_code": self.spec.start_code,
            "one_shot_ordinal": 1,
            "configuration_identity": configuration_identity,
        }
        command = (
            "ACTIVE SETUP "
            f"{request['authorization_sequence']} "
            f"{request['status_generation']} {request['query_nonce']} "
            f"{request['expires_s']} {request['session_id']} "
            f"0x{self.spec.start_code:04X} 1 {configuration_identity}"
        )
        return command, request

    def _retain_setup_authority(
        self,
        health: dict[tuple[str, str], str],
        request: dict[str, object],
    ) -> Path:
        path = self.run_dir / SETUP_AUTHORITY_PATH
        if path.exists():
            raise ValueError(
                "an earlier setup authority record exists; refusing an ambiguous retry"
            )
        write_setup_authority_input(
            path,
            {
                "contract": SETUP_AUTHORITY_CONTRACT,
                "created_utc": _utc_now(),
                "request": request,
                "health": canonical_health(health),
                "active_row_count": len(_read_csv(self.run_dir / ACTIVE_CSV)),
                "dac_row_count": len(_read_csv(self.run_dir / DAC_CSV)),
                "telemetry_drop_baseline": 0,
            },
        )
        self.state["setup_authority_path"] = str(SETUP_AUTHORITY_PATH)
        self._save()
        return path
