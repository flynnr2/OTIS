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
from .active_control_supervisor import (
    ESTIMATES_CSV,
    ControlSupervisorBase,
    _next_selected_interval_is_cadence_eligible,
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
from .contracts import CsvValidationContext, validate_csv
from .bounded_tight_deadband_prewrite_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    PrewriteReadiness,
    evaluate_prewrite_readiness as evaluate_setup_prewrite_readiness,
)
from .frequency_control_supervisor import (
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
from .run_loader import CAPTURE_IN_PROGRESS_FLAG


TOOL_ID = "cx320_active_hybrid_live_supervisor_v1"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
PROFILE_ID = "cx320_active_hybrid"
RUNTIME_RUN_IDENTITY = "cx320_active_hybrid:3200001"
ACTIVE_HYBRID_CSV = Path("csv/active_hybrid_decisions_v1.csv")

SETUP_CODE = 0xA83C
MAXIMUM_APPLICATIONS = 4
MAXIMUM_CUMULATIVE_MOVEMENT_CODES = 84
MAXIMUM_STEP_CODES = 21
MINIMUM_CODE = 0xA800
MAXIMUM_CODE = 0xAB00
QUALIFIED_DURATION_S = 43_200
ABSOLUTE_WALL_LIMIT_S = 57_600
MINIMUM_PHASE_MATERIAL_APPLICATIONS = 2

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
    manifest_sha256: str
    bundle_sha256: str
    policy_sha256: str
    build_identity: str
    uf2_sha256: str
    policy_path: Path
    phase_estimator_sha256: str
    wall_origin_utc: str


def _runtime_envelope(manifest: dict[str, Any]) -> RuntimeEnvelope:
    """Extract identities only from a validated, run-local live manifest."""

    cx320 = manifest.get("cx320", {})
    control = cx320.get("automatic_control", {}) if isinstance(cx320, dict) else {}
    qualification = cx320.get("qualification", {}) if isinstance(cx320, dict) else {}
    setup = cx320.get("setup", {}) if isinstance(cx320, dict) else {}
    firmware = manifest.get("firmware", {})
    policy_binding = manifest.get("policy", {})
    if not isinstance(firmware, dict) or not isinstance(policy_binding, dict):
        raise ValueError("CX320 manifest firmware or policy binding is unavailable")
    policy_path = _bound_file(policy_binding, "policy")
    policy = _read_object(policy_path)
    policy_sha256 = _sha256_identity(
        policy_binding.get("policy_sha256"), "policy.policy_sha256"
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
        manifest.get("programme_id") != PROGRAMME_ID
        or manifest.get("stage")
        != "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE"
        or manifest.get("run_identity") != RUNTIME_RUN_IDENTITY
        or manifest.get("profile_identity") != PROFILE_ID
        or cx320.get("run_identity") != RUNTIME_RUN_IDENTITY
        or cx320.get("profile_id") != PROFILE_ID
        or setup.get("code") != SETUP_CODE
        or control.get("maximum_total_applications") != MAXIMUM_APPLICATIONS
        or control.get("maximum_cumulative_movement_codes")
        != MAXIMUM_CUMULATIVE_MOVEMENT_CODES
        or control.get("maximum_step_codes") != MAXIMUM_STEP_CODES
        or control.get("minimum_applied_cadence_s") != DECISION_CADENCE_S
        or control.get("minimum_code") != MINIMUM_CODE
        or control.get("maximum_code") != MAXIMUM_CODE
        or qualification.get("qualified_duration_s") != QUALIFIED_DURATION_S
        or qualification.get("absolute_wall_clock_limit_s")
        != ABSOLUTE_WALL_LIMIT_S
        or qualification.get("no_extension") is not True
    ):
        raise ValueError("CX320 live manifest does not carry the exact envelope")

    numerical = policy.get("numerical_policy", {})
    authority = policy.get("global_authority_limits", {})
    if (
        policy.get("programme_id") != PROGRAMME_ID
        or policy.get("policy_id") != "CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1"
        or policy.get("setup", {}).get("exact_start_code") != SETUP_CODE
        or authority.get("maximum_total_automatic_applications")
        != MAXIMUM_APPLICATIONS
        or authority.get("maximum_cumulative_absolute_movement_codes")
        != MAXIMUM_CUMULATIVE_MOVEMENT_CODES
        or authority.get("maximum_combined_step_codes") != MAXIMUM_STEP_CODES
        or authority.get("minimum_applied_cadence_s") != DECISION_CADENCE_S
        or authority.get("minimum_code") != MINIMUM_CODE
        or authority.get("maximum_code") != MAXIMUM_CODE
        or numerical.get("settling_exclusion_s") != 900
        or numerical.get("fresh_support_after_settling_s") != 600
        or numerical.get("response_support_total_s") != 1500
    ):
        raise ValueError("current CX320 policy does not carry the exact live envelope")

    bindings = policy.get("bindings", {})
    if not isinstance(bindings, dict):
        raise ValueError("CX320 policy bindings are unavailable")
    phase_estimator_sha256 = _sha256_identity(
        bindings.get("phase_estimator", {}).get("sha256"),
        "policy.phase_estimator_sha256",
    )
    return RuntimeEnvelope(
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
        phase_estimator_sha256=phase_estimator_sha256,
        wall_origin_utc=wall_origin_utc,
    )


def load_active_hybrid_spec(
    manifest: dict[str, Any],
) -> tuple[CampaignSpec, dict[str, str]]:
    """Load the exact runtime contract from a validated live manifest."""

    envelope = _runtime_envelope(manifest)
    policy = _read_object(envelope.policy_path)
    bindings = policy["bindings"]
    identities = {
        "estimator_sha256": _sha256_identity(
            bindings["frequency_estimator"]["sha256"],
            "policy.frequency_estimator_sha256",
        ),
        "model_sha256": _sha256_identity(
            bindings["plant_model"]["sha256"],
            "policy.plant_model_sha256",
        ),
        "active_policy_sha256": envelope.policy_sha256,
        "response_policy_sha256": _sha256_identity(
            bindings["response_policy"]["sha256"],
            "policy.response_policy_sha256",
        ),
        # The firmware's combined controller implementation deliberately uses
        # the semantic active-policy identity as its numerical-policy identity.
        "numerical_policy_sha256": envelope.policy_sha256,
    }
    return (
        CampaignSpec(
            campaign="cx320_active_hybrid",
            profile=PROFILE_ID,
            run_identity=RUNTIME_RUN_IDENTITY,
            start_code=SETUP_CODE,
            correction_limit=MAXIMUM_APPLICATIONS,
            cumulative_limit=MAXIMUM_CUMULATIVE_MOVEMENT_CODES,
            minimum_code=MINIMUM_CODE,
            maximum_code=MAXIMUM_CODE,
            maximum_step=MAXIMUM_STEP_CODES,
        ),
        identities,
    )


def _truth(health: dict[tuple[str, str], str], key: str) -> bool:
    return health.get(("cx317_active", key)) == "true"


class ActiveHybridLiveSupervisor(FrequencyControlSupervisor):
    """CX320 live authority layered on the proven active-control transport."""

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
            raise ValueError("CX320 supervisor requires its manifest-derived spec")
        if (
            spec.run_identity != manifest.get("run_identity")
            or kwargs.get("expected_build_identity") != envelope.build_identity
        ):
            raise ValueError("CX320 supervisor inputs differ from the live manifest")
        super().__init__(
            mode="live",
            leg=TightDeadbandLeg("CX320", 0, "combined_frequency_phase"),
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
            qualified_timeout_s=QUALIFIED_DURATION_S,
            **kwargs,
        )
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        self.envelope = envelope
        self.phase_estimator_sha256 = envelope.phase_estimator_sha256
        self.part = "cx320_active_hybrid_live"
        exact_state = {
            "programme_id": PROGRAMME_ID,
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
        self.state.setdefault("latest_hybrid_state", None)
        self.state.setdefault("first_phase_checkpoint_passed", False)
        self.state.setdefault("later_authority_released", False)
        self.state.setdefault("phase_material_application_count", 0)
        self.state.setdefault("terminal_static_code", None)
        self._save()

    def _fresh_active_snapshot_after(
        self, generation: int
    ) -> dict[tuple[str, str], str]:
        self._command(self._status_query_command())
        deadline = time.monotonic() + 5.0
        while True:
            health = self._current_health()
            observed = int(
                health.get(("cx317_active", "snapshot_generation_complete"), "0")
            )
            if observed > generation:
                return health
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "CX320 fresh active snapshot did not follow evidence acknowledgement"
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
        if (
            health.get(("cx317_active", "evidence_phase")) != expected_phase
            or int(
                health.get(("cx317_active", "evidence_request_sequence"), "0")
            )
            != request_sequence
        ):
            raise ValueError(
                "CX320 firmware evidence frontier differs before acknowledgement: "
                f"request={request_sequence} phase={expected_phase}"
            )
        return {
            "pre_submit_snapshot_generation": int(
                health[("cx317_active", "snapshot_generation_complete")]
            ),
            "pre_submit_evidence_phase": expected_phase,
        }

    def _confirm_evidence_acknowledgement(
        self, acknowledgement: dict[str, object]
    ) -> bool:
        phase = int(acknowledgement["phase"])
        request_sequence = int(acknowledgement["request_sequence"])
        baseline = int(acknowledgement["pre_submit_snapshot_generation"])
        health = self._fresh_active_snapshot_after(baseline)
        observed_phase = health.get(("cx317_active", "evidence_phase"), "")
        observed_request = int(
            health.get(("cx317_active", "evidence_request_sequence"), "0")
        )
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
        if observed_phase not in permitted:
            return False
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
        self._event(
            "cx320_firmware_evidence_acknowledgement_confirmed",
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
        mismatches = list(readiness.mismatches)
        if health.get(("cx317_active", "query_nonce")) != str(
            self.state["host_attach_query_nonce"]
        ):
            mismatches.append("solicited post-attachment snapshot is absent")
        return PrewriteReadiness(
            contract_id="cx320_active_hybrid_prewrite_runtime_contract_v1",
            ready=not readiness.missing and not mismatches,
            missing=readiness.missing,
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
        prior_terminal = self.state.get("terminal")
        super()._process_transactions()
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
        ControlSupervisorBase._check_fail_static_health(self, health)
        integrity = self._runtime_health_integrity(health)
        if integrity.mismatches or (
            self.state["prewrite_contract_ready_utc"] is not None
            and integrity.missing
        ):
            raise ValueError(
                "CX320 continuous runtime health contract failed: "
                + integrity.diagnostic()
            )
        if self.state["manual_start_sent"] and not self._identity_ready(health):
            raise ValueError("CX320 exact runtime identity became unavailable")
        if self.state["manual_start_sent"]:
            required_true = (
                "capture_lease_live",
                "setup_gnss_eligible",
                "setup_reference_eligible",
                "setup_partition_healthy",
            )
            unhealthy = [key for key in required_true if not _truth(health, key)]
            if unhealthy:
                raise ValueError(
                    "CX320 shared D14/D8/GNSS/capture qualification lost: "
                    + ", ".join(unhealthy)
                )

        hybrid_state = health.get(("cx317_active", "hybrid_state"))
        if hybrid_state is None:
            if self.state["manual_start_sent"]:
                raise ValueError("CX320 hybrid firmware state is absent")
            return
        if hybrid_state not in HYBRID_STATES:
            raise ValueError(f"unexpected CX320 hybrid state: {hybrid_state!r}")
        if hybrid_state == "FAIL_STATIC":
            reason = health.get(("cx317_active", "hybrid_reason"), "unknown")
            raise ValueError(f"CX320 firmware entered FAIL_STATIC: {reason}")

        corrections = int(
            health.get(("cx317_active", "correction_count"), "0")
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
        if (
            corrections > MAXIMUM_APPLICATIONS
            or movement > MAXIMUM_CUMULATIVE_MOVEMENT_CODES
            or material > phase_nonzero
            or phase_nonzero + frequency_only > corrections
        ):
            raise ValueError("CX320 firmware exceeded the frozen global authority")
        if material > 1 and not checkpoint:
            raise ValueError("CX320 later material authority preceded its checkpoint")
        if hybrid_state == "HYBRID_TRACKING" and not checkpoint:
            raise ValueError("CX320 HYBRID_TRACKING lacks the first checkpoint")

        changed = hybrid_state != self.state.get("latest_hybrid_state")
        dirty = changed
        if _truth(health, "confirmed_applied_code_known"):
            applied = int(health[("cx317_active", "confirmed_applied_code")], 0)
            if not MINIMUM_CODE <= applied <= MAXIMUM_CODE:
                raise ValueError("CX320 confirmed code is outside the frozen range")
            if self.state.get("terminal_static_code") != applied:
                self.state["terminal_static_code"] = applied
                dirty = True

        if changed:
            self.state["latest_hybrid_state"] = hybrid_state
        if self.state["phase_material_application_count"] != material:
            self.state["phase_material_application_count"] = material
            dirty = True
        if checkpoint and not self.state["first_phase_checkpoint_passed"]:
            self.state["first_phase_checkpoint_passed"] = True
            dirty = True
        if hybrid_state == "HYBRID_TRACKING" and checkpoint:
            if not self.state["later_authority_released"]:
                self.state["later_authority_released"] = True
                dirty = True
                self._event(
                    "cx320_first_phase_checkpoint_release_observed",
                    hybrid_state=hybrid_state,
                    phase_material_application_count=material,
                )
        if dirty:
            self._save()

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
            != SETUP_CODE
            or int(health.get(("cx317_active", "dac_epoch"), "0")) < 1
        ):
            return
        dac_epoch = int(health[("cx317_active", "dac_epoch")])
        estimate = self._fresh_authoritative_selected_estimate(
            _read_csv(self.run_dir / ESTIMATES_CSV), dac_epoch=dac_epoch
        )
        if estimate is None:
            return
        self.state["qualification_started_utc"] = _utc_now()
        self.state["qualified_origin_estimate_id"] = estimate["estimate_id"]
        self._save()
        self._event(
            "cx320_qualified_origin_established",
            estimate_id=estimate["estimate_id"],
            source_count_ref=estimate["source_count_ref"],
            source_dac_ref=estimate["source_dac_ref"],
            dac_epoch=dac_epoch,
            qualified_duration_s=QUALIFIED_DURATION_S,
        )

    def _close_response_horizon_if_required(self, now_epoch: float) -> bool:
        qualified = self.state.get("qualification_started_utc")
        if not isinstance(qualified, str) or not qualified:
            return False
        elapsed = now_epoch - _parse_utc_epoch(qualified)
        if elapsed < QUALIFIED_DURATION_S - CORRECTION_RESPONSE_RESERVE_S:
            return False
        if self.state["response_horizon_closed_utc"] is None:
            self.state["response_horizon_closed_utc"] = _utc_now()
            self._save()
            self._event(
                "cx320_correction_admission_closed_for_response_horizon",
                remaining_qualified_s=max(0, int(QUALIFIED_DURATION_S - elapsed)),
                required_response_reserve_s=CORRECTION_RESPONSE_RESERVE_S,
            )
        return True

    def _maybe_start_or_arm(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if not self._identity_ready(health):
            return
        state = health.get(("cx317_active", "state"), "")
        reason = health.get(("cx317_active", "reason"), "")
        if state in {"FAULT", "ABORTED"}:
            raise ValueError(f"device active state {state.lower()}: {reason}")
        if state == "REFERENCE_HOLD":
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
            self._event(
                "cx320_exact_setup_requested",
                code=SETUP_CODE,
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
                self._event("cx320_unused_zero_delta_arm_consumed_without_write")
        if not manual_confirmed or self.state["arm_pending"]:
            return
        if self._close_response_horizon_if_required(time.time()):
            return

        hybrid_state = health.get(("cx317_active", "hybrid_state"), "")
        # FIRST_PHASE_TRANSACTION stays unarmed until firmware has both passed
        # the durable response checkpoint and observed tight reacquisition.
        # PHASE_DEGRADED and FAIL_STATIC are terminal paths, not arm states.
        if hybrid_state not in ARMABLE_HYBRID_STATES:
            return
        if hybrid_state == "HYBRID_TRACKING" and not _truth(
            health, "first_phase_checkpoint_passed"
        ):
            raise ValueError("later CX320 authority lacks its firmware checkpoint")
        correction_count = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        if correction_count >= MAXIMUM_APPLICATIONS:
            return
        progress = int(
            health.get(("cx317_active", "selected_interval_count"), "0")
        )
        preview_rows = _read_csv(self.run_dir / CONTROL_CSV)
        preview = preview_rows[-1] if preview_rows else None
        if not self._arm_progress_epoch_ready(preview, progress):
            return
        if not (
            state == "DISARMED"
            and _truth(health, "arm_eligible")
            and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
            and not _truth(health, "evidence_pending")
            and progress >= ARM_PROGRESS_THRESHOLD
            and _next_selected_interval_is_cadence_eligible(
                self.run_dir / CONTROL_CSV,
                self.run_dir / ESTIMATES_CSV,
                selected_interval_s=SELECTED_INTERVAL_S,
                decision_cadence_s=DECISION_CADENCE_S,
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
        self._save()
        self._event(
            "cx320_one_decision_armed",
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
            or health.get(("cx317_active", "state")) != "DISARMED"
            or health.get(("cx317_active", "evidence_phase")) != "evidence_clear"
            or _truth(health, "evidence_pending")
            or int(health.get(("cx317_active", "evidence_request_sequence"), "0"))
            != 0
            or not _truth(health, "confirmed_applied_code_known")
        ):
            return False
        code = int(health[("cx317_active", "confirmed_applied_code")], 0)
        if not MINIMUM_CODE <= code <= MAXIMUM_CODE:
            return False
        rows = _read_csv(self.run_dir / ACTIVE_CSV)
        if rows and rows[-1].get("event") not in {"manual_start", "response"}:
            return False
        self.state["terminal_static_code"] = code
        return True

    def _set_healthy_endpoint(
        self, health: dict[tuple[str, str], str], *, endpoint: str
    ) -> None:
        material = int(
            health.get(
                ("cx317_active", "phase_material_application_count"), "0"
            )
        )
        checkpoint = _truth(health, "first_phase_checkpoint_passed")
        if material == 0:
            preliminary = "phase_influence_not_exercised"
        elif material < MINIMUM_PHASE_MATERIAL_APPLICATIONS:
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
        if hybrid_state == "PHASE_DEGRADED_FREQUENCY_ONLY":
            self._abort("phase_channel_degraded_frequency_control_retained")
            return

        qualified = self.state.get("qualification_started_utc")
        if isinstance(qualified, str) and qualified:
            if now_epoch - _parse_utc_epoch(qualified) >= QUALIFIED_DURATION_S:
                if self._healthy_terminal_ready(health):
                    self._set_healthy_endpoint(
                        health, endpoint="cx320_12h_qualified_endpoint_complete"
                    )
                    return

        wall_origin = self.state.get("wall_origin_utc")
        if (
            isinstance(wall_origin, str)
            and wall_origin
            and now_epoch - _parse_utc_epoch(wall_origin)
            >= ABSOLUTE_WALL_LIMIT_S
        ):
            if self._healthy_terminal_ready(health):
                self.state["terminal"] = {
                    "result": "nonpass",
                    "reason": "cx320_16h_absolute_wall_endpoint",
                    "primary_decision": "right_censored_incomplete",
                    "last_confirmed_code": self.state["terminal_static_code"],
                    "utc": _utc_now(),
                }
                self._save()
            else:
                self._abort("cx320_wall_endpoint_without_clear_static_terminal")

    def _abort(self, reason: str) -> None:
        super()._abort(reason)
        terminal = self.state["terminal"]
        if reason == "independent_host_abort_fifo":
            terminal["primary_decision"] = "operator_abort"
        elif reason == "phase_channel_degraded_frequency_control_retained":
            terminal["primary_decision"] = (
                "phase_channel_degraded_frequency_control_retained"
            )
        elif reason.startswith("cx320_wall_endpoint"):
            terminal["primary_decision"] = "right_censored_incomplete"
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
        with AbortFifo(self.abort_fifo) as abort:
            self._live_command_ack_required = True
            self._event(
                "cx320_live_supervisor_started",
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
                    self._command(self._status_query_command())
                    last_query = now
                self._process_transactions()
                health = self._current_health()
                self._check_fail_static_health(health)
                self._check_setup_transaction_timeout(health, time.time())
                self._check_prewrite_contract(health, now - started)
                self._maybe_qualify(health)
                self._maybe_finish(health, time.time(), now - started)
                if self.state["terminal"] is None:
                    self._maybe_start_or_arm(health)
                if self.state["terminal"] is not None:
                    if not self.state["terminal_event_emitted"]:
                        self._event(
                            "cx320_campaign_terminal", **self.state["terminal"]
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
            supervisor._event("cx320_live_supervisor_fault", error=str(exc))
            supervisor._abort(f"cx320_live_supervisor_fault:{exc}")
            return 2
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
