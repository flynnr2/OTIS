"""Executable fail-static supervisor for the frozen CX320 live campaign.

The capture process remains the sole serial owner.  This supervisor submits
only timestamped commands through that owner's bounded normal FIFO and submits
``ACTIVE ABORT`` through the independent emergency FIFO.  Every active
transaction phase is durably retained and replayed by the shared ACT machinery
before the corresponding firmware evidence acknowledgement is released.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import secrets
import time
from typing import Any

from .abort_transport import AbortFifo
from .active_hybrid_evidence_guard import (
    IndependentReplayMismatch,
    ResponseCheckpointRejected,
)
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    programme_from_mapping,
    progressive_checkpoint_contract,
)
from .active_hybrid_policy import load_cx323_policy
from .active_status_live_state import (
    LIVE_FRONTIER_COMPONENT,
    LIVE_FRONTIER_DOMAIN_KEY,
    LIVE_FRONTIER_TICKS_KEY,
)
from .active_control_supervisor import (
    ESTIMATES_CSV,
    RP2040_TIMER0_TICKS_PER_SECOND,
    ControlSupervisorBase,
    _parse_utc_epoch,
)
from .active_transactions import (
    ACTIVE_CSV,
    LEASE_PERIOD_S,
QUERY_PERIOD_S,
    CampaignSpec,
    _read_csv,
    _utc_now,
)
FORWARDED_OUTPUT_STATUS_PERIOD_S = 60.0
from .contracts import CsvValidationContext, validate_csv
from .cx321_plant_sign_evidence_guard import (
    plant_sign_terminal_decision_from_record,
)
from .bounded_tight_deadband_prewrite_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    PrewriteReadiness,
    evaluate_prewrite_readiness as evaluate_setup_prewrite_readiness,
)
from .frequency_control_supervisor import (
    ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S,
    ACTIVE_STATUS_COMPLETE_MAX_AGE_S,
    ARM_LIFETIME_S,
    ARM_PROGRESS_THRESHOLD,
    CONTROL_CSV,
    CORRECTION_RESPONSE_RESERVE_S,
    DAC_CSV,
    DECISION_CADENCE_S,
    SELECTED_INTERVAL_S,
    FrequencyControlSupervisor,
    TightDeadbandLeg,
)
from .gnss_operational_baud_policy import (
    gnss_operational_runtime_invariant_errors,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG
from .time_domains import forward_progress


TOOL_ID = "cx320_active_hybrid_live_supervisor_v1"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
PROFILE_ID = "cx320_active_hybrid"
RUNTIME_RUN_IDENTITY = "cx320_active_hybrid:3200001"
ACTIVE_HYBRID_CSV = Path("csv/active_hybrid_decisions_v1.csv")
PLANT_SIGN_CSV = Path("csv/plant_sign_qualification_v1.csv")

SETUP_CODE = 0xA83C
MAXIMUM_APPLICATIONS = 4
MAXIMUM_CUMULATIVE_MOVEMENT_CODES = 84
MAXIMUM_STEP_CODES = 21
MINIMUM_CODE = 0xA800
MAXIMUM_CODE = 0xAB00
QUALIFIED_DURATION_S = 43_200
ABSOLUTE_WALL_LIMIT_S = 57_600
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
FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH = {
    ("build", "enable_forwarded_d9_output"): "1",
    ("build", "enable_forwarded_d6_monitor"): "1",
    ("build", "enable_d9_d6_readiness_profile"): "0",
    ("forwarded_clock_output", "contract_id"): (
        "OTIS_D9_D6_READINESS_CONTRACT_V1"
    ),
    ("forwarded_clock_output", "contract_sha256"): (
        "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d"
    ),
    ("forwarded_clock_output", "state"): (
        "configured_10mhz_forwarded_unqualified"
    ),
    ("forwarded_clock_output", "source"): "D8_GPIO20_GPIN0",
    ("forwarded_clock_output", "destination"): "D9_GPIO21_GPOUT0",
    ("forwarded_clock_output", "integer_divider"): "1",
    ("forwarded_clock_output", "fractional_divider"): "0",
    ("forwarded_clock_output", "applied_auxsrc"): "1",
    ("forwarded_clock_output", "applied_integer_divider"): "1",
    ("forwarded_clock_output", "applied_fractional_divider"): "0",
    ("forwarded_clock_output", "source_gpio_function"): "8",
    ("forwarded_clock_output", "destination_gpio_function"): "8",
    ("forwarded_clock_output", "inversion"): "0",
    ("forwarded_clock_output", "drive_strength_ma"): "2",
    ("forwarded_clock_output", "slew_rate"): "slow",
    ("forwarded_clock_output", "nominal_frequency_hz"): "10000000",
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
    programme: ActiveHybridProgramme,
    suffix: str,
    *,
    fallback: str,
) -> str:
    """Resolve one exact programme terminal without inheriting labels."""

    matches = sorted(
        decision
        for decision in programme.terminal_decisions
        if decision.endswith(suffix)
    )
    if len(matches) == 1:
        return matches[0]
    if programme.integrated_long_run:
        raise ValueError(
            f"{programme.key} must declare exactly one terminal ending {suffix!r}"
        )
    return fallback


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
PLANT_SIGN_SPAN_INTERVALS = 1_500
# The 110 s one-shot arm must be submitted after at least 1,400 accepted
# one-second intervals.  That leaves at most 100 s until the plant window
# closes and one complete 10 s status-query margin before arm expiry.
PLANT_SIGN_PREARM_MIN_ACCEPTED_INTERVALS = PLANT_SIGN_SPAN_INTERVALS - (
    ARM_LIFETIME_S - int(QUERY_PERIOD_S)
)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256_identity(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"CX320 manifest {label} is not a SHA-256 identity")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            f"CX320 manifest {label} is not a SHA-256 identity"
        ) from exc
    return value


def _bound_file(binding: object, label: str) -> Path:
    if not isinstance(binding, dict):
        raise ValueError(f"CX320 manifest {label} binding is unavailable")
    path = Path(str(binding.get("path", ""))).resolve()
    expected_sha256 = _sha256_identity(binding.get("sha256"), f"{label}.sha256")
    if (
        not path.is_file()
        or sha256(path.read_bytes()).hexdigest() != expected_sha256
        or path.stat().st_size != binding.get("size_bytes")
    ):
        raise ValueError(f"CX320 manifest {label} file binding differs")
    return path


@dataclass(frozen=True)
class RuntimeEnvelope:
    programme: ActiveHybridProgramme
    manifest_sha256: str
    bundle_sha256: str
    policy_sha256: str
    build_identity: str
    uf2_sha256: str
    policy_path: Path
    natural_policy_path: Path
    natural_policy_sha256: str
    phase_estimator_sha256: str
    plant_sign_identities: dict[str, str]
    wall_origin_utc: str


def _runtime_envelope(manifest: dict[str, Any]) -> RuntimeEnvelope:
    """Extract identities only from a validated, run-local live manifest."""

    programme = programme_from_mapping(manifest)
    section = manifest.get(programme.manifest_section, {})
    control = (
        section.get("automatic_control", {}) if isinstance(section, dict) else {}
    )
    qualification = (
        section.get("qualification", {}) if isinstance(section, dict) else {}
    )
    setup = section.get("setup", {}) if isinstance(section, dict) else {}
    firmware = manifest.get("firmware", {})
    natural_policy_binding = manifest.get("policy", {})
    active_policy_binding = (
        manifest.get("programme_policy", {})
        if programme.identification_required
        else natural_policy_binding
    )
    if (
        not isinstance(firmware, dict)
        or not isinstance(natural_policy_binding, dict)
        or not isinstance(active_policy_binding, dict)
    ):
        raise ValueError("CX320 manifest firmware or policy binding is unavailable")
    natural_policy_path = _bound_file(natural_policy_binding, "policy")
    natural_policy = _read_object(natural_policy_path)
    natural_policy_sha256 = _sha256_identity(
        natural_policy_binding.get("policy_sha256"),
        "policy.policy_sha256",
    )
    policy_path = _bound_file(active_policy_binding, "active policy")
    policy = _read_object(policy_path)
    policy_sha256 = _sha256_identity(
        (
            active_policy_binding.get("sha256")
            if programme.identification_required
            else active_policy_binding.get("policy_sha256")
        ),
        "active_policy.sha256",
    )
    build_identity = _manifest_build_identity(manifest)
    source_sha256, separator, configuration_sha256 = build_identity.partition(":")
    if (
        not separator
        or _sha256_identity(source_sha256, "firmware.source_sha256")
        != firmware.get("source_sha256")
        or _sha256_identity(
            configuration_sha256, "firmware.configuration_sha256"
        )
        != firmware.get("configuration_sha256")
    ):
        raise ValueError("CX320 manifest firmware build identity is inconsistent")
    uf2 = firmware.get("uf2", {})
    if not isinstance(uf2, dict):
        raise ValueError("CX320 manifest UF2 binding is unavailable")
    wall_origin_utc = manifest.get("started_at_utc")
    if not isinstance(wall_origin_utc, str):
        raise ValueError("CX320 manifest wall-clock origin is unavailable")
    _parse_utc_epoch(wall_origin_utc)

    if (
        manifest.get("programme_id") != programme.programme_id
        or manifest.get("stage") != programme.live_stage
        or manifest.get("run_identity") != programme.runtime_run_identity
        or manifest.get("profile_identity") != programme.profile_id
        or section.get("run_identity") != programme.runtime_run_identity
        or section.get("profile_id") != programme.profile_id
        or setup.get("code") != programme.setup_code
        or control.get("maximum_total_applications")
        != programme.authorized_maximum_physical_applications
        or control.get(
            "maximum_total_automatic_applications",
            control.get("maximum_total_applications"),
        )
        != programme.authorized_maximum_applications
        or control.get("maximum_deliberate_challenges", 0)
        != programme.maximum_deliberate_challenges
        or control.get("maximum_cumulative_movement_codes")
        != programme.authorized_maximum_cumulative_movement_codes
        or control.get("maximum_step_codes") != programme.maximum_step_codes
        or control.get("minimum_applied_cadence_s")
        != programme.minimum_applied_cadence_s
        or control.get("minimum_code") != programme.minimum_code
        or control.get("maximum_code") != programme.maximum_code
        or qualification.get("qualified_duration_s")
        != programme.qualified_duration_s
        or qualification.get("absolute_wall_clock_limit_s")
        != programme.authorized_absolute_wall_limit_s
        or qualification.get("no_extension") is not True
    ):
        raise ValueError("CX320 live manifest does not carry the exact envelope")

    expected_natural_policy_programme_id = (
        programme.natural_policy_programme_id
        or (
            programme.programme_id
            if programme.response_checkpoint_observational
            else CX320_PROGRAMME.programme_id
        )
    )
    authority = natural_policy.get("global_authority_limits", {})
    if programme.persistent_maintenance_policy:
        try:
            selected_policy = load_cx323_policy(natural_policy_path)
        except ValueError as exc:
            raise ValueError(
                "current CX323 policy does not carry the exact live envelope"
            ) from exc
        selection = natural_policy.get("maintenance_selection", {})
        finite_timing = natural_policy.get("finite_timing", {})
        controller_inhibit = natural_policy.get("live_controller_inhibit", {})
        if (
            natural_policy.get("programme_id")
            != expected_natural_policy_programme_id
            or natural_policy.get("policy_id") != programme.natural_policy_id
            or authority.get("maximum_automatic_applications")
            != programme.maximum_applications
            or authority.get("maximum_cumulative_absolute_movement_codes")
            != programme.maximum_cumulative_movement_codes
            or authority.get("maximum_combined_step_codes")
            != programme.maximum_step_codes
            or authority.get("minimum_applied_cadence_s")
            != programme.minimum_applied_cadence_s
            or authority.get("minimum_code") != programme.minimum_code
            or authority.get("maximum_code") != programme.maximum_code
            or authority.get("maximum_outstanding_requests") != 1
            or authority.get("deliberate_challenges")
            != programme.maximum_deliberate_challenges
            or authority.get("automatic_retry") is not False
            or authority.get("automatic_restoration") is not False
            or selection.get("requires_tight_state") != "TIGHT_INSIDE"
            or selection.get("requires_legacy_phase_material") is not False
            or selection.get("selected_frequency_estimator")
            != selected_policy.frequency_estimator_id
            or selection.get("window_s") != 600
            or selection.get("frontier_support") != "(opening_closing]"
            or selection.get("contiguous_frontier")
            != "next_opening_eq_prior_closing"
            or selection.get("overlap_frontier")
            != "next_opening_lt_prior_closing"
            or selection.get("gap_frontier")
            != "next_opening_gt_prior_closing"
            or selection.get("required_consecutive_same_sign_windows") != 2
            or finite_timing.get("qualified_duration_s")
            != programme.qualified_duration_s
            or finite_timing.get("qualified_clock")
            != "D14_D8_qualified_firmware_tick_domain"
            or finite_timing.get("qualification_deadline_s") != 5_400
            or finite_timing.get("wall_clock_limit_s")
            != programme.authorized_absolute_wall_limit_s
            or finite_timing.get("milestone_interval_qualified_s") != 21_600
            or finite_timing.get("milestones_qualified_s")
            != list(range(21_600, programme.qualified_duration_s + 1, 21_600))
            or finite_timing.get("minimum_final_response_reserve_s") != 1500
            or finite_timing.get("extension") != "forbidden"
            or finite_timing.get("inherited_24h_or_12h_duration") is not False
            or controller_inhibit.get("alternation_or_low_efficiency")
            != "latch_controller_authority_inhibited_acquisition_continues"
            or controller_inhibit.get("host_abort") is not False
            or controller_inhibit.get("endpoint_verdict")
            != "cx323_d9_d6_72h_hybrid_authority_not_sustained"
            or set(natural_policy.get("terminal_decisions", ()))
            != set(programme.terminal_decisions)
        ):
            raise ValueError(
                "current CX323 policy does not carry the exact live envelope"
            )
    else:
        numerical = natural_policy.get("numerical_policy", {})
        if (
            natural_policy.get("programme_id")
            != expected_natural_policy_programme_id
            or natural_policy.get("policy_id") != programme.natural_policy_id
            or natural_policy.get("setup", {}).get("exact_start_code")
            != programme.setup_code
            or authority.get("maximum_total_automatic_applications")
            != programme.maximum_applications
            or authority.get("maximum_cumulative_absolute_movement_codes")
            != programme.maximum_cumulative_movement_codes
            or authority.get("maximum_combined_step_codes")
            != programme.maximum_step_codes
            or authority.get("minimum_applied_cadence_s")
            != programme.minimum_applied_cadence_s
            or authority.get("minimum_code") != programme.minimum_code
            or authority.get("maximum_code") != programme.maximum_code
            or numerical.get("settling_exclusion_s") != 900
            or numerical.get("fresh_support_after_settling_s") != 600
            or numerical.get("response_support_total_s") != 1500
        ):
            raise ValueError(
                "current CX320 policy does not carry the exact live envelope"
            )

    if programme.identification_required:
        active_authority = policy.get("global_authority_limits", {})
        if (
            policy.get("programme_id") != programme.programme_id
            or policy.get("policy_id") != programme.policy_id
            or active_authority.get("maximum_total_automatic_applications")
            != programme.maximum_applications
            or active_authority.get(
                "maximum_cumulative_absolute_movement_codes"
            )
            != programme.maximum_cumulative_movement_codes
            or active_authority.get("maximum_combined_step_codes")
            != programme.maximum_step_codes
            or active_authority.get("minimum_code") != programme.minimum_code
            or active_authority.get("maximum_code") != programme.maximum_code
        ):
            raise ValueError("current CX321 programme policy envelope differs")
    if (
        programme.response_checkpoint_observational
        and not programme.sustained_regulation
        and not programme.persistent_maintenance_policy
    ):
        terminal_semantics = policy.get("terminal_semantics", {})
        if terminal_semantics.get(
            "bounded_direct_hybrid_early_safety_stop_reasons"
        ) != [
            "prospective_repeated_alternation",
            "prospective_low_efficiency_path",
        ]:
            raise ValueError("CX322 prospective early-safety reasons differ")
    if programme.sustained_regulation:
        challenge = policy.get("reversal_challenge", {})
        if (
            not isinstance(challenge, dict)
            or challenge.get("maximum_count") != 1
            or challenge.get("natural_reversal_window_qualified_s") != 43_200
            or challenge.get(
                "first_eligible_challenge_no_later_than_qualified_s"
            )
            != 50_400
            or challenge.get("minimum_post_reversal_qualified_s") != 21_600
            or challenge.get("default_step_codes") != 21
            or challenge.get("automatic_application_counted") is not False
            or challenge.get("physical_and_cumulative_authority_counted")
            is not True
        ):
            raise ValueError("sustained-hybrid reversal challenge differs")

    bindings = policy.get("bindings", {})
    if not isinstance(bindings, dict):
        raise ValueError("CX320 policy bindings are unavailable")
    phase_estimator_sha256 = _sha256_identity(
        bindings.get("phase_estimator", {}).get("sha256"),
        "policy.phase_estimator_sha256",
    )
    plant_sign_identities: dict[str, str] = {}
    if programme.identification_required:
        identification = manifest.get("identification", {})
        if not isinstance(identification, dict):
            raise ValueError("CX321 manifest identification binding is unavailable")
        plant_sign_identities = {
            "policy_sha256": policy_sha256,
            "plant_sign_gate_sha256": _sha256_identity(
                bindings.get("plant_sign_gate", {}).get("sha256"),
                "plant_sign_gate_sha256",
            ),
            "identification_estimator_sha256": _sha256_identity(
                bindings.get("identification_estimator", {}).get("sha256"),
                "identification_estimator_sha256",
            ),
            "identification_estimator_config_sha256": _sha256_identity(
                identification.get("estimator_runtime_config", {}).get("sha256"),
                "identification_estimator_config_sha256",
            ),
            "natural_frequency_estimator_sha256": _sha256_identity(
                bindings.get("natural_frequency_estimator", {}).get("sha256"),
                "natural_frequency_estimator_sha256",
            ),
        }
    return RuntimeEnvelope(
        programme=programme,
        manifest_sha256=_sha256_identity(
            manifest.get("manifest_sha256"), "manifest_sha256"
        ),
        bundle_sha256=_sha256_identity(
            manifest.get("bundle", {}).get("bundle_sha256"),
            "bundle.bundle_sha256",
        ),
        policy_sha256=policy_sha256,
        build_identity=build_identity,
        uf2_sha256=_sha256_identity(uf2.get("sha256"), "firmware.uf2.sha256"),
        policy_path=policy_path,
        natural_policy_path=natural_policy_path,
        natural_policy_sha256=natural_policy_sha256,
        phase_estimator_sha256=phase_estimator_sha256,
        plant_sign_identities=plant_sign_identities,
        wall_origin_utc=wall_origin_utc,
    )


def load_active_hybrid_spec(
    manifest: dict[str, Any],
) -> tuple[CampaignSpec, dict[str, str]]:
    """Load the exact runtime contract from a validated live manifest."""

    envelope = _runtime_envelope(manifest)
    programme = envelope.programme
    policy = _read_object(envelope.policy_path)
    bindings = policy["bindings"]
    frequency_binding = (
        "natural_frequency_estimator"
        if programme.identification_required
        else "frequency_estimator"
    )
    response_binding = (
        "natural_response_classifier"
        if programme.identification_required
        else "response_policy"
    )
    identities = {
        "estimator_sha256": _sha256_identity(
            bindings[frequency_binding]["sha256"],
            "policy.frequency_estimator_sha256",
        ),
        "model_sha256": _sha256_identity(
            bindings["plant_model"]["sha256"],
            "policy.plant_model_sha256",
        ),
        "active_policy_sha256": envelope.policy_sha256,
        "response_policy_sha256": _sha256_identity(
            bindings[response_binding]["sha256"],
            "policy.response_policy_sha256",
        ),
        # The firmware's combined controller implementation deliberately uses
        # the semantic active-policy identity as its numerical-policy identity.
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
    return health.get(("cx317_active", key)) == "true"


_AUTHORITATIVE_CAPTURE_COUNTERS = (
    "rejected_window_count",
    "physical_aperture_incomplete_count",
    "association_loss_count",
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


def _authoritative_capture_health_faults(
    health: dict[tuple[str, str], str],
) -> list[str]:
    faults: list[str] = []
    for key, expected in _AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH.items():
        observed = health.get(("pps_gate", key))
        if observed != expected:
            faults.append(f"{key}:{observed!r}!={expected!r}")
    return faults


class ActiveHybridLiveSupervisor(FrequencyControlSupervisor):
    """CX320 live authority layered on the proven active-control transport."""

    def __init__(
        self,
        *,
        manifest: dict[str, Any],
        manifest_path: Path,
        rehearsal_manifest: bool = False,
        **kwargs: object,
    ) -> None:
        envelope = _runtime_envelope(manifest)
        spec = kwargs.get("spec")
        if not isinstance(spec, CampaignSpec):
            raise ValueError("CX320 supervisor requires its manifest-derived spec")
        if (
            spec.run_identity != manifest.get("run_identity")
            or kwargs.get("expected_build_identity") != envelope.build_identity
        ):
            raise ValueError("CX320 supervisor inputs differ from the live manifest")
        self.programme = envelope.programme
        self.rehearsal_manifest = rehearsal_manifest
        super().__init__(
            mode="live",
            leg=TightDeadbandLeg(
                self.programme.key.upper(), 0, "combined_frequency_phase"
            ),
            allow_manual_start=True,
            allow_arm=True,
            # The installed profile deliberately inhibits D14/D8 control
            # eligibility for 600 s.  Prior physical CX319 evidence first
            # observed the same predicate at 612 s, so retain its frozen
            # 660 s qualification deadline rather than the older CX318
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
        self.plant_sign_identities = envelope.plant_sign_identities
        self.natural_policy_path = envelope.natural_policy_path
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
                    f"CX320 retained supervisor {key} differs from the manifest"
                )
            self.state[key] = value
        self.state.setdefault("qualified_origin_estimate_id", None)
        self.state.setdefault("qualified_origin_timestamp_ticks", None)
        self.state.setdefault("qualified_origin_session_id", None)
        self.state.setdefault("qualified_origin_extended_timestamp_ticks", None)
        self.state.setdefault("qualified_frontier_raw_ticks", None)
        self.state.setdefault("qualified_frontier_extended_ticks", None)
        self.state.setdefault("qualified_endpoint_extended_timestamp_ticks", None)
        self.state.setdefault("qualified_authoritative_capture_baseline", None)
        self.state.setdefault("latest_hybrid_state", None)
        self.state.setdefault("first_phase_checkpoint_passed", False)
        self.state.setdefault("first_phase_observation_checkpoint_exact", False)
        self.state.setdefault("later_authority_released", False)
        self.state.setdefault("phase_material_application_count", 0)
        self.state.setdefault("terminal_static_code", None)
        self.state.setdefault("latest_plant_sign_state", None)
        self.state.setdefault("plant_sign_prearm_sent", False)
        self.state.setdefault("plant_sign_prearm_accepted_intervals", None)
        self.state.setdefault("host_verification_hold", None)
        self.state.setdefault("gnss_metadata_hold", None)
        self.state.setdefault("gnss_metadata_hold_count", 0)
        self.state.setdefault("controller_authority_inhibited_reason", None)
        self.state.setdefault("controller_authority_inhibited_utc", None)
        self.state.setdefault("persistent_wrong_direction_terminal", False)
        self.state.setdefault("unarmed_observation_complete_utc", None)
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
        if not super()._identity_ready(health):
            return False
        for key, expected in self.plant_sign_identities.items():
            if key == "policy_sha256":
                continue
            observed = health.get(("cx317_active", key))
            if observed is None:
                return False
            if observed != expected:
                raise ValueError(
                    f"live {key} mismatch: {observed!r} != {expected!r}"
                )
        return True

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
                health.get(("cx317_active", "snapshot_generation_complete"), "0")
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
                    "CX320 causally bound active snapshot did not follow "
                    f"query_nonce={query_nonce} generation={generation}"
                )
            time.sleep(0.05)

    def _prepare_evidence_acknowledgement(
        self, row: dict[str, str], phase: int
    ) -> dict[str, object]:
        current = self._current_health()
        generation = int(
            current.get(("cx317_active", "snapshot_generation_complete"), "0")
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
            observed_phase = health.get(("cx317_active", "evidence_phase"), "")
            observed_request = int(
                health.get(("cx317_active", "evidence_request_sequence"), "0")
            )
            if (
                observed_phase == expected_phase
                and observed_request == request_sequence
            ):
                return {
                    "pre_submit_snapshot_generation": int(
                        health[("cx317_active", "snapshot_generation_complete")]
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
                    "CX320 firmware evidence frontier differs before "
                    "acknowledgement: "
                    f"expected_request={request_sequence} "
                    f"expected_phase={expected_phase} "
                    f"observed_request={observed_request} "
                    f"observed_phase={observed_phase}"
                )
            generation = int(
                health[("cx317_active", "snapshot_generation_complete")]
            )
            health = self._fresh_active_snapshot_after(generation)
        raise TimeoutError(
            "CX320 firmware evidence frontier did not reach the expected "
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
        # generation-fresh but causally stale.  Retry a bounded number of
        # complete snapshots while the exact pre-submit frontier persists.
        # Four five-second queries remain inside the frozen 30-second host
        # replay/acknowledgement deadline.
        health: dict[tuple[str, str], str] | None = None
        observed_phase = ""
        for _ in range(4):
            health = self._fresh_active_snapshot_after(baseline)
            baseline = int(
                health[("cx317_active", "snapshot_generation_complete")]
            )
            observed_phase = health.get(("cx317_active", "evidence_phase"), "")
            observed_request = int(
                health.get(("cx317_active", "evidence_request_sequence"), "0")
            )
            if observed_phase == pre_submit_phase:
                if observed_request != request_sequence:
                    raise ValueError(
                        "CX320 evidence acknowledgement retained a contradictory "
                        "request identity"
                    )
                continue
            if (
                observed_phase == "evidence_clear"
                and observed_request != 0
            ) or (
                observed_phase != "evidence_clear"
                and observed_request != request_sequence
            ):
                raise ValueError(
                    "CX320 evidence acknowledgement advanced to a contradictory "
                    "request identity"
                )
            if observed_phase not in permitted:
                return False
            break
        else:
            return False
        assert health is not None
        self._programme_event(
            "firmware_evidence_acknowledgement_confirmed",
            request_sequence=request_sequence,
            phase=phase,
            snapshot_generation=int(
                health[("cx317_active", "snapshot_generation_complete")]
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
            "profile_identity": self.spec.profile,
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
        if health.get(("cx317_active", "query_nonce")) != str(
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
            inherited_preview_baseline_code=(
                readiness.inherited_preview_baseline_code
            ),
            inherited_preview_baseline_provenance=(
                readiness.inherited_preview_baseline_provenance
            ),
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
                "active_hybrid_decisions_v1", frozenset(), frozenset()
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
            "profile_identity": self.spec.profile,
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

    def _process_transactions(self) -> None:
        if self.state.get("host_verification_hold") is not None:
            self._validate_hybrid_decisions()
            return
        prior_terminal = self.state.get("terminal")
        try:
            super()._process_transactions()
        except IndependentReplayMismatch as exc:
            rows = _read_csv(self.run_dir / ACTIVE_CSV)
            response = next(
                (row for row in reversed(rows) if row.get("event") == "response"),
                {},
            )
            hold = {
                "entered_utc": _utc_now(),
                "error": str(exc),
                "record_sequence": int(
                    response.get("transaction_record_sequence", "0")
                ),
                "request_sequence": int(response.get("request_sequence", "0")),
                "response_class": response.get(
                    "response_class", "unavailable"
                ),
                "applied_code": int(response.get("applied_code", "0")),
                "dac_epoch": int(response.get("dac_epoch", "0")),
                "correction_count": int(response.get("correction_count", "0")),
                "cumulative_movement_codes": int(
                    response.get("cumulative_movement_codes", "0")
                ),
            }
            self.state["host_verification_hold"] = hold
            self.state["arm_pending"] = False
            self.state["arm_sent_at_utc"] = None
            self._save()
            self._programme_event("host_verification_hold_entered", **hold)
            self._validate_hybrid_decisions()
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
            self._abort("hybrid_response_wrong_or_frequency_not_reacquired")
            self._validate_hybrid_decisions()
            return
        # The shared frequency supervisor historically treated exhausted
        # frequency authority as an early campaign success.  CX320 instead
        # observes the instrument through its full finite qualified duration;
        # exhausted movement authority is a static observation interval.
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
                    self._abort("phase_or_frequency_regulation_not_sustained")
        self._validate_hybrid_decisions()

    def _runtime_health_integrity(
        self, health: dict[tuple[str, str], str]
    ):  # type: ignore[no-untyped-def]
        # Retain the common D14/D8/GNSS/capture integrity contract.  CX320's
        # phase and controller authority is checked separately below.
        return super()._runtime_health_integrity(health)

    def _check_fail_static_health(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        # FrequencyControlSupervisor additionally requires every phase/hybrid
        # preview stream to remain zero-authority.  That condition is correct
        # for CX319 but contradicts CX320's intended combined controller.
        hybrid_state = health.get(("cx317_active", "hybrid_state"))
        hybrid_reason = health.get(("cx317_active", "hybrid_reason"), "unknown")
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
        if (
            self.programme.identification_required
            and health.get(("cx317_active", "fail_static")) == "true"
        ):
            rows = _read_csv(self.run_dir / PLANT_SIGN_CSV)
            last = rows[-1] if rows else {}
            decision = plant_sign_terminal_decision_from_record(last)
            if decision is not None:
                self.state["arm_pending"] = False
                self.state["arm_sent_at_utc"] = None
                self._abort(decision)
                return
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
            platform_health[("cx317_active", "fail_static")] = "false"
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
                "CX320 continuous runtime health contract failed: "
                + integrity.diagnostic()
            )
        setup_established = self.state["setup_confirmed_utc"] is not None
        if setup_established and not self._identity_ready(health):
            raise ValueError("CX320 exact runtime identity became unavailable")
        if setup_established:
            metadata_hold_active = (
                health.get(("cx317_active", "state")) == "GNSS_METADATA_HOLD"
                and _truth(health, "gnss_metadata_hold_active")
            )
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
                    "CX320 shared D14/D8/GNSS/capture qualification lost: "
                    + ", ".join(unhealthy)
                )
            self._update_gnss_metadata_hold(health, metadata_hold_active)

        if hybrid_state is None:
            if setup_established:
                raise ValueError("CX320 hybrid firmware state is absent")
            return
        if hybrid_state not in self.programme.hybrid_states:
            raise ValueError(f"unexpected CX320 hybrid state: {hybrid_state!r}")
        if hybrid_state == "FAIL_STATIC" and not (
            prospective_controller_inhibit
            and self.programme.controller_inhibit_acquisition_continues
        ):
            raise ValueError(f"CX320 firmware entered FAIL_STATIC: {hybrid_reason}")

        corrections = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        automatic_applications = int(
            health.get(
                ("cx317_active", "automatic_application_count"),
                str(corrections),
            )
            if self.programme.sustained_regulation
            else corrections
        )
        movement = int(
            health.get(("cx317_active", "cumulative_movement_codes"), "0")
        )
        material = int(
            health.get(
                ("cx317_active", "phase_material_application_count"), "0"
            )
        )
        phase_nonzero = int(
            health.get(
                ("cx317_active", "phase_nonzero_application_count"), "0"
            )
        )
        frequency_only = int(
            health.get(
                ("cx317_active", "frequency_only_application_count"), "0"
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
            applied = int(health[("cx317_active", "confirmed_applied_code")], 0)
            if not self.programme.minimum_code <= applied <= self.programme.maximum_code:
                raise ValueError("CX320 confirmed code is outside the frozen range")
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
            or automatic_applications
            > self.programme.authorized_maximum_applications
            or movement
            > self.programme.authorized_maximum_cumulative_movement_codes
            or material > phase_nonzero
            or phase_nonzero > corrections
            or material + frequency_only > corrections
        ):
            raise ValueError("CX320 firmware exceeded the frozen global authority")
        if material > 1 and not checkpoint:
            raise ValueError("CX320 later material authority preceded its checkpoint")
        if hybrid_state == "HYBRID_TRACKING" and not checkpoint:
            raise ValueError("CX320 HYBRID_TRACKING lacks the first checkpoint")
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
            raise ValueError("CX320 actuation changed during host verification hold")

        changed = hybrid_state != self.state.get("latest_hybrid_state")
        dirty = changed or confirmed_applied_changed
        if changed:
            self.state["latest_hybrid_state"] = hybrid_state
        if self.programme.identification_required:
            plant_state = health.get(("cx317_active", "plant_sign_state"))
            if plant_state != self.state.get("latest_plant_sign_state"):
                self.state["latest_plant_sign_state"] = plant_state
                dirty = True
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
            code = int(health[("cx317_active", "confirmed_applied_code")], 0)
            epoch = int(health[("cx317_active", "dac_epoch")])
            corrections = int(health[("cx317_active", "correction_count")])
            movement = int(
                health[("cx317_active", "cumulative_movement_codes")]
            )
            entry_sequence = int(
                health[("cx317_active", "gnss_metadata_hold_entry_sequence")]
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
            health[("cx317_active", "gnss_metadata_requalification_sequence")]
        )
        qualification_frontier = int(
            health[("cx317_active", "gnss_metadata_qualification_frontier")]
        )
        observation_sequence = int(
            health[("cx317_active", "d14_d8_observation_sequence")]
        )
        if (
            metadata_sequence <= retained["entry_sequence"]
            or observation_sequence <= qualification_frontier
            or health.get(("cx317_active", "state")) != "DISARMED"
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
            == "cx317_selected_600s_nonoverlap_v1"
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
            or int(health.get(("cx317_active", "confirmed_applied_code"), "0"), 0)
            != self.programme.setup_code
            or int(health.get(("cx317_active", "dac_epoch"), "0")) < 1
        ):
            return
        dac_epoch = int(health[("cx317_active", "dac_epoch")])
        estimate = self._fresh_authoritative_selected_estimate(
            _read_csv(self.run_dir / ESTIMATES_CSV), dac_epoch=dac_epoch
        )
        if estimate is None:
            return
        if estimate.get("time_domain") != "rp2040_timer0":
            raise ValueError("CX320 qualified origin is not in rp2040_timer0")
        try:
            origin_ticks = int(estimate["estimator_timestamp_ticks"])
            current_uptime_s = int(health[("cx317_active", "uptime_s")])
            session_id = int(health[("cx317_active", "session_id")])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("CX320 qualified origin device clock is malformed") from exc
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
                    "campaign18 exact retained producer frontier is absent"
                ) from exc
            if frontier_domain != "rp2040_timer0":
                raise ValueError(
                    "campaign18 retained producer frontier domain differs"
                )
            forward = forward_progress(
                origin_ticks,
                frontier_ticks,
                domain="rp2040_timer0",
                allow_equal=True,
            )
            reverse = forward_progress(
                frontier_ticks,
                origin_ticks,
                domain="rp2040_timer0",
                allow_equal=True,
            )
            maximum_lead_ticks = (
                QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S
                * RP2040_TIMER0_TICKS_PER_SECOND
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
                raise ValueError("CX320 qualified origin device clock is incoherent")
            authoritative_capture_baseline = {}
            for key in _AUTHORITATIVE_CAPTURE_COUNTERS:
                try:
                    value = int(health[("pps_gate", key)])
                except (KeyError, TypeError, ValueError):
                    return
                if value < 0:
                    return
                authoritative_capture_baseline[key] = value
        else:
            current_uptime_lower_bound_ticks = (
                current_uptime_s * RP2040_TIMER0_TICKS_PER_SECOND
            )
            maximum_coherent_origin_ticks = (
                current_uptime_s + QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S
            ) * RP2040_TIMER0_TICKS_PER_SECOND
            if (
                origin_ticks <= 0
                or session_id <= 0
                or origin_ticks > maximum_coherent_origin_ticks
            ):
                raise ValueError("CX320 qualified origin device clock is incoherent")
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
        self.state["qualified_authoritative_capture_baseline"] = (
            authoritative_capture_baseline
        )
        self._save()
        self._programme_event(
            "qualified_origin_established",
            estimate_id=estimate["estimate_id"],
            estimator_timestamp_ticks=origin_ticks,
            time_domain="rp2040_timer0",
            capture_session=session_id,
            source_count_ref=estimate["source_count_ref"],
            source_dac_ref=estimate["source_dac_ref"],
            dac_epoch=dac_epoch,
            qualified_duration_s=self.programme.qualified_duration_s,
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
        for key in _AUTHORITATIVE_CAPTURE_COUNTERS:
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
        if not faults:
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
        self._abort(reason)
        try:
            self._programme_event(
                "authoritative_capture_discontinuity_observed", **detail
            )
        except OSError:
            # The priority abort and retained terminal are decision-bearing;
            # this supplementary event must never delay or undo them.
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
            raise ValueError("CX320 retained qualified origin is incomplete")
        try:
            current_session = int(
                health[
                    (
                        "pps_gate"
                        if self.programme.integrated_long_run
                        else "cx317_active",
                        "snapshot_session"
                        if self.programme.integrated_long_run
                        else "session_id",
                    )
                ]
            )
            current_uptime_s = int(health[("cx317_active", "uptime_s")])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("CX320 current qualified device clock is malformed") from exc
        if current_session != origin_session:
            raise ValueError("CX320 capture session changed after qualified origin")
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
                    "campaign18 exact retained qualified clock is incomplete"
                ) from exc
            if frontier_domain != "rp2040_timer0":
                raise ValueError(
                    "campaign18 retained producer frontier domain differs"
                )
            progress = forward_progress(
                prior_raw_ticks,
                current_raw_ticks,
                domain="rp2040_timer0",
                allow_equal=True,
            )
            if not progress.valid or progress.distance_ticks is None:
                raise ValueError(
                    "campaign18 retained producer frontier moved backward"
                )
            current_extended = prior_extended_ticks + progress.distance_ticks
            if current_extended != prior_extended_ticks:
                self.state["qualified_frontier_raw_ticks"] = current_raw_ticks
                self.state["qualified_frontier_extended_ticks"] = current_extended
                self._save()
            elapsed = current_extended - origin_extended
            if elapsed < 0:
                raise ValueError("CX320 device clock moved behind qualified origin")
            return elapsed
        elapsed = current_uptime_s * RP2040_TIMER0_TICKS_PER_SECOND - origin
        if elapsed < 0:
            raise ValueError("CX320 device clock moved behind qualified origin")
        return elapsed

    def _close_response_horizon_if_required(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        elapsed_ticks = self._qualified_elapsed_ticks(health)
        if elapsed_ticks is None:
            return False
        admission_ticks = (
            self.programme.qualified_duration_s
            - self.programme.correction_response_reserve_s
        ) * RP2040_TIMER0_TICKS_PER_SECOND
        if elapsed_ticks < admission_ticks:
            return False
        if self.state["response_horizon_closed_utc"] is None:
            self.state["response_horizon_closed_utc"] = _utc_now()
            self._save()
            self._programme_event(
                "correction_admission_closed_for_response_horizon",
                elapsed_qualified_device_ticks=elapsed_ticks,
                time_domain="rp2040_timer0",
                remaining_qualified_s=max(
                    0,
                    self.programme.qualified_duration_s
                    - elapsed_ticks // RP2040_TIMER0_TICKS_PER_SECOND,
                ),
                required_response_reserve_s=(
                    self.programme.correction_response_reserve_s
                ),
            )
        return True

    def _unarmed_observation_complete(
        self, elapsed_monotonic_s: float | None
    ) -> bool:
        required_s = self.programme.engineering_unarmed_observation_s
        if required_s <= 0:
            return True
        if elapsed_monotonic_s is None or elapsed_monotonic_s < required_s:
            return False
        if self.state["unarmed_observation_complete_utc"] is None:
            self.state["unarmed_observation_complete_utc"] = _utc_now()
            self._save()
            self._programme_event(
                "unarmed_concurrency_observation_complete",
                required_s=required_s,
                observed_elapsed_monotonic_s=elapsed_monotonic_s,
                setup_commands_issued=0,
            )
        return True

    def _maybe_start_or_arm(
        self,
        health: dict[tuple[str, str], str],
        elapsed_monotonic_s: float | None = None,
    ) -> None:
        if self.state.get("host_verification_hold") is not None:
            return
        if not self._identity_ready(health):
            return
        state = health.get(("cx317_active", "state"), "")
        reason = health.get(("cx317_active", "reason"), "")
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
            if (
                not self.rehearsal_manifest
                and not self._unarmed_observation_complete(
                    elapsed_monotonic_s
                )
            ):
                return
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

        hybrid_state = health.get(("cx317_active", "hybrid_state"), "")
        identification_prearm = False
        if self.programme.identification_required:
            try:
                pre_window_count = int(
                    health.get(
                        ("cx317_active", "plant_sign_pre_window_count"), "-1"
                    )
                )
                accepted_intervals = int(
                    health.get(
                        (
                            "cx317_active",
                            "plant_sign_accumulator_accepted_intervals",
                        ),
                        "-1",
                    )
                )
            except ValueError as exc:
                raise ValueError("CX321 plant-sign progress is malformed") from exc
            plant_state = health.get(("cx317_active", "plant_sign_state"), "")
            firmware_window_eligible = _truth(
                health, "plant_sign_arm_window_eligible"
            )
            identification_prearm = (
                plant_state == "FREQUENCY_ACQUIRE"
                and pre_window_count == 1
                and PLANT_SIGN_PREARM_MIN_ACCEPTED_INTERVALS
                <= accepted_intervals
                < PLANT_SIGN_SPAN_INTERVALS
                and firmware_window_eligible
            )
            if firmware_window_eligible and not identification_prearm:
                raise ValueError(
                    "CX321 firmware plant-sign arm window contradicts retained progress"
                )
        # FIRST_PHASE_TRANSACTION stays unarmed until firmware has durably
        # recorded the response checkpoint and observed tight reacquisition.
        if (
            hybrid_state not in self.programme.armable_hybrid_states
            and not identification_prearm
        ):
            return
        if hybrid_state == "HYBRID_TRACKING" and not _truth(
            health, "first_phase_checkpoint_passed"
        ):
            raise ValueError("later CX320 authority lacks its firmware checkpoint")
        correction_count = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        automatic_count = int(
            health.get(
                ("cx317_active", "automatic_application_count"),
                str(correction_count),
            )
            if self.programme.sustained_regulation
            else correction_count
        )
        challenge_pending = (
            self.programme.sustained_regulation
            and not _truth(health, "natural_reversal_observed")
            and not _truth(health, "deliberate_challenge_applied")
            and not _truth(health, "deliberate_challenge_cancelled")
            and not _truth(health, "deliberate_challenge_unexercised")
        )
        if (
            automatic_count >= self.programme.authorized_maximum_applications
            and not challenge_pending
        ):
            return
        progress = int(
            health.get(("cx317_active", "selected_interval_count"), "0")
        )
        if not identification_prearm:
            preview_rows = _read_csv(self.run_dir / CONTROL_CSV)
            preview = preview_rows[-1] if preview_rows else None
            if not self._arm_progress_epoch_ready(preview, progress):
                return
        # CX320 must arm the next fresh selected-estimate epoch even when the
        # frequency-only predecessor preview is available every 600 seconds.
        # The hybrid firmware owns the 1800-second *applied* cadence and
        # consumes an early or zero-delta one-shot arm without writing.  Using
        # the CX319 preview-cadence predictor here can therefore suppress every
        # phase-material decision after the first armed hold.
        if not (
            state == "DISARMED"
            and _truth(health, "arm_eligible")
            and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
            and not _truth(health, "evidence_pending")
            and (
                identification_prearm
                or progress >= ARM_PROGRESS_THRESHOLD
            )
        ):
            return
        uptime = int(health[("cx317_active", "uptime_s")])
        self.state["authorization_sequence"] += 1
        sequence = self.state["authorization_sequence"]
        nonce = secrets.randbits(32) or 1
        expiry = uptime + ARM_LIFETIME_S
        self._command(f"ACTIVE ARM {sequence} {nonce} {expiry}")
        self.state["arm_pending"] = True
        self.state["arm_sent_at_utc"] = _utc_now()
        if identification_prearm:
            if self.state["plant_sign_prearm_sent"]:
                raise ValueError("CX321 plant-sign identification was armed more than once")
            self.state["plant_sign_prearm_sent"] = True
            self.state["plant_sign_prearm_accepted_intervals"] = accepted_intervals
        self._save()
        self._programme_event(
            "one_decision_armed",
            authorization_sequence=sequence,
            expiry_s=expiry,
            selected_interval_count=progress,
            hybrid_state=hybrid_state,
            identification_prearm=identification_prearm,
            plant_sign_accepted_intervals=(
                accepted_intervals if identification_prearm else None
            ),
        )

    def _healthy_terminal_ready(
        self, health: dict[tuple[str, str], str]
    ) -> bool:
        if (
            not self._identity_ready(health)
            or self.state["arm_pending"]
            or health.get(("cx317_active", "state")) != "DISARMED"
            or health.get(("cx317_active", "evidence_phase")) != "evidence_clear"
            or _truth(health, "evidence_pending")
            or int(health.get(("cx317_active", "evidence_request_sequence"), "0"))
            != 0
            or not _truth(health, "confirmed_applied_code_known")
        ):
            return False
        code = int(health[("cx317_active", "confirmed_applied_code")], 0)
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
        corrections = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        material = int(
            health.get(
                ("cx317_active", "phase_material_application_count"), "0"
            )
        )
        checkpoint = _truth(health, "first_phase_checkpoint_passed")
        if self.programme.response_checkpoint_observational:
            preliminary = "pending_offline_scientific_analysis"
        elif self.programme.identification_required and corrections == 0:
            preliminary = "plant_sign_qualification_not_exercised"
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
        elapsed_monotonic_s: float,
    ) -> None:
        del elapsed_monotonic_s
        if self.state["terminal"] is not None:
            return
        hybrid_state = health.get(("cx317_active", "hybrid_state"), "")
        if (
            hybrid_state == "PHASE_DEGRADED_FREQUENCY_ONLY"
            and not self.programme.response_checkpoint_observational
        ):
            self._abort("phase_channel_degraded_frequency_control_retained")
            return

        if (
            self.programme.terminal_after_first_response
            and (
                self.manifest.get("qualification_evidence") is True
                or (
                    self.rehearsal_manifest
                    and self.manifest.get("rehearsal_endpoint_mode")
                    == "first_response"
                )
            )
            and (
                not progressive_checkpoint_contract(self.programme).get(
                    "phase_material_application_count_is_acquisition_pass_gate",
                    True,
                )
                or (
                    self.state.get("first_phase_observation_checkpoint_exact") is True
                    and _truth(health, "first_phase_checkpoint_passed")
                )
            )
            and int(health.get(("cx317_active", "correction_count"), "0")) == 1
            and self._healthy_terminal_ready(health)
        ):
            self._set_healthy_endpoint(
                health,
                endpoint=(
                    f"{self.programme.key}_first_complete_application_"
                    "consumer_and_response"
                ),
            )
            return

        qualified_elapsed_ticks = self._qualified_elapsed_ticks(health)
        qualified_target_ticks = (
            self.programme.qualified_duration_s
            * RP2040_TIMER0_TICKS_PER_SECOND
        )
        if (
            self.programme.integrated_long_run
            and qualified_elapsed_ticks is not None
            and qualified_elapsed_ticks >= qualified_target_ticks
            and self.state.get("qualified_endpoint_extended_timestamp_ticks")
            is None
        ):
            self.state["qualified_endpoint_extended_timestamp_ticks"] = (
                int(self.state["qualified_origin_extended_timestamp_ticks"])
                + qualified_target_ticks
            )
            self._save()
        hold = self.state.get("host_verification_hold")
        if (
            qualified_elapsed_ticks is not None
            and qualified_elapsed_ticks >= qualified_target_ticks
            and isinstance(hold, dict)
        ):
            if (
                health.get(("cx317_active", "state")) != "DISARMED"
                or self.state.get("arm_pending")
                or not _truth(health, "confirmed_applied_code_known")
                or int(health[("cx317_active", "confirmed_applied_code")], 0)
                != hold.get("applied_code")
            ):
                self._abort(
                    f"{self.programme.key}_host_verification_hold_not_static_at_endpoint"
                )
                return
            self.state["terminal_static_code"] = hold["applied_code"]
            self.state["terminal"] = {
                "result": "nonpass",
                "reason": f"{self.programme.key}_host_verification_hold_endpoint",
                "primary_decision": "host_verification_hold_incomplete",
                "last_confirmed_code": hold["applied_code"],
                "utc": _utc_now(),
            }
            self._save()
            return
        if (
            qualified_elapsed_ticks is not None
            and qualified_elapsed_ticks >= qualified_target_ticks
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
                    "primary_decision": "right_censored_incomplete",
                    "last_confirmed_code": self.state["terminal_static_code"],
                    "utc": _utc_now(),
                }
                self._save()
            else:
                self._abort(
                    f"{self.programme.key}_wall_endpoint_without_clear_static_terminal"
                )

    def _abort(self, reason: str) -> None:
        super()._abort(reason)
        terminal = self.state["terminal"]
        if reason == "independent_host_abort_fifo":
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_operator_abort",
                fallback="operator_abort",
            )
        elif reason == "phase_channel_degraded_frequency_control_retained":
            terminal["primary_decision"] = (
                "phase_channel_degraded_frequency_control_retained"
            )
        elif reason == "hybrid_response_wrong_or_frequency_not_reacquired":
            terminal["primary_decision"] = (
                "hybrid_response_wrong_or_frequency_not_reacquired"
            )
        elif reason == "phase_or_frequency_regulation_not_sustained":
            terminal["primary_decision"] = reason
        elif reason.startswith(
            f"{self.programme.key}_D14_D8_authority_or_capture_fault:"
        ):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_D14_D8_authority_or_capture_fault",
                fallback="measurement_authority_or_platform_fault",
            )
        elif (
            self.programme.integrated_long_run
            and reason.startswith(
                f"{self.programme.key}_live_supervisor_fault:"
            )
        ):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_identity_or_evidence_fault",
                fallback="measurement_authority_or_platform_fault",
            )
        elif self.programme.sustained_regulation and reason in {
            "prospective_repeated_alternation",
            "prospective_low_efficiency_path",
        }:
            terminal["primary_decision"] = "hybrid_policy_chatter_or_path_exhaustion"
        elif self.programme.identification_required and any(
            decision in reason
            for decision in (
                "plant_sign_qualification_not_exercised",
                "plant_sign_qualification_failed",
            )
        ):
            terminal["primary_decision"] = next(
                decision
                for decision in (
                    "plant_sign_qualification_not_exercised",
                    "plant_sign_qualification_failed",
                )
                if decision in reason
            )
        elif "absolute_wall_endpoint" in reason or reason.startswith(
            f"{self.programme.key}_wall_endpoint"
        ):
            terminal["primary_decision"] = _programme_terminal_decision(
                self.programme,
                "_right_censored_incomplete",
                fallback="right_censored_incomplete",
            )
        elif (
            self.programme.response_checkpoint_observational
            and reason
            in {"prospective_repeated_alternation", "prospective_low_efficiency_path"}
        ):
            terminal["primary_decision"] = "bounded_direct_hybrid_early_safety_stop"
        else:
            terminal["primary_decision"] = "measurement_authority_or_platform_fault"
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
                    self._abort("capture_owner_lost")
                    return 4
                if self.duration_s is not None and now - started > self.duration_s:
                    self._abort("supervisor_duration_expired")
                    return 5
                if now - last_lease >= LEASE_PERIOD_S:
                    self._check_capture_transport_state()
                    self._renew_lease()
                    last_lease = now
                if now - last_query >= QUERY_PERIOD_S:
                    current = self._current_health()
                    generation = int(
                        current.get(
                            ("cx317_active", "snapshot_generation_complete"),
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
                if not self._abort_on_authoritative_capture_discontinuity(health):
                    self._process_transactions()
                    health = self._current_health()
                    if not self._abort_on_authoritative_capture_discontinuity(
                        health
                    ):
                        self._check_fail_static_health(health)
                        self._check_setup_transaction_timeout(health, time.time())
                        self._check_prewrite_contract(health, now - started)
                        self._maybe_qualify(health)
                        self._maybe_finish(health, time.time(), now - started)
                        if self.state["terminal"] is None:
                            self._maybe_start_or_arm(
                                health, elapsed_monotonic_s=now - started
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
    rehearsal_manifest: bool = False,
) -> ActiveHybridLiveSupervisor:
    if rehearsal_manifest:
        from .active_hybrid_live_rehearsal import (
            validate_rehearsal_run_manifest,
        )

        manifest = validate_rehearsal_run_manifest(manifest_path)
    else:
        from .active_hybrid_activation import validate_run_manifest

        manifest = validate_run_manifest(manifest_path)
    spec, identities = load_active_hybrid_spec(manifest)
    build_identity = _manifest_build_identity(manifest)
    if expected_build_identity != build_identity:
        raise ValueError("requested build identity differs from the CX320 manifest")
    return ActiveHybridLiveSupervisor(
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
        rehearsal_manifest=rehearsal_manifest,
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
    raise ValueError("CX320 run manifest lacks exact firmware build identity")


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
    parser.add_argument(
        "--rehearsal-manifest",
        action="store_true",
        help=(
            "accept only a non-authorizing PTY live-topology rehearsal manifest; "
            "never valid for a physical device"
        ),
    )
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
            rehearsal_manifest=args.rehearsal_manifest,
        )
        return supervisor.run()
    except (OSError, RuntimeError, SystemExit, TimeoutError, ValueError) as exc:
        if "supervisor" in locals():
            supervisor._programme_event("live_supervisor_fault", error=str(exc))
            supervisor._abort(
                f"{supervisor.programme.key}_live_supervisor_fault:{exc}"
            )
            return 2
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
