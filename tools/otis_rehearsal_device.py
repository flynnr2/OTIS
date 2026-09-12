"""Deterministic PTY evidence producer for engineering rehearsal only.

This module emits firmware-shaped serial records for the actual host consumer
path.  It has no hardware, campaign, finalization, or registration authority.
The caller supplies a validated run-spec runtime projection and programme.
"""

from __future__ import annotations

import json
import os
import select
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
)
from host.otis_tools.adaptive_hybrid_contract import AdaptiveHybridProgramme
from host.otis_tools.adaptive_hybrid_policy import (
    AdaptiveHybridDecision,
    AdaptiveHybridObservation,
    AdaptiveHybridPhasePriorityController,
    policy_from_mapping,
)
from host.otis_tools.adaptive_hybrid_supervisor import (
    FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH,
    _authoritative_capture_counters,
)
from host.otis_tools.authoritative_inputs import (
    ROOT_PROFILE,
    ValidatedAuthoritativeInputs,
    validate_authoritative_inputs,
)
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V3_FIELDS,
    ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS,
    ACTIVE_TRANSACTION_V3_FIELDS,
    CONTRACT_FIELDS,
)
from host.otis_tools.prewrite_readiness_contract import (
    GNSS_PREWRITE_EXACT,
    HEALTH_INTEGRITY_EXACT,
    canonical_prewrite_fixture,
)

RP2040_US = 1_000_000


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise TypeError(f"{label} must contain a JSON object")
    return value


def _write_all_fd(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("zero-byte PTY write")
        view = view[written:]


def _wire_row(fields: list[str], row: dict[str, str]) -> bytes:
    return (",".join(row[field] for field in fields) + "\r\n").encode("ascii")


def _reference_acceptance_binding(inputs: ValidatedAuthoritativeInputs) -> dict[str, str]:
    path = "data_contracts/reference_acceptance_policy_v1.json"
    return {
        "path": path,
        "policy_id": inputs.document(path)["policy_id"],
        "policy_sha256": inputs.binding(path)["sha256"],
    }



@dataclass(frozen=True)
class TransactionFixture:
    request_decision: dict[str, str]
    request_maintenance: dict[str, str]
    phases: tuple[dict[str, str], ...]
    application_maintenance: dict[str, str]
    response_decision: dict[str, str]
    response_decision_maintenance: dict[str, str]
    response_maintenance: dict[str, str]


@dataclass(frozen=True)
class LifecycleFixture:
    manual_start: dict[str, str]
    policy_activation: dict[str, str]
    first_transaction: TransactionFixture
    metadata_hold: dict[str, str]
    metadata_requalified: dict[str, str]
    first_requalification_decision: dict[str, str]
    first_requalification_maintenance: dict[str, str]
    second_requalification_decision: dict[str, str]
    second_requalification_maintenance: dict[str, str]
    second_transaction: TransactionFixture

    @property
    def decisions(self) -> list[dict[str, str]]:
        return [
            self.first_transaction.request_decision,
            self.first_transaction.response_decision,
            self.first_requalification_decision,
            self.second_requalification_decision,
            self.second_transaction.request_decision,
            self.second_transaction.response_decision,
        ]

    @property
    def transactions(self) -> list[dict[str, str]]:
        return [
            self.manual_start,
            *self.first_transaction.phases,
            *self.second_transaction.phases,
        ]

    @property
    def maintenance(self) -> list[dict[str, str]]:
        return [
            self.policy_activation,
            self.first_transaction.request_maintenance,
            self.first_transaction.application_maintenance,
            self.first_transaction.response_decision_maintenance,
            self.first_transaction.response_maintenance,
            self.metadata_hold,
            self.metadata_requalified,
            self.first_requalification_maintenance,
            self.second_requalification_maintenance,
            self.second_transaction.request_maintenance,
            self.second_transaction.application_maintenance,
            self.second_transaction.response_decision_maintenance,
            self.second_transaction.response_maintenance,
        ]


class _LifecycleBuilder:
    """Generate firmware-shaped current records through the policy oracle."""

    def __init__(self, runtime: dict[str, Any], programme: AdaptiveHybridProgramme) -> None:
        self.runtime = runtime
        self.programme = programme
        inputs = validate_authoritative_inputs(runtime["authoritative_inputs"])
        self.policy_document = inputs.document(ROOT_PROFILE)
        root_binding = inputs.binding(ROOT_PROFILE)
        self.policy = policy_from_mapping(
            self.policy_document, policy_sha256=str(root_binding["sha256"])
        )
        self.bindings = {
            name: inputs.binding(relative)
            for name, relative in self.policy_document["bindings"].items()
        }
        self.controller = AdaptiveHybridPhasePriorityController(
            self.policy,
            setup_applied_code=self.programme.setup_code,
            setup_dac_epoch=1,
        )
        self.response_baseline_error_hz: float | None = None
        self.hybrid_sequence = 0
        self.maintenance_sequence = 0
        self.burst_sequence = 0

    def _controller_state(self) -> str:
        controller = self.controller
        if controller.fail_static_reason is not None:
            return "FAIL_STATIC"
        if controller.metadata_hold:
            return "METADATA_HOLD"
        if controller.response_pending:
            return "RESPONSE_PENDING"
        if controller.request_pending:
            return "REQUEST_PENDING"
        if controller.persistence_count:
            return "PERSISTENCE_HOLD"
        return "READY"

    def _snapshot(self, suffix: str) -> dict[str, str]:
        controller = self.controller
        return {
            f"maintenance_state_{suffix}": self._controller_state(),
            f"committed_fll_debt_{suffix}_picocodes": str(
                controller.debt.fll_picocodes
            ),
            f"committed_pll_debt_{suffix}_picocodes": str(
                controller.debt.pll_picocodes
            ),
            f"request_pending_{suffix}": str(controller.request_pending).lower(),
            f"response_pending_{suffix}": str(controller.response_pending).lower(),
            f"metadata_hold_{suffix}": str(controller.metadata_hold).lower(),
            f"persistence_count_{suffix}": str(controller.persistence_count),
            f"requalification_window_count_{suffix}": str(
                controller.requalification_window_count
            ),
        }

    def _frontier_relation(self, observation: AdaptiveHybridObservation) -> str:
        closing = (
            self.controller._requalification_last_closing_accepted_boundary_ordinal
            if self.controller.metadata_requalified
            else self.controller.last_closing_accepted_boundary_ordinal
        )
        if closing is None:
            return "first"
        if observation.source_opening_accepted_boundary_ordinal < closing:
            return "overlap"
        if observation.source_opening_accepted_boundary_ordinal == closing:
            return "contiguous"
        return "gap"

    def _interval_sign(self, observation: AdaptiveHybridObservation) -> int:
        if not observation.phase_valid:
            return 0
        _centre, lower, upper = self.controller._centre(observation)
        return self.controller._sign(lower, upper)

    def _observation(
        self,
        *,
        timestamp_s: int,
        source_first: int,
        source_last: int,
        counts: int,
        phase: int,
    ) -> AdaptiveHybridObservation:
        return AdaptiveHybridObservation(
            timestamp_s=timestamp_s,
            timestamp_ticks=timestamp_s * RP2040_US,
            capture_session=1,
            source_acceptance_epoch=1,
            source_opening_accepted_boundary_ordinal=source_first,
            source_closing_accepted_boundary_ordinal=source_last,
            dac_epoch=self.controller.dac_epoch,
            applied_code=self.controller.applied_code,
            accumulated_edge_error_counts=counts,
            tight_state="TIGHT_INSIDE",
            phase_epoch=1,
            relative_phase_cycles=phase,
        )

    @staticmethod
    def _hybrid_state(
        controller: AdaptiveHybridPhasePriorityController, *, phase_valid: bool
    ) -> str:
        if controller.fail_static_reason is not None:
            return "FAIL_STATIC"
        if not phase_valid:
            return "PHASE_DEGRADED_FREQUENCY_ONLY"
        if controller.request_pending or controller.response_pending:
            return "FIRST_PHASE_TRANSACTION"
        if controller.application_count == 0:
            return "PHASE_QUALIFY"
        return "HYBRID_TRACKING"

    def _decision_row(
        self,
        observation: AdaptiveHybridObservation,
        decision: AdaptiveHybridDecision,
        *,
        state_before: str,
        applications_before: int,
        movement_before: int,
        authority_state: str,
    ) -> dict[str, str]:
        self.hybrid_sequence += 1
        conservative_gain = 0.000173340101
        fll_hz = decision.raw_fll_picocodes / 1_000_000_000_000 * conservative_gain
        pll_hz = decision.raw_pll_picocodes / 1_000_000_000_000 * conservative_gain
        combined_hz = (
            decision.raw_combined_picocodes / 1_000_000_000_000 * conservative_gain
        )
        selected_frequency_hz = float(
            600 * 10_000_000 + observation.accumulated_edge_error_counts
        ) / 600.0
        frequency_error_hz = selected_frequency_hz - 10_000_000.0
        row = {field: "0" for field in ACTIVE_HYBRID_DECISION_V3_FIELDS}
        row.update(
            {
                "record_type": "AHY",
                "schema_version": "3",
                "hybrid_record_sequence": str(self.hybrid_sequence),
                "decision_sequence": str(decision.decision_sequence),
                "decision_timestamp_ticks": str(observation.timestamp_ticks),
                "time_domain": "rp2040_monotonic_us64",
                "decision_timestamp_s": str(observation.timestamp_s),
                "run_identity": self.programme.runtime_run_identity,
                "build_identity": str(self.runtime["firmware"]["build_identity"]),
                "image_identity": self.programme.profile_id,
                "capture_session": str(observation.capture_session),
                "source_acceptance_epoch": str(observation.source_acceptance_epoch),
                "source_opening_accepted_boundary_ordinal": str(observation.source_opening_accepted_boundary_ordinal),
                "source_closing_accepted_boundary_ordinal": str(observation.source_closing_accepted_boundary_ordinal),
                "frequency_estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
                "frequency_error_hz": f"{frequency_error_hz:.12f}",
                "accumulated_edge_error_counts": str(observation.accumulated_edge_error_counts),
                "tight_state": observation.tight_state,
                "phase_estimator_sha256": self.bindings["phase_estimator"]["sha256"],
                "phase_epoch": str(observation.phase_epoch),
                "phase_observation_sequence": str(observation.source_closing_accepted_boundary_ordinal - 1200),
                "relative_phase_cycles": str(observation.relative_phase_cycles),
                "phase_continuous": str(observation.phase_valid).lower(),
                "phase_current": str(observation.phase_valid).lower(),
                "phase_step_detected": "false",
                "phase_recorder_published": str(observation.phase_valid).lower(),
                "current_applied_code": str(observation.applied_code),
                "dac_epoch": str(observation.dac_epoch),
                "phase_applied_code": str(observation.applied_code),
                "phase_dac_epoch": str(observation.dac_epoch),
                "state_before": state_before,
                "state_after": self._hybrid_state(
                    self.controller, phase_valid=observation.phase_valid
                ),
                "frequency_term_hz": f"{fll_hz:.12f}",
                "phase_term_hz": f"{pll_hz:.12f}",
                "combined_demand_hz": f"{combined_hz:.12f}",
                "raw_combined_delta_codes": f"{decision.raw_combined_picocodes / 1_000_000_000_000:.12f}",
                "requested_delta_codes": str(decision.requested_delta_codes),
                "requested_code": str(decision.requested_code),
                "counterfactual_frequency_only_delta_codes": str(
                    decision.counterfactual_frequency_only_delta_codes
                ),
                "phase_materially_influenced": str(
                    decision.phase_materially_influenced
                ).lower(),
                "step_limited": str(decision.step_limited).lower(),
                "range_clamped": str(decision.range_clamped).lower(),
                "cadence_limited": str(decision.cadence_limited).lower(),
                "count_limited": str(decision.count_limited).lower(),
                "cumulative_budget_limited": str(
                    decision.cumulative_budget_limited
                ).lower(),
                "correction_count_before": str(applications_before),
                "cumulative_movement_before_codes": str(movement_before),
                "authority_state": authority_state,
                "response_class": "unavailable",
                "actual_applied_code": str(observation.applied_code),
                "actual_dac_epoch": str(observation.dac_epoch),
                "downstream_epoch_exact": "true",
                "reason": decision.reason,
                "active_policy_sha256": self.policy.policy_sha256,
                "response_policy_sha256": self.bindings["response_classification"]["sha256"],
                "actionable": "false",
            }
        )
        return row

    def _append_decision(
        self,
        observation: AdaptiveHybridObservation,
        *,
        authority_state: str = "ARMED",
    ) -> tuple[AdaptiveHybridDecision, dict[str, str], dict[str, str]]:
        observation = replace(observation, cadence_eligible=authority_state == "ARMED")
        before = {
            **self._snapshot("before"),
            "frontier_relation_before": self._frontier_relation(observation),
            "interval_sign_before": str(self._interval_sign(observation)),
            "current_code": str(self.controller.applied_code),
            "current_epoch": str(self.controller.dac_epoch),
        }
        state_before = self._hybrid_state(
            self.controller, phase_valid=observation.phase_valid
        )
        applications_before = self.controller.application_count
        movement_before = self.controller.cumulative_movement_codes
        decision = self.controller.decide(observation)
        row = self._decision_row(
            observation,
            decision,
            state_before=state_before,
            applications_before=applications_before,
            movement_before=movement_before,
            authority_state=authority_state,
        )
        return decision, row, before

    def _maintenance_row(
        self,
        event: str,
        *,
        before: dict[str, str],
        timestamp_ticks: int,
        reason: str,
        observation: AdaptiveHybridObservation | None = None,
        decision: AdaptiveHybridDecision | None = None,
        hybrid: dict[str, str] | None = None,
        transaction: dict[str, str] | None = None,
        burst_ordinal: int = 1,
        burst_count: int = 1,
        current_code: int | None = None,
        current_epoch: int | None = None,
    ) -> dict[str, str]:
        self.maintenance_sequence += 1
        self.burst_sequence += 1
        row = {field: "0" for field in ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS}
        row.update(
            {
                "record_type": "AHM",
                "schema_version": "2",
                "maintenance_record_sequence": str(self.maintenance_sequence),
                "event": event,
                "event_timestamp_ticks": str(timestamp_ticks),
                "time_domain": "rp2040_monotonic_us64",
                "run_identity": self.programme.runtime_run_identity,
                "build_identity": str(self.runtime["firmware"]["build_identity"]),
                "image_identity": self.programme.profile_id,
                "policy_id": self.programme.policy_id,
                "active_policy_sha256": self.policy.policy_sha256,
                "capture_session": "0",
                "frequency_estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
                "phase_epoch": "0",
                "phase_valid": "false",
                "current_applied_code": str(
                    self.controller.applied_code if current_code is None else current_code
                ),
                "current_dac_epoch": str(
                    self.controller.dac_epoch if current_epoch is None else current_epoch
                ),
                "transaction_event": "none",
                "maintenance_state_before": before["maintenance_state_before"],
                "maintenance_state_after": self._controller_state(),
                "frontier_relation": (
                    before["frontier_relation_before"]
                    if event == "decision"
                    else "not_applicable"
                ),
                "interval_sign": (
                    before.get("interval_sign_before", "0")
                    if observation is not None
                    else "0"
                ),
                "committed_fll_debt_before_picocodes": before[
                    "committed_fll_debt_before_picocodes"
                ],
                "committed_pll_debt_before_picocodes": before[
                    "committed_pll_debt_before_picocodes"
                ],
                "committed_fll_debt_after_picocodes": str(
                    self.controller.debt.fll_picocodes
                ),
                "committed_pll_debt_after_picocodes": str(
                    self.controller.debt.pll_picocodes
                ),
                "request_pending_before": before["request_pending_before"],
                "request_pending_after": str(self.controller.request_pending).lower(),
                "response_pending_before": before["response_pending_before"],
                "response_pending_after": str(self.controller.response_pending).lower(),
                "metadata_hold_before": before["metadata_hold_before"],
                "metadata_hold_after": str(self.controller.metadata_hold).lower(),
                "persistence_count_before": before["persistence_count_before"],
                "persistence_count_after": str(self.controller.persistence_count),
                "requalification_window_count_before": before[
                    "requalification_window_count_before"
                ],
                "requalification_window_count_after": str(
                    self.controller.requalification_window_count
                ),
                "requalification_accepted_boundary_ordinal": (
                    str(self.controller.requalification_accepted_boundary_ordinal)
                    if event == "gnss_metadata_requalified"
                    and self.controller.requalification_accepted_boundary_ordinal is not None
                    else "0"
                ),
                "evidence_burst_sequence": str(self.burst_sequence),
                "evidence_burst_record_ordinal": str(burst_ordinal),
                "evidence_burst_record_count": str(burst_count),
                "reason": reason,
                "actionable": "false",
                "downstream_epoch_exact": "false",
                "requested_code": str(
                    self.controller.applied_code if current_code is None else current_code
                ),
            }
        )
        if observation is not None:
            row.update(
                {
                    "capture_session": str(observation.capture_session),
                    "source_acceptance_epoch": str(observation.source_acceptance_epoch),
                "source_opening_accepted_boundary_ordinal": str(observation.source_opening_accepted_boundary_ordinal),
                    "source_closing_accepted_boundary_ordinal": str(observation.source_closing_accepted_boundary_ordinal),
                    "phase_epoch": str(observation.phase_epoch),
                    "phase_observation_sequence": str(observation.source_closing_accepted_boundary_ordinal - 1200),
                    "phase_valid": str(observation.phase_valid).lower(),
                }
            )
        if hybrid is not None:
            for key in (
                "hybrid_record_sequence",
                "decision_sequence",
                "source_acceptance_epoch",
                "source_opening_accepted_boundary_ordinal",
                "source_closing_accepted_boundary_ordinal",
            ):
                row[key] = hybrid[key]
        if decision is not None:
            row.update(
                {
                    "decision_sequence": str(decision.decision_sequence),
                    "raw_fll_demand_picocodes": str(decision.raw_fll_picocodes),
                    "raw_pll_demand_picocodes": str(decision.raw_pll_picocodes),
                    "candidate_total_demand_picocodes": str(
                        decision.raw_combined_picocodes
                        + decision.committed_debt_picocodes
                    ),
                    "safe_cap_codes": str(decision.safe_cap_codes),
                    "requested_delta_codes": str(decision.requested_delta_codes),
                    "requested_code": str(decision.requested_code),
                }
            )
        if transaction is not None:
            row.update(
                {
                    "transaction_record_sequence": transaction[
                        "transaction_record_sequence"
                    ],
                    "transaction_event": transaction["event"],
                    "request_sequence": transaction["request_sequence"],
                    "application_sequence": transaction["application_sequence"],
                }
            )
            if transaction["event"] in {"application", "response"}:
                row.update(
                    {
                        "actual_applied_code": transaction["applied_code"],
                        "actual_dac_epoch": transaction["dac_epoch"],
                        "downstream_epoch_exact": "true",
                    }
                )
        return row

    def _transaction_rows(
        self,
        *,
        decision: AdaptiveHybridDecision,
        observation: AdaptiveHybridObservation,
        first_record: int,
        request_sequence: int,
        application_sequence: int,
        response_timestamp_s: int,
    ) -> tuple[dict[str, str], ...]:
        cumulative = self.controller.cumulative_movement_codes + abs(
            decision.requested_delta_codes
        )
        dac_epoch = self.controller.dac_epoch + 1
        frequency_error = (
            float(600 * 10_000_000 + observation.accumulated_edge_error_counts)
            / 600.0
            - 10_000_000.0
        )
        if self.response_baseline_error_hz is None:
            self.response_baseline_error_hz = frequency_error
        post_error = 0.0
        observed_response = post_error - frequency_error
        cumulative_response = post_error - self.response_baseline_error_hz
        common = {
            "record_type": "ACT",
            "schema_version": "3",
            "time_domain": "rp2040_monotonic_us64",
            "run_identity": self.programme.runtime_run_identity,
            "build_identity": str(self.runtime["firmware"]["build_identity"]),
            "image_identity": self.programme.profile_id,
            "session_id": "1",
            "authorization_sequence": str(request_sequence),
            "nonce": str(7_000_000 + request_sequence),
            "request_sequence": str(request_sequence),
            "decision_sequence": str(decision.decision_sequence),
            "source_acceptance_epoch": str(observation.source_acceptance_epoch),
                "source_opening_accepted_boundary_ordinal": str(observation.source_opening_accepted_boundary_ordinal),
            "source_closing_accepted_boundary_ordinal": str(observation.source_closing_accepted_boundary_ordinal),
            "decision_timestamp_s": str(observation.timestamp_s),
            "current_applied_code": str(observation.applied_code),
            "requested_delta_codes": str(decision.requested_delta_codes),
            "requested_code": str(decision.requested_code),
            "correction_ordinal": str(application_sequence),
            "cumulative_after_codes": str(cumulative),
            "pre_error_hz": f"{frequency_error:.12f}",
            "consecutive_indeterminate": "0",
            "estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
            "model_sha256": self.bindings["plant_model"]["sha256"],
            "active_policy_sha256": self.policy.policy_sha256,
            "response_policy_sha256": self.bindings["response_classification"]["sha256"],
            "numerical_policy_sha256": self.policy.policy_sha256,
            "actionable": "false",
        }
        phases = (
            {
                "event": "request_created",
                "event_timestamp_ticks": str(observation.timestamp_ticks),
                "accepted_code": "0",
                "accepted_timestamp_s": "0",
                "applied_code": "0",
                "application_sequence": "0",
                "application_timestamp_s": "0",
                "i2c_ok": "false",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(observation.dac_epoch),
                "estimator_history_reset": "false",
                "correction_count": str(application_sequence - 1),
                "cumulative_movement_codes": str(
                    cumulative - abs(decision.requested_delta_codes)
                ),
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "active_state": "REQUEST_PENDING",
                "response_class": "unavailable",
                "reason": "one_combined_request_created",
                "evidence_state": "request_pending",
            },
            {
                "event": "request_accepted",
                "event_timestamp_ticks": str(observation.timestamp_ticks + 100_000),
                "accepted_code": str(decision.requested_code),
                "accepted_timestamp_s": str(observation.timestamp_s),
                "applied_code": "0",
                "application_sequence": "0",
                "application_timestamp_s": "0",
                "i2c_ok": "false",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(observation.dac_epoch),
                "estimator_history_reset": "false",
                "correction_count": str(application_sequence - 1),
                "cumulative_movement_codes": str(
                    cumulative - abs(decision.requested_delta_codes)
                ),
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "active_state": "ACCEPTED_AWAITING_APPLICATION",
                "response_class": "unavailable",
                "reason": "request_consumed_actionable_cleared",
                "evidence_state": "acceptance_pending",
            },
            {
                "event": "application",
                "event_timestamp_ticks": str(observation.timestamp_ticks + 200_000),
                "accepted_code": str(decision.requested_code),
                "accepted_timestamp_s": str(observation.timestamp_s),
                "applied_code": str(decision.requested_code),
                "application_sequence": str(application_sequence),
                "application_timestamp_s": str(observation.timestamp_s),
                "i2c_ok": "true",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(dac_epoch),
                "estimator_history_reset": "true",
                "correction_count": str(application_sequence),
                "cumulative_movement_codes": str(cumulative),
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "active_state": "AWAITING_RESPONSE",
                "response_class": "unavailable",
                "reason": "applied_history_reset_response_required",
                "evidence_state": "application_pending",
            },
            {
                "event": "response",
                "event_timestamp_ticks": str(response_timestamp_s * RP2040_US),
                "accepted_code": str(decision.requested_code),
                "accepted_timestamp_s": str(observation.timestamp_s),
                "applied_code": str(decision.requested_code),
                "application_sequence": str(application_sequence),
                "application_timestamp_s": str(observation.timestamp_s),
                "i2c_ok": "true",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(dac_epoch),
                "estimator_history_reset": "true",
                "correction_count": str(application_sequence),
                "cumulative_movement_codes": str(cumulative),
                "post_error_hz": f"{post_error:.12f}",
                "observed_response_hz": f"{observed_response:.12f}",
                "cumulative_response_hz": f"{cumulative_response:.12f}",
                "consecutive_indeterminate": str(application_sequence),
                "active_state": "DISARMED",
                "response_class": "healthy_indeterminate_near_resolution",
                "reason": "healthy_evidence_below_empirical_detection_floor",
                "evidence_state": "response_pending",
            },
        )
        return tuple(
            {
                **{field: "" for field in ACTIVE_TRANSACTION_V3_FIELDS},
                **common,
                **phase,
                "transaction_record_sequence": str(first_record + offset),
            }
            for offset, phase in enumerate(phases)
        )

    def _transaction(
        self,
        observation: AdaptiveHybridObservation,
        *,
        first_record: int,
        request_sequence: int,
        application_sequence: int,
        response_timestamp_s: int,
        response_source_last: int,
    ) -> TransactionFixture:
        decision, hybrid, before = self._append_decision(observation)
        if decision.requested_delta_codes == 0:
            raise RuntimeError(f"rehearsal transaction did not request control: {decision}")
        phases = self._transaction_rows(
            decision=decision,
            observation=observation,
            first_record=first_record,
            request_sequence=request_sequence,
            application_sequence=application_sequence,
            response_timestamp_s=response_timestamp_s,
        )
        request_maintenance = self._maintenance_row(
            "decision",
            before=before,
            timestamp_ticks=observation.timestamp_ticks,
            reason=decision.reason,
            observation=observation,
            decision=decision,
            hybrid=hybrid,
            transaction=phases[0],
            burst_ordinal=5,
            burst_count=5,
            current_code=observation.applied_code,
            current_epoch=observation.dac_epoch,
        )

        application_before = self._snapshot("before")
        self.controller.confirm_application(
            decision,
            applied_code=decision.requested_code,
            dac_epoch=observation.dac_epoch + 1,
            first_consumer_exact=True,
        )
        application_maintenance = self._maintenance_row(
            "application_first_consumer",
            before=application_before,
            timestamp_ticks=int(phases[2]["event_timestamp_ticks"]),
            reason="application_and_first_consumer_committed",
            observation=observation,
            decision=decision,
            hybrid=hybrid,
            transaction=phases[2],
            burst_ordinal=3,
            burst_count=3,
            current_code=observation.applied_code,
            current_epoch=observation.dac_epoch,
        )

        response_observation = self._observation(
            timestamp_s=response_timestamp_s,
            source_first=response_source_last - 600,
            source_last=response_source_last,
            counts=0,
            phase=observation.relative_phase_cycles,
        )
        response_decision, response_hybrid, response_before = self._append_decision(
            response_observation, authority_state="AWAITING_RESPONSE"
        )
        if response_decision.reason != "response_pending_hold":
            raise RuntimeError("rehearsal response consumer did not remain held")
        response_hybrid.update(
            {
                "request_sequence": str(request_sequence),
                "acceptance_sequence": str(request_sequence),
                "application_sequence": str(application_sequence),
            }
        )
        response_decision_maintenance = self._maintenance_row(
            "decision",
            before=response_before,
            timestamp_ticks=response_observation.timestamp_ticks,
            reason=response_decision.reason,
            observation=response_observation,
            decision=response_decision,
            hybrid=response_hybrid,
            burst_ordinal=3,
            burst_count=3,
            current_code=self.controller.applied_code,
            current_epoch=self.controller.dac_epoch,
        )
        response_before_state = self._snapshot("before")
        self.controller.complete_response(fresh_exact=True)
        response_maintenance = self._maintenance_row(
            "response_complete",
            before=response_before_state,
            timestamp_ticks=int(phases[3]["event_timestamp_ticks"]),
            reason="response_completed",
            observation=observation,
            decision=decision,
            hybrid=hybrid,
            transaction=phases[3],
            burst_ordinal=3,
            burst_count=3,
            current_code=observation.applied_code,
            current_epoch=observation.dac_epoch,
        )
        return TransactionFixture(
            request_decision=hybrid,
            request_maintenance=request_maintenance,
            phases=phases,
            application_maintenance=application_maintenance,
            response_decision=response_hybrid,
            response_decision_maintenance=response_decision_maintenance,
            response_maintenance=response_maintenance,
        )

    def build(self) -> LifecycleFixture:
        setup = self.programme.setup_code
        # Physical setup is sampled at microsecond resolution and is not
        # expected to land exactly on a whole-second boundary.  Keep the
        # fixture shaped like that producer output so the host must validate
        # the declared floor-second projection rather than exact divisibility.
        setup_timestamp_ticks = 1_200 * RP2040_US + 71_551
        manual = {field: "" for field in ACTIVE_TRANSACTION_V3_FIELDS}
        manual.update(
            {
                "record_type": "ACT",
                "schema_version": "3",
                "transaction_record_sequence": "1",
                "event": "manual_start",
                "event_timestamp_ticks": str(setup_timestamp_ticks),
                "time_domain": "rp2040_monotonic_us64",
                "run_identity": self.programme.runtime_run_identity,
                "build_identity": str(self.runtime["firmware"]["build_identity"]),
                "image_identity": self.programme.profile_id,
                "session_id": "1",
                "authorization_sequence": "0",
                "nonce": "0",
                "request_sequence": "0",
                "decision_sequence": "0",
                "source_acceptance_epoch": "0",
                "source_opening_accepted_boundary_ordinal": "0",
                "source_closing_accepted_boundary_ordinal": "0",
                "decision_timestamp_s": "1200",
                "current_applied_code": str(setup),
                "requested_delta_codes": "0",
                "requested_code": str(setup),
                "correction_ordinal": "0",
                "cumulative_after_codes": "0",
                "pre_error_hz": "0.000000000000",
                "accepted_code": str(setup),
                "accepted_timestamp_s": "1200",
                "applied_code": str(setup),
                "application_sequence": "0",
                "application_timestamp_s": "1200",
                "i2c_ok": "true",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": "1",
                "estimator_history_reset": "false",
                "correction_count": "0",
                "cumulative_movement_codes": "0",
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "consecutive_indeterminate": "0",
                "active_state": "DISARMED",
                "response_class": "unavailable",
                "reason": "manual_start_established",
                "estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
                "model_sha256": self.bindings["plant_model"]["sha256"],
                "active_policy_sha256": self.policy.policy_sha256,
                "response_policy_sha256": self.bindings["response_classification"]["sha256"],
                "numerical_policy_sha256": self.policy.policy_sha256,
                "actionable": "false",
                "evidence_state": "evidence_clear",
            }
        )
        inactive = {
            **self._snapshot("before"),
            "maintenance_state_before": "POLICY_INACTIVE",
        }
        self.controller.new_policy_activation()
        activation = self._maintenance_row(
            "policy_activation",
            before=inactive,
            timestamp_ticks=setup_timestamp_ticks,
            reason="new_policy_activation",
            current_code=setup,
            current_epoch=1,
        )

        first = self._transaction(
            self._observation(
                timestamp_s=2701,
                source_first=2101,
                source_last=2701,
                counts=-1,
                phase=-6,
            ),
            first_record=2,
            request_sequence=1,
            application_sequence=1,
            response_timestamp_s=4202,
            response_source_last=4202,
        )

        hold_origin = self._observation(
            timestamp_s=4202,
            source_first=3602,
            source_last=4202,
            counts=0,
            phase=-6,
        )
        hold_before = self._snapshot("before")
        self.controller.enter_metadata_hold()
        metadata_hold = self._maintenance_row(
            "gnss_metadata_hold_enter",
            before=hold_before,
            timestamp_ticks=4_202 * RP2040_US + 300_000,
            reason="recoverable_gnss_metadata_anomaly",
            observation=hold_origin,
            hybrid=first.response_decision,
        )
        requalified_before = self._snapshot("before")
        self.controller.requalify_metadata(acceptance_epoch=1, accepted_boundary_ordinal=4202)
        metadata_requalified = self._maintenance_row(
            "gnss_metadata_requalified",
            before=requalified_before,
            timestamp_ticks=4_202 * RP2040_US + 400_000,
            reason="fresh_same_receiver_metadata",
            observation=hold_origin,
            hybrid=first.response_decision,
        )

        first_requalification_observation = self._observation(
            timestamp_s=4802,
            source_first=4202,
            source_last=4802,
            counts=3,
            phase=-3,
        )
        first_rq, first_rq_hybrid, first_rq_before = self._append_decision(
            first_requalification_observation, authority_state="REFERENCE_HOLD"
        )
        first_rq_maintenance = self._maintenance_row(
            "decision",
            before=first_rq_before,
            timestamp_ticks=first_requalification_observation.timestamp_ticks,
            reason=first_rq.reason,
            observation=first_requalification_observation,
            decision=first_rq,
            hybrid=first_rq_hybrid,
            burst_ordinal=2,
            burst_count=2,
        )

        second_requalification_observation = self._observation(
            timestamp_s=5402,
            source_first=4802,
            source_last=5402,
            counts=3,
            phase=0,
        )
        second_rq, second_rq_hybrid, second_rq_before = self._append_decision(
            second_requalification_observation, authority_state="REFERENCE_HOLD"
        )
        second_rq_maintenance = self._maintenance_row(
            "decision",
            before=second_rq_before,
            timestamp_ticks=second_requalification_observation.timestamp_ticks,
            reason=second_rq.reason,
            observation=second_requalification_observation,
            decision=second_rq,
            hybrid=second_rq_hybrid,
            burst_ordinal=2,
            burst_count=2,
        )
        if self.controller.metadata_hold:
            raise RuntimeError("rehearsal metadata hold did not causally clear")

        second = self._transaction(
            self._observation(
                timestamp_s=6302,
                source_first=5702,
                source_last=6302,
                counts=1,
                phase=6,
            ),
            first_record=6,
            request_sequence=2,
            application_sequence=2,
            response_timestamp_s=7803,
            response_source_last=7803,
        )
        return LifecycleFixture(
            manual_start=manual,
            policy_activation=activation,
            first_transaction=first,
            metadata_hold=metadata_hold,
            metadata_requalified=metadata_requalified,
            first_requalification_decision=first_rq_hybrid,
            first_requalification_maintenance=first_rq_maintenance,
            second_requalification_decision=second_rq_hybrid,
            second_requalification_maintenance=second_rq_maintenance,
            second_transaction=second,
        )


def build_lifecycle_fixture(runtime: dict[str, Any], programme: AdaptiveHybridProgramme) -> LifecycleFixture:
    """Return the deterministic current record choreography."""

    return _LifecycleBuilder(runtime, programme).build()


class DeterministicPtyInstrument:
    """Small firmware-shaped peer for the real capture/supervisor topology.

    This is intentionally not a firmware simulator.  It supplies deterministic
    records at each host protocol boundary so the host's process, FIFO,
    durability, replay, and ordering claims can be tested without physical I/O.
    """

    def __init__(self, master_fd: int, runtime: dict[str, Any], programme: AdaptiveHybridProgramme) -> None:
        self.master_fd = master_fd
        self.runtime = runtime
        self.programme = programme
        self.inputs = inputs = validate_authoritative_inputs(runtime["authoritative_inputs"])
        self.fixture = build_lifecycle_fixture(runtime, programme)
        self.reference_acceptance_binding = _reference_acceptance_binding(inputs)
        self.identities = {
            "run_identity": self.programme.runtime_run_identity,
            "build_identity": str(runtime["firmware"]["build_identity"]),
            "image_identity": self.programme.profile_id,
            "estimator_sha256": inputs.binding(
                inputs.document(ROOT_PROFILE)["bindings"]["frequency_estimator"],
            )["sha256"],
            "model_sha256": inputs.binding(
                inputs.document(ROOT_PROFILE)["bindings"]["plant_model"],
            )["sha256"],
            "active_policy_sha256": runtime["policy"]["policy_sha256"],
            "response_policy_sha256": inputs.binding(
                inputs.document(ROOT_PROFILE)["bindings"]["response_classification"],
            )["sha256"],
            "numerical_policy_sha256": runtime["policy"]["policy_sha256"],
        }
        self.stop_event = threading.Event()
        self.ready_for_obstruction = threading.Event()
        self.abort_observed = threading.Event()
        self.error: BaseException | None = None
        self.commands: list[str] = []
        self.generation = 0
        self.pps_snapshot_generation = 0
        self.status_sequence = 0
        self.latest_event_timestamp_ticks = 1200 * RP2040_US
        self.query_nonce = 1
        self.capture_lease_received = False
        self.setup = False
        self.selected_interval_count = 0
        self.transaction_index = 0
        self.evidence_phase = "evidence_clear"
        self.metadata_state = "normal"
        self.first_checkpoint = False
        self.raw_snapshot_sequence = 1
        self.accepted_boundary_ordinal = 1
        self.raw_reference_event_sequence = 1002
        self.raw_cumulative_down_counter = (0xFFFFFFFF - 10_000_000) % (1 << 32)
        self.estimate_sequence = 0
        self.control_sequence = 0
        source_decisions = (
            self.fixture.first_transaction.request_decision,
            self.fixture.first_transaction.response_decision,
            self.fixture.first_requalification_decision,
            self.fixture.second_requalification_decision,
            self.fixture.second_transaction.request_decision,
            self.fixture.second_transaction.response_decision,
        )
        self.raw_interval_adjustments = {
            int(row["source_closing_accepted_boundary_ordinal"]): int(
                row["accumulated_edge_error_counts"]
            )
            for row in source_decisions
        }
        self.raw_interval_adjustments.update({1600: -5, 5500: 5})
        self._lock = threading.RLock()
        self._timers: list[threading.Timer] = []

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, name="otis-pty-instrument")
        thread.start()
        return thread

    def stop(self) -> None:
        self.stop_event.set()
        for timer in self._timers:
            timer.cancel()

    def _later(self, delay_s: float, callback: Callable[[], None]) -> None:
        timer = threading.Timer(delay_s, callback)
        timer.daemon = True
        self._timers.append(timer)
        timer.start()

    def _emit_rows(self, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
        with self._lock:
            for row in rows:
                self.latest_event_timestamp_ticks = max(
                    self.latest_event_timestamp_ticks,
                    int(row.get("event_timestamp_ticks", row.get("decision_timestamp_ticks", "0"))),
                )
                _write_all_fd(self.master_fd, _wire_row(fields, row))

    def _emit_late_attach_boot_preamble(self) -> None:
        lines = (
            (
                "=0x00000000,wd_s1=0x00000000,wd_s2=0x0000000a,"
                "wd_s3=0x00010100,wd_s4=0x00000000,wd_s5=0x4ff824a4,"
                "wd_s6=0x20042000,wd_s7=0x00001b89,"
                "resets_reset=0x00000000,resets_done=0x01ffffff,"
                "clk_ref_ctrl=0x00000002,clk_ref_div=0x00000100,"
                "clk_sys_ctrl=0x00000001,clk_sys_div=0x00000100,"
                "clk_peri_ctrl=0x00000840,clk_peri_div=0x00000000,"
                "xosc_status=0x81001001,rosc_status=0x81011000,"
                "rosc_ctrl=0x00fab000,pll_sys_cs=0x80000001,"
                "pll_usb_cs=0x80000001,vreg=0x000010b1,bod=0x00000091,"
                "chip_id=0x20002927,platform=0x00000002,"
                "gitref_rp2040=0xe0c912e8"
            ),
            "BOOT_WARN,v=1,key=serial_absent,wait_ms=250",
            (
                "BOOTDIAG,v=1,wd_reason=0x00000001,wd_s0=0x00000000,"
                "wd_s1=0x00000000,wd_s2=0x0000000a,wd_s3=0x00010100,"
                "wd_s4=0x00000000,wd_s5=0x4ff824a4,wd_s6=0x20042000,"
                "wd_s7=0x00001b89,resets_reset=0x00000000,"
                "resets_done=0x01ffffff,clk_ref_ctrl=0x00000002,"
                "clk_ref_div=0x00000100,clk_sys_ctrl=0x00000001,"
                "clk_sys_div=0x00000100,clk_peri_ctrl=0x00000840,"
                "clk_peri_div=0x00000000,xosc_status=0x81001001,"
                "rosc_status=0x81011000,rosc_ctrl=0x00fab000,"
                "pll_sys_cs=0x80000001,pll_usb_cs=0x80000001,"
                "vreg=0x000010b1,bod=0x00000091,chip_id=0x20002927,"
                "platform=0x00000002,gitref_rp2040=0xe0c912e8"
            ),
        )
        with self._lock:
            _write_all_fd(
                self.master_fd,
                ("\r\n".join(lines) + "\r\n").encode("ascii"),
            )

    def _emit_nonactive_health(self) -> None:
        self._emit_provenance_health()
        prewrite = canonical_prewrite_fixture(
            expected_identity=self.identities,
            planned_live_stimulus_code=self.programme.setup_code,
        )
        health = {
            **GNSS_PREWRITE_EXACT,
            **HEALTH_INTEGRITY_EXACT,
            **FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH,
            **{
                key: value
                for key, value in prewrite.items()
                if key[0] == "dac"
            },
            ("forwarded_clock_output", "first_valid_ticks"): "1000000",
            ("forwarded_clock_monitor", "state"): "diagnostic_only",
            ("forwarded_clock_monitor", "configured"): "true",
            ("forwarded_clock_monitor", "running"): "true",
            ("forwarded_clock_monitor", "session"): "1",
            ("forwarded_clock_monitor", "snapshot_count"): "1",
            ("forwarded_clock_monitor", "no_snapshot_count"): "0",
            ("forwarded_clock_monitor", "fifo_backlog_count"): "0",
            ("forwarded_clock_monitor", "pio_rxstall_count"): "0",
            ("forwarded_clock_monitor", "fault_flags"): "0",
        }
        self._emit_health_map(health)

    def _emit_provenance_health(self) -> None:
        firmware = self.runtime["firmware"]
        if firmware.get("build_provenance_required") is not True:
            return
        provenance = firmware.get("provenance")
        if not isinstance(provenance, dict):
            raise TypeError("runtime firmware provenance is missing")
        source = provenance["source"]
        configuration = provenance["configuration"]
        target = provenance["target"]
        toolchain = provenance["toolchain"]
        invocation = provenance["invocation"]
        items = [
            (("build", "provenance_format"), "otis_fixed_firmware_build_v1"),
            (("firmware", "audit_revision"), str(provenance["firmware_audit_revision"])),
            (("firmware", "source_state"), str(source["state"])),
            (("firmware", "source_hash"), str(source["sha256"])),
            (("firmware", "config_hash"), str(configuration["sha256"])),
            (("system", "board"), str(target["board_id"])),
            (("system", "board_name"), str(target["board_name"])),
            (("system", "fqbn"), str(target["fqbn"])),
            (("system", "arduino_core_provider"), str(target["core_provider"])),
            (("system", "arduino_core_version"), str(target["core_version"])),
            (("system", "arduino_core_installed_hash"), str(target["core_installed_sha256"])),
            (("build", "image_id"), str(configuration["image_id"])),
            (("build", "toolchain"), f"{toolchain['name']}@{toolchain['version']}"),
            (("build", "compiler"), str(toolchain["compiler_identity"])),
            (("build", "toolchain_installed_hash"), str(toolchain["installed_sha256"])),
            (("build", "arduino_cli_version"), str(invocation["arduino_cli_version"])),
            (("build", "invocation_id"), str(invocation["id"])),
        ]
        self._emit_health_items(items)

    def _active_health(self) -> dict[tuple[str, str], str]:
        health = canonical_prewrite_fixture(
            expected_identity=self.identities,
            planned_live_stimulus_code=self.programme.setup_code,
        )
        active = {
            key: value
            for (component, key), value in health.items()
            if component == "adaptive_hybrid"
        }
        active.update(
            {
                "query_nonce": str(self.query_nonce),
                "capture_lease_live": str(self.capture_lease_received).lower(),
                "uptime_s": str(max(1200, self.accepted_boundary_ordinal)),
                "gnss_metadata_hold_active": "false",
                "gnss_metadata_hold_transaction_pending": "false",
                "gnss_metadata_hold_entry_sequence": "0",
                "gnss_metadata_requalification_sequence": "0",
                "gnss_qualified_accepted_ordinal": "0",
                "accepted_boundary_ordinal": str(self.accepted_boundary_ordinal),
                "acceptance_epoch": "1",
                "accepted_anchor_current": "true",
                "reference_acceptance_state": "tracking",
                "reference_acceptance_policy_sha256": self.reference_acceptance_binding["policy_sha256"],
                "hybrid_state": "SETUP_PENDING",
                "hybrid_reason": "setup_consumers_pending",
                "first_phase_checkpoint_passed": "false",
                "phase_nonzero_application_count": "0",
                "phase_material_application_count": "0",
                "frequency_only_application_count": "0",
            }
        )
        if self.abort_observed.is_set():
            # Zero-write runs have no SETUP branch to overwrite these fields;
            # publish the same complete fail-static terminal snapshot either way.
            active.update({
                "state": "ABORTED", "reason": "host_abort", "fail_static": "true",
                "hybrid_state": "FAIL_STATIC", "hybrid_reason": "host_abort",
                "arm_eligible": "false", "evidence_pending": "false",
                "evidence_phase": "evidence_clear", "evidence_request_sequence": "0",
            })
        if self.setup:
            applied_count = self._applied_transaction_count()
            active.update(
                {
                    "manual_start_confirmed": "true",
                    "confirmed_applied_code_known": "true",
                    "confirmed_applied_code": str(self._applied_code()),
                    "dac_epoch": str(1 + applied_count),
                    "correction_count": str(applied_count),
                    "cumulative_movement_codes": str(6 * applied_count),
                    "selected_interval_count": str(self.selected_interval_count),
                    "state": self._active_state(),
                    "reason": self._active_reason(),
                    "hybrid_state": self._hybrid_state(),
                    "hybrid_reason": "deterministic_rehearsal_fixture",
                    "evidence_pending": str(
                        self.evidence_phase != "evidence_clear"
                    ).lower(),
                    "evidence_phase": self.evidence_phase,
                    "evidence_request_sequence": str(
                        self.transaction_index
                        if self.evidence_phase != "evidence_clear"
                        else 0
                    ),
                    "arm_eligible": str(
                        self.metadata_state in {"normal", "requalified"}
                        and self.evidence_phase == "evidence_clear"
                        and self.selected_interval_count >= 520
                        and self.transaction_index < 2
                    ).lower(),
                    "setup_gnss_eligible": str(
                        self.metadata_state != "hold"
                    ).lower(),
                    "gnss_metadata_hold_active": str(
                        self.metadata_state == "hold"
                    ).lower(),
                    "gnss_metadata_hold_transaction_pending": "false",
                    "gnss_metadata_hold_entry_sequence": (
                        "1" if self.metadata_state in {"hold", "requalified"} else "0"
                    ),
                    "gnss_metadata_requalification_sequence": (
                        "2" if self.metadata_state == "requalified" else "0"
                    ),
                    "gnss_qualified_accepted_ordinal": (
                        "4202" if self.metadata_state == "requalified" else "0"
                    ),
                    "accepted_boundary_ordinal": (
                        str(self.accepted_boundary_ordinal)
                    ),
                    "first_phase_checkpoint_passed": str(
                        self.first_checkpoint
                    ).lower(),
                    "phase_nonzero_application_count": str(applied_count),
                    "phase_material_application_count": str(applied_count),
                    "frequency_only_application_count": "0",
                    "uptime_s": str(max(1200, self.accepted_boundary_ordinal)),
                }
            )
            health[("dac", "applied_code_known")] = "true"
            health[("dac", "last_write_ok")] = "true"
            health[("dac", "last_applied_code")] = str(self._applied_code())
        return {
            **{
                key: value
                for key, value in health.items()
                if key[0] != "adaptive_hybrid"
            },
            **{("adaptive_hybrid", key): value for key, value in active.items()},
        }

    def _applied_transaction_count(self) -> int:
        if self.evidence_phase in {"request_pending", "acceptance_pending"}:
            return max(0, self.transaction_index - 1)
        return self.transaction_index

    def _applied_code(self) -> int:
        applied_count = self._applied_transaction_count()
        if applied_count == 0:
            return self.programme.setup_code
        transaction = (
            self.fixture.first_transaction
            if applied_count == 1
            else self.fixture.second_transaction
        )
        return int(transaction.phases[2]["applied_code"])

    def _active_state(self) -> str:
        if self.abort_observed.is_set():
            return "ABORTED"
        if self.metadata_state == "hold":
            return "GNSS_METADATA_HOLD"
        return "DISARMED" if self.evidence_phase == "evidence_clear" else {
            "request_pending": "REQUEST_PENDING",
            "acceptance_pending": "ACCEPTED_AWAITING_APPLICATION",
            "application_pending": "AWAITING_RESPONSE",
            "response_pending": "DISARMED",
        }[self.evidence_phase]

    def _active_reason(self) -> str:
        if self.abort_observed.is_set():
            return "host_abort"
        if self.metadata_state == "hold":
            return "recoverable_gnss_metadata_anomaly"
        return "deterministic_rehearsal_fixture"

    def _hybrid_state(self) -> str:
        if self.abort_observed.is_set():
            return "FAIL_STATIC"
        if self.evidence_phase != "evidence_clear":
            return "FIRST_PHASE_TRANSACTION"
        if self.transaction_index == 0:
            return "PHASE_QUALIFY"
        return "HYBRID_TRACKING"

    def _emit_health_items(self, health: Iterable[tuple[tuple[str, str], str]]) -> None:
        with self._lock:
            rows: list[dict[str, str]] = []
            for (component, key), value in health:
                self.status_sequence += 1
                rows.append(
                    {
                        "record_type": "STS",
                        "schema_version": "1",
                        "status_seq": str(self.status_sequence),
                        "timestamp_ticks": str(max(self.latest_event_timestamp_ticks, self.accepted_boundary_ordinal * RP2040_US) % (1 << 32)),
                        "status_domain": "rp2040_monotonic_us32",
                        "component": component,
                        "status_key": key,
                        "status_value": value,
                        "severity": "INFO",
                        "flags": "0",
                    }
                )
            self._emit_rows(CONTRACT_FIELDS["health_v1"], rows)

    def _emit_health_map(self, health: dict[tuple[str, str], str]) -> None:
        self._emit_health_items((key, health[key]) for key in sorted(health))

    def _emit_idle_wakeup(self) -> None:
        # Timer callbacks publish complete record groups from separate threads.
        # Serialize the otherwise empty carrier wake-up with those groups so it
        # can never split a decision-bearing record in the PTY byte stream.
        with self._lock:
            _write_all_fd(self.master_fd, b"\n")

    def _pps_health(self) -> dict[tuple[str, str], str]:
        return {
            **{("pps_gate", key): "0" for key in _authoritative_capture_counters(self.programme)},
            ("pps_gate", "boundary_owner"): "pio_state_machine",
            ("pps_gate", "aperture_backend"): "pio_wait_cumulative_snapshot_dma_v1",
            ("pps_gate", "backend_qualified"): "true",
            ("pps_gate", "boundary_ring_capacity"): "127",
            ("pps_gate", "snapshot_session"): "1",
            ("pps_gate", "reference_acceptance_epoch"): "1",
            ("pps_gate", "reference_acceptance_last_loss_reason"): "none",
            ("pps_gate", "accepted_boundary_ordinal"): str(self.accepted_boundary_ordinal),
            ("pps_gate", "accepted_anchor_timestamp_ticks"): str(
                max(
                    self.latest_event_timestamp_ticks,
                    self.accepted_boundary_ordinal * RP2040_US,
                )
                % (1 << 32)
            ),
            ("pps_gate", "reference_acceptance_policy_sha256"): self.reference_acceptance_binding["policy_sha256"],
            ("pps_gate", "reference_acceptance_state"): "tracking",
            ("pps_gate", "accepted_anchor_current"): "true",
            ("pps_gate", "fifo_continuity"): "continuous",
            ("pps_gate", "association_state"): "clean",
        }

    def _emit_config_reply(self) -> None:
        # Representative core-0 CONFIG? records. Timing configuration belongs
        # to core 1 and must not be copied into this independently emitted group.
        self._emit_health_items([
            (("command", "config_snapshot"), "begin"),
            (("dual_core", "pre_carrier_records_discarded"), "0"),
            (("build", "tcxo_counter_backend"), "d14_gated_d8_snapshot"),
            (("command", "config_snapshot"), "end"),
            (("command", "timing_config_snapshot"), "queued_to_core1"),
        ])

    def _emit_interleaved_status(self, items: list[tuple[tuple[str, str], str]]) -> None:
        # Core-0 command replies can interrupt drainage of a core-1 cohort at
        # complete-record boundaries. Force that legal order on every rehearsal
        # snapshot instead of hoping a short PTY run happens to encounter it.
        split = len(items) // 2
        self._emit_health_items(items[:split])
        self._emit_config_reply()
        self._emit_health_items(items[split:])

    def _emit_pps_snapshot(self) -> None:
        self.pps_snapshot_generation += 1
        health = self._pps_health()
        ordered = [
            (("pps_gate", "snapshot"), "begin"),
            (
                ("pps_gate", "snapshot_generation"),
                str(self.pps_snapshot_generation),
            ),
            *((key, health[key]) for key in sorted(health)),
            (("pps_gate", "snapshot"), "end"),
        ]
        self._emit_interleaved_status(ordered)

    def _emit_snapshot(self) -> None:
        with self._lock:
            # A solicited ACTIVE reply can precede the first periodic PPS
            # diagnostics on real firmware. Exercise that startup order through
            # the actual carrier, reducer and census, not an all-ready fixture.
            if self.generation > 0:
                self._emit_pps_snapshot()
            self.generation += 1
            active = {
                key: value
                for (component, key), value in self._active_health().items()
                if component == "adaptive_hybrid"
            }
            ordered: list[tuple[str, str]] = [
                (SNAPSHOT_BEGIN_KEY, str(self.generation)),
                (SNAPSHOT_CONTRACT_KEY, ACTIVE_STATUS_SNAPSHOT_CONTRACT),
                *((key, active[key]) for key in ACTIVE_STATUS_KEYS),
                (SNAPSHOT_COMPLETE_KEY, str(self.generation)),
            ]
            self._emit_interleaved_status([
                (("adaptive_hybrid", key), value) for key, value in ordered
            ])

    def _emit_initial_observations(self) -> None:
        # The first SNP/REF is an anchor; only its adjacent successor produces
        # CNT. The live capture observer freezes this earliest complete pair
        # before the supervisor can submit SETUP.
        self._emit_rows(
            CONTRACT_FIELDS["raw_events_v1"],
            [{
                "record_type": "EVT", "schema_version": "1", "event_seq": "1000",
                "channel_id": "0", "edge": "R", "timestamp_ticks": "0",
                "capture_domain": "rp2040_monotonic_us32", "flags": "0",
            }] + [{
                "record_type": "REF", "schema_version": "1", "event_seq": str(1001 + sequence),
                "channel_id": "1", "edge": "R", "timestamp_ticks": str(sequence * 1_000_000),
                "capture_domain": "rp2040_monotonic_us32", "flags": "16",
            } for sequence in range(2)],
        )
        self._emit_rows(
            CONTRACT_FIELDS["pps_snapshots_v1"],
            [{
                "record_type": "SNP", "schema_version": "1", "session": "1",
                "snapshot_sequence": str(sequence),
                "cumulative_down_counter": str(0xFFFFFFFF - sequence * 10_000_000),
                "reference_sequence": str(sequence),
                "reference_timestamp_ticks": str(sequence * 1_000_000),
                "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1",
            } for sequence in range(2)],
        )
        self._emit_rows(
            CONTRACT_FIELDS["count_observations_v1"],
            [{
                "record_type": "CNT", "schema_version": "1", "count_seq": "1",
                "channel_id": "2", "gate_open_ticks": "0", "gate_close_ticks": "1000000",
                "gate_domain": "rp2040_monotonic_us32", "counted_edges": "10000000",
                "source_edge": "R", "source_domain": "h1_oscillator_10mhz", "flags": "16",
            }],
        )

        self._emit_rows(CONTRACT_FIELDS["accepted_pps_spans_v1"], [self._accepted_span(1)])

    @staticmethod
    def _source_ticks(accepted_ordinal: int) -> int:
        return (accepted_ordinal * RP2040_US) % (1 << 32)

    @staticmethod
    def _raw_sequence(accepted_ordinal: int) -> int:
        # One retained early candidate occurs inside accepted span 1500.
        return accepted_ordinal + int(accepted_ordinal >= 1500)

    def _accepted_span(self, ordinal: int) -> dict[str, str]:
        opening = self._raw_sequence(ordinal - 1)
        closing = self._raw_sequence(ordinal)
        return {
            "record_type": "APS", "schema_version": "1",
            "capture_session": "1", "acceptance_epoch": "1",
            "accepted_boundary_ordinal": str(ordinal),
            "opening_snapshot_sequence": str(opening),
            "closing_snapshot_sequence": str(closing),
            "opening_reference_sequence": str(opening),
            "closing_reference_sequence": str(closing),
            "opening_reference_timestamp_ticks": str(self._source_ticks(ordinal - 1)),
            "closing_reference_timestamp_ticks": str(self._source_ticks(ordinal)),
            "time_domain": "rp2040_monotonic_us32",
            "source_count_first_sequence": str(opening + 1),
            "source_count_last_sequence": str(closing),
            "source_count_record_count": str(closing - opening),
            "counted_edges": str(10_000_000 + self.raw_interval_adjustments.get(ordinal, 0)),
            "excluded_candidate_count": str(closing - opening - 1),
            "nominal_interval_count": "1",
            "acceptance_policy_sha256": self.reference_acceptance_binding["policy_sha256"],
        }

    def _emit_source_through(self, target_sequence: int) -> None:
        """Retain every raw pair and derived accepted span, including exclusion."""
        if target_sequence < self.accepted_boundary_ordinal:
            raise RuntimeError("rehearsal accepted source cannot move backwards")
        payload = bytearray()
        while self.accepted_boundary_ordinal < target_sequence:
            ordinal = self.accepted_boundary_ordinal + 1
            opening_ticks = self._source_ticks(ordinal - 1)
            fragments = (
                [(self._source_ticks(1499) + 246294, 2462937, 4120),
                 (self._source_ticks(1500), 7537063, 4120)]
                if ordinal == 1500 else
                [(self._source_ticks(ordinal),
                  10_000_000 + self.raw_interval_adjustments.get(ordinal, 0),
                  4120 if ordinal == 1501 else 16)]
            )
            for closing_ticks, counted_edges, flags in fragments:
                self.raw_snapshot_sequence += 1
                self.raw_reference_event_sequence += 1
                self.raw_cumulative_down_counter = (
                    self.raw_cumulative_down_counter - counted_edges
                ) % (1 << 32)
                sequence = self.raw_snapshot_sequence
                for contract, row in (
                    ("raw_events_v1", {
                        "record_type": "REF", "schema_version": "1",
                        "event_seq": str(self.raw_reference_event_sequence),
                        "channel_id": "1", "edge": "R", "timestamp_ticks": str(closing_ticks),
                        "capture_domain": "rp2040_monotonic_us32", "flags": "16",
                    }),
                    ("pps_snapshots_v1", {
                        "record_type": "SNP", "schema_version": "1", "session": "1",
                        "snapshot_sequence": str(sequence),
                        "cumulative_down_counter": str(self.raw_cumulative_down_counter),
                        "reference_sequence": str(sequence), "reference_timestamp_ticks": str(closing_ticks),
                        "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1",
                    }),
                    ("count_observations_v1", {
                        "record_type": "CNT", "schema_version": "1", "count_seq": str(sequence),
                        "channel_id": "2", "gate_open_ticks": str(opening_ticks),
                        "gate_close_ticks": str(closing_ticks), "gate_domain": "rp2040_monotonic_us32",
                        "counted_edges": str(counted_edges), "source_edge": "R",
                        "source_domain": "h1_oscillator_10mhz", "flags": str(flags),
                    }),
                ):
                    payload.extend(_wire_row(CONTRACT_FIELDS[contract], row))
                opening_ticks = closing_ticks
            payload.extend(_wire_row(CONTRACT_FIELDS["accepted_pps_spans_v1"], self._accepted_span(ordinal)))
            self.accepted_boundary_ordinal = ordinal
        if payload:
            with self._lock:
                _write_all_fd(self.master_fd, bytes(payload))

    def _emit_selected_estimate(self, decision: dict[str, str]) -> dict[str, str]:
        first = int(decision["source_opening_accepted_boundary_ordinal"])
        last = int(decision["source_closing_accepted_boundary_ordinal"])
        accumulated = int(decision["accumulated_edge_error_counts"])
        selected_frequency = float(600 * 10_000_000 + accumulated) / 600.0
        frequency_error = selected_frequency - 10_000_000.0
        estimate_id = f"rehearsal:selected:{self.estimate_sequence}"
        row = {field: "" for field in CONTRACT_FIELDS["estimates_v3"]}
        row.update(
            {
                "record_type": "EST",
                "schema_version": "3",
                "estimate_seq": str(self.estimate_sequence),
                "estimate_id": estimate_id,
                "estimator_timestamp_ticks": str(self._source_ticks(last)),
                "time_domain": "rp2040_monotonic_us32",
                "capture_session": "1",
                "source_acceptance_epoch": "1",
                "source_opening_accepted_boundary_ordinal": str(first),
                "source_closing_accepted_boundary_ordinal": str(last),
                "source_opening_snapshot_sequence": str(self._raw_sequence(first)),
                "source_closing_snapshot_sequence": str(self._raw_sequence(last)),
                "source_opening_reference_sequence": str(self._raw_sequence(first)),
                "source_closing_reference_sequence": str(self._raw_sequence(last)),
                "source_accepted_spans_ref": f"live:APS:1:1:{first}:{last}",
                "source_status_refs": f"live:SNP:{self._raw_sequence(first)}:{self._raw_sequence(last)}",
                "source_dac_ref": f"live:DAC:{decision['dac_epoch']}",
                "manifest_ref": "run_manifest",
                "estimator_version": "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1",
                "config_hash": self.identities["estimator_sha256"],
                "observation_validity": "valid",
                "observation_reason_codes": "complete_selected_window",
                "reference_validity": "valid",
                "reference_age_s": "0",
                "reference_continuity": "true",
                "count_validity": "valid",
                "count_age_s": "0",
                "count_continuity": "true",
                "diagnostic_health": "healthy",
                "diagnostic_reason_codes": "none",
                "frequency_observation_hz": f"{selected_frequency:.12f}",
                "accepted_sample_count": "600",
                "estimator_confidence": "high",
                "frequency_estimate_hz": f"{selected_frequency:.12f}",
                "frequency_error_hz": f"{frequency_error:.12f}",
                "dispersion_hz": "0.000000000000",
                "uncertainty_status": "unavailable",
                "uncertainty_reason_codes": "uncertainty_model_unavailable",
                "correlation_policy": "not_combined_missing_components",
                "uncertainty_model_ref": "unavailable:rehearsal_fixture",
                "drift_enabled": "false",
                "preview_eligibility": "true",
                "eligibility_reason_codes": "eligible",
            }
        )
        self.estimate_sequence += 1
        self._emit_rows(CONTRACT_FIELDS["estimates_v3"], [row])
        self._emit_phase_source(decision)
        return row

    def _emit_phase_source(self, decision: dict[str, str]) -> None:
        ordinal = int(decision["source_closing_accepted_boundary_ordinal"])
        span = self._accepted_span(ordinal)
        phase_sequence = ordinal - 1200
        # Phase opens at setup. Every adjustment since then is retained in raw APS.
        phase = sum(delta for closing, delta in self.raw_interval_adjustments.items()
                    if 1200 < closing <= ordinal)
        if phase != int(decision["relative_phase_cycles"]):
            raise RuntimeError("rehearsal phase differs from retained cumulative D8 counts")
        phase_hash = self.inputs.binding(self.inputs.document(ROOT_PROFILE)["bindings"]["phase_estimator"])["sha256"]
        row = {
            "record_type": "RPH", "schema_version": "2", "phase_epoch": "1",
            "observation_sequence": str(phase_sequence), "capture_session": "1",
            "acceptance_epoch": "1", "accepted_boundary_ordinal": str(ordinal),
            "source_accepted_span_ref": f"live:APS:1:1:{ordinal}",
            **{key: span[key] for key in ("opening_snapshot_sequence", "closing_snapshot_sequence",
                                         "opening_reference_sequence", "closing_reference_sequence")},
            "dac_epoch": decision["dac_epoch"],
            "source_backend": "pio_wait_cumulative_snapshot_dma_v1",
            "source_file_sha256": "live_stream_unsealed",
            "method_id": "D14_ACCEPTED_SPAN_RELATIVE_PHASE_ACCUMULATOR_V1",
            "configuration_sha256": phase_hash,
            "interval_edges": span["counted_edges"],
            "edge_error_cycles": str(int(span["counted_edges"]) - 10_000_000),
            "relative_phase_cycles": str(phase), "relative_phase_time_ns": str(phase * 100),
            "qualification_state": "qualified", "observation_age_s": "0",
            "discontinuity_reason": "", "calibrated_uncertainty_status": "unavailable",
        }
        self._emit_rows(CONTRACT_FIELDS["relative_phase_observations_v2"], [row])
        # The existing phase estimator retains a 600-span endpoint slope at
        # its own 600-span output cadence. DAC changes reset that support only.
        dac_epoch = int(decision["dac_epoch"])
        support_origin = (1200 if dac_epoch == 1 else
            int((self.fixture.first_transaction if dac_epoch == 2 else
                 self.fixture.second_transaction).phases[2]["application_timestamp_s"]) + 1)
        frequency_closing = support_origin + ((ordinal - support_origin) // 600) * 600
        frequency_error = sum(delta for closing, delta in self.raw_interval_adjustments.items()
                              if frequency_closing - 600 < closing <= frequency_closing) / 600.0
        self._emit_rows(CONTRACT_FIELDS["phase_estimator_outputs_v2"], [{
            "record_type": "PHE", "schema_version": "2", "phase_epoch": "1",
            "observation_sequence": str(phase_sequence), "capture_session": "1",
            "acceptance_epoch": "1", "accepted_boundary_ordinal": str(ordinal),
            "source_relative_phase_observation": f"RPH:1:{phase_sequence}",
            "raw_relative_phase_cycles": str(phase), "raw_relative_phase_time_ns": str(phase * 100),
            "filtered_relative_phase_cycles": str(phase),
            "estimated_frequency_error_hz": f"{frequency_error:.12f}",
            "estimator_id": "OTIS_RELATIVE_PHASE_ESTIMATOR_V1", "configuration_sha256": phase_hash,
            "estimate_age_s": str(ordinal - frequency_closing), "qualification_state": "qualified",
            "uncertainty_status": "unavailable", "reason_codes": ("frequency_estimate_fresh" if ordinal == frequency_closing else "frequency_estimate_retained"),
        }])

    def _emit_control_preview(
        self, estimate: dict[str, str], decision: dict[str, str]
    ) -> None:
        self.control_sequence += 1
        current_code = int(decision["current_applied_code"])
        requested_delta = int(decision["requested_delta_codes"])
        row = {
            "record_type": "CTL",
            "schema_version": "1",
            "control_seq": str(self.control_sequence),
            "decision_id": f"rehearsal:control:{self.control_sequence}",
            "decision_timestamp_ticks": estimate["estimator_timestamp_ticks"],
            "time_domain": "rp2040_monotonic_us32",
            "est_input_ref": estimate["estimate_id"],
            "plant_model_ref": "model:pps_gated_oscillator_plant_v1",
            "plant_model_id": "OTIS_PPS_GATED_OSCILLATOR_PLANT_V1",
            "plant_model_version": "1",
            "plant_model_hash": self.identities["model_sha256"],
            "policy_version": self.programme.programme_id,
            "config_hash": self.identities["active_policy_sha256"],
            "control_state": "LOCKED_PREVIEW",
            "previous_control_state": "LOCKED_PREVIEW",
            "state_transition": "false",
            "transition_reason_code": "selected_estimate_complete",
            "preview_eligibility": "true",
            "eligibility_reason_codes": "eligible",
            "diagnostic_health": "healthy",
            "model_applicability": "applicable",
            "model_reason_codes": "model_applicable",
            "current_dac_code": str(current_code),
            "frequency_error_hz": estimate["frequency_error_hz"],
            "hz_per_code": "0.000170084677",
            "raw_delta_codes": str(requested_delta),
            "limited_delta_codes": str(requested_delta),
            "proposed_dac_code": str(current_code + requested_delta),
            "step_limited": "false",
            "range_clamped": "false",
            "preview_available": "true",
            "preview_only": "true",
            "actuation_authorized": "false",
            "actionable": "false",
            "decision_reason_code": "eligible_preview",
        }
        self._emit_rows(CONTRACT_FIELDS["control_previews_v1"], [row])

    def _enter_hold(self) -> None:
        if self.stop_event.is_set() or self.transaction_index != 1:
            return
        self.metadata_state = "hold"
        self._emit_rows(
            ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS, [self.fixture.metadata_hold]
        )
        self._emit_snapshot()
        # Retain the anomaly state long enough for the real supervisor loop to
        # consume it before publishing the causally later qualification.
        self._later(2.5, self._requalify)

    def _requalify(self) -> None:
        if self.stop_event.is_set():
            return
        self.metadata_state = "requalified"
        self.selected_interval_count = 0
        for decision in (
            self.fixture.first_requalification_decision,
            self.fixture.second_requalification_decision,
        ):
            self._emit_source_through(int(decision["source_closing_accepted_boundary_ordinal"]))
            estimate = self._emit_selected_estimate(decision)
            self._emit_control_preview(estimate, decision)
        next_decision = self.fixture.second_transaction.request_decision
        self._emit_source_through(int(next_decision["source_closing_accepted_boundary_ordinal"]))
        estimate = self._emit_selected_estimate(next_decision)
        self._emit_control_preview(estimate, next_decision)
        self._emit_rows(
            ACTIVE_HYBRID_DECISION_V3_FIELDS,
            [
                self.fixture.first_requalification_decision,
                self.fixture.second_requalification_decision,
            ],
        )
        self._emit_rows(
            ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS,
            [
                self.fixture.metadata_requalified,
                self.fixture.first_requalification_maintenance,
                self.fixture.second_requalification_maintenance,
            ],
        )
        self._emit_snapshot()
        # Keep this complete low-progress generation visible across at least
        # one genuine supervisor polling cycle.  Advancing immediately to 600
        # would let the live-health reducer replace the reset generation before
        # the supervisor can latch the fresh arm-progress epoch.
        self._later(2.5, self._make_armable)

    def _make_armable(self) -> None:
        if self.stop_event.is_set():
            return
        self.selected_interval_count = 600
        self._emit_snapshot()

    def _handle_command(self, command: str) -> None:
        self.commands.append(command)
        if command in {"CONFIG?", "DUALCORE?", "DAC?"}:
            if command == "CONFIG?":
                self._emit_config_reply()
            self._emit_nonactive_health()
            return
        if command.startswith("ACTIVE LEASE "):
            self.capture_lease_received = True
            return
        if command.startswith("ACTIVE SNAPSHOT "):
            self.query_nonce = int(command.rsplit(" ", 1)[1])
            self._emit_snapshot()
            if self.transaction_index == 2 and self.evidence_phase == "evidence_clear":
                self.ready_for_obstruction.set()
            return
        if command.startswith("ACTIVE SETUP "):
            if self.setup:
                raise RuntimeError("deterministic fixture received duplicate setup")
            self.setup = True
            self.selected_interval_count = 0
            self._emit_rows(
                ACTIVE_TRANSACTION_V3_FIELDS, [self.fixture.manual_start]
            )
            self._emit_rows(
                ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS,
                [self.fixture.policy_activation],
            )
            decision = self.fixture.first_transaction.request_decision
            self._emit_source_through(int(decision["source_closing_accepted_boundary_ordinal"]))
            estimate = self._emit_selected_estimate(decision)
            self._emit_control_preview(estimate, decision)
            self._emit_snapshot()
            # The real supervisor must first consume this low-progress setup
            # generation before the same epoch becomes armable at 600.
            self._later(2.5, self._make_armable)
            return
        if command.startswith("ACTIVE ARM "):
            if self.evidence_phase != "evidence_clear" or self.transaction_index >= 2:
                raise RuntimeError("deterministic fixture received impossible arm")
            self.transaction_index += 1
            self.selected_interval_count = 0
            self.first_checkpoint = False
            self.evidence_phase = "request_pending"
            transaction = (
                self.fixture.first_transaction
                if self.transaction_index == 1
                else self.fixture.second_transaction
            )
            self._emit_rows(ACTIVE_HYBRID_DECISION_V3_FIELDS, [transaction.request_decision])
            self._emit_rows(ACTIVE_TRANSACTION_V3_FIELDS, [transaction.phases[0]])
            self._emit_rows(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS, [transaction.request_maintenance])
            self._emit_snapshot()
            return
        if command.startswith("ACTIVE EVIDENCE "):
            fields = command.split()
            request, phase = int(fields[2]), int(fields[3])
            if request != self.transaction_index:
                raise RuntimeError("deterministic evidence request identity changed")
            expected = {
                1: "request_pending",
                2: "acceptance_pending",
                3: "application_pending",
                4: "response_pending",
            }[phase]
            if self.evidence_phase != expected:
                raise RuntimeError("deterministic evidence phase order changed")
            self.evidence_phase = {
                1: "acceptance_pending",
                2: "application_pending",
                3: "response_pending",
                4: "evidence_clear",
            }[phase]
            transaction = (self.fixture.first_transaction if request == 1
                           else self.fixture.second_transaction)
            if phase == 1:
                self._emit_rows(ACTIVE_TRANSACTION_V3_FIELDS, [transaction.phases[1]])
            elif phase == 2:
                self._emit_rows(ACTIVE_TRANSACTION_V3_FIELDS, [transaction.phases[2]])
                self._emit_rows(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS, [transaction.application_maintenance])
            elif phase == 3:
                response = transaction.response_decision
                self._emit_source_through(int(response["source_closing_accepted_boundary_ordinal"]))
                estimate = self._emit_selected_estimate(response)
                self._emit_control_preview(estimate, response)
                self._emit_rows(ACTIVE_HYBRID_DECISION_V3_FIELDS, [response])
                self._emit_rows(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS, [transaction.response_decision_maintenance])
                self._emit_rows(ACTIVE_TRANSACTION_V3_FIELDS, [transaction.phases[3]])
                self._emit_rows(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS, [transaction.response_maintenance])
            if phase == 4:
                self.first_checkpoint = True
            self._emit_snapshot()
            if phase == 4 and self.transaction_index == 1:
                self._later(0.5, self._enter_hold)
            return
        if command == "ACTIVE ABORT":
            self.abort_observed.set()
            self._emit_snapshot()
            return
        if command == "ACTIVE?":
            self._emit_snapshot()
            return
        raise RuntimeError(f"unhandled deterministic instrument command: {command}")

    def _run(self) -> None:
        buffer = bytearray()
        try:
            self._emit_late_attach_boot_preamble()
            self._emit_initial_observations()
            self._emit_source_through(1200)
            while not self.stop_event.is_set():
                readable, _, _ = select.select([self.master_fd], [], [], 0.05)
                if not readable:
                    # Wake the genuine capture reader so it services FIFO
                    # ingress promptly; an empty line is not a device record.
                    self._emit_idle_wakeup()
                    continue
                try:
                    chunk = os.read(self.master_fd, 4096)
                except OSError as exc:
                    if exc.errno == 5 and not self.stop_event.is_set():
                        time.sleep(0.02)
                        continue
                    raise
                if not chunk:
                    continue
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer[:] = remainder
                    command = raw.rstrip(b"\r").decode("ascii").strip()
                    if command:
                        self._handle_command(command)
        except Exception as exc:  # noqa: BLE001 - producer must retain a thread failure for the caller.
            self.error = exc
            self.stop_event.set()

