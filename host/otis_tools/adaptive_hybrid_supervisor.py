"""Executable fail-static supervisor for the frozen ADAPTIVE_HYBRID live campaign.

The capture process remains the sole serial owner.  This supervisor submits
only timestamped commands through that owner's bounded normal FIFO and submits
``ACTIVE ABORT`` through the independent emergency FIFO.  Every active
transaction phase is durably retained and replayed by the shared ACT machinery
before the corresponding firmware evidence acknowledgement is released.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .acquisition_frontier import read_acquisition_readiness
from .active_status_live_state import (
    LIVE_FRONTIER_COMPONENT,
    LIVE_FRONTIER_DOMAIN_KEY,
    LIVE_FRONTIER_TICKS_KEY,
)
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    CAUSAL_STATE_CONTRACT_ID,
    CAUSAL_STATE_SCHEMA_VERSION,
    UNATTENDED_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
    UNATTENDED_CLOSURE_RESERVE_S,
    AdaptiveHybridProgramme,
    BenchAttemptEnvelope,
    programme_from_mapping,
    validate_bench_attempt_envelope,
)
from .adaptive_hybrid_evidence import (
    IndependentReplayMismatch,
    ResponseCheckpointRejected,
)
from .adaptive_hybrid_health import (
    ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S,
    ACTIVE_STATUS_COMPLETE_MAX_AGE_S,
    ARM_LIFETIME_S,
    ARM_PROGRESS_THRESHOLD,
    CONTROL_CSV,
    DAC_CSV,
    SELECTED_INTERVAL_S,
    SETUP_AUTHORITY_CONTRACT,
    SETUP_AUTHORITY_LIFETIME_S,
    SETUP_AUTHORITY_PATH,
    SETUP_RESULT_GRACE_S,
    AdaptiveHybridSupervisorBase,
    canonical_health,
)
from .adaptive_hybrid_policy import AdaptiveHybridPolicy, policy_from_mapping
from .adaptive_hybrid_transactions import (
    ACTIVE_CSV,
    LEASE_PERIOD_S,
    QUERY_PERIOD_S,
    CampaignSpec,
    _read_csv,
    _utc_now,
)
from .adaptive_hybrid_transport import (
    ESTIMATES_CSV,
    RP2040_MONOTONIC_US_PER_SECOND,
    ControlSupervisorBase,
    ExplicitSupervisorAbort,
    _parse_utc_epoch,
)
from .authoritative_inputs import (
    ROOT_PROFILE,
    ValidatedAuthoritativeInputs,
    transaction_identities_from_manifest,
    validate_authoritative_inputs,
)
from .capture_device import CAPTURE_STATE
from .contracts import CsvValidationContext, validate_csv
from .firmware_bindings import current_forwarded_clock_contract
from .prewrite_readiness_contract import (
    GNSS_OPERATIONAL_PREWRITE_EXACT,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    PrewriteReadiness,
)
from .prewrite_readiness_contract import (
    evaluate_prewrite_readiness as evaluate_setup_prewrite_readiness,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .serial_commands import send_timestamped_command_to_fifo
from .time_domains import forward_progress

FORWARDED_OUTPUT_STATUS_PERIOD_S = 60.0
STARTUP_CENSUS_CONTRACT = "adaptive_hybrid_startup_census_v1"


def _startup_query_command(command: str) -> bool:
    """Return whether *command* is observational and safe before ownership."""

    return command in {
        "CONFIG?",
        "DUALCORE?",
        "DAC?",
        "DAC LIMITS?",
        "COUNT?",
        "ACTIVE?",
    } or command.startswith("ACTIVE SNAPSHOT ")


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
ACTIVE_HYBRID_CSV = Path("csv/active_hybrid_decisions_v3.csv")
HOST_CONTRACT_RECOVERY_PATH = Path(
    "reports/adaptive_hybrid_host_contract_recovery_v1.json"
)

SETUP_CODE = ADAPTIVE_HYBRID_PROGRAMME.setup_code
MAXIMUM_APPLICATIONS = ADAPTIVE_HYBRID_PROGRAMME.maximum_applications
MAXIMUM_CUMULATIVE_MOVEMENT_CODES = ADAPTIVE_HYBRID_PROGRAMME.maximum_cumulative_movement_codes
MAXIMUM_STEP_CODES = ADAPTIVE_HYBRID_PROGRAMME.maximum_step_codes
MINIMUM_CODE = ADAPTIVE_HYBRID_PROGRAMME.minimum_code
MAXIMUM_CODE = ADAPTIVE_HYBRID_PROGRAMME.maximum_code
QUALIFIED_DURATION_S = ADAPTIVE_HYBRID_PROGRAMME.qualified_duration_s
ABSOLUTE_WALL_LIMIT_S = ADAPTIVE_HYBRID_PROGRAMME.absolute_wall_limit_s
MINIMUM_PHASE_MATERIAL_APPLICATIONS = 2


def _tick_is_within_reported_whole_second(
    event_timestamp_ticks: int, reported_timestamp_s: int
) -> bool:
    """Validate the firmware's explicit microsecond-to-second projection."""
    return (
        event_timestamp_ticks // RP2040_MONOTONIC_US_PER_SECOND
        == reported_timestamp_s
    )


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

@dataclass(frozen=True, slots=True)
class AdaptiveHybridRuntimeContext:
    """One immutable, manifest-bound static configuration for a supervisor."""

    programme: AdaptiveHybridProgramme
    bench_attempt: BenchAttemptEnvelope
    manifest_sha256: str
    run_spec_sha256: str
    policy_sha256: str
    build_identity: str
    uf2_sha256: str
    policy: AdaptiveHybridPolicy
    natural_policy_sha256: str
    frequency_estimator_sha256: str
    phase_estimator_sha256: str
    wall_origin_utc: str
    authoritative_inputs: ValidatedAuthoritativeInputs
    _manifest_json: str
    _transaction_identities: tuple[tuple[str, str], ...]

    def manifest_document(self) -> dict[str, Any]:
        return json.loads(self._manifest_json)

    def policy_document(self) -> dict[str, Any]:
        return self.authoritative_inputs.document(ROOT_PROFILE)

    def transaction_identities(self) -> dict[str, str]:
        return dict(self._transaction_identities)

    def matches_manifest(self, manifest: object) -> bool:
        try:
            encoded = json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return False
        return encoded == self._manifest_json


def _profile_binding_sha256(
    inputs: ValidatedAuthoritativeInputs, policy: dict[str, Any], name: str
) -> str:
    binding = policy.get("bindings", {}).get(name)
    if not isinstance(binding, str):
        raise ValueError(f"adaptive-hybrid policy binding {name!r} is unavailable")
    return str(inputs.binding(binding)["sha256"])


def _prepare_runtime_context(
    manifest: dict[str, Any],
    *,
    authoritative_inputs: ValidatedAuthoritativeInputs | None = None,
) -> AdaptiveHybridRuntimeContext:
    """Validate and detach the one current static runtime configuration."""

    programme = programme_from_mapping(manifest)
    section = manifest.get(programme.manifest_section, {})
    firmware = manifest.get("firmware", {})
    binding = manifest.get("policy", {})
    if not isinstance(section, dict) or not isinstance(firmware, dict) or not isinstance(binding, dict):
        raise ValueError("adaptive-hybrid manifest envelope is malformed")
    raw_bench_attempt = manifest.get("bench_attempt")
    if not isinstance(raw_bench_attempt, dict):
        raise ValueError("adaptive-hybrid bench-attempt envelope is malformed")
    bench_attempt = validate_bench_attempt_envelope(raw_bench_attempt)
    execution_kind = manifest.get("execution_kind")
    entry_authorization = manifest.get("entry_authorization")
    authority = section.get("authority")
    if (
        execution_kind not in {"physical", "simulated"}
        or not isinstance(authority, dict)
        or authority.get("effective") is not True
        or authority.get("physical_execution") is not (execution_kind == "physical")
        or (execution_kind == "physical") != isinstance(entry_authorization, dict)
    ):
        raise ValueError("adaptive-hybrid execution authority boundary differs")
    inputs = authoritative_inputs
    if inputs is None:
        inputs = validate_authoritative_inputs(manifest.get("authoritative_inputs"))
    elif (
        not isinstance(inputs, ValidatedAuthoritativeInputs)
        or not inputs.matches(manifest.get("authoritative_inputs"))
    ):
        raise ValueError("validated input context differs from the runtime manifest")
    policy = inputs.document(ROOT_PROFILE)
    root_binding = inputs.binding(ROOT_PROFILE)
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
    identities = transaction_identities_from_manifest(manifest, inputs=inputs)
    return AdaptiveHybridRuntimeContext(
        programme=programme,
        bench_attempt=bench_attempt,
        manifest_sha256=_sha256_identity(manifest.get("manifest_sha256"), "manifest_sha256"),
        run_spec_sha256=_sha256_identity(
            manifest.get("run_spec", {}).get("sha256"), "run_spec.sha256"
        ),
        policy_sha256=selected.policy_sha256,
        build_identity=build_identity,
        uf2_sha256=_sha256_identity(uf2.get("sha256"), "firmware.uf2.sha256"),
        policy=selected,
        natural_policy_sha256=selected.policy_sha256,
        frequency_estimator_sha256=_profile_binding_sha256(
            inputs, policy, "frequency_estimator"
        ),
        phase_estimator_sha256=_profile_binding_sha256(
            inputs, policy, "phase_estimator"
        ),
        wall_origin_utc=str(manifest["started_at_utc"]),
        authoritative_inputs=inputs,
        _manifest_json=json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        _transaction_identities=tuple(sorted(identities.items())),
    )


def prepare_runtime_context(
    manifest: dict[str, Any],
) -> AdaptiveHybridRuntimeContext:
    """Prepare one validated physical or PTY runtime configuration once."""

    return _prepare_runtime_context(manifest)


def runtime_spec(
    context: AdaptiveHybridRuntimeContext,
) -> tuple[CampaignSpec, dict[str, str]]:
    programme = context.programme
    return (
        CampaignSpec(
            campaign=programme.campaign_name,
            profile=programme.profile_id,
            run_identity=programme.runtime_run_identity,
            start_code=programme.setup_code,
            correction_limit=context.bench_attempt.limits.automatic_application_limit,
            cumulative_limit=(
                programme.authorized_maximum_cumulative_movement_codes
            ),
            minimum_code=programme.minimum_code,
            maximum_code=programme.maximum_code,
            maximum_step=programme.maximum_step_codes,
        ),
        context.transaction_identities(),
    )


def _truth(health: dict[tuple[str, str], str], key: str) -> bool:
    return health.get(("adaptive_hybrid", key)) == "true"


_AUTHORITATIVE_CAPTURE_COUNTERS = (
    "physical_aperture_incomplete_count",
    "capture_loss_count",
    "reference_acceptance_loss_count",
)
_ADAPTIVE_HYBRID_AUTHORITATIVE_CAPTURE_COUNTERS = _AUTHORITATIVE_CAPTURE_COUNTERS + (
    "capture_service_stale_count",
    "count_saturated_count",
    "boundary_sequence_gap_count",
    "boundary_sequence_duplicate_count",
    "boundary_overflow_count",
    "counter_snapshot_invalid_count",
    "snapshot_ring_full_count",
    "snapshot_continuity_loss_count",
    "snapshot_pio_rxstall_count",
    "snapshot_irq_budget_exhausted_count",
    "snapshot_timestamp_ambiguous_count",
)
_AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH = {
    "snapshot": "end",
    "aperture_backend": "pio_wait_cumulative_snapshot_fifo_irq_v2",
    "reference_acceptance_state": "tracking",
    "accepted_anchor_current": "true",
    "fifo_continuity": "continuous",
    "capture_state": "clean",
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
    # PPS diagnostics and solicited ACTIVE snapshots are separate publications.
    # Their current ordinals need not match. Require each view to qualify on
    # its own; session and policy bind the common reference. Epochs are checked
    # against the retained qualification origin by the progress consumers.
    # Qualified progress is measured from PPS ordinals and retained counters,
    # never from equality with the latest independently emitted ACTIVE ordinal.
    faults: list[str] = []
    for key, expected in _AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH.items():
        observed = health.get(("pps_gate", key))
        if observed != expected:
            faults.append(f"{key}:{observed!r}!={expected!r}")
    for key in ("reference_acceptance_state", "accepted_anchor_current"):
        expected = _AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH[key]
        observed = health.get(("adaptive_hybrid", key))
        if observed != expected:
            faults.append(f"adaptive_hybrid.{key}:{observed!r}!={expected!r}")
    key = "reference_acceptance_policy_sha256"
    pps = health.get(("pps_gate", key))
    active = health.get(("adaptive_hybrid", key))
    if pps is None or active is None or pps != active:
        faults.append(f"accepted_status_mismatch:{key}:{pps!r}!={active!r}")
    if health.get(("pps_gate", "snapshot_session")) != health.get(
        ("adaptive_hybrid", "session_id")
    ):
        faults.append("accepted_status_mismatch:capture_session")
    try:
        anchor_ticks = int(health[("pps_gate", "accepted_anchor_timestamp_ticks")])
        active_frontier_ticks = int(
            health[(LIVE_FRONTIER_COMPONENT, LIVE_FRONTIER_TICKS_KEY)]
        )
        frontier_domain = health[(LIVE_FRONTIER_COMPONENT, LIVE_FRONTIER_DOMAIN_KEY)]
    except (KeyError, TypeError, ValueError):
        faults.append("accepted_status_mismatch:producer_frontier_unavailable")
    else:
        progress = forward_progress(
            anchor_ticks,
            active_frontier_ticks,
            domain=str(frontier_domain),
            allow_equal=True,
        )
        maximum_lead_ticks = (
            QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S * RP2040_MONOTONIC_US_PER_SECOND
        )
        if (
            frontier_domain != "rp2040_monotonic_us32"
            or not progress.valid
            or progress.distance_ticks is None
            or progress.distance_ticks > maximum_lead_ticks
        ):
            faults.append("accepted_status_mismatch:producer_frontier_stale")
    return faults


def require_fresh_inhibited_attempt(
    runtime_context: AdaptiveHybridRuntimeContext, run_dir: Path,
) -> None:
    """Reject restart before mutating state or acquiring a new capture owner."""
    retained = run_dir / "reports/adaptive_hybrid_supervisor_state.json"
    if runtime_context.bench_attempt.purpose in {INHIBITED_ZERO_WRITE, UNATTENDED_72_HOUR_HYBRID_CONTROL} and (
        retained.exists() or retained.is_symlink()
    ):
        raise ValueError(
            "finite attempt cannot resume retained supervisor state; "
            "its monotonic observation window must not restart"
        )


class AdaptiveHybridSupervisor(AdaptiveHybridSupervisorBase):
    """ADAPTIVE_HYBRID live authority layered on the proven active-control transport."""

    def __init__(
        self,
        *,
        runtime_context: AdaptiveHybridRuntimeContext,
        manifest_path: Path,
        **kwargs: object,
    ) -> None:
        requested_run_dir = kwargs.get("run_dir")
        expected_capture_pid = kwargs.pop("expected_capture_pid", None)
        if expected_capture_pid is not None and (
            type(expected_capture_pid) is not int or expected_capture_pid <= 0
        ):
            raise ValueError("expected capture PID is malformed")
        self.expected_capture_pid = expected_capture_pid
        if not isinstance(requested_run_dir, Path):
            raise ValueError("ADAPTIVE_HYBRID supervisor requires a run directory")
        self._retained_supervisor_state_at_start = (
            requested_run_dir / "reports/adaptive_hybrid_supervisor_state.json"
        ).is_file()
        self._startup_census_process_nonce = secrets.randbits(32) or 1
        if not isinstance(runtime_context, AdaptiveHybridRuntimeContext):
            raise ValueError("ADAPTIVE_HYBRID supervisor requires a validated runtime context")
        require_fresh_inhibited_attempt(runtime_context, requested_run_dir)
        if any(name in kwargs for name in ("spec", "identities", "expected_build_identity")):
            raise ValueError("ADAPTIVE_HYBRID static inputs must come from one runtime context")
        spec, identities = runtime_spec(runtime_context)
        self.programme = runtime_context.programme
        limits = runtime_context.bench_attempt.limits
        if (
            spec.correction_limit != limits.automatic_application_limit
            or spec.start_code != self.programme.setup_code
        ):
            raise ValueError(
                "ADAPTIVE_HYBRID supervisor spec differs from the bench-attempt envelope"
            )
        super().__init__(
            control_authority_enabled=(
                limits.setup_application_limit == 1
                and limits.arm_submission_limit > 0
            ),
            # The installed profile deliberately inhibits D14/D8 control
            # eligibility for 600 s.  Prior physical adaptive-hybrid evidence first
            # observed the same predicate at 612 s, so retain its frozen
            # 660 s qualification deadline rather than the older adaptive-hybrid
            # 30 s complete-snapshot grace.
            prewrite_contract_startup_grace_s=(
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
            spec=spec,
            identities=identities,
            expected_build_identity=runtime_context.build_identity,
            **kwargs,
        )
        self.manifest_path = manifest_path.resolve()
        loaded_manifest = load_manifest(requested_run_dir)
        if loaded_manifest.path.resolve() != self.manifest_path:
            raise ValueError("supervisor did not receive the canonical run record")
        acquisition_manifest = loaded_manifest.data
        if not runtime_context.matches_manifest(acquisition_manifest):
            raise ValueError(
                "ADAPTIVE_HYBRID acquisition manifest differs from the runtime context"
            )
        self.acquisition_manifest = acquisition_manifest
        reference_acceptance = acquisition_manifest.get("reference_acceptance")
        if (
            not isinstance(reference_acceptance, dict)
            or set(reference_acceptance) != {"policy_id", "policy_sha256", "path"}
        ):
            raise ValueError("ADAPTIVE_HYBRID reference-acceptance binding is unavailable")
        self.reference_acceptance_policy_sha256 = str(
            reference_acceptance["policy_sha256"]
        )
        self.runtime_context = runtime_context
        owner_now_ns = time.monotonic_ns()
        wall_limit_s = int(
            runtime_context.bench_attempt.as_dict()["timing"]["absolute_wall_limit_s"]
        )
        self._inhibited_observation_started_monotonic_ns: int | None = None
        # Both finite purposes start after capture readiness in this process.
        # A stopped owner cannot recreate the deadline through reattachment.
        self._inhibited_observation_started_monotonic_ns = owner_now_ns
        self._wall_deadline_monotonic_ns = owner_now_ns + wall_limit_s * 1_000_000_000
        self._setup_requested_monotonic_ns: int | None = None
        self._setup_confirmed_monotonic_ns: int | None = None
        self._arm_sent_monotonic_ns: int | None = None
        self.phase_estimator_sha256 = runtime_context.phase_estimator_sha256
        self.natural_policy = runtime_context.policy
        self.natural_policy_document = runtime_context.policy_document()
        self.natural_estimator_sha256 = runtime_context.frequency_estimator_sha256
        self.expected_active_policy_sha256 = runtime_context.policy_sha256
        self.part = f"{self.programme.key}_active_hybrid_live"
        exact_state = {
            "programme_id": self.programme.programme_id,
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": runtime_context.manifest_sha256,
            "run_spec_sha256": runtime_context.run_spec_sha256,
            "policy_sha256": runtime_context.policy_sha256,
            "build_identity": runtime_context.build_identity,
            "uf2_sha256": runtime_context.uf2_sha256,
            "runtime_run_identity": self.spec.run_identity,
            "wall_origin_utc": runtime_context.wall_origin_utc,
        }
        exact_state.update(
            {
                "bench_attempt": runtime_context.bench_attempt.as_dict(),
                "bench_attempt_purpose": runtime_context.bench_attempt.purpose,
                "bench_attempt_envelope_sha256": (
                    runtime_context.bench_attempt.as_dict()["envelope_sha256"]
                ),
            }
        )
        for key, value in exact_state.items():
            prior = self.state.get(key)
            if prior is not None and prior != value:
                raise ValueError(
                    f"ADAPTIVE_HYBRID retained supervisor {key} differs from the manifest"
                )
            self.state[key] = value
        if self._inhibited_observation_started_monotonic_ns is not None:
            self.state["inhibited_observation_window"] = {
                "clock_domain": "host_monotonic_ns",
                "origin": runtime_context.bench_attempt.as_dict()["timing"][
                    "wall_limit_origin"
                ],
                "owner_pid": os.getpid(),
                "owner_nonce": self._startup_census_process_nonce,
                "started_monotonic_ns": self._inhibited_observation_started_monotonic_ns,
                "deadline_monotonic_ns": self._wall_deadline_monotonic_ns,
            }
        self.state.setdefault("qualified_origin_estimate_id", None)
        self.state.setdefault("qualified_origin_timestamp_ticks", None)
        self.state.setdefault("qualified_origin_session_id", None)
        self.state.setdefault("qualified_origin_extended_timestamp_ticks", None)
        self.state.setdefault("qualified_frontier_raw_ticks", None)
        self.state.setdefault("qualified_frontier_extended_ticks", None)
        self.state.setdefault("qualified_endpoint_extended_timestamp_ticks", None)
        self.state.setdefault("qualified_acceptance_epoch_origin", None)
        self.state.setdefault("qualified_acceptance_ordinal_origin", None)
        self.state.setdefault("qualified_d14_accepted_apertures", None)
        self.state.setdefault("qualified_acceptance_ordinal_endpoint", None)
        self.state.setdefault("qualified_authoritative_capture_baseline", None)
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
        prior_census = self.state.get("startup_census")
        census_history = self.state.setdefault("startup_census_history", [])
        if not isinstance(census_history, list):
            raise ValueError("retained startup census history is malformed")
        if prior_census is not None:
            if not isinstance(prior_census, dict):
                raise ValueError("retained startup census is malformed")
            if not census_history or census_history[-1] != prior_census:
                census_history.append(prior_census)
        # Every supervisor process must obtain its own solicited snapshot.  A
        # census retained by an earlier process is provenance, not continuing
        # permission for this process to renew a lease or release evidence.
        self.state["startup_census"] = None
        self.state["startup_census_authority_admitted"] = False
        self.state["startup_census_process_nonce"] = (
            self._startup_census_process_nonce
        )
        initial_closed = bool(limits.authority_initially_closed)
        initial_causal_state = {
            "schema_version": CAUSAL_STATE_SCHEMA_VERSION,
            "contract": CAUSAL_STATE_CONTRACT_ID,
            "durable_ACT_application_count": 0,
            "firmware_correction_count": 0,
            "authority_closed": initial_closed,
            "closure": (
                {
                    "trigger": "initial_contract_state",
                    "bench_attempt_purpose": runtime_context.bench_attempt.purpose,
                    "bench_attempt_envelope_sha256": (
                        runtime_context.bench_attempt.as_dict()["envelope_sha256"]
                    ),
                }
                if initial_closed
                else None
            ),
        }
        retained_causal_state = self.state.get("bench_attempt_causal_state")
        if retained_causal_state is None:
            self.state["bench_attempt_causal_state"] = initial_causal_state
        else:
            self._validate_bench_attempt_causal_state(retained_causal_state)
        self.state.setdefault(
            "bench_attempt_arm_admission_closed", initial_closed
        )
        self.state.setdefault("bench_attempt_arm_admission_closed_utc", None)
        self.state.setdefault("bench_attempt_arm_admission_endpoint", None)
        self.state.setdefault("bench_attempt_arm_submission_count", 0)
        self.state.setdefault("bench_attempt_last_arm_opportunity", None)
        self.state.setdefault("bench_attempt_arm_admissions", [])
        arm_count = self.state.get("bench_attempt_arm_submission_count")
        admission_closed = self.state.get(
            "bench_attempt_arm_admission_closed"
        )
        if (
            type(arm_count) is not int
            or not 0 <= arm_count <= limits.arm_submission_limit
            or type(admission_closed) is not bool
            or (
                self._bench_authority_closed()
                and not admission_closed
            )
        ):
            raise ValueError(
                "retained ARM authority differs from the bench-attempt envelope"
            )
        self._validate_bench_attempt_arm_admissions()
        if (
            runtime_context.bench_attempt.purpose == INHIBITED_ZERO_WRITE
            and (
                self.state.get("manual_start_sent") is not False
                or self.state.get("arm_pending") is not False
                or self.state.get("authorization_sequence") != 0
                or self.state.get("bench_attempt_arm_submission_count") != 0
            )
        ):
            raise ValueError(
                "inhibited zero-write retained state contains control authority"
            )
        # The attachment nonce is immutable package identity. Runtime queries
        # rotate a separate nonce so a fresh file cannot masquerade as the
        # causally requested post-frontier snapshot.
        self.state.setdefault(
            "active_snapshot_request_nonce",
            int(self.state["host_attach_query_nonce"]),
        )
        self._save()

    def _save(self) -> None:
        """Publish whether this owner can presently admit another control command."""
        census = self.state.get("startup_census")
        causal = self.state.get("bench_attempt_causal_state")
        setup_pending = bool(
            self.state.get("manual_start_sent")
            and self.state.get("setup_confirmed_utc") is None
        )
        self.state["control_authority"] = bool(
            getattr(self, "control_authority_enabled", False)
            and isinstance(census, dict)
            and self._startup_census_admitted()
            and self.state.get("host_verification_hold") is None
            and self.state.get("gnss_metadata_hold") is None
            and self.state.get("terminal") is None
            and self.state.get("controller_authority_inhibited_reason") is None
            and self.state.get("arm_pending") is False
            and self.state.get("inflight_evidence_acknowledgement") is None
            and not getattr(self, "_normal_command_ack_pending", False)
            and not setup_pending
            and self.state.get("bench_attempt_arm_admission_closed") is False
            and (
                not isinstance(causal, dict)
                or causal.get("authority_closed") is False
            )
        )
        super()._save()

    def _validate_bench_attempt_arm_admissions(self) -> None:
        """Validate every durable host authorization decision on restart."""

        bench_attempt = self.runtime_context.bench_attempt
        admissions = self.state.get("bench_attempt_arm_admissions")
        count = self.state.get("bench_attempt_arm_submission_count")
        expected_fields = {
            "authorization_sequence",
            "arm_nonce",
            "expiry_s",
            "authorizing_snapshot_generation",
            "authorizing_query_nonce",
            "accepted_D14_D8_apertures",
            "admission_deadline_delta",
            "natural_opportunity",
            "admitted_utc",
        }
        if (
            not isinstance(admissions, list)
            or type(count) is not int
            or len(admissions) != count
            or count > bench_attempt.limits.arm_submission_limit
        ):
            raise ValueError("retained bench-attempt ARM admissions differ")
        prior_sequence = 0
        prior_coordinate = -1
        opportunities: set[str] = set()
        for admission in admissions:
            if not isinstance(admission, dict) or set(admission) != expected_fields:
                raise ValueError("retained bench-attempt ARM admission is malformed")
            sequence = admission.get("authorization_sequence")
            generation = admission.get("authorizing_snapshot_generation")
            query_nonce = admission.get("authorizing_query_nonce")
            coordinate = admission.get("accepted_D14_D8_apertures")
            deadline = admission.get("admission_deadline_delta")
            opportunity = admission.get("natural_opportunity")
            if (
                type(sequence) is not int
                or sequence <= prior_sequence
                or type(admission.get("arm_nonce")) is not int
                or admission["arm_nonce"] <= 0
                or type(admission.get("expiry_s")) is not int
                or admission["expiry_s"] <= 0
                or type(generation) is not int
                or generation <= 0
                or type(query_nonce) is not int
                or query_nonce <= 0
                or type(coordinate) is not int
                or not prior_coordinate <= coordinate < deadline
                or deadline
                != bench_attempt.limits.automatic_application_admission_deadline_apertures
                or not isinstance(opportunity, str)
                or not opportunity
                or opportunity in opportunities
                or not isinstance(admission.get("admitted_utc"), str)
                or not admission["admitted_utc"]
            ):
                raise ValueError("retained bench-attempt ARM admission differs")
            prior_sequence = sequence
            prior_coordinate = coordinate
            opportunities.add(opportunity)
        expected_last = admissions[-1]["natural_opportunity"] if admissions else None
        if (
            self.state.get("bench_attempt_last_arm_opportunity") != expected_last
            or (admissions and self.state.get("authorization_sequence", 0) < prior_sequence)
        ):
            raise ValueError("retained bench-attempt ARM admission order differs")

    def _validate_bench_attempt_causal_state(self, value: object) -> None:
        bench_attempt = self.runtime_context.bench_attempt
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "contract",
            "durable_ACT_application_count",
            "firmware_correction_count",
            "authority_closed",
            "closure",
        }:
            raise ValueError("bench-attempt causal state is malformed")
        limits = bench_attempt.limits
        durable_count = value.get("durable_ACT_application_count")
        firmware_count = value.get("firmware_correction_count")
        authority_closed = value.get("authority_closed")
        closure = value.get("closure")
        if (
            value.get("schema_version") != CAUSAL_STATE_SCHEMA_VERSION
            or value.get("contract") != CAUSAL_STATE_CONTRACT_ID
            or type(durable_count) is not int
            or type(firmware_count) is not int
            or type(authority_closed) is not bool
            or not 0 <= durable_count <= limits.automatic_application_limit
            or not 0 <= firmware_count <= limits.automatic_application_limit
            or durable_count != firmware_count
            or authority_closed != (closure is not None)
        ):
            raise ValueError("bench-attempt causal state differs from its contract")
        if bench_attempt.purpose == INHIBITED_ZERO_WRITE:
            expected = {
                "trigger": "initial_contract_state",
                "bench_attempt_purpose": bench_attempt.purpose,
                "bench_attempt_envelope_sha256": bench_attempt.as_dict()[
                    "envelope_sha256"
                ],
            }
            if durable_count != 0 or not authority_closed or closure != expected:
                raise ValueError(
                    "inhibited zero-write causal state grants application authority"
                )
            return
        if bench_attempt.purpose != UNATTENDED_72_HOUR_HYBRID_CONTROL:
            raise ValueError("unsupported authority-bearing bench attempt")
        if authority_closed:
            required_closure_fields = {
                "trigger",
                "bench_attempt_purpose",
                "bench_attempt_envelope_sha256",
                "request_sequence",
                "transaction_record_sequence",
                "decision_sequence",
                "application_sequence",
                "snapshot_generation",
                "query_nonce",
                "accepted_D14_D8_apertures_at_application",
                "closed_utc",
            }
            if (
                durable_count != limits.automatic_application_limit
                or not isinstance(closure, dict)
                or set(closure) != required_closure_fields
                or closure.get("trigger")
                != "automatic_application_limit_reached"
                or closure.get("bench_attempt_purpose") != bench_attempt.purpose
                or closure.get("bench_attempt_envelope_sha256")
                != bench_attempt.as_dict()["envelope_sha256"]
                or type(closure.get("request_sequence")) is not int
                or type(closure.get("transaction_record_sequence")) is not int
                or type(closure.get("decision_sequence")) is not int
                or type(closure.get("application_sequence")) is not int
                or type(closure.get("snapshot_generation")) is not int
                or type(closure.get("query_nonce")) is not int
                or any(
                    closure.get(field, 0) <= 0
                    for field in (
                        "request_sequence",
                        "transaction_record_sequence",
                        "decision_sequence",
                        "application_sequence",
                        "snapshot_generation",
                        "query_nonce",
                    )
                )
                or (
                    closure.get("accepted_D14_D8_apertures_at_application")
                    is not None
                    and type(
                        closure.get("accepted_D14_D8_apertures_at_application")
                    )
                    is not int
                )
                or (
                    isinstance(
                        closure.get("accepted_D14_D8_apertures_at_application"),
                        int,
                    )
                    and closure["accepted_D14_D8_apertures_at_application"] < 0
                )
                or not isinstance(closure.get("closed_utc"), str)
            ):
                raise ValueError("closed bench-attempt causal state is malformed")
            try:
                _parse_utc_epoch(closure["closed_utc"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "closed bench-attempt causal timestamp is malformed"
                ) from exc
        elif (
            not 0 <= durable_count < limits.automatic_application_limit
            or closure is not None
        ):
            raise ValueError(
                "open long-run causal state exceeds its application authority"
            )

    def _bench_authority_closed(self) -> bool:
        causal_state = self.state.get("bench_attempt_causal_state")
        self._validate_bench_attempt_causal_state(causal_state)
        return bool(causal_state["authority_closed"])

    def _record_bench_application_before_acknowledgement(
        self,
        row: dict[str, str],
        health: dict[tuple[str, str], str],
    ) -> dict[str, object]:
        """Persist each physical application frontier before phase-3 ACK."""

        bench_attempt = self.runtime_context.bench_attempt
        if bench_attempt.purpose != UNATTENDED_72_HOUR_HYBRID_CONTROL:
            raise ValueError(
                "inhibited zero-write attempt observed an ACT application"
            )
        if row.get("event") != "application":
            raise ValueError(
                "bench-attempt phase-3 evidence is not a successful application"
            )
        rows = _read_csv(self.run_dir / ACTIVE_CSV)
        application_rows = [item for item in rows if item.get("event") == "application"]
        record_sequence = int(row["transaction_record_sequence"])
        if (
            not application_rows
            or application_rows[-1] != row
            or int(application_rows[-1]["transaction_record_sequence"])
            != record_sequence
        ):
            raise ValueError(
                "durable ACT application frontier differs from the long-run envelope"
            )
        durable_count = len(application_rows)
        firmware_count = int(
            health.get(("adaptive_hybrid", "correction_count"), "-1")
        )
        row_count = int(row["correction_count"])
        limit = bench_attempt.limits.automatic_application_limit
        if (
            not 1 <= durable_count <= limit
            or row_count != durable_count
            or firmware_count != durable_count
        ):
            raise ValueError(
                "durable ACT and causally complete firmware correction counts differ: "
                f"ACT={durable_count} row={row_count} firmware={firmware_count}"
            )
        accepted_apertures = self._qualified_d14_apertures(health)
        authority_closed = durable_count == limit
        closure = (
            {
                "trigger": "automatic_application_limit_reached",
                "bench_attempt_purpose": bench_attempt.purpose,
                "bench_attempt_envelope_sha256": bench_attempt.as_dict()[
                    "envelope_sha256"
                ],
                "request_sequence": int(row["request_sequence"]),
                "transaction_record_sequence": record_sequence,
                "decision_sequence": int(row["decision_sequence"]),
                "application_sequence": int(row["application_sequence"]),
                "snapshot_generation": int(
                    health[("adaptive_hybrid", "snapshot_generation_complete")]
                ),
                "query_nonce": int(health[("adaptive_hybrid", "query_nonce")]),
                "accepted_D14_D8_apertures_at_application": accepted_apertures,
                "closed_utc": _utc_now(),
            }
            if authority_closed
            else None
        )
        retained = self.state.get("bench_attempt_causal_state")
        self._validate_bench_attempt_causal_state(retained)
        retained_count = retained["durable_ACT_application_count"]
        if retained_count == durable_count:
            if retained["authority_closed"]:
                retained_closure = retained["closure"]
                stable_closure = {
                    "trigger": "automatic_application_limit_reached",
                    "bench_attempt_purpose": bench_attempt.purpose,
                    "bench_attempt_envelope_sha256": bench_attempt.as_dict()[
                        "envelope_sha256"
                    ],
                    "request_sequence": int(row["request_sequence"]),
                    "transaction_record_sequence": record_sequence,
                    "decision_sequence": int(row["decision_sequence"]),
                    "application_sequence": int(row["application_sequence"]),
                }
                if any(
                    retained_closure.get(field) != value
                    for field, value in stable_closure.items()
                ):
                    raise ValueError(
                        "retained long-run authority closure changed identity"
                    )
            return {
                "bench_attempt_authority_closed": retained["authority_closed"],
                "bench_attempt_envelope_sha256": bench_attempt.as_dict()[
                    "envelope_sha256"
                ],
                "bench_attempt_durable_application_count": retained_count,
            }
        if retained["authority_closed"] or retained_count != durable_count - 1:
            raise ValueError(
                "retained long-run application frontier is not the exact predecessor"
            )

        causal_state = {
            "schema_version": CAUSAL_STATE_SCHEMA_VERSION,
            "contract": CAUSAL_STATE_CONTRACT_ID,
            "durable_ACT_application_count": durable_count,
            "firmware_correction_count": firmware_count,
            "authority_closed": authority_closed,
            "closure": closure,
        }
        self._validate_bench_attempt_causal_state(causal_state)
        self.state["bench_attempt_causal_state"] = causal_state
        if authority_closed:
            self.state["bench_attempt_arm_admission_closed"] = True
            self.state["arm_pending"] = False
            self.state["arm_sent_at_utc"] = None
            self._arm_sent_monotonic_ns = None
        self._save()
        # Event append is itself fsynced.  The phase-3 command is submitted by
        # the base transaction layer only after this method returns.
        self._programme_event(
            (
                "bench_attempt_authority_closed"
                if authority_closed
                else "bench_attempt_application_frontier_persisted"
            ),
            durable_ACT_application_count=durable_count,
            firmware_correction_count=firmware_count,
            accepted_D14_D8_apertures_at_application=accepted_apertures,
            authority_closed=authority_closed,
            **({"closure": closure} if closure is not None else {}),
        )
        return {
            "bench_attempt_authority_closed": authority_closed,
            "bench_attempt_envelope_sha256": bench_attempt.as_dict()[
                "envelope_sha256"
            ],
            "bench_attempt_durable_application_count": durable_count,
        }

    def _programme_event(self, suffix: str, **payload: object) -> None:
        self._event(f"{self.programme.key}_{suffix}", **payload)

    def _identity_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        """Discover instrument identity independently of reference acquisition."""
        expected = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "image_identity": self.spec.profile,
            **self.identities,
        }
        for key, value in expected.items():
            observed = health.get(("adaptive_hybrid", key))
            if observed is None:
                return False
            if observed != value:
                raise ValueError(f"live {key} mismatch: {observed!r} != {value!r}")
        try:
            session = int(health.get(("adaptive_hybrid", "session_id"), "0"))
        except (TypeError, ValueError):
            return False
        if session == 0:
            return False
        if self.state["initial_session_id"] is None:
            self.state["initial_session_id"] = session
            self._save()
        elif session != self.state["initial_session_id"]:
            raise ValueError("active snapshot session changed during the campaign")
        policy = health.get(("adaptive_hybrid", "reference_acceptance_policy_sha256"))
        if policy is None:
            return False
        if policy != self.reference_acceptance_policy_sha256:
            raise ValueError("live reference acceptance policy differs from the frozen policy")
        return True

    def _startup_census_admitted(self) -> bool:
        census = self.state.get("startup_census")
        if not isinstance(census, dict):
            return False
        return bool(
            self.state.get("startup_census_authority_admitted") is True
            and census.get("contract") == STARTUP_CENSUS_CONTRACT
            and census.get("authority_admitted") is True
            and census.get("process_nonce")
            == self.state.get("startup_census_process_nonce")
            and census.get("session_id") == self.state.get("initial_session_id")
        )

    def _assert_command_admitted(self, command: str) -> None:
        """Enforce the lowest host command boundary before serial ingress."""

        if _startup_query_command(command):
            return
        if not self._startup_census_admitted():
            raise ValueError(
                "startup census has not admitted controller command authority"
            )
        if command.startswith("ACTIVE EVIDENCE "):
            fields = command.split()
            inflight = self.state.get("inflight_evidence_acknowledgement")
            if (
                len(fields) != 4
                or not isinstance(inflight, dict)
                or str(inflight.get("request_sequence")) != fields[2]
                or str(inflight.get("phase")) != fields[3]
                or inflight.get("host_write_confirmed") is not False
            ):
                raise ValueError(
                    "evidence command lacks its exact retained pending acknowledgement"
                )
        if (
            command.startswith(("ACTIVE SETUP ", "ACTIVE ARM "))
            and self.state.get("host_verification_hold") is not None
        ):
            raise ValueError("host verification hold inhibits new SETUP/ARM authority")

    def _ack_observation_deadline(self, acknowledgement: dict[str, object]) -> int:
        owner = acknowledgement.get("causal_observation_owner_nonce")
        if (type(owner) is not int or owner <= 0
            or owner != self.state.get("startup_census_process_nonce")):
            raise ValueError("inflight acknowledgement deadline belongs to an unknown supervisor process")
        deadline = acknowledgement.get("causal_observation_deadline_monotonic_ns")
        if type(deadline) is not int or deadline <= 0:
            raise ValueError("inflight acknowledgement lacks its causal observation deadline")
        return deadline

    def _pending_ack_deadline(self) -> int | None:
        acknowledgement = self.state.get("inflight_evidence_acknowledgement")
        if isinstance(acknowledgement, dict) and self._startup_census_admitted():
            return self._ack_observation_deadline(acknowledgement)
        return None

    def _command(self, command: str) -> None:
        self._assert_command_admitted(command)
        deadline_ns = self._pending_ack_deadline()
        if deadline_ns is not None:
            with self._causal_observation(
                ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S, deadline_ns=deadline_ns
            ):
                super()._command(command)
        else:
            super()._command(command)

    def _current_health(
        self, *, required_query_nonce: int | None = None
    ) -> dict[tuple[str, str], str]:
        if required_query_nonce is None:
            required_query_nonce = int(self.state["active_snapshot_request_nonce"])
        # Periodic observations between confirmation passes consume the same
        # pending phase budget. A cleared phase cannot constrain its successor.
        with self._causal_observation(
            ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S,
            deadline_ns=self._pending_ack_deadline(),
        ):
            return super()._current_health(required_query_nonce=required_query_nonce)

    def _renew_lease(self) -> None:
        if getattr(self, "_normal_command_ack_pending", False):
            raise ValueError("normal command acknowledgement is unresolved")
        self._check_wait_deadline(self._pending_ack_deadline())
        # The base implementation advances the durable lease sequence before
        # submitting the command.  Check census first so a rejected startup
        # cannot leave a fictitious retained lease sequence.
        self._assert_command_admitted(
            f"ACTIVE LEASE {int(self.state.get('lease_sequence', 0)) + 1}"
        )
        super()._renew_lease()
        self._last_lease_monotonic_ns = time.monotonic_ns()

    def _fresh_startup_state_exact(
        self, health: dict[tuple[str, str], str]
    ) -> tuple[bool, list[str]]:
        expected_health = {
            "state": "DISARMED",
            "evidence_pending": "false",
            "evidence_phase": "evidence_clear",
            "capture_lease_live": "false",
            "manual_start_confirmed": "false",
            "arm_eligible": "false",
            "fail_static": "false",
            "hybrid_state": "SETUP_PENDING",
            "first_phase_checkpoint_passed": "false",
            "phase_nonzero_application_count": "0",
            "phase_material_application_count": "0",
            "frequency_only_application_count": "0",
            "evidence_request_sequence": "0",
            "confirmed_applied_code_known": "false",
            "confirmed_applied_code": "unavailable",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "dac_epoch": "0",
            "automatic_retry": "false",
            "automatic_restore": "false",
        }
        mismatches = [
            f"adaptive_hybrid.{key}={health.get(('adaptive_hybrid', key))!r}, expected {value!r}"
            for key, value in expected_health.items()
            if health.get(("adaptive_hybrid", key)) != value
        ]
        expected_code = health.get(("adaptive_hybrid", "expected_setup_code"))
        if expected_code is None:
            mismatches.append("adaptive_hybrid.expected_setup_code is missing")
        else:
            try:
                if int(expected_code, 0) != self.programme.setup_code:
                    mismatches.append(
                        "adaptive_hybrid.expected_setup_code differs from the programme"
                    )
            except ValueError:
                mismatches.append("adaptive_hybrid.expected_setup_code is malformed")
        pristine_state = {
            "manual_start_sent": False,
            "arm_pending": False,
            "authorization_sequence": 0,
            "lease_sequence": 0,
            "setup_confirmed_utc": None,
            "setup_confirmation": None,
            "setup_authority_path": None,
            "setup_requested_utc": None,
            "terminal": None,
            "inflight_evidence_acknowledgement": None,
            "acknowledged_record_sequences": [],
            "observed_manual_record_sequences": [],
            "host_verification_hold": None,
        }
        mismatches.extend(
            f"retained {key} is not pristine"
            for key, value in pristine_state.items()
            if self.state.get(key) != value
        )
        return not mismatches, mismatches

    def _classify_startup_snapshot(
        self, health: dict[tuple[str, str], str]
    ) -> tuple[str, bool, list[str]]:
        if not self._identity_ready(health):
            return "incoherent", False, ["complete current firmware identity is unavailable"]
        fresh, fresh_mismatches = self._fresh_startup_state_exact(health)
        if fresh:
            return "fresh_disarmed", True, []
        state = health.get(("adaptive_hybrid", "state"))
        evidence_pending = health.get(("adaptive_hybrid", "evidence_pending"))
        manual = health.get(("adaptive_hybrid", "manual_start_confirmed"))
        if (
            state in {"FAULT", "ABORTED", "OUT_OF_MODEL_HOLD"}
            or health.get(("adaptive_hybrid", "fail_static")) == "true"
            or health.get(("adaptive_hybrid", "hybrid_state")) == "FAIL_STATIC"
        ):
            classification = "terminal_or_fault"
        elif evidence_pending == "true" or health.get(
            ("adaptive_hybrid", "evidence_phase")
        ) != "evidence_clear":
            classification = "transaction_inflight"
        elif manual == "true" or state != "DISARMED":
            classification = "already_setup_or_tracking"
        else:
            classification = "incoherent"
        return classification, False, [
            *fresh_mismatches,
            (
                "retained supervisor continuation is unsupported; this process "
                "may observe and preserve capture but cannot assume prior authority"
            ),
        ]

    def _establish_startup_census(self) -> dict[tuple[str, str], str]:
        if self.state.get("startup_census") is not None:
            raise ValueError("startup census was already established for this process")
        health: dict[tuple[str, str], str] = {}
        try:
            current = self._current_health()
            generation_text = current.get(
                ("adaptive_hybrid", "snapshot_generation_complete")
            )
            generation = 0 if generation_text is None else int(generation_text)
            health = self._fresh_active_snapshot_after(generation)
            classification, admitted, diagnostics = self._classify_startup_snapshot(
                health
            )
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            classification = "incoherent"
            admitted = False
            diagnostics = [f"{type(exc).__name__}: {exc}"]

        def optional_integer(key: str) -> int | None:
            value = health.get(("adaptive_hybrid", key))
            try:
                return int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        snapshot = canonical_health(health)
        census = {
            "contract": STARTUP_CENSUS_CONTRACT,
            "observed_utc": _utc_now(),
            "classification": classification,
            "authority_admitted": admitted,
            "process_nonce": self.state.get("startup_census_process_nonce"),
            "retained_supervisor_state_at_start": self._retained_supervisor_state_at_start,
            "snapshot_generation": optional_integer("snapshot_generation_complete"),
            "query_nonce": optional_integer("query_nonce"),
            "session_id": optional_integer("session_id"),
            "snapshot_sha256": sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "health": snapshot,
            "diagnostics": diagnostics,
        }
        self.state["startup_census"] = census
        self.state["startup_census_authority_admitted"] = admitted
        self._save()
        self._programme_event("startup_census_established", **census)
        if not admitted:
            self._enter_host_verification_hold(
                ValueError(
                    f"startup census classified {classification}: "
                    + "; ".join(diagnostics)
                ),
                source="startup_census",
            )
        return health

    def _fresh_active_snapshot_after(
        self, generation: int
    ) -> dict[tuple[str, str], str]:
        with self._causal_observation(
            ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S,
            deadline_ns=self._pending_ack_deadline(),
        ):
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
                self._wait_slice(0.05, allow_lease=True)

    def _prepare_evidence_acknowledgement(
        self, row: dict[str, str], phase: int
    ) -> dict[str, object]:
        with self._causal_observation(ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S) as deadline_ns:
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
            # Causally behind snapshots are pending within this one operation.
            # Every returned response is examined; a query never resets the budget.
            while True:
                self._check_wait_deadline()
                observed_phase = health.get(("adaptive_hybrid", "evidence_phase"), "")
                observed_request = int(
                    health.get(("adaptive_hybrid", "evidence_request_sequence"), "0")
                )
                if (
                    observed_phase == expected_phase
                    and observed_request == request_sequence
                ):
                    preparation = {
                        "causal_observation_owner_nonce": self.state["startup_census_process_nonce"],
                        "causal_observation_deadline_monotonic_ns": deadline_ns,
                        "pre_submit_snapshot_generation": int(
                            health[("adaptive_hybrid", "snapshot_generation_complete")]
                        ),
                        "pre_submit_evidence_phase": expected_phase,
                    }
                    if phase == 3:
                        preparation.update(
                            self._record_bench_application_before_acknowledgement(
                                row, health
                            )
                        )
                    return preparation
                if observed_phase == "evidence_clear" and observed_request == 0 or (
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

    def _confirm_evidence_acknowledgement(
        self, acknowledgement: dict[str, object]
    ) -> bool:
        deadline_ns = self._ack_observation_deadline(acknowledgement)
        with self._causal_observation(
            ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S, deadline_ns=deadline_ns
        ):
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

    def _acquisition_authority_ready(
        self,
        *,
        expected_capture_session: int,
        source_estimate_id: str | None = None,
    ) -> bool:
        """Require retained live source evidence before issuing authority."""

        try:
            capture_state = json.loads(
                (self.run_dir / CAPTURE_STATE).read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError) as error:
            self._enter_host_verification_hold(
                ValueError(f"capture observer state is unreadable: {error}"),
                source="acquisition_frontier",
            )
            return False
        if (
            not isinstance(capture_state, dict)
            or "acquisition_frontier_observer_error" not in capture_state
        ):
            self._enter_host_verification_hold(
                ValueError(
                    "capture observer state lacks its current acquisition-"
                    "frontier health field"
                ),
                source="acquisition_frontier",
            )
            return False
        observer_error = capture_state.get(
            "acquisition_frontier_observer_error"
        )
        if observer_error is not None:
            if not isinstance(observer_error, str) or not observer_error:
                observer_error = "capture observer failure field is malformed"
            self._enter_host_verification_hold(
                ValueError(observer_error),
                source="acquisition_frontier",
            )
            return False
        readiness = read_acquisition_readiness(
            self.run_dir,
            self.acquisition_manifest,
            source_estimate_id=source_estimate_id,
            expected_capture_session=expected_capture_session,
            validated_inputs=self.runtime_context.authoritative_inputs,
        )
        errors = readiness.get("errors")
        if not isinstance(errors, list) or not all(
            isinstance(error, str) and error for error in errors
        ):
            errors = ["acquisition readiness result is malformed"]
        if errors:
            self._enter_host_verification_hold(
                ValueError("; ".join(errors)),
                source="acquisition_frontier",
            )
            return False
        if readiness.get("ready") is not True:
            return False
        if readiness.get("capture_session") != expected_capture_session:
            return False
        if source_estimate_id is None:
            return True
        proof = readiness.get("source_proof")
        record = proof.get("record") if isinstance(proof, dict) else None
        if (
            not isinstance(record, dict)
            or proof.get("capture_session") != expected_capture_session
            or record.get("estimate_id") != source_estimate_id
            or record.get("estimator_version")
            != self.natural_policy.frequency_estimator_id
            or record.get("config_hash") != self.identities["estimator_sha256"]
            or proof.get("source_acceptance_epoch")
                != int(record.get("source_acceptance_epoch", "0"))
            or proof.get("source_opening_accepted_boundary_ordinal")
                != int(record.get("source_opening_accepted_boundary_ordinal", "0"))
            or proof.get("source_closing_accepted_boundary_ordinal")
                != int(record.get("source_closing_accepted_boundary_ordinal", "0"))
        ):
            self._enter_host_verification_hold(
                ValueError(
                    "selected EST readiness proof differs from the current "
                    "capture session or frozen estimator identity"
                ),
                source="acquisition_frontier",
            )
            return False
        return True

    def _capture_session_for_authority(
        self, health: dict[tuple[str, str], str]
    ) -> int | None:
        try:
            capture_session = int(health[("pps_gate", "snapshot_session")])
        except (KeyError, TypeError, ValueError):
            capture_session = 0
        if capture_session <= 0:
            self._enter_host_verification_hold(
                ValueError(
                    "current D14/D8 capture session is unavailable for "
                    "acquisition-frontier authority"
                ),
                source="acquisition_frontier",
            )
            return None
        return capture_session

    def _validate_hybrid_decisions(self) -> None:
        path = self.run_dir / ACTIVE_HYBRID_CSV
        if not path.exists():
            return
        validation = validate_csv(
            path,
            CsvValidationContext(
                "active_hybrid_decisions_v3",
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
            "reviewer_required_for_capture": False,
            "unanswered_escalation_action": "retain_capture_hold_new_authority",
            "timeout_approval_permitted": False,
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
        self._arm_sent_monotonic_ns = None
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

    def _validate_bench_transaction_prefix(self) -> None:
        bench_attempt = self.runtime_context.bench_attempt
        rows = _read_csv(self.run_dir / ACTIVE_CSV)
        manual_count = sum(row.get("event") == "manual_start" for row in rows)
        application_count = sum(row.get("event") == "application" for row in rows)
        limits = bench_attempt.limits
        if (
            manual_count > limits.setup_application_limit
            or application_count > limits.automatic_application_limit
            or (
                bench_attempt.purpose == INHIBITED_ZERO_WRITE
                and bool(rows)
            )
        ):
            raise ValueError(
                "ACT transaction prefix exceeds the physical bench-attempt envelope"
            )

    def _process_transactions(self) -> None:
        if not self._startup_census_admitted():
            return
        if self.state.get("host_verification_hold") is not None:
            self._process_transactions_during_host_verification_hold()
            return
        if not self._validate_hybrid_decisions_or_hold():
            return
        prior_terminal = self.state.get("terminal")
        try:
            self._validate_bench_transaction_prefix()
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
        except (OSError, RuntimeError, TimeoutError, UnicodeError, ValueError) as exc:
            self._enter_host_verification_hold(
                exc, source="transaction_evidence_validation"
            )
            return
        try:
            self._latch_setup_confirmation()
        except (OSError, RuntimeError, TimeoutError, UnicodeError, ValueError) as exc:
            self._enter_host_verification_hold(
                exc, source="setup_first_consumer_confirmation"
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
        if self.state["terminal"] is None:
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

    def _latch_setup_confirmation(self) -> bool:
        """Bind the validated leading ``manual_start`` to setup authority.

        The base transaction consumer durably records that it has observed the
        leading manual-start row, but the concrete supervisor also needs an
        explicit setup frontier before qualification and recoverable GNSS
        metadata holds may be consumed.  Only the exact firmware row emitted
        for the one retained setup request can open that frontier.
        """

        retained_timestamp = self.state.get("setup_confirmed_utc")
        retained_confirmation = self.state.get("setup_confirmation")
        if (retained_timestamp is None) != (retained_confirmation is None):
            raise ValueError(
                "ADAPTIVE_HYBRID retained setup confirmation presence differs"
            )

        rows = _read_csv(self.run_dir / ACTIVE_CSV)
        manual_rows = [row for row in rows if row.get("event") == "manual_start"]
        if not manual_rows:
            return False
        if len(manual_rows) != 1 or manual_rows[0] is not rows[0]:
            raise ValueError("ADAPTIVE_HYBRID setup evidence is not one leading row")
        row = manual_rows[0]
        record_sequence = int(row["transaction_record_sequence"])
        if record_sequence not in set(self.state["observed_manual_record_sequences"]):
            return False

        authority_relative = self.state.get("setup_authority_path")
        if authority_relative != str(SETUP_AUTHORITY_PATH):
            raise ValueError("ADAPTIVE_HYBRID setup confirmation lacks retained authority")
        authority_path = (self.run_dir / authority_relative).resolve()
        try:
            authority_path.relative_to(self.run_dir.resolve())
            authority = json.loads(authority_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                "ADAPTIVE_HYBRID retained setup authority is unreadable"
            ) from exc
        unsigned_authority = {
            key: value for key, value in authority.items() if key != "record_sha256"
        }
        authority_sha256 = sha256(
            json.dumps(
                unsigned_authority, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        request = authority.get("request")
        authority_fields = {
            "contract",
            "created_utc",
            "request",
            "health",
            "active_row_count",
            "dac_row_count",
            "telemetry_drop_baseline",
            "record_sha256",
        }
        request_fields = {
            "authorization_sequence",
            "status_generation",
            "query_nonce",
            "expires_s",
            "session_id",
            "requested_code",
            "one_shot_ordinal",
            "configuration_identity",
        }
        if (
            set(authority) != authority_fields
            or authority.get("contract") != SETUP_AUTHORITY_CONTRACT
            or authority.get("record_sha256") != authority_sha256
            or not isinstance(request, dict)
            or set(request) != request_fields
        ):
            raise ValueError("ADAPTIVE_HYBRID retained setup authority differs")
        try:
            _parse_utc_epoch(str(authority["created_utc"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ADAPTIVE_HYBRID retained setup authority timestamp differs"
            ) from exc

        retained_health = authority.get("health")
        if not isinstance(retained_health, list) or not all(
            isinstance(item, dict) and set(item) == {"component", "key", "value"}
            for item in retained_health
        ):
            raise ValueError("ADAPTIVE_HYBRID setup authority health is malformed")
        health_keys = [
            (str(item["component"]), str(item["key"]))
            for item in retained_health
        ]
        if health_keys != sorted(health_keys) or len(health_keys) != len(set(health_keys)):
            raise ValueError("ADAPTIVE_HYBRID setup authority health is not canonical")
        authority_health = {
            key: str(item["value"])
            for key, item in zip(health_keys, retained_health, strict=True)
        }
        expected_identity = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "image_identity": self.spec.profile,
            **self.identities,
        }
        readiness = evaluate_setup_prewrite_readiness(
            authority_health,
            expected_identity=expected_identity,
            planned_live_stimulus_code=self.spec.start_code,
            active_row_count=int(authority.get("active_row_count", -1)),
            dac_row_count=int(authority.get("dac_row_count", -1)),
            telemetry_drop_baseline=int(
                authority.get("telemetry_drop_baseline", -1)
            ),
        )
        if not readiness.ready:
            raise ValueError(
                "ADAPTIVE_HYBRID retained setup authority prewrite differs: "
                + readiness.diagnostic()
            )

        session_id = int(row["session_id"])
        application_timestamp_s = int(row["application_timestamp_s"])
        event_timestamp_ticks = int(row["event_timestamp_ticks"])
        setup_code = self.programme.setup_code
        exact = {
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "current_applied_code": str(setup_code),
            "requested_delta_codes": "0",
            "requested_code": str(setup_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "accepted_code": str(setup_code),
            "applied_code": str(setup_code),
            "application_sequence": "0",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "1",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "active_state": "DISARMED",
            "response_class": "unavailable",
            "reason": "manual_start_established",
            "evidence_state": "evidence_clear",
        }
        mismatched = sorted(
            field for field, expected in exact.items() if row.get(field) != expected
        )
        if (
            mismatched
            or session_id <= 0
            or event_timestamp_ticks <= 0
            or not _tick_is_within_reported_whole_second(
                event_timestamp_ticks, application_timestamp_s
            )
            or request.get("session_id") != session_id
            or request.get("requested_code") != setup_code
            or request.get("one_shot_ordinal") != 1
            or request.get("authorization_sequence")
            != self.state.get("setup_authorization_sequence")
            or request.get("configuration_identity")
            != self.expected_build_identity.split(":", 1)[1]
            or authority.get("active_row_count") != 0
            or authority.get("dac_row_count") != 0
            or authority.get("telemetry_drop_baseline") != 0
            or authority_health.get(
                ("adaptive_hybrid", "snapshot_generation_complete")
            )
            != str(request.get("status_generation"))
            or authority_health.get(("adaptive_hybrid", "query_nonce"))
            != str(request.get("query_nonce"))
            or authority_health.get(("adaptive_hybrid", "session_id"))
            != str(request.get("session_id"))
            or int(request.get("expires_s", 0))
            <= int(authority_health.get(("adaptive_hybrid", "uptime_s"), "0"))
            or self.state.get("initial_session_id") != session_id
        ):
            detail = ", ".join(mismatched) or "authority/session/time binding"
            raise ValueError(
                "ADAPTIVE_HYBRID setup confirmation differs: " + detail
            )

        confirmation = {
            "transaction_record_sequence": record_sequence,
            "event_timestamp_ticks": event_timestamp_ticks,
            "time_domain": row["time_domain"],
            "session_id": session_id,
            "applied_code": setup_code,
            "dac_epoch": 1,
            "setup_authorization_sequence": int(request["authorization_sequence"]),
            "setup_status_generation": int(request["status_generation"]),
            "setup_query_nonce": int(request["query_nonce"]),
            "setup_authority_record_sha256": authority_sha256,
        }
        retained = self.state.get("setup_confirmation")
        if retained is not None and retained != confirmation:
            raise ValueError("ADAPTIVE_HYBRID retained setup confirmation changed")
        if self.state.get("setup_confirmed_utc") is None:
            self.state["setup_confirmed_utc"] = _utc_now()
            self._setup_confirmed_monotonic_ns = time.monotonic_ns()
            self.state["setup_confirmation"] = confirmation
            self.state["terminal_static_code"] = setup_code
            self._save()
            self._programme_event("setup_first_consumer_confirmed", **confirmation)
        return True

    def _runtime_health_integrity(
        self, health: dict[tuple[str, str], str]
    ):  # type: ignore[no-untyped-def]
        # Apply the D14/D8/GNSS/capture integrity contract. Phase and controller
        # authority are checked separately below.
        return super()._runtime_health_integrity(health)

    def _check_setup_transaction_timeout(
        self,
        health: dict[tuple[str, str], str],
    ) -> None:
        """Turn physical setup-observation discrepancies into review holds."""

        if not self.state["manual_start_sent"]:
            return
        if self.runtime_context.bench_attempt.purpose == INHIBITED_ZERO_WRITE:
            self._enter_host_verification_hold(
                ValueError("zero-write attempt retained an impossible setup request"),
                source="setup_transaction_observer",
            )
            return
        if health.get(("adaptive_hybrid", "manual_start_confirmed")) == "true":
            return
        requested_ns = self._setup_requested_monotonic_ns
        if type(requested_ns) is not int:
            self._enter_host_verification_hold(
                ValueError("setup transaction lacks its owner-monotonic origin"),
                source="setup_transaction_observer",
            )
            return
        if time.monotonic_ns() - requested_ns >= int(
            (SETUP_AUTHORITY_LIFETIME_S + SETUP_RESULT_GRACE_S) * 1_000_000_000
        ):
            self._enter_host_verification_hold(
                TimeoutError("setup transaction expired without an observed result"),
                source="setup_transaction_observer",
            )

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        bench_attempt = self.runtime_context.bench_attempt
        self._validate_bench_attempt_causal_state(
            self.state.get("bench_attempt_causal_state")
        )
        dac_write_count = len(_read_csv(self.run_dir / DAC_CSV))
        if (
            dac_write_count
            > bench_attempt.limits.total_dac_value_write_limit
            or (
                bench_attempt.purpose == INHIBITED_ZERO_WRITE
                and self.state.get("manual_start_sent") is not False
            )
        ):
            raise ValueError(
                "physical DAC evidence exceeds the bench-attempt envelope"
            )
        # Preview streams remain zero-authority; the combined controller has a
        # separate explicit transaction boundary.
        hybrid_state = health.get(("adaptive_hybrid", "hybrid_state"))
        hybrid_reason = health.get(("adaptive_hybrid", "hybrid_reason"), "unknown")
        prospective_controller_inhibit = (
            hybrid_state == "FAIL_STATIC"
            and hybrid_reason
            in {"prospective_repeated_alternation", "prospective_low_efficiency_path"}
        )
        metadata_hold_active = (
            health.get(("adaptive_hybrid", "state")) == "GNSS_METADATA_HOLD"
            and _truth(health, "gnss_metadata_hold_active")
        )
        platform_health = health
        if prospective_controller_inhibit:
            self.state["arm_pending"] = False
            self.state["arm_sent_at_utc"] = None
            self._arm_sent_monotonic_ns = None
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
        gnss_missing, gnss_mismatches = gnss_operational_runtime_invariant_errors(
            health,
            require_present=self.state["prewrite_contract_ready_utc"] is not None,
        )
        if gnss_missing or gnss_mismatches:
            raise ValueError(
                "integrated GNSS bootstrap/runtime invariant changed: "
                + "; ".join((*gnss_missing, *gnss_mismatches))
            )
        if self.state["prewrite_contract_ready_utc"] is not None:
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
            capture_faults = _authoritative_capture_health_faults(health)
            if capture_faults:
                raise ValueError("ADAPTIVE_HYBRID reference qualification unavailable: "
                                 + "; ".join(capture_faults))
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
        if hybrid_state == "FAIL_STATIC" and not prospective_controller_inhibit:
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
        maximum_applications = bench_attempt.limits.automatic_application_limit
        if (
            corrections > maximum_applications
            or corrections > self.spec.correction_limit
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
            self.state["first_phase_observation_checkpoint_exact"] = True
            dirty = True
        if (
            hybrid_state == "HYBRID_TRACKING"
            and checkpoint
            and not self.state["later_authority_released"]
        ):
            self.state["later_authority_released"] = True
            dirty = True
            self._programme_event(
                "first_phase_observation_checkpoint_release_observed",
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
                    "capture_session": int(health[("adaptive_hybrid", "session_id")]),
                    "acceptance_epoch": int(health[("adaptive_hybrid", "acceptance_epoch")]),
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
            health[("adaptive_hybrid", "gnss_qualified_accepted_ordinal")]
        )
        observation_sequence = int(
            health[("adaptive_hybrid", "accepted_boundary_ordinal")]
        )
        if (
            metadata_sequence <= retained["entry_sequence"]
            or not 0 <= observation_sequence < 1 << 32
            or not 0 <= qualification_frontier < 1 << 32
            or not 0 < (observation_sequence - qualification_frontier) % (1 << 32) < 1 << 31
            or int(health[("adaptive_hybrid", "session_id")]) != retained["capture_session"]
            or int(health[("adaptive_hybrid", "acceptance_epoch")]) != retained["acceptance_epoch"]
            or health.get(("adaptive_hybrid", "state")) != "DISARMED"
        ):
            raise ValueError("GNSS metadata hold cleared without fresh causal requalification")
        self.state["gnss_metadata_hold"] = None
        self._save()
        self._programme_event(
            "gnss_metadata_hold_requalified",
            metadata_sequence=metadata_sequence,
            qualification_frontier=qualification_frontier,
            post_qualification_accepted_boundary_ordinal=observation_sequence,
            applied_code=retained["applied_code"],
            dac_epoch=retained["dac_epoch"],
        )

    def _authoritative_selected_estimates(
        self,
        rows: list[dict[str, str]], *, dac_epoch: int,
    ) -> list[dict[str, str]]:
        expected_dac_ref = f"live:DAC:{dac_epoch}"
        return [
            row
            for row in rows
            if row.get("estimator_version")
            == self.natural_policy.frequency_estimator_id
            and row.get("observation_validity") == "valid"
            and row.get("reference_validity") == "valid"
            and row.get("reference_continuity") == "true"
            and row.get("count_validity") == "valid"
            and row.get("count_continuity") == "true"
            and row.get("diagnostic_health") == "healthy"
            and row.get("preview_eligibility") == "true"
            and row.get("source_dac_ref") == expected_dac_ref
            and int(row.get("accepted_sample_count") or "0") == SELECTED_INTERVAL_S
            and row.get("source_accepted_spans_ref", "").startswith("live:APS:")
        ]

    def _fresh_authoritative_selected_estimate(
        self,
        rows: list[dict[str, str]], *, dac_epoch: int,
    ) -> dict[str, str] | None:
        candidates = self._authoritative_selected_estimates(
            rows, dac_epoch=dac_epoch
        )
        return candidates[-1] if candidates else None


    def _maybe_qualify(self, health: dict[tuple[str, str], str]) -> None:
        if self.state["qualification_started_utc"] is not None:
            return
        bench_attempt = self.runtime_context.bench_attempt
        if bench_attempt.purpose == INHIBITED_ZERO_WRITE:
            self._maybe_establish_zero_write_aperture_origin(health)
            return
        if (self.state["setup_confirmed_utc"] is None
            or not self._identity_ready(health)
            or _authoritative_capture_health_faults(health)):
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
            session_id = int(health[("adaptive_hybrid", "session_id")])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ADAPTIVE_HYBRID qualified origin device clock is malformed") from exc
        authoritative_capture_baseline: dict[str, int] | None = None
        qualified_origin_extended_ticks: int | None = None
        qualified_frontier_raw_ticks: int | None = None
        qualified_frontier_extended_ticks: int | None = None
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
                acceptance_epoch_origin = int(estimate["source_acceptance_epoch"])
                accepted_origin = int(
                    estimate["source_closing_accepted_boundary_ordinal"]
                )
                current_epoch = int(
                    health[("pps_gate", "reference_acceptance_epoch")]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "ADAPTIVE_HYBRID qualified D14 aperture origin is unavailable"
                ) from exc
            if (
                acceptance_epoch_origin <= 0
                or not (0 <= accepted_origin < 1 << 32)
            ):
                raise ValueError("ADAPTIVE_HYBRID qualified D14 aperture origin is malformed")
            if (current_epoch != acceptance_epoch_origin
                or health.get(("adaptive_hybrid", "acceptance_epoch"))
                != str(acceptance_epoch_origin)):
                # Independent observations may straddle reacquisition.
                # Do not freeze a qualified origin until they name its epoch.
                return
        self.state["qualification_started_utc"] = _utc_now()
        self.state["qualified_origin_estimate_id"] = estimate["estimate_id"]
        self.state["qualified_origin_timestamp_ticks"] = origin_ticks
        self.state["qualified_origin_session_id"] = session_id
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
            self.state["qualified_acceptance_epoch_origin"] = acceptance_epoch_origin
            self.state["qualified_acceptance_ordinal_origin"] = accepted_origin
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
            source_accepted_spans_ref=estimate["source_accepted_spans_ref"],
            source_dac_ref=estimate["source_dac_ref"],
            dac_epoch=dac_epoch,
            qualified_duration_s=self.programme.qualified_duration_s,
            qualified_d14_aperture_count=(
                self.programme.qualified_d14_aperture_count
            ),
            acceptance_epoch_origin=self.state.get("qualified_acceptance_epoch_origin"),
            accepted_boundary_ordinal_origin=self.state.get(
                "qualified_acceptance_ordinal_origin"
            ),
            authoritative_capture_baseline=self.state.get(
                "qualified_authoritative_capture_baseline"
            ),
        )

    def _maybe_establish_zero_write_aperture_origin(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        """Establish the zero-write endpoint without inventing a DAC epoch."""

        if (
            not self._identity_ready(health)
            or _authoritative_capture_health_faults(health)
            or health.get(("adaptive_hybrid", "state")) != "DISARMED"
            or _truth(health, "manual_start_confirmed")
            or _truth(health, "evidence_pending")
            or health.get(("adaptive_hybrid", "evidence_phase")) != "evidence_clear"
        ):
            return
        if health.get(("pps_gate", "reference_acceptance_epoch")) != health.get(
            ("adaptive_hybrid", "acceptance_epoch")
        ):
            return
        try:
            session_id = int(health[("pps_gate", "snapshot_session")])
            acceptance_epoch = int(
                health[("pps_gate", "reference_acceptance_epoch")]
            )
            accepted_origin = int(
                health[("pps_gate", "accepted_boundary_ordinal")]
            )
            baseline = {
                key: int(health[("pps_gate", key)])
                for key in _authoritative_capture_counters(self.programme)
            }
        except (KeyError, TypeError, ValueError):
            return
        if (
            session_id <= 0
            or acceptance_epoch <= 0
            or not 0 <= accepted_origin < 1 << 32
            or any(value < 0 for value in baseline.values())
        ):
            return
        self.state["qualification_started_utc"] = _utc_now()
        self.state["qualified_origin_estimate_id"] = (
            "bench_attempt:no_setup_accepted_D14_D8_aperture_origin"
        )
        self.state["qualified_origin_session_id"] = session_id
        self.state["qualified_acceptance_epoch_origin"] = acceptance_epoch
        self.state["qualified_acceptance_ordinal_origin"] = accepted_origin
        self.state["qualified_authoritative_capture_baseline"] = baseline
        self._save()
        self._programme_event(
            "zero_write_aperture_origin_established",
            capture_session=session_id,
            acceptance_epoch_origin=acceptance_epoch,
            accepted_boundary_ordinal_origin=accepted_origin,
            setup_application_count=0,
            DAC_value_write_count=0,
            progress_domain="accepted_D14_D8_apertures",
        )

    def _abort_on_authoritative_capture_discontinuity(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        """Stop an integrated long run before post-discontinuity work."""

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
        origin_epoch = self.state.get("qualified_acceptance_epoch_origin")
        if origin_epoch is not None:
            for component, key in (("pps_gate", "reference_acceptance_epoch"),
                                   ("adaptive_hybrid", "acceptance_epoch")):
                if health.get((component, key)) != str(origin_epoch):
                    faults.append(f"{component}.{key}_differs_from_qualified_origin")
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
        self._arm_sent_monotonic_ns = None
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
                    ("pps_gate", "snapshot_session")
                ]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ADAPTIVE_HYBRID current qualified device clock is malformed") from exc
        if current_session != origin_session:
            raise ValueError("ADAPTIVE_HYBRID capture session changed after qualified origin")
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

    def _qualified_d14_apertures(
        self, health: dict[tuple[str, str], str]
    ) -> int | None:
        target = self.programme.qualified_d14_aperture_count
        if target is None:
            return None
        origin_epoch = self.state.get("qualified_acceptance_epoch_origin")
        origin_ordinal = self.state.get("qualified_acceptance_ordinal_origin")
        origin_session = self.state.get("qualified_origin_session_id")
        if not all(type(value) is int for value in (
            origin_epoch, origin_ordinal, origin_session
        )):
            return None
        try:
            current_session = int(health[("pps_gate", "snapshot_session")])
            current_epoch = int(health[("pps_gate", "reference_acceptance_epoch")])
            current_ordinal = int(health[("pps_gate", "accepted_boundary_ordinal")])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "ADAPTIVE_HYBRID accepted-span progress is unavailable"
            ) from exc
        if current_session != origin_session or current_epoch != origin_epoch:
            raise ValueError(
                "ADAPTIVE_HYBRID acceptance session or epoch changed during qualification"
            )
        if (
            origin_epoch <= 0 or origin_session <= 0
            or not 0 <= origin_ordinal < 1 << 32
            or not 0 <= current_ordinal < 1 << 32
        ):
            raise ValueError("ADAPTIVE_HYBRID accepted boundary coordinate is malformed")
        accepted_delta = (current_ordinal - origin_ordinal) & 0xFFFFFFFF
        if accepted_delta > 0x7FFFFFFF:
            raise ValueError(
                "ADAPTIVE_HYBRID accepted boundary ordinal moved backward"
            )
        self.state["qualified_d14_accepted_apertures"] = accepted_delta
        self.state["qualified_acceptance_ordinal_endpoint"] = current_ordinal
        return accepted_delta

    def _close_bench_arm_admission_if_required(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        """Close new ARM admission in the exact accepted-aperture domain."""

        bench_attempt = self.runtime_context.bench_attempt
        if self._bench_authority_closed():
            if not self.state.get("bench_attempt_arm_admission_closed"):
                self.state["bench_attempt_arm_admission_closed"] = True
                self._save()
            return True
        if self.state.get("bench_attempt_arm_admission_closed"):
            return True
        if bench_attempt.purpose != UNATTENDED_72_HOUR_HYBRID_CONTROL:
            raise ValueError("unknown physical bench-attempt authority state")
        if time.monotonic_ns() >= self._wall_deadline_monotonic_ns - UNATTENDED_CLOSURE_RESERVE_S * 1_000_000_000:
            self.state["bench_attempt_arm_admission_closed"] = True
            self.state["bench_attempt_arm_admission_closed_utc"] = _utc_now()
            self.state["bench_attempt_arm_admission_reason"] = "fixed_host_endpoint_closure_reserve"
            self._save()
            return True
        aperture_progress = self._qualified_d14_apertures(health)
        deadline = (
            bench_attempt.limits.automatic_application_admission_deadline_apertures
        )
        if aperture_progress is None or aperture_progress < deadline:
            return False
        self.state["bench_attempt_arm_admission_closed"] = True
        self.state["bench_attempt_arm_admission_closed_utc"] = _utc_now()
        self.state["bench_attempt_arm_admission_endpoint"] = aperture_progress
        self._save()
        self._programme_event(
            "bench_attempt_arm_admission_closed",
            accepted_D14_D8_apertures=aperture_progress,
            admission_deadline_delta=deadline,
            progress_domain="accepted_D14_D8_apertures",
            endpoint_contract="qualified_D14_D8_aperture_count_v2",
            new_ARM_authority=False,
            attempt_extension_permitted=False,
        )
        return True

    def _maybe_start_or_arm(
        self,
        health: dict[tuple[str, str], str],
    ) -> None:
        if not self._startup_census_admitted():
            return
        if self.state.get("host_verification_hold") is not None:
            return
        bench_attempt = self.runtime_context.bench_attempt
        if self._bench_authority_closed():
            return
        if (
            self.state.get("bench_attempt_arm_admission_closed")
            and not self.state.get("arm_pending")
        ):
            return
        if (not self._identity_ready(health)
            or _authoritative_capture_health_faults(health)):
            return
        state = health.get(("adaptive_hybrid", "state"), "")
        reason = health.get(("adaptive_hybrid", "reason"), "")
        controller_inhibit = (
            state == "FAULT"
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
            capture_session = self._capture_session_for_authority(health)
            if capture_session is None or not self._acquisition_authority_ready(
                expected_capture_session=capture_session
            ):
                return
            command, request = self._setup_command(health)
            self._retain_setup_authority(health, request)
            self._command(command)
            self.state["manual_start_sent"] = True
            self.state["setup_requested_utc"] = _utc_now()
            self._setup_requested_monotonic_ns = time.monotonic_ns()
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

        setup_confirmation = self.state.get("setup_confirmation")
        setup_confirmation_exact = (
            isinstance(self.state.get("setup_confirmed_utc"), str)
            and bool(self.state.get("setup_confirmed_utc"))
            and isinstance(setup_confirmation, dict)
            and setup_confirmation.get("session_id")
            == self.state.get("initial_session_id")
            and setup_confirmation.get("applied_code")
            == self.programme.setup_code
            and setup_confirmation.get("dac_epoch") == 1
        )
        if manual_confirmed and not setup_confirmation_exact:
            self._enter_host_verification_hold(
                ValueError(
                    "firmware manual-start status lacks the exact retained "
                    "setup first-consumer confirmation"
                ),
                source="setup_first_consumer_confirmation",
            )
            return

        if self.state["arm_pending"] and state == "DISARMED":
            sent_ns = self._arm_sent_monotonic_ns
            if (
                type(sent_ns) is int
                and time.monotonic_ns() - sent_ns > 15_000_000_000
            ):
                self.state["arm_pending"] = False
                self.state["arm_sent_at_utc"] = None
                self._arm_sent_monotonic_ns = None
                self._save()
                self._programme_event(
                    "unused_zero_delta_arm_consumed_without_write"
                )
        if not manual_confirmed or self.state["arm_pending"]:
            return
        if self._close_bench_arm_admission_if_required(health):
            return

        # FIRST_PHASE_TRANSACTION stays unarmed until firmware has durably
        # recorded the response checkpoint and observed tight reacquisition.
        hybrid_state = health.get(("adaptive_hybrid", "hybrid_state"), "")
        if hybrid_state not in self.programme.armable_hybrid_states:
            return
        if hybrid_state == "HYBRID_TRACKING" and not _truth(
            health, "first_phase_checkpoint_passed"
        ):
            raise ValueError("later ADAPTIVE_HYBRID authority lacks its firmware checkpoint")
        correction_count = int(
            health.get(("adaptive_hybrid", "correction_count"), "0")
        )
        correction_limit = bench_attempt.limits.automatic_application_limit
        if correction_count >= correction_limit:
            return
        progress = int(
            health.get(("adaptive_hybrid", "selected_interval_count"), "0")
        )
        preview_rows = _read_csv(self.run_dir / CONTROL_CSV)
        preview = preview_rows[-1] if preview_rows else None
        if (
            preview is None
            or preview.get("preview_available") != "true"
            or preview.get("preview_eligibility") != "true"
        ):
            # Immediately after setup there is no natural correction
            # opportunity yet.  A durable CTL decision without an eligible
            # preview is also explicitly zero-authority.  Wait for the first
            # eligible preview rather than deriving ARM authority merely from
            # decision_id/control_seq presence.
            return
        if not self._arm_progress_epoch_ready(preview, progress):
            return
        opportunity = None
        if preview is not None:
            opportunity = preview.get("decision_id") or preview.get("control_seq")
        arm_count = self.state.get("bench_attempt_arm_submission_count")
        if type(arm_count) is not int:
            raise ValueError("bench-attempt ARM submission count is malformed")
        if arm_count >= bench_attempt.limits.arm_submission_limit:
            self.state["bench_attempt_arm_admission_closed"] = True
            self.state["bench_attempt_arm_admission_closed_utc"] = _utc_now()
            self._save()
            self._programme_event(
                "bench_attempt_arm_submission_limit_reached",
                arm_submission_count=arm_count,
                new_ARM_authority=False,
            )
            return
        if opportunity is None:
            raise ValueError(
                "bench-attempt ARM lacks a distinct natural-correction opportunity"
            )
        if opportunity == self.state.get("bench_attempt_last_arm_opportunity"):
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
        source_estimate_id = (
            preview.get("est_input_ref") if preview is not None else None
        )
        if not source_estimate_id:
            self._enter_host_verification_hold(
                ValueError("ARM opportunity lacks its selected EST identity"),
                source="acquisition_frontier",
            )
            return
        capture_session = self._capture_session_for_authority(health)
        if capture_session is None:
            return
        if not self._acquisition_authority_ready(
            expected_capture_session=capture_session,
            source_estimate_id=source_estimate_id
        ):
            return
        uptime = int(health[("adaptive_hybrid", "uptime_s")])
        sequence = int(self.state["authorization_sequence"]) + 1
        nonce = secrets.randbits(32) or 1
        expiry = uptime + ARM_LIFETIME_S
        arm_sent_at_utc = _utc_now()
        arm_sent_monotonic_ns = time.monotonic_ns()
        admission: dict[str, object] | None = None
        aperture_coordinate = self._qualified_d14_apertures(health)
        if aperture_coordinate is None:
            raise ValueError("bench-attempt ARM lacks an accepted-aperture coordinate")
        admission = {
            "authorization_sequence": sequence,
            "arm_nonce": nonce,
            "expiry_s": expiry,
            "authorizing_snapshot_generation": int(
                health[("adaptive_hybrid", "snapshot_generation_complete")]
            ),
            "authorizing_query_nonce": int(
                health[("adaptive_hybrid", "query_nonce")]
            ),
            "accepted_D14_D8_apertures": aperture_coordinate,
            "admission_deadline_delta": (
                bench_attempt.limits.automatic_application_admission_deadline_apertures
            ),
            "natural_opportunity": str(opportunity),
            "admitted_utc": arm_sent_at_utc,
        }
        admissions = self.state["bench_attempt_arm_admissions"]
        if not isinstance(admissions, list):
            raise ValueError("bench-attempt ARM admissions are malformed")
        # Validate retained state and all inputs before publishing any new
        # authorization state.  A host-side coordinate/parser failure must
        # leave no ghost ARM sequence or pending transaction behind.
        self._validate_bench_attempt_arm_admissions()

        if self._close_bench_arm_admission_if_required(health):
            return
        self.state["authorization_sequence"] = sequence
        self.state["arm_pending"] = True
        self.state["arm_sent_at_utc"] = arm_sent_at_utc
        self._arm_sent_monotonic_ns = arm_sent_monotonic_ns
        assert admission is not None
        admissions = self.state["bench_attempt_arm_admissions"]
        assert isinstance(admissions, list)
        admissions.append(admission)
        self.state["bench_attempt_arm_submission_count"] = arm_count + 1
        self.state["bench_attempt_last_arm_opportunity"] = opportunity
        self._validate_bench_attempt_arm_admissions()
        self._save()
        self._command(f"ACTIVE ARM {sequence} {nonce} {expiry}")
        self._programme_event(
            "one_decision_armed",
            authorization_sequence=sequence,
            expiry_s=expiry,
            selected_interval_count=progress,
            hybrid_state=hybrid_state,
            bench_attempt_arm_submission_count=arm_count + 1,
            bench_attempt_natural_opportunity=opportunity,
            bench_attempt_admission=admission,
        )

    def _healthy_terminal_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        if (
            not self._identity_ready(health)
            or _authoritative_capture_health_faults(health)
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

    def _inhibited_zero_write_terminal_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        """Require a static no-authority endpoint without inventing a DAC code."""

        bench_attempt = self.runtime_context.bench_attempt
        if (
            bench_attempt.purpose != INHIBITED_ZERO_WRITE
            or not self._identity_ready(health)
            or _authoritative_capture_health_faults(health)
        ):
            return False

        exact_health = {
            "state": "DISARMED",
            "reason": "initialized_disarmed",
            "hybrid_state": "SETUP_PENDING",
            "hybrid_reason": "setup_consumers_pending",
            "capture_lease_live": "true",
            "manual_start_confirmed": "false",
            "arm_eligible": "false",
            "fail_static": "false",
            "evidence_phase": "evidence_clear",
            "evidence_pending": "false",
            "evidence_request_sequence": "0",
            "confirmed_applied_code_known": "false",
            "confirmed_applied_code": "unavailable",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "dac_epoch": "0",
            "phase_material_application_count": "0",
            "phase_nonzero_application_count": "0",
            "frequency_only_application_count": "0",
            "first_phase_checkpoint_passed": "false",
            "automatic_retry": "false",
            "automatic_restore": "false",
        }
        if any(
            health.get(("adaptive_hybrid", key)) != expected
            for key, expected in exact_health.items()
        ):
            return False

        causal_state = self.state.get("bench_attempt_causal_state")
        try:
            self._validate_bench_attempt_causal_state(causal_state)
        except ValueError:
            return False
        if (
            self.state.get("host_verification_hold") is not None
            or self.state.get("terminal_static_code") is not None
            or self.state.get("manual_start_sent") is not False
            or self.state.get("arm_pending") is not False
            or self.state.get("arm_sent_at_utc") is not None
            or self.state.get("authorization_sequence") != 0
            or self.state.get("setup_authorization_sequence") != 0
            or self.state.get("setup_requested_utc") is not None
            or self.state.get("setup_confirmed_utc") is not None
            or self.state.get("setup_authority_path") is not None
            or self.state.get("setup_confirmation") is not None
            or self.state.get("bench_attempt_arm_admission_closed") is not True
            or self.state.get("bench_attempt_arm_submission_count") != 0
            or self.state.get("bench_attempt_last_arm_opportunity") is not None
            or self.state.get("bench_attempt_arm_admissions") != []
            or self.state.get("later_authority_released", False) is not False
            or self.state.get("first_phase_checkpoint_passed", False) is not False
            or self.state.get("first_phase_observation_checkpoint_exact", False)
            is not False
            or self.state.get("phase_material_application_count", 0) != 0
            or causal_state.get("durable_ACT_application_count") != 0
            or causal_state.get("firmware_correction_count") != 0
            or causal_state.get("authority_closed") is not True
            or _read_csv(self.run_dir / ACTIVE_CSV)
            or _read_csv(self.run_dir / DAC_CSV)
            or (self.run_dir / SETUP_AUTHORITY_PATH).exists()
        ):
            return False

        origin_session = self.state.get("qualified_origin_session_id")
        baseline = self.state.get("qualified_authoritative_capture_baseline")
        try:
            current_session = int(health[("pps_gate", "snapshot_session")])
            counters_unchanged = isinstance(baseline, dict) and all(
                type(baseline.get(key)) is int
                and int(health[("pps_gate", key)]) == baseline[key]
                for key in _authoritative_capture_counters(self.programme)
            )
        except (KeyError, TypeError, ValueError):
            return False
        return (
            type(origin_session) is int
            and current_session == origin_session
            and counters_unchanged
        )

    def _set_healthy_endpoint(
        self, health: dict[tuple[str, str], str], *, endpoint: str,
        observed_terminal_monotonic_ns: int | None = None,
    ) -> None:
        preliminary = "pending_offline_scientific_analysis"
        self.state["terminal"] = {
            "result": "healthy_stop",
            "reason": endpoint,
            "preliminary_decision": preliminary,
            "last_confirmed_code": self.state["terminal_static_code"],
            "utc": _utc_now(),
        }
        if self.runtime_context.bench_attempt.purpose in {INHIBITED_ZERO_WRITE, UNATTENDED_72_HOUR_HYBRID_CONTROL}:
            # Raw same-process host coordinates make the observation duration
            # reviewable without projecting UTC or firmware time into it.
            self.state["terminal"]["observation_window"] = {
                **self.state["inhibited_observation_window"],
                "observed_terminal_monotonic_ns": observed_terminal_monotonic_ns,
            }
        self._save()

    def _maybe_finish_bench_attempt(
        self,
        health: dict[tuple[str, str], str],
        now_monotonic_ns: int,
    ) -> bool:
        """Apply only the terminal horizons frozen in the bench envelope."""

        bench_attempt = self.runtime_context.bench_attempt
        document = bench_attempt.as_dict()
        terminals = document["terminal_semantics"]
        progress = self._qualified_d14_apertures(health)
        wall_reached = now_monotonic_ns >= self._wall_deadline_monotonic_ns
        if bench_attempt.purpose == INHIBITED_ZERO_WRITE:
            if (
                progress is not None
                and wall_reached
                and self._inhibited_zero_write_terminal_ready(health)
            ):
                self._set_healthy_endpoint(
                    health, endpoint=str(terminals["success_terminal"]),
                    observed_terminal_monotonic_ns=now_monotonic_ns,
                )
            elif wall_reached:
                self._enter_host_verification_hold(
                    ValueError("zero-write wall endpoint lacks a clear static terminal"),
                    source="bench_attempt_wall_endpoint_observer",
                )
            return True
        if bench_attempt.purpose != UNATTENDED_72_HOUR_HYBRID_CONTROL:
            raise ValueError("unsupported physical bench-attempt terminal semantics")
        # Qualified progress is evidence, never a replacement for elapsed
        # endurance duration. 72 accepted hours is a nonterminal checkpoint.
        if not wall_reached:
            return True
        if self._healthy_terminal_ready(health):
            self._set_healthy_endpoint(
                health, endpoint=str(terminals["success_terminal"]),
                observed_terminal_monotonic_ns=now_monotonic_ns,
            )
            if self.state.get("host_verification_hold") is not None:
                self.state["terminal"].update(
                    result="scheduled_stop",
                    reason="adaptive_hybrid_scheduled_stop_review_required",
                    unresolved_review=self.state["host_verification_hold"],
                )
                self._save()
        else:
            self._enter_host_verification_hold(
                ValueError("endurance endpoint lacks exact disarmed static evidence"),
                source="unattended_wall_endpoint",
            )
        return True

    def _maybe_finish(
        self,
        health: dict[tuple[str, str], str],
        now_monotonic_ns: int,
    ) -> None:
        if self.state["terminal"] is None:
            self._maybe_finish_bench_attempt(health, now_monotonic_ns)

    def _record_abort_terminal(self, reason: str) -> None:
        terminal: dict[str, object] = {
            "result": "aborted",
            "reason": reason,
            "utc": _utc_now(),
        }
        if reason == "independent_emergency_abort_fifo":
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_operator_abort"
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
                self.programme, "_D14_D8_authority_or_capture_fault"
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
                self.programme, "_identity_or_evidence_fault"
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
        ) or reason.endswith("_qualification_deadline_expired"):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_right_censored_incomplete"
            )
        else:
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme, "_identity_or_evidence_fault"
            )
        static_code = self.state.get("terminal_static_code")
        if isinstance(static_code, int):
            terminal["last_confirmed_code"] = static_code
        self.state["terminal"] = terminal
        self._save()

    def _abort(self, reason: str) -> None:
        """Submit one priority abort directly to capture, then retain its reason."""
        try:
            send_timestamped_command_to_fifo(
                self.emergency_command_fifo, "ACTIVE ABORT"
            )
            self._event("emergency_device_abort_submitted", reason=reason)
        except (OSError, SystemExit, ValueError) as exc:
            self._event(
                "device_abort_submission_failed", reason=reason, error=str(exc)
            )
        self._record_abort_terminal(reason)

    def _observe_explicit_capture_abort(self, state: dict[str, Any]) -> None:
        """Adopt a direct external priority abort without sending it again."""
        if self.state.get("terminal") is not None:
            return
        self._event(
            "external_priority_abort_observed",
            emergency_aborts_sent=int(state.get("emergency_aborts_sent", 0)),
        )
        self._record_abort_terminal("independent_emergency_abort_fifo")

    def _emit_terminal_once(self) -> None:
        terminal = self.state.get("terminal")
        if isinstance(terminal, dict) and not self.state["terminal_event_emitted"]:
            self._programme_event("campaign_terminal", **terminal)
            self.state["terminal_event_emitted"] = True
            self._save()

    def run(self) -> int:
        """Run the decision owner in the foreground process."""
        capture_flag = self.run_dir / CAPTURE_IN_PROGRESS_FLAG
        if not capture_flag.exists():
            raise RuntimeError("capture is not marked in progress")
        started = time.monotonic()
        last_query = 0.0
        last_output_status_query = started
        self._live_command_ack_required = True
        self.state["runtime_owner"] = {
            "pid": os.getpid(),
            "started_monotonic_ns": time.monotonic_ns(),
            "execution": "foreground",
            "priority_abort_ingress": str(self.emergency_command_fifo),
        }
        self._save()
        self._programme_event(
            "live_supervisor_started",
            emergency_abort_fifo=str(self.emergency_command_fifo),
            manifest_sha256=self.runtime_context.manifest_sha256,
            run_spec_sha256=self.runtime_context.run_spec_sha256,
            policy_sha256=self.runtime_context.policy_sha256,
            wall_origin_utc=self.runtime_context.wall_origin_utc,
        )
        try:
            while True:
                self._poll_wait_abort()
                now = time.monotonic()
                if not capture_flag.exists():
                    self._enter_host_verification_hold(
                        RuntimeError("capture owner in-progress marker is absent"),
                        source="capture_owner_observer",
                    )
                    time.sleep(0.2)
                    continue
                try:
                    if (
                        self.state.get("startup_census") is None
                        and self.state.get("host_verification_hold") is None
                    ):
                        self._command("CONFIG?")
                        self._command("DUALCORE?")
                        self._command("DAC?")
                        self._establish_startup_census()
                        last_query = time.monotonic()
                    if (
                        self._startup_census_admitted()
                        and (
                            getattr(self, "_last_lease_monotonic_ns", None) is None
                            or time.monotonic_ns() - self._last_lease_monotonic_ns
                            >= int(LEASE_PERIOD_S * 1_000_000_000)
                        )
                    ):
                        self._check_capture_transport_state()
                        self._renew_lease()
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
                    if now - last_output_status_query >= FORWARDED_OUTPUT_STATUS_PERIOD_S:
                        self._command("CONFIG?")
                        last_output_status_query = now
                    health = self._current_health()
                    if not self._startup_census_admitted():
                        time.sleep(0.2)
                        continue
                    # At the authorized endpoint, an unrelated retained diagnostic
                    # cannot veto closure if static/disarmed evidence is exact.
                    # Evaluate this before the diagnostic path that raised it.
                    if (self.state.get("host_verification_hold") is not None
                            and time.monotonic_ns() >= self._wall_deadline_monotonic_ns):
                        self._maybe_finish(health, time.monotonic_ns())
                        if self.state.get("terminal") is not None:
                            self._emit_terminal_once()
                            return 2  # Review pending; no scientific failure claim.
                    if not self._abort_on_authoritative_capture_discontinuity(health):
                        self._check_fail_static_health(health)
                        self._process_transactions()
                        health = self._current_health()
                        if not self._abort_on_authoritative_capture_discontinuity(health):
                            self._check_fail_static_health(health)
                            if self.state.get("host_verification_hold") is None:
                                self._check_setup_transaction_timeout(health)
                            self._check_prewrite_contract(health, now - started)
                            self._maybe_qualify(health)
                            self._maybe_finish(health, time.monotonic_ns())
                            if self.state["terminal"] is None:
                                self._maybe_start_or_arm(health)
                except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                    self._enter_host_verification_hold(
                        exc, source="live_supervisor_diagnostic_cycle"
                    )
                if self.state["terminal"] is not None:
                    self._emit_terminal_once()
                    return (
                        0
                        if self.state["terminal"]["result"] == "healthy_stop"
                        else 2
                    )
                time.sleep(0.2)
        except ExplicitSupervisorAbort:
            self._emit_terminal_once()
            return 3

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
