"""Finite host-side state contract for the CX320 active-hybrid programme.

This module has no device, FIFO, or actuator surface.  It records and checks
the decision-bearing host transitions which a future live runner must drive
through the existing sole-owner capture and active-transaction machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TOOL_ID = "cx320_active_hybrid_supervisor_contract_v1"


class SupervisorContractError(RuntimeError):
    """A CX320 host transition violated the frozen ordering contract."""


@dataclass
class ActiveHybridSupervisor:
    run_identity: str
    bundle_sha256: str
    policy_sha256: str
    build_identity: str
    profile_identity: str = "cx320_active_hybrid"
    state: str = "CREATED"
    serial_owner: str | None = None
    setup_code: int | None = None
    dac_epoch: int | None = None
    request_outstanding: bool = False
    response_outstanding: bool = False
    later_authority_released: bool = False
    abort_submitted: bool = False
    abort_delivered: bool = False
    terminal_code: int | None = None
    terminal_reason: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def _event(self, event: str, **fields: Any) -> None:
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "event": event,
                "state": self.state,
                **fields,
            }
        )

    def establish_capture(self, *, owner: str) -> None:
        if self.state != "CREATED" or not owner:
            raise SupervisorContractError("capture must establish one named owner first")
        self.serial_owner = owner
        self.state = "CAPTURE_ESTABLISHED"
        self._event("capture_owner_established", owner=owner, owner_count=1)

    def confirm_identity(
        self,
        *,
        run_identity: str,
        bundle_sha256: str,
        policy_sha256: str,
        build_identity: str,
        profile_identity: str,
    ) -> None:
        if self.state != "CAPTURE_ESTABLISHED":
            raise SupervisorContractError("identity confirmation must follow capture")
        observed = (
            run_identity,
            bundle_sha256,
            policy_sha256,
            build_identity,
            profile_identity,
        )
        expected = (
            self.run_identity,
            self.bundle_sha256,
            self.policy_sha256,
            self.build_identity,
            self.profile_identity,
        )
        if observed != expected:
            self.fail_static("exact_run_bundle_policy_build_or_profile_identity_mismatch")
            raise SupervisorContractError(self.terminal_reason or "identity mismatch")
        self.state = "IDENTITY_CONFIRMED"
        self._event("exact_identity_confirmed")

    def confirm_setup_propagation(
        self,
        *,
        requested_code: int,
        accepted_code: int,
        applied_code: int,
        dac_epoch: int,
        consumer_epochs: dict[str, int],
    ) -> None:
        if self.state != "IDENTITY_CONFIRMED":
            raise SupervisorContractError("setup propagation must follow identity")
        required = {
            "frequency_estimator",
            "phase_estimator",
            "controller",
            "preview_replay",
            "recorder",
            "response_classifier",
        }
        if (
            requested_code != accepted_code
            or accepted_code != applied_code
            or dac_epoch <= 0
            or set(consumer_epochs) != required
            or any(epoch != dac_epoch for epoch in consumer_epochs.values())
        ):
            self.fail_static("setup_or_first_consumer_epoch_propagation_mismatch")
            raise SupervisorContractError(self.terminal_reason or "setup mismatch")
        self.setup_code = applied_code
        self.dac_epoch = dac_epoch
        self.terminal_code = applied_code
        self.state = "SETUP_PROPAGATED"
        self._event(
            "setup_propagated",
            requested_code=requested_code,
            applied_code=applied_code,
            dac_epoch=dac_epoch,
            consumers=sorted(consumer_epochs),
        )

    def arm(self) -> None:
        if self.state != "SETUP_PROPAGATED":
            raise SupervisorContractError("arm requires exact setup propagation")
        self.state = "ARMED_PROGRESSIVE"
        self._event("progressive_authority_armed", later_authority_released=False)

    def request_created(
        self,
        *,
        decision_sequence: int,
        request_sequence: int,
        requested_code: int,
        phase_material: bool,
    ) -> None:
        if self.state not in {"ARMED_PROGRESSIVE", "HYBRID_RELEASED"}:
            raise SupervisorContractError("request is not allowed in the current state")
        if self.request_outstanding or self.response_outstanding:
            self.fail_static("overlapping_request_or_response")
            raise SupervisorContractError(self.terminal_reason or "overlap")
        self.request_outstanding = True
        if phase_material and not self.later_authority_released:
            self.state = "FIRST_PHASE_TRANSACTION"
        self._event(
            "request_created",
            decision_sequence=decision_sequence,
            request_sequence=request_sequence,
            requested_code=requested_code,
            phase_material=phase_material,
        )

    def application_propagated(
        self,
        *,
        request_sequence: int,
        acceptance_sequence: int,
        application_sequence: int,
        applied_code: int,
        dac_epoch: int,
        consumer_epochs: dict[str, int],
    ) -> None:
        if not self.request_outstanding:
            self.fail_static("application_without_one_outstanding_request")
            raise SupervisorContractError(self.terminal_reason or "missing request")
        if (
            request_sequence <= 0
            or acceptance_sequence <= 0
            or application_sequence <= 0
            or dac_epoch != (self.dac_epoch or 0) + 1
            or any(epoch != dac_epoch for epoch in consumer_epochs.values())
        ):
            self.fail_static("application_identity_or_downstream_epoch_mismatch")
            raise SupervisorContractError(self.terminal_reason or "application mismatch")
        self.request_outstanding = False
        self.response_outstanding = True
        self.dac_epoch = dac_epoch
        self.terminal_code = applied_code
        self._event(
            "application_propagated",
            request_sequence=request_sequence,
            acceptance_sequence=acceptance_sequence,
            application_sequence=application_sequence,
            applied_code=applied_code,
            dac_epoch=dac_epoch,
            consumers=sorted(consumer_epochs),
        )

    def response_replayed_and_acknowledged(
        self,
        *,
        request_sequence: int,
        response_class: str,
        support_fresh: bool,
        sign_healthy: bool,
        replay_exact: bool,
        tight_reacquired: bool,
        durable_decision_record: bool,
        durable_transaction_record: bool,
    ) -> None:
        if not self.response_outstanding:
            self.fail_static("response_without_outstanding_application")
            raise SupervisorContractError(self.terminal_reason or "missing response")
        healthy = (
            response_class in {"healthy_detected", "healthy_indeterminate_near_resolution"}
            and support_fresh
            and sign_healthy
            and replay_exact
            and tight_reacquired
            and durable_decision_record
            and durable_transaction_record
        )
        if not healthy:
            self.fail_static("first_phase_response_checkpoint_failed")
            return
        self.response_outstanding = False
        if self.state == "FIRST_PHASE_TRANSACTION":
            self.later_authority_released = True
            self.state = "HYBRID_RELEASED"
        self._event(
            "response_replayed_before_acknowledgement",
            request_sequence=request_sequence,
            response_class=response_class,
            later_authority_released=self.later_authority_released,
        )

    def degrade_phase_cleanly(self, *, reason: str) -> None:
        if self.request_outstanding or self.response_outstanding:
            self.fail_static("phase_invalid_during_transaction_or_response_horizon")
            return
        if self.state == "FAIL_STATIC":
            return
        self.state = "PHASE_DEGRADED_FREQUENCY_ONLY"
        self._event("phase_authority_revoked_clean_boundary", reason=reason)

    def transport_obstructed(self) -> None:
        self._event("transport_obstruction_detected")
        self.fail_static("transport_obstruction_shared_fault")

    def fail_static(self, reason: str) -> None:
        self.state = "FAIL_STATIC"
        self.terminal_reason = reason
        self._event(
            "fail_static_entered",
            reason=reason,
            last_confirmed_code=self.terminal_code,
        )

    def submit_priority_abort(self) -> None:
        if self.state != "FAIL_STATIC" or self.abort_submitted:
            raise SupervisorContractError("priority abort submission is not available")
        self.abort_submitted = True
        self._event("priority_abort_submitted")

    def confirm_priority_abort_delivery(self) -> None:
        if not self.abort_submitted or self.abort_delivered:
            raise SupervisorContractError("priority abort delivery lacks one submission")
        self.abort_delivered = True
        self._event("priority_abort_delivered")

    def record_priority_abort_delivery_failure(self, *, reason: str) -> None:
        if not self.abort_submitted or self.abort_delivered:
            raise SupervisorContractError("abort delivery failure lacks one submission")
        self.terminal_reason = "failed_priority_abort_delivery"
        self._event("priority_abort_delivery_failed", reason=reason)

    def terminal_clear(self, *, reason: str) -> None:
        if self.request_outstanding or self.response_outstanding:
            raise SupervisorContractError("terminal clear requires no outstanding transaction")
        if self.state == "FAIL_STATIC":
            raise SupervisorContractError("fail-static terminal requires priority abort handling")
        self.state = "TERMINAL_CLEAR"
        self.terminal_reason = reason
        self._event(
            "terminal_authority_cleared",
            reason=reason,
            last_confirmed_code=self.terminal_code,
            latent_authority=False,
        )

    def close_capture(self, *, owner: str, logical_rotation: bool) -> None:
        if owner != self.serial_owner:
            raise SupervisorContractError("serial owner changed during capture")
        if self.state == "FAIL_STATIC" and not self.abort_delivered:
            raise SupervisorContractError("capture cannot close before priority abort delivery")
        self._event(
            "capture_closed",
            owner=owner,
            owner_count=1,
            logical_rotation=logical_rotation,
            ownerless_interval=False,
        )
        self.state = "CLOSED"

    def snapshot(self) -> dict[str, Any]:
        return {
            "tool": TOOL_ID,
            "run_identity": self.run_identity,
            "bundle_sha256": self.bundle_sha256,
            "policy_sha256": self.policy_sha256,
            "build_identity": self.build_identity,
            "profile_identity": self.profile_identity,
            "state": self.state,
            "serial_owner": self.serial_owner,
            "setup_code": self.setup_code,
            "dac_epoch": self.dac_epoch,
            "request_outstanding": self.request_outstanding,
            "response_outstanding": self.response_outstanding,
            "later_authority_released": self.later_authority_released,
            "abort_submitted": self.abort_submitted,
            "abort_delivered": self.abort_delivered,
            "terminal_code": self.terminal_code,
            "terminal_reason": self.terminal_reason,
            "events": list(self.events),
        }
