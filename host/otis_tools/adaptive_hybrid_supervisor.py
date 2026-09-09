"""Executable fail-static supervisor for the frozen ADAPTIVE_HYBRID live campaign.

The capture process remains the sole serial owner.  This supervisor submits
only timestamped commands through that owner's bounded normal FIFO and submits
``ACTIVE ABORT`` through the independent emergency FIFO.  Every active
transaction phase is durably retained and replayed by the shared ACT machinery
before the corresponding firmware evidence acknowledgement is released.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import time
from typing import Any

from .abort_transport import AbortFifo
from .adaptive_hybrid_evidence import (
    IndependentReplayMismatch,
    ResponseCheckpointRejected,
)
from .adaptive_hybrid_contract import (
    AdaptiveHybridProgramme,
    ADAPTIVE_HYBRID_PROGRAMME,
    programme_from_mapping,
)
from .adaptive_hybrid_policy import AdaptiveHybridPolicy, policy_from_mapping
from .authoritative_inputs import (
    ROOT_PROFILE,
    authoritative_binding,
    authoritative_document,
    validate_authoritative_inputs,
)
from .active_status_live_state import (
    LIVE_FRONTIER_COMPONENT,
    LIVE_FRONTIER_DOMAIN_KEY,
    LIVE_FRONTIER_TICKS_KEY,
)
from .adaptive_hybrid_transport import (
    ESTIMATES_CSV,
    RP2040_MONOTONIC_US_PER_SECOND,
    ControlSupervisorBase,
    _parse_utc_epoch,
)
from .adaptive_hybrid_transactions import (
    ACTIVE_CSV,
    LEASE_PERIOD_S,
QUERY_PERIOD_S,
    CampaignSpec,
    _read_csv,
    _utc_now,
)
FORWARDED_OUTPUT_STATUS_PERIOD_S = 60.0
from .contracts import CsvValidationContext, validate_csv
from .firmware_bindings import current_forwarded_clock_contract
from .prewrite_readiness_contract import (
    GNSS_OPERATIONAL_PREWRITE_EXACT,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    PrewriteReadiness,
    evaluate_prewrite_readiness as evaluate_setup_prewrite_readiness,
)
from .adaptive_hybrid_health import (
    ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S,
    ACTIVE_STATUS_COMPLETE_MAX_AGE_S,
    ARM_LIFETIME_S,
    ARM_PROGRESS_THRESHOLD,
    CONTROL_CSV,
    CORRECTION_RESPONSE_RESERVE_S,
    DAC_CSV,
    DECISION_CADENCE_S,
    SELECTED_INTERVAL_S,
    AdaptiveHybridSupervisorBase,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG
from .time_domains import forward_progress


def gnss_operational_runtime_invariant_errors(
    health: dict[tuple[str, str], str], *, require_present: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    bootstrap = health.get(("gnss_receiver", "operational_bootstrap_state"))
    if not require_present and bootstrap in {None, "in_progress"}:
        return (), ()
    missing: list[str] = []
    mismatches: list[str] = []
    for key, required in GNSS_OPERATIONAL_PREWRITE_EXACT.items():
        observed = health.get(key)
        name = f"{key[0]}.{key[1]}"
        if observed is None:
            if require_present:
                missing.append(name)
        elif observed != required:
            mismatches.append(f"{name}={observed!r}, expected {required!r}")
    return tuple(missing), tuple(mismatches)


TOOL_ID = "adaptive_hybrid_supervisor_v1"
PROGRAMME_ID = ADAPTIVE_HYBRID_PROGRAMME.programme_id
PROFILE_ID = ADAPTIVE_HYBRID_PROGRAMME.profile_id
RUNTIME_RUN_IDENTITY = ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity
ACTIVE_HYBRID_CSV = Path("csv/active_hybrid_decisions_v2.csv")

SETUP_CODE = ADAPTIVE_HYBRID_PROGRAMME.setup_code
MAXIMUM_APPLICATIONS = ADAPTIVE_HYBRID_PROGRAMME.maximum_applications
MAXIMUM_CUMULATIVE_MOVEMENT_CODES = ADAPTIVE_HYBRID_PROGRAMME.maximum_cumulative_movement_codes
MAXIMUM_STEP_CODES = ADAPTIVE_HYBRID_PROGRAMME.maximum_step_codes
MINIMUM_CODE = ADAPTIVE_HYBRID_PROGRAMME.minimum_code
MAXIMUM_CODE = ADAPTIVE_HYBRID_PROGRAMME.maximum_code
QUALIFIED_DURATION_S = ADAPTIVE_HYBRID_PROGRAMME.qualified_duration_s
ABSOLUTE_WALL_LIMIT_S = ADAPTIVE_HYBRID_PROGRAMME.absolute_wall_limit_s
MINIMUM_PHASE_MATERIAL_APPLICATIONS = 2
# ``uptime_s`` is an integer status value, while estimator timestamps retain
# the fractional RP2040 timer coordinate.  A fresh estimator can also be
# published after the latest complete queried status snapshot.  This bound is
# therefore the complete-snapshot freshness limit plus the one-second uptime
# quantization interval; it is a coherence guard, not qualified duration.
QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S = (
    int(ACTIVE_STATUS_COMPLETE_MAX_AGE_S) + 1
)

# CONFIG? publishes these non-active records before the solicited ACTIVE
# snapshot.  The atomic live-health reducer carries their latest values into
# that snapshot, allowing the integrated programme to fail closed on a D9
# register/GPIO contradiction without granting D9 measurement or controller
# authority.  D6 is deliberately different: its status must be observable,
# but every value (including a local fault) remains admissible here.
_FORWARDED_CLOCK_CONTRACT, _FORWARDED_CLOCK_CONTRACT_SHA256 = (
    current_forwarded_clock_contract()
)
FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH = {
    ("forwarded_clock_output", "contract_id"): (
        str(_FORWARDED_CLOCK_CONTRACT["contract_id"])
    ),
    ("forwarded_clock_output", "contract_sha256"): (
        _FORWARDED_CLOCK_CONTRACT_SHA256
    ),
    ("forwarded_clock_output", "state"): (
        str(_FORWARDED_CLOCK_CONTRACT["state"])
    ),
    ("forwarded_clock_output", "source"): str(_FORWARDED_CLOCK_CONTRACT["source"]),
    ("forwarded_clock_output", "destination"): str(
        _FORWARDED_CLOCK_CONTRACT["destination"]
    ),
    ("forwarded_clock_output", "integer_divider"): str(
        _FORWARDED_CLOCK_CONTRACT["integer_divider"]
    ),
    ("forwarded_clock_output", "fractional_divider"): str(
        _FORWARDED_CLOCK_CONTRACT["fractional_divider"]
    ),
    ("forwarded_clock_output", "applied_auxsrc"): str(
        _FORWARDED_CLOCK_CONTRACT["applied_auxsrc"]
    ),
    ("forwarded_clock_output", "applied_integer_divider"): str(
        _FORWARDED_CLOCK_CONTRACT["integer_divider"]
    ),
    ("forwarded_clock_output", "applied_fractional_divider"): str(
        _FORWARDED_CLOCK_CONTRACT["fractional_divider"]
    ),
    ("forwarded_clock_output", "source_gpio_function"): "8",
    ("forwarded_clock_output", "destination_gpio_function"): "8",
    ("forwarded_clock_output", "inversion"): str(
        int(bool(_FORWARDED_CLOCK_CONTRACT["inversion"]))
    ),
    ("forwarded_clock_output", "drive_strength_ma"): str(
        _FORWARDED_CLOCK_CONTRACT["drive_strength_ma"]
    ),
    ("forwarded_clock_output", "slew_rate"): str(
        _FORWARDED_CLOCK_CONTRACT["slew_rate"]
    ),
    ("forwarded_clock_output", "nominal_frequency_hz"): str(
        _FORWARDED_CLOCK_CONTRACT["nominal_frequency_hz"]
    ),
    ("forwarded_clock_output", "readback_valid"): "true",
}
FORWARDED_MONITOR_OBSERVABILITY_KEYS = (
    ("forwarded_clock_monitor", "state"),
    ("forwarded_clock_monitor", "configured"),
    ("forwarded_clock_monitor", "running"),
    ("forwarded_clock_monitor", "session"),
    ("forwarded_clock_monitor", "snapshot_count"),
    ("forwarded_clock_monitor", "no_snapshot_count"),
    ("forwarded_clock_monitor", "fifo_backlog_count"),
    ("forwarded_clock_monitor", "pio_rxstall_count"),
    ("forwarded_clock_monitor", "fault_flags"),
)


def _programme_terminal_decision(
    programme: AdaptiveHybridProgramme,
    suffix: str,
) -> str:
    """Resolve one exact terminal from the sole current programme contract."""

    matches = sorted(
        decision
        for decision in programme.terminal_decisions
        if decision.endswith(suffix)
    )
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        f"{programme.key} must declare exactly one terminal ending {suffix!r}"
    )


def forwarded_output_integration_prewrite_evidence(
    health: dict[tuple[str, str], str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Validate D9 exactness and D6 observability without using either as truth."""

    missing: list[str] = []
    mismatches: list[str] = []
    for key, expected in FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH.items():
        observed = health.get(key)
        label = f"{key[0]}.{key[1]}"
        if observed is None:
            missing.append(label)
        elif observed != expected:
            mismatches.append(f"{label}={observed!r}, expected {expected!r}")
    first_valid_key = ("forwarded_clock_output", "first_valid_ticks")
    first_valid = health.get(first_valid_key)
    if first_valid is None:
        missing.append("forwarded_clock_output.first_valid_ticks")
    else:
        try:
            if int(first_valid) <= 0:
                raise ValueError
        except ValueError:
            mismatches.append(
                "forwarded_clock_output.first_valid_ticks must be positive"
            )
    for key in FORWARDED_MONITOR_OBSERVABILITY_KEYS:
        if key not in health:
            missing.append(f"{key[0]}.{key[1]}")
    return tuple(missing), tuple(mismatches)

HYBRID_STATES = frozenset(
    {
        "SETUP_PENDING",
        "FREQUENCY_ACQUIRE",
        "PHASE_QUALIFY",
        "FIRST_PHASE_TRANSACTION",
        "HYBRID_TRACKING",
        "PHASE_DEGRADED_FREQUENCY_ONLY",
        "FAIL_STATIC",
    }
)
ARMABLE_HYBRID_STATES = frozenset(
    {"FREQUENCY_ACQUIRE", "PHASE_QUALIFY", "HYBRID_TRACKING"}
)
def _sha256_identity(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"ADAPTIVE_HYBRID manifest {label} is not a SHA-256 identity")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            f"ADAPTIVE_HYBRID manifest {label} is not a SHA-256 identity"
        ) from exc
    return value

@dataclass(frozen=True)
class RuntimeEnvelope:
    programme: AdaptiveHybridProgramme
    manifest_sha256: str
    bundle_sha256: str
    policy_sha256: str
    build_identity: str
    uf2_sha256: str
    policy: AdaptiveHybridPolicy
    policy_document: dict[str, Any]
    natural_policy_sha256: str
    frequency_estimator_sha256: str
    phase_estimator_sha256: str
    wall_origin_utc: str


def _profile_binding_sha256(
    frozen_inputs: object, policy: dict[str, Any], name: str
) -> str:
    binding = policy.get("bindings", {}).get(name)
    if not isinstance(binding, str):
        raise ValueError(f"adaptive-hybrid policy binding {name!r} is unavailable")
    return str(authoritative_binding(frozen_inputs, binding)["sha256"])


def _runtime_envelope(manifest: dict[str, Any]) -> RuntimeEnvelope:
    """Extract the one current manifest and policy envelope."""

    programme = programme_from_mapping(manifest)
    section = manifest.get(programme.manifest_section, {})
    firmware = manifest.get("firmware", {})
    binding = manifest.get("policy", {})
    if not isinstance(section, dict) or not isinstance(firmware, dict) or not isinstance(binding, dict):
        raise ValueError("adaptive-hybrid manifest envelope is malformed")
    frozen_inputs = manifest.get("authoritative_inputs")
    validate_authoritative_inputs(frozen_inputs)
    policy = authoritative_document(frozen_inputs, ROOT_PROFILE)
    root_binding = authoritative_binding(frozen_inputs, ROOT_PROFILE)
    selected = policy_from_mapping(
        policy, policy_sha256=str(root_binding["sha256"])
    )
    build_identity = _manifest_build_identity(manifest)
    uf2 = firmware.get("uf2", {})
    if (
        manifest.get("programme_id") != programme.programme_id
        or manifest.get("image_identity") != programme.profile_id
        or manifest.get("run_identity") != programme.runtime_run_identity
        or manifest.get("stage") != programme.live_stage
        or selected.policy_id != programme.policy_id
        or binding.get("policy_sha256") != selected.policy_sha256
        or binding.get("path") != ROOT_PROFILE
        or binding.get("sha256") != root_binding["sha256"]
        or binding.get("size_bytes") != root_binding["size_bytes"]
        or not isinstance(uf2, dict)
    ):
        raise ValueError("adaptive-hybrid manifest identity or policy differs")
    return RuntimeEnvelope(
        programme=programme,
        manifest_sha256=_sha256_identity(manifest.get("manifest_sha256"), "manifest_sha256"),
        bundle_sha256=_sha256_identity(manifest.get("bundle", {}).get("bundle_sha256"), "bundle.bundle_sha256"),
        policy_sha256=selected.policy_sha256,
        build_identity=build_identity,
        uf2_sha256=_sha256_identity(uf2.get("sha256"), "firmware.uf2.sha256"),
        policy=selected,
        policy_document=policy,
        natural_policy_sha256=selected.policy_sha256,
        frequency_estimator_sha256=_profile_binding_sha256(
            frozen_inputs, policy, "frequency_estimator"
        ),
        phase_estimator_sha256=_profile_binding_sha256(
            frozen_inputs, policy, "phase_estimator"
        ),
        wall_origin_utc=str(manifest["started_at_utc"]),
    )


def load_active_hybrid_spec(
    manifest: dict[str, Any],
) -> tuple[CampaignSpec, dict[str, str]]:
    """Load the exact runtime contract from a validated live manifest."""

    envelope = _runtime_envelope(manifest)
    programme = envelope.programme
    policy = envelope.policy_document
    frozen_inputs = manifest["authoritative_inputs"]
    identities = {
        "estimator_sha256": _profile_binding_sha256(
            frozen_inputs, policy, "frequency_estimator"
        ),
        "model_sha256": _profile_binding_sha256(
            frozen_inputs, policy, "plant_model"
        ),
        "active_policy_sha256": envelope.policy_sha256,
        "response_policy_sha256": _profile_binding_sha256(
            frozen_inputs, policy, "response_classification"
        ),
        "numerical_policy_sha256": envelope.natural_policy_sha256,
    }
    return (
        CampaignSpec(
            campaign=programme.campaign_name,
            profile=programme.profile_id,
            run_identity=programme.runtime_run_identity,
            start_code=programme.setup_code,
            correction_limit=programme.authorized_maximum_physical_applications,
            cumulative_limit=(
                programme.authorized_maximum_cumulative_movement_codes
            ),
            minimum_code=programme.minimum_code,
            maximum_code=programme.maximum_code,
            maximum_step=programme.maximum_step_codes,
        ),
        identities,
    )


def _truth(health: dict[tuple[str, str], str], key: str) -> bool:
    return health.get(("adaptive_hybrid", key)) == "true"


_AUTHORITATIVE_CAPTURE_COUNTERS = (
    "rejected_window_count",
    "physical_aperture_incomplete_count",
    "association_loss_count",
)
_ADAPTIVE_HYBRID_AUTHORITATIVE_CAPTURE_COUNTERS = _AUTHORITATIVE_CAPTURE_COUNTERS + (
    "boundary_ring_dropped_count",
    "missing_pps_count",
    "pps_interval_anomaly_count",
    "count_saturated_count",
    "boundary_sequence_gap_count",
    "boundary_sequence_duplicate_count",
    "boundary_overflow_count",
    "counter_snapshot_invalid_count",
    "snapshot_overwrite_count",
    "snapshot_continuity_loss_count",
    "snapshot_pio_rxstall_count",
    "snapshot_dma_error_count",
    "snapshot_dma_stopped_count",
    "physical_pps_missing_count",
)
_ADAPTIVE_HYBRID_RECOVERABLE_APERTURE_COUNTERS = frozenset(
    {"rejected_window_count", "pps_interval_anomaly_count"}
)
_AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH = {
    "valid": "true",
    "control_eligible": "true",
    "reference_validity": "valid",
    "count_validity": "valid",
    "boundary_validity": "valid",
    "aperture_validity": "valid",
    "observation_pair_validity": "valid",
    "fifo_continuity": "continuous",
    "association_state": "clean",
}


def _authoritative_capture_counters(
    programme: AdaptiveHybridProgramme,
) -> tuple[str, ...]:
    # The aperture-count endpoint requires every irreversible D14/D8
    # discontinuity emitted by the installed snapshot backend to remain at its
    # qualified-origin value.  The instantaneous validity fields can recover;
    # these monotonic counters preserve the otherwise-hidden gap.  Retain the
    if programme.qualified_d14_aperture_count is not None:
        return _ADAPTIVE_HYBRID_AUTHORITATIVE_CAPTURE_COUNTERS
    return _AUTHORITATIVE_CAPTURE_COUNTERS


def _authoritative_capture_health_faults(
    health: dict[tuple[str, str], str],
) -> list[str]:
    faults: list[str] = []
    for key, expected in _AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH.items():
        observed = health.get(("pps_gate", key))
        if observed != expected:
            faults.append(f"{key}:{observed!r}!={expected!r}")
    return faults


class AdaptiveHybridSupervisor(AdaptiveHybridSupervisorBase):
    """ADAPTIVE_HYBRID live authority layered on the proven active-control transport."""

    def __init__(
        self,
        *,
        manifest: dict[str, Any],
        manifest_path: Path,
        **kwargs: object,
    ) -> None:
        envelope = _runtime_envelope(manifest)
        spec = kwargs.get("spec")
        if not isinstance(spec, CampaignSpec):
            raise ValueError("ADAPTIVE_HYBRID supervisor requires its manifest-derived spec")
        if (
            spec.run_identity != manifest.get("run_identity")
            or kwargs.get("expected_build_identity") != envelope.build_identity
        ):
            raise ValueError("ADAPTIVE_HYBRID supervisor inputs differ from the live manifest")
        self.programme = envelope.programme
        super().__init__(
            allow_manual_start=True,
            allow_arm=True,
            # The installed profile deliberately inhibits D14/D8 control
            # eligibility for 600 s.  Prior physical adaptive-hybrid evidence first
            # observed the same predicate at 612 s, so retain its frozen
            # 660 s qualification deadline rather than the older adaptive-hybrid
            # 30 s complete-snapshot grace.
            prewrite_contract_startup_grace_s=(
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
            qualified_timeout_s=self.programme.qualified_duration_s,
            observational_responses=(
                self.programme.response_checkpoint_observational
            ),
            **kwargs,
        )
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        self.envelope = envelope
        self.phase_estimator_sha256 = envelope.phase_estimator_sha256
        self.natural_policy = envelope.policy
        self.natural_policy_document = envelope.policy_document
        self.natural_estimator_sha256 = envelope.frequency_estimator_sha256
        self.expected_active_policy_sha256 = envelope.policy_sha256
        self.part = f"{self.programme.key}_active_hybrid_live"
        exact_state = {
            "programme_id": self.programme.programme_id,
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": envelope.manifest_sha256,
            "bundle_sha256": envelope.bundle_sha256,
            "policy_sha256": envelope.policy_sha256,
            "build_identity": envelope.build_identity,
            "uf2_sha256": envelope.uf2_sha256,
            "runtime_run_identity": self.spec.run_identity,
            "wall_origin_utc": envelope.wall_origin_utc,
        }
        for key, value in exact_state.items():
            prior = self.state.get(key)
            if prior is not None and prior != value:
                raise ValueError(
                    f"ADAPTIVE_HYBRID retained supervisor {key} differs from the manifest"
                )
            self.state[key] = value
        self.state.setdefault("qualified_origin_estimate_id", None)
        self.state.setdefault("qualified_origin_timestamp_ticks", None)
        self.state.setdefault("qualified_origin_session_id", None)
        self.state.setdefault("qualified_origin_extended_timestamp_ticks", None)
        self.state.setdefault("qualified_frontier_raw_ticks", None)
        self.state.setdefault("qualified_frontier_extended_ticks", None)
        self.state.setdefault("qualified_endpoint_extended_timestamp_ticks", None)
        self.state.setdefault("qualified_d14_accepted_window_origin", None)
        self.state.setdefault("qualified_d14_reference_sequence_origin", None)
        self.state.setdefault("qualified_d14_accepted_apertures", None)
        self.state.setdefault("qualified_d14_reference_sequence_endpoint", None)
        self.state.setdefault("qualified_authoritative_capture_baseline", None)
        self.state.setdefault("qualified_d14_completed_apertures_before_segment", 0)
        self.state.setdefault("qualified_d14_segment_accepted_window_origin", None)
        self.state.setdefault("qualified_d14_segment_reference_sequence_origin", None)
        self.state.setdefault("authoritative_capture_interventions", [])
        self.state.setdefault("latest_hybrid_state", None)
        self.state.setdefault("first_phase_checkpoint_passed", False)
        self.state.setdefault("first_phase_observation_checkpoint_exact", False)
        self.state.setdefault("later_authority_released", False)
        self.state.setdefault("phase_material_application_count", 0)
        self.state.setdefault("terminal_static_code", None)
        self.state.setdefault("host_verification_hold", None)
        self.state.setdefault("gnss_metadata_hold", None)
        self.state.setdefault("gnss_metadata_hold_count", 0)
        self.state.setdefault("controller_authority_inhibited_reason", None)
        self.state.setdefault("controller_authority_inhibited_utc", None)
        self.state.setdefault("persistent_wrong_direction_terminal", False)
        # The attachment nonce is immutable package identity. Runtime queries
        # rotate a separate nonce so a fresh file cannot masquerade as the
        # causally requested post-frontier snapshot.
        self.state.setdefault(
            "active_snapshot_request_nonce",
            int(self.state["host_attach_query_nonce"]),
        )
        self._save()

    def _programme_event(self, suffix: str, **payload: object) -> None:
        self._event(f"{self.programme.key}_{suffix}", **payload)

    def _current_health(
        self, *, required_query_nonce: int | None = None
    ) -> dict[tuple[str, str], str]:
        if required_query_nonce is None:
            required_query_nonce = int(
                self.state["active_snapshot_request_nonce"]
            )
        return super()._current_health(
            required_query_nonce=required_query_nonce
        )

    def _identity_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        return super()._identity_ready(health)

    def _fresh_active_snapshot_after(
        self, generation: int
    ) -> dict[tuple[str, str], str]:
        prior_nonce = int(self.state["active_snapshot_request_nonce"])
        query_nonce = prior_nonce + 1 if prior_nonce < 0xFFFFFFFF else 1
        if query_nonce == int(self.state["host_attach_query_nonce"]):
            query_nonce = query_nonce + 1 if query_nonce < 0xFFFFFFFF else 1
        self.state["active_snapshot_request_nonce"] = query_nonce
        self._save()
        self._programme_event(
            "active_snapshot_query_started",
            query_nonce=query_nonce,
            pre_submit_snapshot_generation=generation,
        )
        self._command(f"ACTIVE SNAPSHOT {query_nonce}")
        # One request remains outstanding until a matching, later complete
        # generation arrives. Fresh host publication alone is insufficient:
        # periodic snapshots retain the prior nonce, and a generation at or
        # behind the pre-submit frontier cannot answer this request.
        deadline = time.monotonic() + ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S
        while True:
            health = self._current_health(required_query_nonce=query_nonce)
            observed = int(
                health.get(("adaptive_hybrid", "snapshot_generation_complete"), "0")
            )
            if observed > generation:
                self._programme_event(
                    "active_snapshot_query_completed",
                    query_nonce=query_nonce,
                    pre_submit_snapshot_generation=generation,
                    response_snapshot_generation=observed,
                )
                return health
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "ADAPTIVE_HYBRID causally bound active snapshot did not follow "
                    f"query_nonce={query_nonce} generation={generation}"
                )
            time.sleep(0.05)

    def _prepare_evidence_acknowledgement(
        self, row: dict[str, str], phase: int
    ) -> dict[str, object]:
        current = self._current_health()
        generation = int(
            current.get(("adaptive_hybrid", "snapshot_generation_complete"), "0")
        )
        health = self._fresh_active_snapshot_after(generation)
        expected_phase = {
            1: "request_pending",
            2: "acceptance_pending",
            3: "application_pending",
            4: "response_pending",
        }[phase]
        request_sequence = int(row["request_sequence"])
        stale_phases = {
            1: (),
            2: ("request_pending",),
            3: ("request_pending", "acceptance_pending"),
            4: (
                "request_pending",
                "acceptance_pending",
                "application_pending",
            ),
        }[phase]
        # A periodic query can already be in flight when the ACT record arrives.
        # Its completion is generation-fresh but causally precedes the record.
        # Wait through that bounded stale frontier instead of aborting a valid
        # transaction.  Four queries remain inside the firmware's frozen
        # 30-second evidence-acknowledgement deadline.
        for _ in range(4):
            observed_phase = health.get(("adaptive_hybrid", "evidence_phase"), "")
            observed_request = int(
                health.get(("adaptive_hybrid", "evidence_request_sequence"), "0")
            )
            if (
                observed_phase == expected_phase
                and observed_request == request_sequence
            ):
                return {
                    "pre_submit_snapshot_generation": int(
                        health[("adaptive_hybrid", "snapshot_generation_complete")]
                    ),
                    "pre_submit_evidence_phase": expected_phase,
                }
            if observed_phase == "evidence_clear" and observed_request == 0:
                pass
            elif (
                observed_phase in stale_phases
                and observed_request == request_sequence
            ):
                pass
            else:
                raise ValueError(
                    "ADAPTIVE_HYBRID firmware evidence frontier differs before "
                    "acknowledgement: "
                    f"expected_request={request_sequence} "
                    f"expected_phase={expected_phase} "
                    f"observed_request={observed_request} "
                    f"observed_phase={observed_phase}"
                )
            generation = int(
                health[("adaptive_hybrid", "snapshot_generation_complete")]
            )
            health = self._fresh_active_snapshot_after(generation)
        raise TimeoutError(
            "ADAPTIVE_HYBRID firmware evidence frontier did not reach the expected "
            "pre-acknowledgement state: "
            f"request={request_sequence} phase={expected_phase}"
        )

    def _confirm_evidence_acknowledgement(
        self, acknowledgement: dict[str, object]
    ) -> bool:
        phase = int(acknowledgement["phase"])
        request_sequence = int(acknowledgement["request_sequence"])
        baseline = int(acknowledgement["pre_submit_snapshot_generation"])
        pre_submit_phase = str(acknowledgement["pre_submit_evidence_phase"])
        permitted = {
            1: {
                "evidence_clear",
                "acceptance_pending",
                "application_pending",
                "response_pending",
            },
            2: {"evidence_clear", "application_pending", "response_pending"},
            3: {"evidence_clear", "response_pending"},
            4: {"evidence_clear"},
        }[phase]
        # A periodic status query submitted immediately before the evidence
        # command can arrive after the pre-submit baseline and is therefore
        # generation-fresh but causally stale.  Observe one complete snapshot
        # per supervisor pass and persist that frontier in the inflight record.
        # This keeps platform-health checks interleaved with acknowledgement
        # observation instead of blocking them behind four back-to-back queries.
        baseline = int(
            acknowledgement.get("last_observed_snapshot_generation", baseline)
        )
        health = self._fresh_active_snapshot_after(baseline)
        observed_generation = int(
            health[("adaptive_hybrid", "snapshot_generation_complete")]
        )
        acknowledgement["last_observed_snapshot_generation"] = observed_generation
        observed_phase = health.get(("adaptive_hybrid", "evidence_phase"), "")
        observed_request = int(
            health.get(("adaptive_hybrid", "evidence_request_sequence"), "0")
        )
        if observed_phase == pre_submit_phase:
            if observed_request != request_sequence:
                raise ValueError(
                    "ADAPTIVE_HYBRID evidence acknowledgement retained a contradictory "
                    "request identity"
                )
            return False
        if (
            observed_phase == "evidence_clear" and observed_request != 0
        ) or (
            observed_phase != "evidence_clear"
            and observed_request != request_sequence
        ):
            raise ValueError(
                "ADAPTIVE_HYBRID evidence acknowledgement advanced to a contradictory "
                "request identity"
            )
        if observed_phase not in permitted:
            raise ValueError(
                "ADAPTIVE_HYBRID evidence acknowledgement advanced to an impossible "
                "phase ordering: "
                f"submitted_phase={phase} "
                f"pre_submit_phase={pre_submit_phase} "
                f"observed_phase={observed_phase}"
            )
        self._programme_event(
            "firmware_evidence_acknowledgement_confirmed",
            request_sequence=request_sequence,
            phase=phase,
            snapshot_generation=int(
                health[("adaptive_hybrid", "snapshot_generation_complete")]
            ),
            resulting_evidence_phase=observed_phase,
        )
        return True

    def _prewrite_readiness(
        self, health: dict[tuple[str, str], str]
    ) -> PrewriteReadiness:
        """Require the firmware's exact setup-authority inputs before setup."""

        identity = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "image_identity": self.spec.profile,
            **self.identities,
        }
        readiness = evaluate_setup_prewrite_readiness(
            health,
            expected_identity=identity,
            planned_live_stimulus_code=self.spec.start_code,
            active_row_count=len(_read_csv(self.run_dir / ACTIVE_CSV)),
            dac_row_count=len(_read_csv(self.run_dir / DAC_CSV)),
            telemetry_drop_baseline=0,
        )
        missing = list(readiness.missing)
        mismatches = list(readiness.mismatches)
        if health.get(("adaptive_hybrid", "query_nonce")) != str(
            self.state["active_snapshot_request_nonce"]
        ):
            mismatches.append("solicited post-attachment snapshot is absent")
        if self.programme.forwarded_output_integration:
            output_missing, output_mismatches = (
                forwarded_output_integration_prewrite_evidence(health)
            )
            missing.extend(output_missing)
            mismatches.extend(output_mismatches)
        return PrewriteReadiness(
            contract_id=(
                f"{self.programme.key}_active_hybrid_prewrite_runtime_contract_v1"
            ),
            ready=not missing and not mismatches,
            missing=tuple(dict.fromkeys(missing)),
            mismatches=tuple(dict.fromkeys(mismatches)),
            planned_live_stimulus_code=readiness.planned_live_stimulus_code,
            physical_dac_confirmation=readiness.physical_dac_confirmation,
        )

    def _validate_hybrid_decisions(self) -> None:
        path = self.run_dir / ACTIVE_HYBRID_CSV
        if not path.exists():
            return
        validation = validate_csv(
            path,
            CsvValidationContext(
                "active_hybrid_decisions_v2",
                frozenset(),
                frozenset({"rp2040_monotonic_us64"}),
            ),
        )
        if validation.errors:
            raise ValueError(
                "AHY contract validation failed: "
                + "; ".join(validation.errors)
            )
        expected = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "image_identity": self.spec.profile,
            "frequency_estimator_sha256": self.identities["estimator_sha256"],
            "phase_estimator_sha256": self.phase_estimator_sha256,
            "active_policy_sha256": self.identities["active_policy_sha256"],
            "response_policy_sha256": self.identities["response_policy_sha256"],
            "actionable": "false",
        }
        for row in _read_csv(path):
            for field, value in expected.items():
                if row.get(field) != value:
                    raise ValueError(
                        f"AHY identity mismatch for {field}: "
                        f"{row.get(field)!r} != {value!r}"
                    )

    def _enter_host_verification_hold(
        self, error: Exception, *, source: str = "host_verifier"
    ) -> None:
        """Inhibit host authority without terminating firmware acquisition."""
        existing = self.state.get("host_verification_hold")
        if isinstance(existing, dict):
            existing["last_observed_utc"] = _utc_now()
            existing["last_source"] = source
            existing["last_error"] = str(error)
            existing["occurrence_count"] = int(
                existing.get("occurrence_count", 1)
            ) + 1
            self._save()
            return
        try:
            rows = _read_csv(self.run_dir / ACTIVE_CSV)
        except (OSError, UnicodeError, ValueError):
            rows = []
        physical = next(
            (
                row
                for row in reversed(rows)
                if row.get("event")
                in {"response", "application", "manual_start"}
            ),
            {},
        )

        def integer(field: str, fallback: int = 0) -> int:
            try:
                return int(physical.get(field, fallback))
            except (TypeError, ValueError):
                return fallback

        retained_code = self.state.get("terminal_static_code")
        fallback_code = retained_code if isinstance(retained_code, int) else 0

        hold = {
            "entered_utc": _utc_now(),
            "last_observed_utc": _utc_now(),
            "source": source,
            "last_source": source,
            "error_type": type(error).__name__,
            "error": str(error),
            "last_error": str(error),
            "occurrence_count": 1,
            "review_status": "operator_review_required",
            "new_authority": False,
            "capture_and_serial_owner_retained": True,
            "evidence_ack_policy": "continue_exact_withhold_unverifiable",
            "record_sequence": integer("transaction_record_sequence"),
            "request_sequence": integer("request_sequence"),
            "response_class": physical.get("response_class", "unavailable"),
            "applied_code": integer("applied_code", fallback_code),
            "dac_epoch": integer("dac_epoch"),
            "correction_count": integer("correction_count"),
            "cumulative_movement_codes": integer(
                "cumulative_movement_codes"
            ),
        }
        self.state["host_verification_hold"] = hold
        self.state["arm_pending"] = False
        self.state["arm_sent_at_utc"] = None
        self._save()
        try:
            self._programme_event("host_verification_hold_entered", **hold)
        except OSError:
            # The atomically retained state is authoritative; a broken
            # supplementary event sink must not defeat the review hold.
            pass

    def _process_transactions_during_host_verification_hold(self) -> None:
        """Drain only transactions which still pass the frozen exact guards."""
        prior_terminal = self.state.get("terminal")
        try:
            # This continues already-authorized request/accept/application/
            # response handshakes.  It does not issue SETUP or ARM authority.
            super()._process_transactions()
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            self._enter_host_verification_hold(
                exc, source="transaction_evidence_during_hold"
            )
            return
        terminal = self.state.get("terminal")
        if prior_terminal is None and isinstance(terminal, dict):
            # A host-side response interpretation is an alert pending review,
            # not authority to stop the acquisition or classify the campaign.
            self.state["terminal"] = None
            self._enter_host_verification_hold(
                ValueError(
                    "transaction consumer proposed terminal: "
                    + json.dumps(terminal, sort_keys=True)
                ),
                source="transaction_terminal_during_hold",
            )
            self._save()

    def _validate_hybrid_decisions_or_hold(self) -> bool:
        try:
            self._validate_hybrid_decisions()
        except (OSError, UnicodeError, ValueError) as exc:
            self._enter_host_verification_hold(exc)
            return False
        return True

    def _process_transactions(self) -> None:
        if self.state.get("host_verification_hold") is not None:
            self._process_transactions_during_host_verification_hold()
            return
        if not self._validate_hybrid_decisions_or_hold():
            return
        prior_terminal = self.state.get("terminal")
        try:
            super()._process_transactions()
        except IndependentReplayMismatch as exc:
            self._enter_host_verification_hold(exc)
            return
        except ResponseCheckpointRejected as exc:
            rows = _read_csv(self.run_dir / ACTIVE_CSV)
            response = next(
                (row for row in reversed(rows) if row.get("event") == "response"),
                {},
            )
            self._programme_event(
                "first_phase_response_checkpoint_rejected",
                error=str(exc),
                request_sequence=int(response.get("request_sequence", "0")),
                response_class=response.get("response_class", "unavailable"),
                observed_response_hz=float(
                    response.get("observed_response_hz", "nan")
                ),
            )
            self._enter_host_verification_hold(
                exc, source="response_checkpoint_replay"
            )
            return
        if self.state.get("inflight_evidence_acknowledgement") is not None:
            # The already-written command is awaiting a causally later
            # firmware snapshot.  Do not perform downstream transaction or
            # controller accounting and, critically, do not resend it.
            return
        # Exhausted frequency authority is a static observation interval; the
        # instrument remains under observation through its finite duration.
        terminal = self.state.get("terminal")
        if prior_terminal is None and isinstance(terminal, dict) and terminal.get(
            "reason"
        ) in {"inside_deadband", "limit_reached", "correction_limit_reached"}:
            self.state["terminal"] = None
            self._save()
        if self.programme.sustained_regulation and self.state["terminal"] is None:
            responses = [
                row
                for row in _read_csv(self.run_dir / ACTIVE_CSV)
                if row.get("event") == "response"
            ]
            applications = {
                row.get("request_sequence"): row
                for row in _read_csv(self.run_dir / ACTIVE_CSV)
                if row.get("event") == "application"
            }
            phase_by_decision = {
                row.get("decision_sequence"): row.get("phase_epoch")
                for row in _read_csv(self.run_dir / ACTIVE_HYBRID_CSV)
                if row.get("phase_epoch") not in {None, "", "0"}
            }
            if len(responses) >= 2:
                last_two = responses[-2:]
                classes = [row.get("response_class") for row in last_two]
                phase_epochs = [
                    phase_by_decision.get(
                        applications.get(row.get("request_sequence"), {}).get(
                            "decision_sequence"
                        )
                    )
                    for row in last_two
                ]
                if (
                    all(value in {"wrong_sign", "growing_error"} for value in classes)
                    and phase_epochs[0] is not None
                    and phase_epochs[0] == phase_epochs[1]
                ):
                    self.state["persistent_wrong_direction_terminal"] = True
                    self._programme_event(
                        "persistent_wrong_direction_response_terminal",
                        request_sequences=[
                            int(row["request_sequence"]) for row in last_two
                        ],
                        response_classes=classes,
                        phase_epoch=int(phase_epochs[0]),
                    )
                    self._enter_host_verification_hold(
                        ValueError("phase_or_frequency_regulation_not_sustained"),
                        source="persistent_response_interpretation",
                    )
        self._validate_hybrid_decisions_or_hold()

    def _runtime_health_integrity(
        self, health: dict[tuple[str, str], str]
    ):  # type: ignore[no-untyped-def]
        # Apply the D14/D8/GNSS/capture integrity contract. Phase and controller
        # authority are checked separately below.
        return super()._runtime_health_integrity(health)

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        # Preview streams remain zero-authority; the combined controller has a
        # separate explicit transaction boundary.
        hybrid_state = health.get(("adaptive_hybrid", "hybrid_state"))
        hybrid_reason = health.get(("adaptive_hybrid", "hybrid_reason"), "unknown")
        prospective_controller_inhibit = (
            self.programme.response_checkpoint_observational
            and hybrid_state == "FAIL_STATIC"
            and hybrid_reason
            in {"prospective_repeated_alternation", "prospective_low_efficiency_path"}
        )
        if (
            prospective_controller_inhibit
            and not self.programme.controller_inhibit_acquisition_continues
        ):
            self.state["arm_pending"] = False
            self.state["arm_sent_at_utc"] = None
            self._abort(hybrid_reason)
            return
        metadata_hold_active = (
            health.get(("adaptive_hybrid", "state")) == "GNSS_METADATA_HOLD"
            and _truth(health, "gnss_metadata_hold_active")
        )
        platform_health = health
        if (
            prospective_controller_inhibit
            and self.programme.controller_inhibit_acquisition_continues
        ):
            self.state["arm_pending"] = False
            self.state["arm_sent_at_utc"] = None
            if self.state.get("controller_authority_inhibited_reason") is None:
                self.state["controller_authority_inhibited_reason"] = hybrid_reason
                self.state["controller_authority_inhibited_utc"] = _utc_now()
                self._save()
                self._programme_event(
                    "controller_authority_inhibited_acquisition_continues",
                    reason=hybrid_reason,
                    d14_d8_acquisition_continues=True,
                    new_dac_authority=False,
                    terminal_deferred_to_exact_qualified_endpoint=True,
                )
            # This firmware assertion is the intended controller-local
            # authority inhibition. Preserve all independent platform and
            # D14/D8 checks while preventing it from terminating the finite
            # integrated long run.
            platform_health = dict(health)
            platform_health[("adaptive_hybrid", "fail_static")] = "false"
        ControlSupervisorBase._check_fail_static_health(self, platform_health)
        gnss_missing, gnss_mismatches = (
            gnss_operational_runtime_invariant_errors(
                health,
                require_present=(
                    self.programme.forwarded_output_integration
                    and self.state["prewrite_contract_ready_utc"] is not None
                ),
            )
            if self.programme.forwarded_output_integration
            else ((), ())
        )
        if gnss_missing or gnss_mismatches:
            raise ValueError(
                "integrated GNSS bootstrap/runtime invariant changed: "
                + "; ".join((*gnss_missing, *gnss_mismatches))
            )
        if (
            self.programme.forwarded_output_integration
            and self.state["prewrite_contract_ready_utc"] is not None
        ):
            output_missing, output_mismatches = (
                forwarded_output_integration_prewrite_evidence(health)
            )
            d9_missing = tuple(
                item
                for item in output_missing
                if not item.startswith("forwarded_clock_monitor.")
            )
            if d9_missing or output_mismatches:
                raise ValueError(
                    "integrated D9 digital configuration/readback lost: "
                    + "; ".join((*d9_missing, *output_mismatches))
                )
        integrity = self._runtime_health_integrity(platform_health)
        if integrity.mismatches or (
            self.state["prewrite_contract_ready_utc"] is not None
            and integrity.missing
        ):
            raise ValueError(
                "ADAPTIVE_HYBRID continuous runtime health contract failed: "
                + integrity.diagnostic()
            )
        setup_established = self.state["setup_confirmed_utc"] is not None
        if setup_established and not self._identity_ready(health):
            raise ValueError("ADAPTIVE_HYBRID exact runtime identity became unavailable")
        if setup_established:
            required_true = (
                "capture_lease_live",
                "setup_reference_eligible",
                "setup_partition_healthy",
            )
            if not metadata_hold_active:
                required_true = (*required_true, "setup_gnss_eligible")
            unhealthy = [key for key in required_true if not _truth(health, key)]
            if unhealthy:
                raise ValueError(
                    "ADAPTIVE_HYBRID shared D14/D8/GNSS/capture qualification lost: "
                    + ", ".join(unhealthy)
                )
            self._update_gnss_metadata_hold(health, metadata_hold_active)

        if hybrid_state is None:
            if setup_established:
                raise ValueError("ADAPTIVE_HYBRID hybrid firmware state is absent")
            return
        if hybrid_state not in self.programme.hybrid_states:
            raise ValueError(f"unexpected ADAPTIVE_HYBRID hybrid state: {hybrid_state!r}")
        if hybrid_state == "FAIL_STATIC" and not (
            prospective_controller_inhibit
            and self.programme.controller_inhibit_acquisition_continues
        ):
            raise ValueError(f"ADAPTIVE_HYBRID firmware entered FAIL_STATIC: {hybrid_reason}")

        corrections = int(
            health.get(("adaptive_hybrid", "correction_count"), "0")
        )
        movement = int(
            health.get(("adaptive_hybrid", "cumulative_movement_codes"), "0")
        )
        material = int(
            health.get(
                ("adaptive_hybrid", "phase_material_application_count"), "0"
            )
        )
        phase_nonzero = int(
            health.get(
                ("adaptive_hybrid", "phase_nonzero_application_count"), "0"
            )
        )
        frequency_only = int(
            health.get(
                ("adaptive_hybrid", "frequency_only_application_count"), "0"
            )
        )
        checkpoint = _truth(health, "first_phase_checkpoint_passed")

        # Preserve the latest confirmed physical state before evaluating any
        # post-application accounting invariant that can terminate the run.
        # Otherwise an accounting fault can leave the abort-delivery gate
        # waiting for the pre-application code even though firmware has
        # already durably reported the new applied code and DAC epoch.
        confirmed_applied_changed = False
        if _truth(health, "confirmed_applied_code_known"):
            applied = int(health[("adaptive_hybrid", "confirmed_applied_code")], 0)
            if not self.programme.minimum_code <= applied <= self.programme.maximum_code:
                raise ValueError("ADAPTIVE_HYBRID confirmed code is outside the frozen range")
            if self.state.get("terminal_static_code") != applied:
                self.state["terminal_static_code"] = applied
                confirmed_applied_changed = True

        # phase_nonzero is an overlapping descriptive count: a combined
        # request can contain a non-zero phase term yet round to the same DAC
        # delta as the frequency-only counterfactual. Such an application is
        # both phase_nonzero and frequency_only, but is not phase-material.
        # The mutually exclusive partition is phase_material versus
        # frequency_only; each individual count must remain bounded by the
        # global correction count.
        if (
            corrections
            > self.programme.authorized_maximum_physical_applications
            or corrections > self.programme.authorized_maximum_applications
            or movement
            > self.programme.authorized_maximum_cumulative_movement_codes
            or material > phase_nonzero
            or phase_nonzero > corrections
            or material + frequency_only > corrections
        ):
            raise ValueError("ADAPTIVE_HYBRID firmware exceeded the frozen global authority")
        # The firmware checkpoint flag describes the current transaction and
        # clears when a later material application starts.  Later authority is
        # permitted by the first response checkpoint that the host already
        # observed and durably latched, not by that transient current flag.
        if material > 1 and not self.state["later_authority_released"]:
            raise ValueError("ADAPTIVE_HYBRID later material authority preceded its checkpoint")
        if hybrid_state == "HYBRID_TRACKING" and not checkpoint:
            raise ValueError("ADAPTIVE_HYBRID HYBRID_TRACKING lacks the first checkpoint")
        hold = self.state.get("host_verification_hold")
        if isinstance(hold, dict) and (
            corrections != hold.get("correction_count")
            or movement != hold.get("cumulative_movement_codes")
            or (
                _truth(health, "confirmed_applied_code_known")
                and self.state.get("terminal_static_code")
                != hold.get("applied_code")
            )
        ):
            raise ValueError("ADAPTIVE_HYBRID actuation changed during host verification hold")

        changed = hybrid_state != self.state.get("latest_hybrid_state")
        dirty = changed or confirmed_applied_changed
        if changed:
            self.state["latest_hybrid_state"] = hybrid_state
        if self.state["phase_material_application_count"] != material:
            self.state["phase_material_application_count"] = material
            dirty = True
        if checkpoint and not self.state["first_phase_checkpoint_passed"]:
            self.state["first_phase_checkpoint_passed"] = True
            if self.programme.response_checkpoint_observational:
                self.state["first_phase_observation_checkpoint_exact"] = True
            dirty = True
        if hybrid_state == "HYBRID_TRACKING" and checkpoint:
            if not self.state["later_authority_released"]:
                self.state["later_authority_released"] = True
                dirty = True
                self._programme_event(
                    (
                        "first_phase_observation_checkpoint_release_observed"
                        if self.programme.response_checkpoint_observational
                        else "first_phase_checkpoint_release_observed"
                    ),
                    hybrid_state=hybrid_state,
                    phase_material_application_count=material,
                )
        if dirty:
            self._save()

    def _update_gnss_metadata_hold(
        self,
        health: dict[tuple[str, str], str],
        active: bool,
    ) -> None:
        retained = self.state.get("gnss_metadata_hold")
        if active:
            if not _truth(health, "confirmed_applied_code_known"):
                raise ValueError("GNSS metadata hold lacks confirmed DAC identity")
            code = int(health[("adaptive_hybrid", "confirmed_applied_code")], 0)
            epoch = int(health[("adaptive_hybrid", "dac_epoch")])
            corrections = int(health[("adaptive_hybrid", "correction_count")])
            movement = int(
                health[("adaptive_hybrid", "cumulative_movement_codes")]
            )
            entry_sequence = int(
                health[("adaptive_hybrid", "gnss_metadata_hold_entry_sequence")]
            )
            if not isinstance(retained, dict):
                retained = {
                    "entry_sequence": entry_sequence,
                    "applied_code": code,
                    "dac_epoch": epoch,
                    "correction_count": corrections,
                    "cumulative_movement_codes": movement,
                    "transaction_resolution_pending": _truth(
                        health, "gnss_metadata_hold_transaction_pending"
                    ),
                    "entered_utc": _utc_now(),
                }
                self.state["gnss_metadata_hold"] = retained
                self.state["gnss_metadata_hold_count"] = int(
                    self.state.get("gnss_metadata_hold_count", 0)
                ) + 1
                self._save()
                self._programme_event(
                    "gnss_metadata_hold_entered",
                    **retained,
                    d14_d8_measurement_continues=True,
                    new_correction_authority=False,
                )
            elif retained.get("transaction_resolution_pending"):
                if not _truth(
                    health, "gnss_metadata_hold_transaction_pending"
                ):
                    retained.update(
                        {
                            "applied_code": code,
                            "dac_epoch": epoch,
                            "correction_count": corrections,
                            "cumulative_movement_codes": movement,
                            "transaction_resolution_pending": False,
                        }
                    )
                    self._save()
                    self._programme_event(
                        "gnss_metadata_hold_transaction_resolved",
                        applied_code=code,
                        dac_epoch=epoch,
                        correction_count=corrections,
                        cumulative_movement_codes=movement,
                    )
            elif (
                code != retained["applied_code"]
                or epoch != retained["dac_epoch"]
                or corrections != retained["correction_count"]
                or movement != retained["cumulative_movement_codes"]
                or entry_sequence != retained["entry_sequence"]
            ):
                raise ValueError("actuation identity changed during GNSS metadata hold")
            return
        if not isinstance(retained, dict):
            return
        metadata_sequence = int(
            health[("adaptive_hybrid", "gnss_metadata_requalification_sequence")]
        )
        qualification_frontier = int(
            health[("adaptive_hybrid", "gnss_metadata_qualification_frontier")]
        )
        observation_sequence = int(
            health[("adaptive_hybrid", "d14_d8_observation_sequence")]
        )
        if (
            metadata_sequence <= retained["entry_sequence"]
            or observation_sequence <= qualification_frontier
            or health.get(("adaptive_hybrid", "state")) != "DISARMED"
        ):
            raise ValueError("GNSS metadata hold cleared without fresh causal requalification")
        self.state["gnss_metadata_hold"] = None
        self._save()
        self._programme_event(
            "gnss_metadata_hold_requalified",
            metadata_sequence=metadata_sequence,
            qualification_frontier=qualification_frontier,
            post_qualification_observation_sequence=observation_sequence,
            applied_code=retained["applied_code"],
            dac_epoch=retained["dac_epoch"],
        )

    @staticmethod
    def _fresh_authoritative_selected_estimate(
        rows: list[dict[str, str]], *, dac_epoch: int,
    ) -> dict[str, str] | None:
        expected_dac_ref = f"live:DAC:{dac_epoch}"
        candidates = [
            row
            for row in rows
            if row.get("estimator_version")
            == "adaptive_hybrid_selected_600s_nonoverlap_v1"
            and row.get("observation_validity") == "valid"
            and row.get("reference_validity") == "valid"
            and row.get("reference_continuity") == "true"
            and row.get("count_validity") == "valid"
            and row.get("count_continuity") == "true"
            and row.get("diagnostic_health") == "healthy"
            and row.get("preview_eligibility") == "true"
            and row.get("source_dac_ref") == expected_dac_ref
            and int(row.get("accepted_sample_count") or "0") >= SELECTED_INTERVAL_S
        ]
        return candidates[-1] if candidates else None

    def _maybe_qualify(self, health: dict[tuple[str, str], str]) -> None:
        if self.state["qualification_started_utc"] is not None:
            return
        if self.state["setup_confirmed_utc"] is None or not self._identity_ready(health):
            return
        if (
            not _truth(health, "manual_start_confirmed")
            or not _truth(health, "confirmed_applied_code_known")
            or int(health.get(("adaptive_hybrid", "confirmed_applied_code"), "0"), 0)
            != self.programme.setup_code
            or int(health.get(("adaptive_hybrid", "dac_epoch"), "0")) < 1
        ):
            return
        dac_epoch = int(health[("adaptive_hybrid", "dac_epoch")])
        estimate = self._fresh_authoritative_selected_estimate(
            _read_csv(self.run_dir / ESTIMATES_CSV), dac_epoch=dac_epoch
        )
        if estimate is None:
            return
        if estimate.get("time_domain") != "rp2040_monotonic_us32":
            raise ValueError("ADAPTIVE_HYBRID qualified origin is not in rp2040_monotonic_us32")
        try:
            origin_ticks = int(estimate["estimator_timestamp_ticks"])
            current_uptime_s = int(health[("adaptive_hybrid", "uptime_s")])
            session_id = int(health[("adaptive_hybrid", "session_id")])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ADAPTIVE_HYBRID qualified origin device clock is malformed") from exc
        authoritative_capture_baseline: dict[str, int] | None = None
        qualified_origin_extended_ticks: int | None = None
        qualified_frontier_raw_ticks: int | None = None
        qualified_frontier_extended_ticks: int | None = None
        if self.programme.integrated_long_run:
            if _authoritative_capture_health_faults(health):
                return
            try:
                session_id = int(health[("pps_gate", "snapshot_session")])
                frontier_ticks = int(
                    health[(LIVE_FRONTIER_COMPONENT, LIVE_FRONTIER_TICKS_KEY)]
                )
                frontier_domain = health[
                    (LIVE_FRONTIER_COMPONENT, LIVE_FRONTIER_DOMAIN_KEY)
                ]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "exact retained producer frontier is absent"
                ) from exc
            if frontier_domain != "rp2040_monotonic_us32":
                raise ValueError(
                    "retained producer frontier domain differs"
                )
            forward = forward_progress(
                origin_ticks,
                frontier_ticks,
                domain="rp2040_monotonic_us32",
                allow_equal=True,
            )
            reverse = forward_progress(
                frontier_ticks,
                origin_ticks,
                domain="rp2040_monotonic_us32",
                allow_equal=True,
            )
            maximum_lead_ticks = (
                QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S
                * RP2040_MONOTONIC_US_PER_SECOND
            )
            if forward.valid and forward.distance_ticks is not None and (
                forward.distance_ticks <= maximum_lead_ticks
            ):
                qualified_origin_extended_ticks = origin_ticks
                qualified_frontier_raw_ticks = frontier_ticks
                qualified_frontier_extended_ticks = (
                    origin_ticks + forward.distance_ticks
                )
            elif reverse.valid and reverse.distance_ticks is not None and (
                reverse.distance_ticks <= maximum_lead_ticks
            ):
                return
            else:
                raise ValueError("ADAPTIVE_HYBRID qualified origin device clock is incoherent")
            authoritative_capture_baseline = {}
            for key in _authoritative_capture_counters(self.programme):
                try:
                    value = int(health[("pps_gate", key)])
                except (KeyError, TypeError, ValueError):
                    return
                if value < 0:
                    return
                authoritative_capture_baseline[key] = value
            if self.programme.qualified_d14_aperture_count is not None:
                try:
                    accepted_origin = int(
                        health[("pps_gate", "accepted_window_count")]
                    )
                    reference_origin = int(
                        health[("pps_gate", "boundary_reference_sequence")]
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "ADAPTIVE_HYBRID qualified D14 aperture origin is unavailable"
                    ) from exc
                if not (0 <= accepted_origin < 1 << 32) or not (
                    0 <= reference_origin < 1 << 32
                ):
                    raise ValueError("ADAPTIVE_HYBRID qualified D14 aperture origin is malformed")
        else:
            current_uptime_lower_bound_ticks = (
                current_uptime_s * RP2040_MONOTONIC_US_PER_SECOND
            )
            maximum_coherent_origin_ticks = (
                current_uptime_s + QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S
            ) * RP2040_MONOTONIC_US_PER_SECOND
            if (
                origin_ticks <= 0
                or session_id <= 0
                or origin_ticks > maximum_coherent_origin_ticks
            ):
                raise ValueError("ADAPTIVE_HYBRID qualified origin device clock is incoherent")
            # The integer uptime value is a conservative lower bound.  Do not
            # reject a legitimate exact estimator timestamp in its fractional
            # second (or just after the last complete status snapshot); wait until
            # a later snapshot's lower bound has actually reached it.
            if origin_ticks > current_uptime_lower_bound_ticks:
                return
        self.state["qualification_started_utc"] = _utc_now()
        self.state["qualified_origin_estimate_id"] = estimate["estimate_id"]
        self.state["qualified_origin_timestamp_ticks"] = origin_ticks
        self.state["qualified_origin_session_id"] = session_id
        if self.programme.integrated_long_run:
            self.state["qualified_origin_extended_timestamp_ticks"] = (
                qualified_origin_extended_ticks
            )
            self.state["qualified_frontier_raw_ticks"] = (
                qualified_frontier_raw_ticks
            )
            self.state["qualified_frontier_extended_ticks"] = (
                qualified_frontier_extended_ticks
            )
            if self.programme.qualified_d14_aperture_count is not None:
                self.state["qualified_d14_accepted_window_origin"] = accepted_origin
                self.state["qualified_d14_reference_sequence_origin"] = reference_origin
                self.state["qualified_d14_completed_apertures_before_segment"] = 0
                self.state["qualified_d14_segment_accepted_window_origin"] = (
                    accepted_origin
                )
                self.state["qualified_d14_segment_reference_sequence_origin"] = (
                    reference_origin
                )
        self.state["qualified_authoritative_capture_baseline"] = (
            authoritative_capture_baseline
        )
        self._save()
        self._programme_event(
            "qualified_origin_established",
            estimate_id=estimate["estimate_id"],
            estimator_timestamp_ticks=origin_ticks,
            time_domain="rp2040_monotonic_us32",
            capture_session=session_id,
            source_count_ref=estimate["source_count_ref"],
            source_dac_ref=estimate["source_dac_ref"],
            dac_epoch=dac_epoch,
            qualified_duration_s=self.programme.qualified_duration_s,
            qualified_d14_aperture_count=(
                self.programme.qualified_d14_aperture_count
            ),
            accepted_window_count_origin=self.state.get(
                "qualified_d14_accepted_window_origin"
            ),
            boundary_reference_sequence_origin=self.state.get(
                "qualified_d14_reference_sequence_origin"
            ),
            authoritative_capture_baseline=self.state.get(
                "qualified_authoritative_capture_baseline"
            ),
        )

    def _abort_on_authoritative_capture_discontinuity(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        """Stop an integrated long run before post-discontinuity work."""

        if not self.programme.integrated_long_run:
            return False
        origin_session = self.state.get("qualified_origin_session_id")
        if origin_session is None:
            return False
        faults: list[str] = []
        if type(origin_session) is not int:
            faults.append("qualified_capture_session_malformed")
            origin_session = -1
        faults.extend(_authoritative_capture_health_faults(health))
        try:
            current_session = int(health[("pps_gate", "snapshot_session")])
        except (KeyError, TypeError, ValueError):
            current_session = -1
            faults.append("current_capture_session_unavailable")

        if current_session != origin_session:
            faults.append(
                f"capture_session_changed:{origin_session}->{current_session}"
            )
        baseline = self.state.get("qualified_authoritative_capture_baseline")
        if not isinstance(baseline, dict):
            baseline = {}
            faults.append("qualified_authoritative_capture_baseline_unavailable")
        observed_counters: dict[str, int | str | None] = {}
        changed_counters: dict[str, tuple[int, int]] = {}
        for key in _authoritative_capture_counters(self.programme):
            try:
                expected = int(baseline[key])
                observed = int(health[("pps_gate", key)])
            except (KeyError, TypeError, ValueError):
                observed_counters[key] = health.get(("pps_gate", key))
                faults.append(f"{key}_unavailable")
                continue
            observed_counters[key] = observed
            if observed != expected:
                faults.append(f"{key}_changed:{expected}->{observed}")
                changed_counters[key] = (expected, observed)
        if not faults:
            return False

        if self._recover_adaptive_hybrid_aperture_extension(
            health=health,
            origin_session=origin_session,
            current_session=current_session,
            baseline=baseline,
            observed_counters=observed_counters,
            changed_counters=changed_counters,
            faults=faults,
        ):
            return False

        self.state["arm_pending"] = False
        self.state["arm_sent_at_utc"] = None
        reason = (
            f"{self.programme.key}_D14_D8_authority_or_capture_fault:"
            + ",".join(faults)
        )
        detail = {
            "reason": reason,
            "qualified_origin_session_id": origin_session,
            "observed_capture_session_id": current_session,
            "authoritative_capture_baseline": baseline,
            "observed_authoritative_capture_counters": observed_counters,
            "last_confirmed_code": self.state.get("terminal_static_code"),
            "new_control_authority": False,
        }
        self.state["authoritative_capture_terminal_detail"] = detail
        self._enter_host_verification_hold(
            ValueError(reason), source="authoritative_capture_observer"
        )
        try:
            self._programme_event(
                "authoritative_capture_discontinuity_observed", **detail
            )
        except OSError:
            # The retained hold and detail are decision-bearing; this
            # supplementary event must never delay continued acquisition.
            pass
        return True

    def _recover_adaptive_hybrid_aperture_extension(
        self,
        *,
        health: dict[tuple[str, str], str],
        origin_session: int,
        current_session: int,
        baseline: dict[str, Any],
        observed_counters: dict[str, int | str | None],
        changed_counters: dict[str, tuple[int, int]],
        faults: list[str],
    ) -> bool:
        """Rebase a bounded ADAPTIVE_HYBRID rejected-aperture interval after recovery.

        The lifetime counters remain immutable provenance.  Only the two
        counters which describe rejected D14/D8 windows may advance, and only
        after every instantaneous capture gate has returned clean in the same
        session.  Qualified duration remains a sum of accepted apertures; the
        rejected reference boundaries never enter that sum.
        """

        if (
            self.programme.qualified_d14_aperture_count is None
            or current_session != origin_session
            or not changed_counters
            or not set(changed_counters) <= _ADAPTIVE_HYBRID_RECOVERABLE_APERTURE_COUNTERS
            or _authoritative_capture_health_faults(health)
        ):
            return False
        expected_faults = {
            f"{key}_changed:{before}->{after}"
            for key, (before, after) in changed_counters.items()
        }
        if set(faults) != expected_faults or any(
            after <= before for before, after in changed_counters.values()
        ):
            return False
        if any(type(value) is not int for value in observed_counters.values()):
            return False

        try:
            current_identity = {
                "applied_code": int(
                    health[("adaptive_hybrid", "confirmed_applied_code")], 0
                ),
                "dac_epoch": int(health[("adaptive_hybrid", "dac_epoch")]),
                "correction_count": int(
                    health[("adaptive_hybrid", "correction_count")]
                ),
                "cumulative_movement_codes": int(
                    health[("adaptive_hybrid", "cumulative_movement_codes")]
                ),
            }
        except (KeyError, TypeError, ValueError):
            return False
        if (
            not _truth(health, "confirmed_applied_code_known")
            or current_identity["applied_code"]
            != self.state.get("terminal_static_code")
        ):
            return False

        hold = self.state.get("host_verification_hold")
        if isinstance(hold, dict):
            reason_prefix = f"{self.programme.key}_D14_D8_authority_or_capture_fault:"
            if (
                hold.get("source") != "authoritative_capture_observer"
                or not str(hold.get("error", "")).startswith(reason_prefix)
            ):
                return False
            if any(hold.get(key) != value for key, value in current_identity.items()):
                return False

        try:
            accepted_now = int(health[("pps_gate", "accepted_window_count")])
            reference_now = int(
                health[("pps_gate", "boundary_reference_sequence")]
            )
            completed = self._qualified_d14_apertures(health)
        except (KeyError, TypeError, ValueError):
            return False
        if completed is None:
            return False

        accepted_segment_origin = self.state.get(
            "qualified_d14_segment_accepted_window_origin"
        )
        reference_segment_origin = self.state.get(
            "qualified_d14_segment_reference_sequence_origin"
        )
        if type(accepted_segment_origin) is not int:
            accepted_segment_origin = self.state.get(
                "qualified_d14_accepted_window_origin"
            )
        if type(reference_segment_origin) is not int:
            reference_segment_origin = self.state.get(
                "qualified_d14_reference_sequence_origin"
            )
        if type(accepted_segment_origin) is not int or type(reference_segment_origin) is not int:
            return False
        accepted_in_segment = (accepted_now - accepted_segment_origin) & 0xFFFFFFFF
        references_in_segment = (reference_now - reference_segment_origin) & 0xFFFFFFFF
        excluded_reference_boundaries = references_in_segment - accepted_in_segment
        rejected_window_delta = changed_counters.get(
            "rejected_window_count", (0, 0)
        )
        if (
            references_in_segment < accepted_in_segment
            or excluded_reference_boundaries
            != rejected_window_delta[1] - rejected_window_delta[0]
        ):
            return False

        interventions = self.state.get("authoritative_capture_interventions")
        if not isinstance(interventions, list):
            return False
        intervention = {
            "intervention_sequence": len(interventions) + 1,
            "recorded_utc": _utc_now(),
            "reason": "recovered_rejected_aperture_interval",
            "capture_session": current_session,
            "baseline_before": dict(baseline),
            "baseline_after": dict(observed_counters),
            "counter_deltas": {
                key: after - before
                for key, (before, after) in sorted(changed_counters.items())
            },
            "segment_accepted_window_origin": accepted_segment_origin,
            "segment_reference_sequence_origin": reference_segment_origin,
            "accepted_window_count_at_recovery": accepted_now,
            "boundary_reference_sequence_at_recovery": reference_now,
            "accepted_apertures_in_segment": accepted_in_segment,
            "excluded_reference_boundaries_in_segment": excluded_reference_boundaries,
            "qualified_accepted_apertures_after_segment": completed,
            "current_capture_gates_clean": True,
            "new_control_authority": False,
            "control_identity_at_recovery": current_identity,
            "superseded_host_verification_hold": hold,
        }
        interventions.append(intervention)
        self.state["qualified_authoritative_capture_baseline"] = dict(
            observed_counters
        )
        self.state["qualified_d14_completed_apertures_before_segment"] = completed
        self.state["qualified_d14_segment_accepted_window_origin"] = accepted_now
        self.state["qualified_d14_segment_reference_sequence_origin"] = reference_now
        self.state["authoritative_capture_terminal_detail"] = None
        if isinstance(hold, dict):
            self.state["host_verification_hold"] = None
        self.state["arm_pending"] = False
        self.state["arm_sent_at_utc"] = None
        self._save()
        try:
            self._programme_event(
                "authoritative_capture_corrected_extension_started", **intervention
            )
        except OSError:
            pass
        return True

    def _qualified_elapsed_ticks(
        self, health: dict[tuple[str, str], str]
    ) -> int | None:
        origin = self.state.get("qualified_origin_timestamp_ticks")
        origin_session = self.state.get("qualified_origin_session_id")
        if origin is None and origin_session is None:
            return None
        if type(origin) is not int or type(origin_session) is not int:
            raise ValueError("ADAPTIVE_HYBRID retained qualified origin is incomplete")
        try:
            current_session = int(
                health[
                    (
                        "pps_gate"
                        if self.programme.integrated_long_run
                        else "adaptive_hybrid",
                        "snapshot_session"
                        if self.programme.integrated_long_run
                        else "session_id",
                    )
                ]
            )
            current_uptime_s = int(health[("adaptive_hybrid", "uptime_s")])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ADAPTIVE_HYBRID current qualified device clock is malformed") from exc
        if current_session != origin_session:
            raise ValueError("ADAPTIVE_HYBRID capture session changed after qualified origin")
        if self.programme.integrated_long_run:
            try:
                current_raw_ticks = int(
                    health[(LIVE_FRONTIER_COMPONENT, LIVE_FRONTIER_TICKS_KEY)]
                )
                frontier_domain = health[
                    (LIVE_FRONTIER_COMPONENT, LIVE_FRONTIER_DOMAIN_KEY)
                ]
                origin_extended = int(
                    self.state["qualified_origin_extended_timestamp_ticks"]
                )
                prior_raw_ticks = int(self.state["qualified_frontier_raw_ticks"])
                prior_extended_ticks = int(
                    self.state["qualified_frontier_extended_ticks"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "exact retained qualified clock is incomplete"
                ) from exc
            if frontier_domain != "rp2040_monotonic_us32":
                raise ValueError(
                    "retained producer frontier domain differs"
                )
            progress = forward_progress(
                prior_raw_ticks,
                current_raw_ticks,
                domain="rp2040_monotonic_us32",
                allow_equal=True,
            )
            if not progress.valid or progress.distance_ticks is None:
                raise ValueError(
                    "retained producer frontier moved backward"
                )
            current_extended = prior_extended_ticks + progress.distance_ticks
            if current_extended != prior_extended_ticks:
                self.state["qualified_frontier_raw_ticks"] = current_raw_ticks
                self.state["qualified_frontier_extended_ticks"] = current_extended
                self._save()
            elapsed = current_extended - origin_extended
            if elapsed < 0:
                raise ValueError("ADAPTIVE_HYBRID device clock moved behind qualified origin")
            return elapsed
        elapsed = current_uptime_s * RP2040_MONOTONIC_US_PER_SECOND - origin
        if elapsed < 0:
            raise ValueError("ADAPTIVE_HYBRID device clock moved behind qualified origin")
        return elapsed

    def _qualified_d14_apertures(
        self, health: dict[tuple[str, str], str]
    ) -> int | None:
        target = self.programme.qualified_d14_aperture_count
        if target is None:
            return None
        accepted_origin = self.state.get(
            "qualified_d14_segment_accepted_window_origin"
        )
        reference_origin = self.state.get(
            "qualified_d14_segment_reference_sequence_origin"
        )
        if type(accepted_origin) is not int:
            accepted_origin = self.state.get("qualified_d14_accepted_window_origin")
        if type(reference_origin) is not int:
            reference_origin = self.state.get(
                "qualified_d14_reference_sequence_origin"
            )
        if type(accepted_origin) is not int or type(reference_origin) is not int:
            return None
        try:
            accepted_now = int(health[("pps_gate", "accepted_window_count")])
            reference_now = int(
                health[("pps_gate", "boundary_reference_sequence")]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ADAPTIVE_HYBRID qualified D14 aperture progress is unavailable") from exc
        accepted_delta = (accepted_now - accepted_origin) & 0xFFFFFFFF
        reference_delta = (reference_now - reference_origin) & 0xFFFFFFFF
        if accepted_delta > 0x7FFFFFFF or reference_delta > 0x7FFFFFFF:
            raise ValueError("ADAPTIVE_HYBRID qualified D14 aperture counter moved backward")
        if accepted_delta > reference_delta:
            raise ValueError(
                "ADAPTIVE_HYBRID accepted-window progress exceeds D14 reference progress"
            )
        completed_before = self.state.get(
            "qualified_d14_completed_apertures_before_segment", 0
        )
        if type(completed_before) is not int or completed_before < 0:
            raise ValueError("ADAPTIVE_HYBRID retained segmented aperture progress is malformed")
        accepted_total = completed_before + accepted_delta
        self.state["qualified_d14_accepted_apertures"] = accepted_total
        self.state["qualified_d14_reference_sequence_endpoint"] = reference_now
        return accepted_total

    def _close_response_horizon_if_required(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        if self.programme.qualified_d14_aperture_count is not None:
            aperture_progress = self._qualified_d14_apertures(health)
            reserve = self.programme.correction_response_reserve_d14_apertures
            if aperture_progress is None or reserve is None:
                return False
            if aperture_progress < self.programme.qualified_d14_aperture_count - reserve:
                return False
            if self.state["response_horizon_closed_utc"] is None:
                self.state["response_horizon_closed_utc"] = _utc_now()
                self._save()
                self._programme_event(
                    "correction_admission_closed_for_response_horizon",
                    accepted_d14_d8_apertures=aperture_progress,
                    required_response_reserve_d14_apertures=reserve,
                    endpoint_contract="qualified_D14_D8_aperture_count_v2",
                )
            return True
        elapsed_ticks = self._qualified_elapsed_ticks(health)
        if elapsed_ticks is None:
            return False
        admission_ticks = (
            self.programme.qualified_duration_s
            - self.programme.correction_response_reserve_s
        ) * RP2040_MONOTONIC_US_PER_SECOND
        if elapsed_ticks < admission_ticks:
            return False
        if self.state["response_horizon_closed_utc"] is None:
            self.state["response_horizon_closed_utc"] = _utc_now()
            self._save()
            self._programme_event(
                "correction_admission_closed_for_response_horizon",
                elapsed_qualified_device_ticks=elapsed_ticks,
                time_domain="rp2040_monotonic_us32",
                remaining_qualified_s=max(
                    0,
                    self.programme.qualified_duration_s
                    - elapsed_ticks // RP2040_MONOTONIC_US_PER_SECOND,
                ),
                required_response_reserve_s=(
                    self.programme.correction_response_reserve_s
                ),
            )
        return True

    def _maybe_start_or_arm(
        self,
        health: dict[tuple[str, str], str],
    ) -> None:
        if self.state.get("host_verification_hold") is not None:
            return
        if not self._identity_ready(health):
            return
        state = health.get(("adaptive_hybrid", "state"), "")
        reason = health.get(("adaptive_hybrid", "reason"), "")
        controller_inhibit = (
            self.programme.controller_inhibit_acquisition_continues
            and state == "FAULT"
            and reason
            in {
                "prospective_repeated_alternation",
                "prospective_low_efficiency_path",
            }
            and self.state.get("controller_authority_inhibited_reason") == reason
        )
        if controller_inhibit:
            # _check_fail_static_health() has already converted this exact
            # firmware policy terminal into the programme's controller-local
            # no-new-authority state.  The next run-loop consumer must not
            # reinterpret the same retained FAULT record as a platform fault.
            return
        if state in {"FAULT", "ABORTED"}:
            raise ValueError(f"device active state {state.lower()}: {reason}")
        if state in {"REFERENCE_HOLD", "GNSS_METADATA_HOLD"}:
            return
        if state == "OUT_OF_MODEL_HOLD":
            raise ValueError(f"device entered out-of-model hold: {reason}")

        manual_confirmed = _truth(health, "manual_start_confirmed")
        if (
            not manual_confirmed
            and not self.state["manual_start_sent"]
            and state == "DISARMED"
        ):
            if not self._prewrite_readiness(health).ready:
                return
            command, request = self._setup_command(health)
            self._retain_setup_authority(health, request)
            self._command(command)
            self.state["manual_start_sent"] = True
            self.state["setup_requested_utc"] = _utc_now()
            self._save()
            self._programme_event(
                "exact_setup_requested",
                code=self.programme.setup_code,
                authorization_sequence=request["authorization_sequence"],
                status_generation=request["status_generation"],
                query_nonce=request["query_nonce"],
                expires_s=request["expires_s"],
                session_id=request["session_id"],
            )
            return

        if self.state["arm_pending"] and state == "DISARMED":
            sent_at = self.state.get("arm_sent_at_utc")
            age = (
                time.time() - _parse_utc_epoch(sent_at)
                if isinstance(sent_at, str) and sent_at
                else 0.0
            )
            if age > 15.0:
                self.state["arm_pending"] = False
                self.state["arm_sent_at_utc"] = None
                self._save()
                self._programme_event(
                    "unused_zero_delta_arm_consumed_without_write"
                )
        if not manual_confirmed or self.state["arm_pending"]:
            return
        if self._close_response_horizon_if_required(health):
            return

        hybrid_state = health.get(("adaptive_hybrid", "hybrid_state"), "")
        # FIRST_PHASE_TRANSACTION stays unarmed until firmware has durably
        # recorded the response checkpoint and observed tight reacquisition.
        if hybrid_state not in self.programme.armable_hybrid_states:
            return
        if hybrid_state == "HYBRID_TRACKING" and not _truth(
            health, "first_phase_checkpoint_passed"
        ):
            raise ValueError("later ADAPTIVE_HYBRID authority lacks its firmware checkpoint")
        correction_count = int(
            health.get(("adaptive_hybrid", "correction_count"), "0")
        )
        if correction_count >= self.programme.authorized_maximum_applications:
            return
        progress = int(
            health.get(("adaptive_hybrid", "selected_interval_count"), "0")
        )
        preview_rows = _read_csv(self.run_dir / CONTROL_CSV)
        preview = preview_rows[-1] if preview_rows else None
        if not self._arm_progress_epoch_ready(preview, progress):
            return
        # ADAPTIVE_HYBRID must arm the next fresh selected-estimate epoch even when the
        # The frequency-only preview is available every 600 seconds.
        # The hybrid firmware owns the 1800-second *applied* cadence and
        # consumes an early or zero-delta one-shot arm without writing.  Using
        # the adaptive-hybrid preview-cadence predictor here can therefore suppress every
        # phase-material decision after the first armed hold.
        if not (
            state == "DISARMED"
            and _truth(health, "arm_eligible")
            and health.get(("adaptive_hybrid", "evidence_phase")) == "evidence_clear"
            and not _truth(health, "evidence_pending")
            and progress >= ARM_PROGRESS_THRESHOLD
        ):
            return
        uptime = int(health[("adaptive_hybrid", "uptime_s")])
        self.state["authorization_sequence"] += 1
        sequence = self.state["authorization_sequence"]
        nonce = secrets.randbits(32) or 1
        expiry = uptime + ARM_LIFETIME_S
        self._command(f"ACTIVE ARM {sequence} {nonce} {expiry}")
        self.state["arm_pending"] = True
        self.state["arm_sent_at_utc"] = _utc_now()
        self._save()
        self._programme_event(
            "one_decision_armed",
            authorization_sequence=sequence,
            expiry_s=expiry,
            selected_interval_count=progress,
            hybrid_state=hybrid_state,
        )

    def _healthy_terminal_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        if (
            not self._identity_ready(health)
            or self.state["arm_pending"]
            or health.get(("adaptive_hybrid", "state")) != "DISARMED"
            or health.get(("adaptive_hybrid", "evidence_phase")) != "evidence_clear"
            or _truth(health, "evidence_pending")
            or int(health.get(("adaptive_hybrid", "evidence_request_sequence"), "0"))
            != 0
            or not _truth(health, "confirmed_applied_code_known")
        ):
            return False
        code = int(health[("adaptive_hybrid", "confirmed_applied_code")], 0)
        if not self.programme.minimum_code <= code <= self.programme.maximum_code:
            return False
        rows = _read_csv(self.run_dir / ACTIVE_CSV)
        if rows and rows[-1].get("event") not in {
            "manual_start",
            "response",
            "request_withdrawn",
        }:
            return False
        self.state["terminal_static_code"] = code
        return True

    def _set_healthy_endpoint(
        self, health: dict[tuple[str, str], str], *, endpoint: str
    ) -> None:
        material = int(
            health.get(
                ("adaptive_hybrid", "phase_material_application_count"), "0"
            )
        )
        checkpoint = _truth(health, "first_phase_checkpoint_passed")
        if self.programme.response_checkpoint_observational:
            preliminary = "pending_offline_scientific_analysis"
        elif material == 0:
            preliminary = "phase_influence_not_exercised"
        elif material < self.programme.minimum_natural_phase_material_applications:
            preliminary = "first_phase_transaction_passed_sustained_result_incomplete"
        elif not checkpoint:
            preliminary = "hybrid_response_wrong_or_frequency_not_reacquired"
        else:
            preliminary = "pending_offline_scientific_analysis"
        self.state["terminal"] = {
            "result": "healthy_stop",
            "reason": endpoint,
            "preliminary_decision": preliminary,
            "last_confirmed_code": self.state["terminal_static_code"],
            "utc": _utc_now(),
        }
        self._save()

    def _maybe_finish(
        self,
        health: dict[tuple[str, str], str],
        now_epoch: float,
    ) -> None:
        if self.state["terminal"] is not None:
            return
        hybrid_state = health.get(("adaptive_hybrid", "hybrid_state"), "")
        if (
            hybrid_state == "PHASE_DEGRADED_FREQUENCY_ONLY"
            and not self.programme.response_checkpoint_observational
        ):
            self._abort("phase_channel_degraded_frequency_control_retained")
            return

        qualification_deadline_s = self.programme.qualification_deadline_s
        setup_confirmed_utc = self.state.get("setup_confirmed_utc")
        if (
            qualification_deadline_s is not None
            and isinstance(setup_confirmed_utc, str)
            and setup_confirmed_utc
            and self.state.get("qualification_started_utc") is None
        ):
            if (
                now_epoch - _parse_utc_epoch(setup_confirmed_utc)
                >= qualification_deadline_s
            ):
                reason = f"{self.programme.key}_qualification_deadline_expired"
                self._enter_host_verification_hold(
                    ValueError(reason), source="qualification_deadline_observer"
                )
            return

        if self.programme.qualified_d14_aperture_count is not None:
            qualified_d14_apertures = self._qualified_d14_apertures(health)
            endpoint_reached = (
                qualified_d14_apertures is not None
                and qualified_d14_apertures
                >= self.programme.qualified_d14_aperture_count
            )
        else:
            qualified_elapsed_ticks = self._qualified_elapsed_ticks(health)
            qualified_target_ticks = (
                self.programme.qualified_duration_s
                * RP2040_MONOTONIC_US_PER_SECOND
            )
            endpoint_reached = (
                qualified_elapsed_ticks is not None
                and qualified_elapsed_ticks >= qualified_target_ticks
            )
        if (
            self.programme.integrated_long_run
            and self.programme.qualified_d14_aperture_count is None
            and endpoint_reached
            and self.state.get("qualified_endpoint_extended_timestamp_ticks")
            is None
        ):
            self.state["qualified_endpoint_extended_timestamp_ticks"] = self.state.get(
                "qualified_frontier_extended_ticks"
            )
            self._save()
        hold = self.state.get("host_verification_hold")
        if (
            endpoint_reached
            and isinstance(hold, dict)
        ):
            if hold.get("qualified_endpoint_observed_utc") is None:
                hold["qualified_endpoint_observed_utc"] = _utc_now()
                hold["qualified_endpoint_review_required"] = True
                self._save()
                self._programme_event(
                    "host_verification_hold_qualified_endpoint_observed",
                    applied_code=self.state.get("terminal_static_code"),
                    firmware_state=health.get(("adaptive_hybrid", "state")),
                    evidence_phase=health.get(("adaptive_hybrid", "evidence_phase")),
                    review_status="operator_review_required",
                    capture_continues=True,
                )
            return
        if (
            endpoint_reached
            and self._healthy_terminal_ready(health)
        ):
            self._set_healthy_endpoint(
                health,
                endpoint=self.programme.qualified_endpoint_reason,
            )
            return

        wall_origin = self.state.get("wall_origin_utc")
        if (
            isinstance(wall_origin, str)
            and wall_origin
            and now_epoch - _parse_utc_epoch(wall_origin)
            >= self.programme.authorized_absolute_wall_limit_s
        ):
            if self._healthy_terminal_ready(health):
                self.state["terminal"] = {
                    "result": "nonpass",
                    "reason": (
                        f"{self.programme.key}_"
                        f"{self.programme.authorized_absolute_wall_limit_s // 3600}h_absolute_wall_endpoint"
                    ),
                    "primary_decision": _programme_terminal_decision(
                        self.programme, "_right_censored_incomplete"
                    ),
                    "last_confirmed_code": self.state["terminal_static_code"],
                    "utc": _utc_now(),
                }
                self._save()
            else:
                reason = (
                    f"{self.programme.key}_"
                    "wall_endpoint_without_clear_static_terminal"
                )
                self._enter_host_verification_hold(
                    ValueError(reason), source="wall_endpoint_observer"
                )

    def _abort(self, reason: str) -> None:
        super()._abort(reason)
        terminal = self.state["terminal"]
        if reason == "independent_host_abort_fifo":
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_operator_abort",
            )
        elif reason in {
            "phase_channel_degraded_frequency_control_retained",
            "hybrid_response_wrong_or_frequency_not_reacquired",
            "phase_or_frequency_regulation_not_sustained",
        }:
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_authority_not_sustained"
            )
        elif reason.startswith(
            f"{self.programme.key}_D14_D8_authority_or_capture_fault:"
        ):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_D14_D8_authority_or_capture_fault",
            )
        elif "D9" in reason or "forwarded_clock_output" in reason:
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_D9_configuration_or_readback_fault"
            )
        elif "maintenance" in reason:
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_maintenance_evidence_fault"
            )
        elif reason.startswith(f"{self.programme.key}_live_supervisor_fault:"):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_identity_or_evidence_fault",
            )
        elif reason in {
            "prospective_repeated_alternation",
            "prospective_low_efficiency_path",
        }:
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_controller_or_transaction_fault"
            )
        elif "absolute_wall_endpoint" in reason or reason.startswith(
            f"{self.programme.key}_wall_endpoint"
        ):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_right_censored_incomplete",
            )
        elif reason.endswith("_qualification_deadline_expired"):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_right_censored_incomplete",
            )
        else:
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_identity_or_evidence_fault"
            )
        static_code = self.state.get("terminal_static_code")
        if isinstance(static_code, int):
            terminal["last_confirmed_code"] = static_code
        self._save()

    def run(self) -> int:
        capture_flag = self.run_dir / CAPTURE_IN_PROGRESS_FLAG
        if not capture_flag.exists():
            raise RuntimeError("capture is not marked in progress")
        started = time.monotonic()
        last_lease = 0.0
        last_query = 0.0
        last_output_status_query = time.monotonic()
        with AbortFifo(self.abort_fifo) as abort:
            self._live_command_ack_required = True
            self._programme_event(
                "live_supervisor_started",
                abort_fifo=str(self.abort_fifo),
                manifest_sha256=self.envelope.manifest_sha256,
                bundle_sha256=self.envelope.bundle_sha256,
                policy_sha256=self.envelope.policy_sha256,
                wall_origin_utc=self.envelope.wall_origin_utc,
            )
            self._command("CONFIG?")
            self._command("DUALCORE?")
            self._command("DAC?")
            while True:
                now = time.monotonic()
                if abort.poll():
                    self._abort("independent_host_abort_fifo")
                    return 3
                if not capture_flag.exists():
                    self._enter_host_verification_hold(
                        RuntimeError("capture owner in-progress marker is absent"),
                        source="capture_owner_observer",
                    )
                    time.sleep(0.2)
                    continue
                if self.duration_s is not None and now - started > self.duration_s:
                    self._enter_host_verification_hold(
                        RuntimeError("supervisor duration observer expired"),
                        source="supervisor_duration_observer",
                    )
                    self.duration_s = None
                try:
                    if now - last_lease >= LEASE_PERIOD_S:
                        self._check_capture_transport_state()
                        self._renew_lease()
                        last_lease = now
                    if now - last_query >= QUERY_PERIOD_S:
                        current = self._current_health()
                        generation = int(
                            current.get(
                                ("adaptive_hybrid", "snapshot_generation_complete"),
                                "0",
                            )
                        )
                        self._fresh_active_snapshot_after(generation)
                        last_query = time.monotonic()
                    if (
                        self.programme.forwarded_output_integration
                        and now - last_output_status_query
                        >= FORWARDED_OUTPUT_STATUS_PERIOD_S
                    ):
                        self._command("CONFIG?")
                        last_output_status_query = now
                    health = self._current_health()
                    if not self._abort_on_authoritative_capture_discontinuity(
                        health
                    ):
                        # Firmware fail-static remains independent.  Host-side
                        # interpretation failures enter a durable no-authority
                        # review hold and leave acquisition alive.
                        self._check_fail_static_health(health)
                        self._process_transactions()
                        health = self._current_health()
                        if not self._abort_on_authoritative_capture_discontinuity(
                            health
                        ):
                            self._check_fail_static_health(health)
                            if self.state.get("host_verification_hold") is None:
                                self._check_setup_transaction_timeout(
                                    health, time.time()
                                )
                            self._check_prewrite_contract(health, now - started)
                            self._maybe_qualify(health)
                            self._maybe_finish(health, time.time())
                            if self.state["terminal"] is None:
                                self._maybe_start_or_arm(health)
                except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                    self._enter_host_verification_hold(
                        exc, source="live_supervisor_diagnostic_cycle"
                    )
                if self.state["terminal"] is not None:
                    if not self.state["terminal_event_emitted"]:
                        self._programme_event(
                            "campaign_terminal", **self.state["terminal"]
                        )
                        self.state["terminal_event_emitted"] = True
                        self._save()
                    return (
                        0
                        if self.state["terminal"]["result"] == "healthy_stop"
                        else 2
                    )
                time.sleep(0.2)


def create_supervisor(
    *,
    manifest_path: Path,
    run_dir: Path,
    command_fifo: Path,
    emergency_command_fifo: Path,
    abort_fifo: Path,
    expected_build_identity: str,
    duration_s: float | None = None,
    console_events: bool = False,
) -> AdaptiveHybridSupervisor:
    from .adaptive_hybrid_activation import validate_run_manifest

    manifest = validate_run_manifest(manifest_path)
    spec, identities = load_active_hybrid_spec(manifest)
    build_identity = _manifest_build_identity(manifest)
    if expected_build_identity != build_identity:
        raise ValueError("requested build identity differs from the ADAPTIVE_HYBRID manifest")
    return AdaptiveHybridSupervisor(
        manifest=manifest,
        manifest_path=manifest_path,
        run_dir=run_dir,
        command_fifo=command_fifo,
        emergency_command_fifo=emergency_command_fifo,
        abort_fifo=abort_fifo,
        spec=spec,
        identities=identities,
        expected_build_identity=build_identity,
        duration_s=duration_s,
        console_events=console_events,
    )


def _manifest_build_identity(manifest: dict[str, Any]) -> str:
    firmware = manifest.get("firmware", {})
    if isinstance(firmware, dict):
        direct = firmware.get("build_identity")
        if isinstance(direct, str):
            return direct
        source = firmware.get("source_sha256")
        configuration = firmware.get("configuration_sha256")
        if isinstance(source, str) and isinstance(configuration, str):
            return f"{source}:{configuration}"
    raise ValueError("ADAPTIVE_HYBRID run manifest lacks exact firmware build identity")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--emergency-command-fifo", type=Path, required=True)
    parser.add_argument("--abort-fifo", type=Path, required=True)
    parser.add_argument("--expected-build-identity", required=True)
    parser.add_argument("--duration-s", type=float)
    parser.add_argument("--console-events", action="store_true")
    args = parser.parse_args(argv)

    try:
        fifo_paths = {
            args.command_fifo.absolute(),
            args.emergency_command_fifo.absolute(),
            args.abort_fifo.absolute(),
        }
        if (
            len(fifo_paths) != 3
            or args.manifest.resolve()
            != (args.run_dir / "run_manifest.json").resolve()
        ):
            parser.error("manifest, FIFOs, run directory, or build identity differs")
        supervisor = create_supervisor(
            manifest_path=args.manifest,
            run_dir=args.run_dir,
            command_fifo=args.command_fifo,
            emergency_command_fifo=args.emergency_command_fifo,
            abort_fifo=args.abort_fifo,
            expected_build_identity=args.expected_build_identity,
            duration_s=args.duration_s,
            console_events=args.console_events,
        )
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, TimeoutError, ValueError) as exc:
        if "supervisor" in locals():
            supervisor._programme_event("live_supervisor_fault", error=str(exc))
            supervisor._enter_host_verification_hold(
                exc, source="live_supervisor_outer_boundary"
            )
            return 2
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
