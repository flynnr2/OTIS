"""Exercise the exact CX320 host topology with accelerated no-I/O evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any

from .active_hybrid_bundle import validate_bundle
from .active_hybrid_evidence_guard import replay_response_before_acknowledgement
from .active_hybrid_finalize import finalize, validate_seal
from .active_hybrid_policy import (
    ActiveHybridController,
    HybridDecision,
    HybridObservation,
    load_policy,
)
from .active_hybrid_proposal import validate_proposal
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    programme_from_mapping,
)
from .active_hybrid_supervisor import ActiveHybridSupervisor, SupervisorContractError
from .contracts import ACTIVE_HYBRID_DECISION_V1_FIELDS, CONTRACT_FIELDS
from .evidence_index import package_identity, register_package, validate_index


TOOL_ID = "cx320_active_hybrid_accelerated_operational_rehearsal_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to replace rehearsal evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to replace rehearsal evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _observation(
    controller: ActiveHybridController,
    *,
    timestamp_s: int,
    sequence: int,
    frequency_error_hz: float,
    counts: int,
    tight_state: str,
    relative_phase_cycles: int,
    phase_valid: bool = True,
    outstanding_response: bool = False,
) -> HybridObservation:
    return HybridObservation(
        timestamp_s=timestamp_s,
        capture_session=1,
        source_first_sequence=max(1, sequence - 599),
        source_last_sequence=sequence,
        dac_epoch=controller.dac_epoch,
        applied_code=controller.applied_code,
        frequency_error_hz=frequency_error_hz,
        accumulated_edge_error_counts=counts,
        tight_state=tight_state,
        phase_epoch=1,
        phase_observation_sequence=sequence,
        relative_phase_cycles=relative_phase_cycles,
        phase_dac_epoch=controller.dac_epoch,
        phase_applied_code=controller.applied_code,
        phase_continuous=phase_valid,
        phase_current=phase_valid,
        phase_consumers_exact=True,
        outstanding_request=controller.transaction_outstanding,
        outstanding_response=outstanding_response,
    )


def _ahy_row(
    decision: HybridDecision,
    *,
    record_sequence: int,
    run_identity: str,
    build_identity: str,
    policy_sha256: str,
    response_policy_sha256: str,
    profile_identity: str = "cx320_active_hybrid",
) -> dict[str, str]:
    value = asdict(decision)
    return {
        "record_type": "AHY",
        "schema_version": "1",
        "hybrid_record_sequence": str(record_sequence),
        "decision_sequence": str(decision.decision_sequence),
        "decision_timestamp_s": str(decision.timestamp_s),
        "run_identity": run_identity,
        "build_identity": build_identity,
        "profile_identity": profile_identity,
        "capture_session": str(decision.capture_session),
        "source_first_sequence": str(decision.source_first_sequence),
        "source_last_sequence": str(decision.source_last_sequence),
        "frequency_estimator_sha256": decision.frequency_estimator_sha256,
        "frequency_error_hz": f"{decision.frequency_error_hz:.12f}",
        "accumulated_edge_error_counts": str(decision.accumulated_edge_error_counts),
        "tight_state": decision.tight_state,
        "phase_estimator_sha256": decision.phase_estimator_sha256,
        "phase_epoch": str(decision.phase_epoch),
        "phase_observation_sequence": str(decision.phase_observation_sequence),
        "relative_phase_cycles": str(decision.relative_phase_cycles),
        "phase_continuous": "true",
        "phase_current": "true",
        "phase_step_detected": "false",
        "phase_recorder_published": "true",
        "current_applied_code": str(decision.current_applied_code),
        "dac_epoch": str(decision.dac_epoch),
        "phase_applied_code": str(decision.current_applied_code),
        "phase_dac_epoch": str(decision.dac_epoch),
        "state_before": decision.state_before,
        "state_after": decision.state_after,
        "frequency_term_hz": f"{decision.frequency_term_hz:.12f}",
        "phase_term_hz": f"{decision.phase_term_hz:.12f}",
        "combined_demand_hz": f"{decision.combined_demand_hz:.12f}",
        "raw_combined_delta_codes": f"{decision.raw_combined_delta_codes:.12f}",
        "requested_delta_codes": str(decision.requested_delta_codes),
        "requested_code": str(decision.requested_code),
        "counterfactual_frequency_only_delta_codes": str(
            decision.counterfactual_frequency_only_delta_codes
        ),
        "phase_materially_influenced": str(decision.phase_materially_influenced).lower(),
        "step_limited": str(decision.step_limited).lower(),
        "range_clamped": str(decision.range_clamped).lower(),
        "cadence_limited": str(decision.cadence_limited).lower(),
        "count_limited": str(decision.count_limited).lower(),
        "cumulative_budget_limited": str(decision.cumulative_budget_limited).lower(),
        "correction_count_before": str(decision.correction_count_before),
        "cumulative_movement_before_codes": str(
            decision.cumulative_movement_before_codes
        ),
        "authority_state": "ARMED",
        "request_sequence": "0",
        "acceptance_sequence": "0",
        "application_sequence": "0",
        "response_class": "unavailable",
        "actual_applied_code": str(decision.current_applied_code),
        "actual_dac_epoch": str(decision.dac_epoch),
        "downstream_epoch_exact": "true",
        "reason": str(value["reason"]),
        "active_policy_sha256": policy_sha256,
        "response_policy_sha256": response_policy_sha256,
        "actionable": "false",
    }


def _transaction_rows(
    decision: HybridDecision,
    *,
    record_sequence: int,
    request_sequence: int,
    application_sequence: int,
    dac_epoch: int,
    cumulative_movement: int,
    run_identity: str,
    build_identity: str,
    policy_sha256: str,
    estimator_sha256: str,
    model_sha256: str,
    response_policy_sha256: str,
    numerical_policy_sha256: str | None = None,
    profile_identity: str = "cx320_active_hybrid",
) -> list[dict[str, str]]:
    numerical_policy_sha256 = numerical_policy_sha256 or policy_sha256
    observed_response_hz = (
        decision.requested_delta_codes * 0.00017008467693813145
    )
    post_error_hz = decision.frequency_error_hz + observed_response_hz
    inside_deadband = abs(post_error_hz) <= 0.006249995628992717
    common = {
        "record_type": "ACT",
        "schema_version": "1",
        "run_identity": run_identity,
        "build_identity": build_identity,
        "profile_identity": profile_identity,
        "session_id": "1",
        "authorization_sequence": str(request_sequence),
        "nonce": str(3_200_000 + request_sequence),
        "request_sequence": str(request_sequence),
        "decision_sequence": str(decision.decision_sequence),
        "source_first_sequence": str(decision.source_first_sequence),
        "source_last_sequence": str(decision.source_last_sequence),
        "decision_timestamp_s": str(decision.timestamp_s),
        "current_applied_code": str(decision.current_applied_code),
        "requested_delta_codes": str(decision.requested_delta_codes),
        "requested_code": str(decision.requested_code),
        "correction_ordinal": str(application_sequence),
        "cumulative_after_codes": str(cumulative_movement),
        "pre_error_hz": f"{decision.frequency_error_hz:.12f}",
        "consecutive_indeterminate": "0",
        "estimator_sha256": estimator_sha256,
        "model_sha256": model_sha256,
        "active_policy_sha256": policy_sha256,
        "response_policy_sha256": response_policy_sha256,
        "numerical_policy_sha256": numerical_policy_sha256,
        "actionable": "false",
    }
    phases = (
        {
            "event": "request_created",
            "accepted_code": "0",
            "accepted_timestamp_s": "0",
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": str(dac_epoch - 1),
            "estimator_history_reset": "false",
            "correction_count": str(application_sequence - 1),
            "cumulative_movement_codes": str(
                cumulative_movement - abs(decision.requested_delta_codes)
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
            "event": "core0_accepted",
            "accepted_code": str(decision.requested_code),
            "accepted_timestamp_s": str(decision.timestamp_s + 1),
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": str(dac_epoch - 1),
            "estimator_history_reset": "false",
            "correction_count": str(application_sequence - 1),
            "cumulative_movement_codes": str(
                cumulative_movement - abs(decision.requested_delta_codes)
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
            "accepted_code": str(decision.requested_code),
            "accepted_timestamp_s": str(decision.timestamp_s + 1),
            "applied_code": str(decision.requested_code),
            "application_sequence": str(application_sequence),
            "application_timestamp_s": str(decision.timestamp_s + 2),
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": str(dac_epoch),
            "estimator_history_reset": "true",
            "correction_count": str(application_sequence),
            "cumulative_movement_codes": str(cumulative_movement),
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
            "accepted_code": str(decision.requested_code),
            "accepted_timestamp_s": str(decision.timestamp_s + 1),
            "applied_code": str(decision.requested_code),
            "application_sequence": str(application_sequence),
            "application_timestamp_s": str(decision.timestamp_s + 2),
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": str(dac_epoch),
            "estimator_history_reset": "true",
            "correction_count": str(application_sequence),
            "cumulative_movement_codes": str(cumulative_movement),
            "post_error_hz": f"{post_error_hz:.12f}",
            "observed_response_hz": f"{observed_response_hz:.12f}",
            "cumulative_response_hz": f"{observed_response_hz:.12f}",
            "active_state": "ARMED",
            "response_class": (
                "inside_deadband" if inside_deadband else "healthy_detected"
            ),
            "reason": (
                "post_error_inside_frozen_deadband"
                if inside_deadband
                else "response_detected_with_commanded_sign"
            ),
            "evidence_state": "response_pending",
        },
    )
    return [
        {
            **common,
            **phase,
            "transaction_record_sequence": str(record_sequence + offset),
        }
        for offset, phase in enumerate(phases)
    ]


def _prepared_supervisor(
    bundle: dict[str, Any], *, owner: str, programme: ActiveHybridProgramme
) -> ActiveHybridSupervisor:
    active_policy_sha256 = (
        bundle["programme_policy"]["sha256"]
        if programme.identification_required
        else bundle["policy"]["policy_sha256"]
    )
    supervisor = ActiveHybridSupervisor(
        run_identity=bundle["run_identity"],
        bundle_sha256=bundle["bundle_sha256"],
        policy_sha256=active_policy_sha256,
        build_identity=bundle["firmware"]["build_identity"],
        profile_identity=programme.profile_id,
        response_checkpoint_observational=(
            programme.response_checkpoint_observational
        ),
    )
    supervisor.establish_capture(owner=owner)
    supervisor.confirm_identity(
        run_identity=bundle["run_identity"],
        bundle_sha256=bundle["bundle_sha256"],
        policy_sha256=active_policy_sha256,
        build_identity=bundle["firmware"]["build_identity"],
        profile_identity=programme.profile_id,
    )
    supervisor.confirm_setup_propagation(
        requested_code=0xA83C,
        accepted_code=0xA83C,
        applied_code=0xA83C,
        dac_epoch=1,
        consumer_epochs={name: 1 for name in bundle["setup"]["consumer_epoch_propagation_required"]},
    )
    supervisor.arm()
    return supervisor


def _modeled_transaction(
    bundle: dict[str, Any],
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    policy = load_policy(
        Path(str(bundle["policy"].get("path", programme.natural_policy_path)))
    )
    active_policy_sha256 = (
        bundle["programme_policy"]["sha256"]
        if programme.identification_required
        else policy.policy_sha256
    )
    controller = ActiveHybridController(policy, setup_application_s=0)
    supervisor = _prepared_supervisor(
        bundle, owner="capture_owner_3201", programme=programme
    )
    ahy_rows: list[dict[str, str]] = []
    transaction_rows: list[dict[str, str]] = []
    request_sequence = 0
    transaction_record_sequence = 1
    response_attestations = []
    observations = (
        (1800, 1800, -0.010, -6, "OUTSIDE", 0),
        (3600, 3600, 0.0, 0, "TIGHT_INSIDE", 0),
        (5400, 5400, 0.0, 0, "TIGHT_INSIDE", 36),
        (7200, 7200, 0.0, 0, "TIGHT_INSIDE", 28),
        (9000, 9000, 0.0, 0, "TIGHT_INSIDE", 18),
    )
    timing_bridge: dict[str, Any] | None = None
    if programme.identification_required:
        programme_policy = json.loads(
            Path(str(bundle["programme_policy"]["path"])).read_text(
                encoding="utf-8"
            )
        )
        timing = programme_policy["finite_timing"]
        identification_application_s = int(
            timing[
                "setup_application_to_identification_decision_lower_bound_s"
            ]
        )
        application_to_natural_s = int(
            timing[
                "identification_application_to_first_eligible_natural_selected_epoch_lower_bound_s"
            ]
        )
        setup_to_natural_s = int(
            timing[
                "setup_application_to_first_eligible_natural_request_lower_bound_s_excluding_identification_transaction_latency"
            ]
        )
        first_natural_epoch_s = max(
            identification_application_s + application_to_natural_s,
            setup_to_natural_s,
        )
        shift_s = first_natural_epoch_s - observations[0][0]
        observations = tuple(
            (timestamp + shift_s, sequence + shift_s, *rest)
            for timestamp, sequence, *rest in observations
        )
        timing_bridge = {
            "source_policy_sha256": bundle["programme_policy"]["sha256"],
            "modeled_setup_application_s": 0,
            "modeled_identification_application_s_excluding_transaction_latency": (
                identification_application_s
            ),
            "identification_application_to_first_natural_selected_epoch_lower_bound_s": (
                application_to_natural_s
            ),
            "setup_to_first_natural_request_lower_bound_s_excluding_identification_transaction_latency": (
                setup_to_natural_s
            ),
            "first_natural_selected_epoch_s": first_natural_epoch_s,
        }
    hybrid_record_sequence = 0
    for item in observations:
        decision = controller.decide(
            _observation(
                controller,
                timestamp_s=item[0],
                sequence=item[1],
                frequency_error_hz=item[2],
                counts=item[3],
                tight_state=item[4],
                relative_phase_cycles=item[5],
            )
        )
        hybrid_record_sequence += 1
        ahy_rows.append(
            _ahy_row(
                decision,
                record_sequence=hybrid_record_sequence,
                run_identity=bundle["run_identity"],
                build_identity=bundle["firmware"]["build_identity"],
                policy_sha256=active_policy_sha256,
                response_policy_sha256=policy.response_policy_sha256,
                profile_identity=programme.profile_id,
            )
        )
        if decision.requested_delta_codes == 0:
            continue
        request_sequence += 1
        supervisor.request_created(
            decision_sequence=decision.decision_sequence,
            request_sequence=request_sequence,
            requested_code=decision.requested_code,
            phase_material=decision.phase_materially_influenced,
        )
        controller.note_application(
            decision,
            applied_code=decision.requested_code,
            dac_epoch=controller.dac_epoch + 1,
            downstream_consumers_exact=True,
        )
        supervisor.application_propagated(
            request_sequence=request_sequence,
            acceptance_sequence=request_sequence,
            application_sequence=controller.correction_count,
            applied_code=controller.applied_code,
            dac_epoch=controller.dac_epoch,
            consumer_epochs={
                name: controller.dac_epoch
                for name in bundle["setup"]["consumer_epoch_propagation_required"]
            },
        )
        new_rows = _transaction_rows(
            decision,
            record_sequence=transaction_record_sequence,
            request_sequence=request_sequence,
            application_sequence=controller.correction_count,
            dac_epoch=controller.dac_epoch,
            cumulative_movement=controller.cumulative_movement_codes,
            run_identity=bundle["run_identity"],
            build_identity=bundle["firmware"]["build_identity"],
            policy_sha256=active_policy_sha256,
            estimator_sha256=policy.frequency_estimator_sha256,
            model_sha256=policy.plant_model_sha256,
            response_policy_sha256=policy.response_policy_sha256,
            numerical_policy_sha256=policy.policy_sha256,
            profile_identity=programme.profile_id,
        )
        transaction_rows.extend(new_rows)
        transaction_record_sequence += 4
        response_row = new_rows[-1]
        response_timestamp_s = int(new_rows[2]["application_timestamp_s"]) + (
            policy.settling_exclusion_s + policy.fresh_support_s
        )
        response_decision = controller.decide(
            _observation(
                controller,
                timestamp_s=response_timestamp_s,
                sequence=response_timestamp_s,
                frequency_error_hz=float(response_row["post_error_hz"]),
                counts=round(float(response_row["post_error_hz"]) * 600),
                tight_state=(
                    "TIGHT_INSIDE"
                    if abs(float(response_row["post_error_hz"]))
                    <= 2.0 / 600.0
                    else "OUTSIDE"
                ),
                relative_phase_cycles=item[5],
                outstanding_response=True,
            )
        )
        hybrid_record_sequence += 1
        response_ahy = _ahy_row(
            response_decision,
            record_sequence=hybrid_record_sequence,
            run_identity=bundle["run_identity"],
            build_identity=bundle["firmware"]["build_identity"],
            policy_sha256=active_policy_sha256,
            response_policy_sha256=policy.response_policy_sha256,
            profile_identity=programme.profile_id,
        )
        response_ahy.update(
            {
                "authority_state": "AWAITING_RESPONSE",
                "request_sequence": str(request_sequence),
                "acceptance_sequence": str(request_sequence),
                "application_sequence": str(controller.correction_count),
            }
        )
        ahy_rows.append(response_ahy)
        controller.note_response(
            classification=response_row["response_class"],
            predicted_sign_observed=True,
            exact_replay=True,
            support_fresh=True,
            applied_epoch_exact=True,
        )
        supervisor.response_replayed_and_acknowledged(
            request_sequence=request_sequence,
            response_class=response_row["response_class"],
            support_fresh=True,
            sign_healthy=True,
            replay_exact=True,
            tight_reacquired=True,
            durable_decision_record=True,
            durable_transaction_record=True,
        )

    supervisor.terminal_clear(reason="accelerated_modeled_path_complete")
    supervisor.close_capture(owner="capture_owner_3201", logical_rotation=True)
    snapshot = supervisor.snapshot()
    snapshot.update(controller.snapshot())
    if timing_bridge is not None:
        first_natural_request_s = min(
            int(row["decision_timestamp_s"])
            for row in ahy_rows
            if int(row["requested_delta_codes"]) != 0
        )
        timing_bridge["first_natural_request_s"] = first_natural_request_s
        timing_bridge["application_bridge_passed"] = (
            first_natural_request_s
            >= timing_bridge[
                "modeled_identification_application_s_excluding_transaction_latency"
            ]
            + timing_bridge[
                "identification_application_to_first_natural_selected_epoch_lower_bound_s"
            ]
        )
        timing_bridge["setup_bridge_passed"] = (
            first_natural_request_s
            >= timing_bridge[
                "setup_to_first_natural_request_lower_bound_s_excluding_identification_transaction_latency"
            ]
        )
        if not (
            timing_bridge["application_bridge_passed"]
            and timing_bridge["setup_bridge_passed"]
        ):
            raise ValueError("CX321 natural-controller timing bridge differs")
        snapshot["cx321_natural_timing_bridge"] = timing_bridge
    snapshot["events"] = supervisor.events
    snapshot["response_attestations"] = response_attestations
    return snapshot, ahy_rows, transaction_rows


def _scenario_clean_degradation(
    bundle: dict[str, Any],
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    supervisor = _prepared_supervisor(
        bundle, owner="capture_owner_3202", programme=programme
    )
    supervisor.degrade_phase_cleanly(reason="deterministic_phase_epoch_invalidation")
    return supervisor.snapshot()


def _scenario_shared_fault(
    bundle: dict[str, Any],
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    supervisor = _prepared_supervisor(
        bundle, owner="capture_owner_3203", programme=programme
    )
    supervisor.transport_obstructed()
    supervisor.submit_priority_abort()
    supervisor.confirm_priority_abort_delivery()
    supervisor.close_capture(owner="capture_owner_3203", logical_rotation=True)
    return supervisor.snapshot()


def _scenario_abort_failure(
    bundle: dict[str, Any],
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    supervisor = _prepared_supervisor(
        bundle, owner="capture_owner_3204", programme=programme
    )
    supervisor.transport_obstructed()
    supervisor.submit_priority_abort()
    supervisor.record_priority_abort_delivery_failure(reason="injected_abort_fifo_obstruction")
    rejected = False
    try:
        supervisor.close_capture(owner="capture_owner_3204", logical_rotation=True)
    except SupervisorContractError:
        rejected = True
    result = supervisor.snapshot()
    result["capture_close_rejected_before_delivery"] = rejected
    return result


def _scenario_observational_response_classes(
    bundle: dict[str, Any], programme: ActiveHybridProgramme
) -> dict[str, Any]:
    if not programme.response_checkpoint_observational:
        return {"applicable": False}
    results: dict[str, Any] = {"applicable": True, "classes": {}}
    for ordinal, (response_class, sign_healthy) in enumerate(
        (
            ("healthy_indeterminate_near_resolution", False),
            ("wrong_sign", False),
            ("growing_error", False),
            ("excess_response", False),
        ),
        start=1,
    ):
        supervisor = _prepared_supervisor(
            bundle,
            owner=f"capture_owner_322_observation_{ordinal}",
            programme=programme,
        )
        supervisor.request_created(
            decision_sequence=ordinal,
            request_sequence=ordinal,
            requested_code=0xA83C + ordinal,
            phase_material=True,
        )
        supervisor.application_propagated(
            request_sequence=ordinal,
            acceptance_sequence=ordinal,
            application_sequence=1,
            applied_code=0xA83C + ordinal,
            dac_epoch=2,
            consumer_epochs={
                name: 2
                for name in bundle["setup"][
                    "consumer_epoch_propagation_required"
                ]
            },
        )
        supervisor.response_replayed_and_acknowledged(
            request_sequence=ordinal,
            response_class=response_class,
            support_fresh=True,
            sign_healthy=sign_healthy,
            replay_exact=True,
            tight_reacquired=True,
            durable_decision_record=True,
            durable_transaction_record=True,
        )
        results["classes"][response_class] = {
            "state": supervisor.state,
            "later_authority_released": supervisor.later_authority_released,
            "terminal_reason": supervisor.terminal_reason,
        }
    invalid = _prepared_supervisor(
        bundle, owner="capture_owner_322_invalid", programme=programme
    )
    invalid.request_created(
        decision_sequence=99,
        request_sequence=99,
        requested_code=0xA83D,
        phase_material=True,
    )
    invalid.application_propagated(
        request_sequence=99,
        acceptance_sequence=99,
        application_sequence=1,
        applied_code=0xA83D,
        dac_epoch=2,
        consumer_epochs={
            name: 2
            for name in bundle["setup"]["consumer_epoch_propagation_required"]
        },
    )
    invalid.response_replayed_and_acknowledged(
        request_sequence=99,
        response_class="measurement_or_actuator_fault",
        support_fresh=True,
        sign_healthy=False,
        replay_exact=True,
        tight_reacquired=True,
        durable_decision_record=True,
        durable_transaction_record=True,
    )
    results["invalid_measurement_fails_static"] = (
        invalid.state == "FAIL_STATIC"
        and invalid.terminal_reason == "first_phase_response_checkpoint_failed"
    )
    return results


def run(*, bundle_path: Path, proposal_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(raw_bundle, dict):
        raise ValueError("active-hybrid rehearsal bundle root is not an object")
    programme = programme_from_mapping(raw_bundle)
    bundle = (
        validate_bundle(bundle_path)
        if programme is CX320_PROGRAMME
        else validate_bundle(bundle_path, programme)
    )
    proposal = (
        validate_proposal(proposal_path)
        if programme is CX320_PROGRAMME
        else validate_proposal(proposal_path, programme)
    )
    if proposal["exact_bundle"]["bundle_sha256"] != bundle["bundle_sha256"]:
        raise ValueError("rehearsal proposal and bundle differ")
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"CX320 rehearsal output must be empty: {output_dir}")
    evidence_dir = output_dir / "evidence"
    registration_dir = output_dir / "registration"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    registration_dir.mkdir(parents=True, exist_ok=True)

    primary, ahy_rows, transaction_rows = _modeled_transaction(bundle, programme)
    active_policy_sha256 = (
        bundle["programme_policy"]["sha256"]
        if programme.identification_required
        else bundle["policy"]["policy_sha256"]
    )
    run_manifest = {
        "schema_version": 1,
        "programme_id": bundle["programme_id"],
        "run_identity": bundle["run_identity"] + ":offline_rehearsal",
        "mode": "accelerated_no_io_operational_rehearsal",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "authority_effective": False,
        "bundle_path": str(bundle_path.resolve()),
        "bundle_file_sha256": sha256(bundle_path.read_bytes()).hexdigest(),
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_path": str(proposal_path.resolve()),
        "proposal_sha256": proposal["proposal_sha256"],
        "policy_sha256": active_policy_sha256,
        "numerical_policy_sha256": bundle["policy"]["policy_sha256"],
        "build_identity": bundle["firmware"]["build_identity"],
        "profile_identity": programme.profile_id,
        "timing": bundle["finite_limits"],
        "created_utc": _utc_now(),
    }
    _write_new_json(evidence_dir / "run_manifest.json", run_manifest)
    _write_csv(
        evidence_dir / "csv/active_hybrid_decisions_v1.csv",
        ACTIVE_HYBRID_DECISION_V1_FIELDS,
        ahy_rows,
    )
    _write_csv(
        evidence_dir / "csv/active_transactions_v1.csv",
        CONTRACT_FIELDS["active_transactions_v1"],
        transaction_rows,
    )

    # Exercise the exact durable-response guard over the first material request.
    first_material = next(
        row for row in ahy_rows if row["phase_materially_influenced"] == "true"
    )
    first_material_response = next(
        row
        for row in transaction_rows
        if row["event"] == "response"
        and row["decision_sequence"] == first_material["decision_sequence"]
    )
    attestation = replay_response_before_acknowledgement(
        active_hybrid_csv=evidence_dir / "csv/active_hybrid_decisions_v1.csv",
        active_transactions_csv=evidence_dir / "csv/active_transactions_v1.csv",
        response_row=first_material_response,
        policy_path=Path(str(bundle["policy"]["path"])),
        expected_profile_identity=programme.profile_id,
        expected_active_policy_sha256=active_policy_sha256,
    )
    primary["response_attestations"] = [attestation]
    trace = {
        "schema_version": 1,
        "trace_type": f"{programme.key}_active_hybrid_operational_trace_v1",
        "tool": TOOL_ID,
        "tool_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "created_utc": _utc_now(),
        "bundle_sha256": bundle["bundle_sha256"],
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "accelerated_boundaries": [
            "600s_estimator_interval",
            "1800s_phase_qualification_residence",
            "900s_settling_plus_600s_fresh_response_support",
            "43200s_qualified_and_57600s_wall_deadlines",
        ],
        "real_components_exercised": [
            "host_reference_controller",
            "AHY_contract_validator",
            "response_replay_before_ACKE_guard",
            "progressive_supervisor_state_contract",
            "analyzer",
            "finalizer_and_sealer",
            "external_evidence_registration",
        ],
        "physical_boundaries_not_exercised": [
            "firmware_cross_core_runtime",
            "physical_D14_D8_capture",
            "AD5693R_write",
            "CX317_plant_response",
            "USB_device_transport",
        ],
        "successor_scope": {
            "programme": programme.key,
            "natural_controller_semantics_exercised_in_isolation": True,
            "plant_sign_identification_lifecycle_modeled_here": False,
            "plant_sign_identification_lifecycle_is_exercised_by_live_topology_rehearsal": (
                programme.identification_required
            ),
        },
        "modeled_phase_transaction": primary,
        "clean_phase_degradation": _scenario_clean_degradation(bundle, programme),
        "shared_fail_static_transport_obstruction": _scenario_shared_fault(bundle, programme),
        "abort_delivery_failure": _scenario_abort_failure(bundle, programme),
        "observational_response_classification": (
            _scenario_observational_response_classes(bundle, programme)
        ),
    }
    _write_new_json(evidence_dir / "reports/operational_trace_v1.json", trace)
    seal = finalize(evidence_dir)
    validate_seal(evidence_dir)

    with tempfile.TemporaryDirectory(prefix=f"{programme.key}-rehearsal-registration-") as temporary:
        index_path = Path(temporary) / "evidence_index_v1.json"
        registration = register_package(
            index_path=index_path,
            package_path=evidence_dir,
            source_revision=bundle["firmware"]["source_revision"],
            build_identity=bundle["firmware"]["build_identity"],
            profile_identity=programme.profile_id,
            attempt_classification="successful_rehearsal",
            result_or_failure_reason="accelerated_operational_path_passed",
            analyzer_identity=seal["analysis"]["analysis_sha256"],
        )
        index_validation = validate_index(index_path)
        if not index_validation["valid"]:
            raise ValueError("CX320 temporary external registration validation failed")
    receipt = {
        "schema_version": 1,
        "receipt_type": f"{programme.key}_active_hybrid_rehearsal_registration_receipt_v1",
        "created_utc": _utc_now(),
        "temporary_external_index_exercised": True,
        "index_validation": index_validation,
        "registration": registration,
        "evidence_content_identity_after_seal": package_identity(evidence_dir),
    }
    _write_new_json(registration_dir / "registration_receipt_v1.json", receipt)
    result = {
        "status": "passed",
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "seal_sha256": seal["seal_sha256"],
        "evidence_content_sha256": registration["content_sha256"],
        "registration_valid": index_validation["valid"],
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "output_dir": str(output_dir),
    }
    if programme.identification_required:
        result["cx321_natural_timing_bridge"] = primary[
            "cx321_natural_timing_bridge"
        ]
    _write_new_json(output_dir / "operational_rehearsal_result_v1.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run(
        bundle_path=args.bundle,
        proposal_path=args.proposal,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
