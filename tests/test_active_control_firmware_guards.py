from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
MATRIX = ROOT / "firmware/arduino/firmware_matrix.json"


def _hash(relative: str) -> str:
    return sha256((ROOT / relative).read_bytes()).hexdigest()


def test_live_firmware_embeds_every_exact_frozen_identity() -> None:
    policy_path = "profiles/discipline/cx317_bounded_active_v2.json"
    policy = json.loads((ROOT / policy_path).read_text(encoding="utf-8"))
    source = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    bindings = policy["bindings"]

    assert _hash(policy_path) in source
    assert bindings["plant_model_sha256"] in source
    assert bindings["selected_estimator_sha256"] in source
    assert bindings["numerical_preview_policy_sha256"] in source
    assert bindings["response_policy_sha256"] in source
    assert 'OTIS_BUILD_SOURCE_SHA256 ":" OTIS_BUILD_CONFIG_SHA256' in source
    assert "const char *run_identity" in (
        FIRMWARE / "otis_cx317_active_transaction.h"
    ).read_text(encoding="utf-8")


def test_only_actuator_owner_has_controller_to_dac_call_and_no_retry() -> None:
    owner = (FIRMWARE / "otis_cx317_active_actuator.cpp").read_text(
        encoding="utf-8"
    )
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )

    assert owner.count("otis_dac_ad5693r_set_raw(") == 1
    assert "otis_dac_ad5693r_set_raw(" not in active
    assert "otis_dac_ad5693r_set_raw(" not in preview
    assert owner.count("otis_cx317_active_actuator_apply_once") == 1
    assert "for (" not in owner and "while (" not in owner
    assert "automatic_restore" not in owner
    assert "retry" not in owner.lower()
    assert '"automatic_retry", "false"' in active
    assert '"automatic_restore", "false"' in active


def test_prewrite_capsule_requires_exact_phase_ack_before_single_i2c_attempt() -> None:
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    decision = active[
        active.index("void otis_cx317_active_live_on_decision") :
        active.index("bool otis_cx317_active_live_take_application_outcome")
    ]
    acknowledgement = active[
        active.index("bool otis_cx317_active_live_acknowledge_evidence") :
        active.index("bool otis_cx317_active_live_manual_start_allowed")
    ]

    assert '"request_created"' in decision
    assert '"request_accepted"' in decision
    assert "otis_cx317_active_actuator_apply_once" not in decision
    assert acknowledgement.index("phase_sequence !=") < acknowledgement.index(
        "otis_cx317_active_actuator_apply_once"
    )
    assert acknowledgement.index("frame.length != 0u") < acknowledgement.index(
        "otis_cx317_active_actuator_apply_once"
    )
    assert acknowledgement.count("otis_cx317_active_actuator_apply_once") == 1
    assert "OtisCriticalMessageKind::ActuatorRequest" in acknowledgement
    assert "OtisCriticalMessageKind::ActuatorExecute" in acknowledgement
    assert "otis_cx317_active_live_on_cross_core_ack" in acknowledgement
    assert "EvidencePhase::Acceptance" in acknowledgement
    assert "EvidencePhase::Application" in acknowledgement
    assert "evidence_acknowledgement_timeout" in active


def test_serialized_act_evidence_never_copies_private_actionability() -> None:
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    serializer = active[
        active.index("bool queue_frame(") : active.index(
            "bool queue_manual_start_frame("
        )
    ]
    assert '"false", evidence_state_name()' in serializer
    assert "transaction.request.actionable" not in serializer
    assert "cross.actionable = request.actionable" in active
    assert "pending_actionable_request = request" in active


def test_active_commands_cannot_supply_feedback_code_or_actionability() -> None:
    parser = (FIRMWARE / "otis_serial_command.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    arm_parse = parser[
        parser.index('strncmp(command, "ACTIVE ARM ",') :
        parser.index('strcmp(command, "ACTIVE ABORT")')
    ]
    assert "parse_u16_code" not in arm_parse
    assert "actionable" not in arm_parse.lower()
    assert "values[3]" in sketch
    assert "otis_cx317_active_live_arm(" in sketch
    assert "queue_dual_core_active_control(" in sketch
    assert "requested_code" not in sketch[
        sketch.index("OtisSerialCommandKind::ActiveArm") :
        sketch.index("OtisSerialCommandKind::ActiveAbort")
    ]


def test_manual_path_is_exact_start_once_and_faults_other_active_commands() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "code == OTIS_CX317_ACTIVE_START_CODE" in live
    assert "!manual_start_confirmed" in live
    handler = sketch[
        sketch.index("void handle_dac_set") :
        sketch.index("#if OTIS_ENABLE_H1_DAC_SWEEP", sketch.index("void handle_dac_set"))
    ]
    assert handler.index("otis_cx317_active_live_manual_start_allowed") < handler.index(
        "otis_dac_ad5693r_set_raw"
    )
    assert 'otis_cx317_active_live_abort("nonprogramme_manual_dac_command")' in handler


def test_measurement_model_control_and_arm_gates_are_separate() -> None:
    transaction = (FIRMWARE / "otis_cx317_active_transaction.cpp").read_text(
        encoding="utf-8"
    )
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    common_fields = [
        "gnss_metadata_valid",
        "gnss_identity_stable",
        "gnss_3d_evidence",
        "raw_pps_valid",
        "count_valid",
        "applied_code_confirmed",
        "capture_owner_live",
        "abort_path_live",
        "transaction_evidence_available",
    ]
    control_eligibility = transaction[
        transaction.index("bool otis_cx317_active_eligibility_valid") :
        transaction.index("bool otis_cx317_active_arm_eligibility_valid")
    ]
    for field in common_fields + ["estimator_valid", "model_applicable"]:
        assert f"value->{field}" in control_eligibility
    assert "value->temperature_valid" not in control_eligibility
    # One check gates a request; the other releases OUT_OF_MODEL_HOLD only
    # after the full control eligibility set is healthy again.
    assert transaction.count("otis_cx317_active_eligibility_valid(eligibility)") == 2
    assert transaction.count("otis_cx317_active_arm_eligibility_valid(eligibility)") == 1
    arm_eligibility = transaction[
        transaction.index("bool otis_cx317_active_arm_eligibility_valid") :
        transaction.index("bool otis_cx317_active_response_measurement_valid")
    ]
    for field in common_fields:
        assert f"value->{field}" in arm_eligibility
    assert "value->estimator_valid" not in arm_eligibility
    assert "value->model_applicable" not in arm_eligibility
    assert "value->temperature_valid" not in arm_eligibility
    response_eligibility = transaction[
        transaction.index("bool otis_cx317_active_response_measurement_valid") :
        transaction.index("void otis_cx317_active_fault")
    ]
    for field in common_fields + ["estimator_valid"]:
        assert f"value->{field}" in response_eligibility
    assert "value->model_applicable" not in response_eligibility
    assert "value->temperature_valid" not in response_eligibility
    assert "decision->measurement_valid" in live
    assert "decision->model_applicable" in live
    assert "decision->control_eligible" in live
    assert "latest_health.applied_code == transaction.applied_code" in live


def test_current_firmware_has_no_d10_pps_observer_or_authority_path() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    board = (FIRMWARE / "otis_board.h").read_text(encoding="utf-8")
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    resources = (FIRMWARE / "otis_resource_registry.cpp").read_text(
        encoding="utf-8"
    )
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    health = sketch[
        sketch.index("void service_cx317_active_health(void)") :
        sketch.index("void service_cx317_active_application_outcome(void)")
    ]

    assert "d14.d14_accepted_pps_count > 0u" in health
    assert "otis_pps_snapshot_backend_get_stats(&snapshot)" in health
    assert "OTIS_PIN_GENERIC_EVENT = D10" in board
    assert "OTIS_PIN_PPS_REFERENCE = D14" in board
    assert "OTIS_PIN_OSC_OBSERVATION = D8" in board
    assert "OTIS_PIN_GENERIC_EVENT, INPUT_PULLDOWN" in sketch
    assert "OTIS_PIN_GENERIC_EVENT, OUTPUT" not in sketch
    assert "digitalWrite(OTIS_PIN_GENERIC_EVENT" not in sketch
    assert "gpio_put(OTIS_PIN_GENERIC_EVENT" not in sketch
    assert resources.count("OTIS_PIN_GENERIC_EVENT") == 1
    assert "OTIS_PIN_GENERIC_EVENT" not in health
    assert "OTIS_ENABLE_PPS_DUAL_OBSERVER" not in config
    for profile in matrix["profiles"]:
        assert "OTIS_ENABLE_PPS_DUAL_OBSERVER" not in profile["defines"]
    for forbidden in (
        "otis_pps_dual_observer",
        "pps_dual_observer",
        "pps_d10",
        "d10_pps_witness",
        "d14_raw_minus_d10_raw",
    ):
        assert forbidden not in sketch

    for host_path in (
        ROOT / "host/otis_tools/bounded_tight_deadband_prewrite_contract.py",
        ROOT / "host/otis_tools/pps_cumulative_span_estimator.py",
        ROOT / "host/otis_tools/service_plane_probe.py",
    ):
        host_source = host_path.read_text(encoding="utf-8")
        assert "pps_dual_observer" not in host_source
        assert "pps_d10" not in host_source
        assert "d14_raw_minus_d10_raw" not in host_source

    model = json.loads(
        (ROOT / "profiles/plant_models/cx317_pps_gated_v2.json").read_text(
            encoding="utf-8"
        )
    )
    invalidation = " ".join(model["invalidation_conditions"])
    assert "Any use of D10 as a PPS observer" in invalidation


def test_setup_ack_survives_one_in_flight_pre_setup_health_sample() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    health_update = live[
        live.index("void otis_cx317_active_live_update_health") :
        live.index("void otis_cx317_active_live_service")
    ]
    manual_start = live[
        live.index("void otis_cx317_active_live_note_manual_start") :
        live.index("void otis_cx317_active_live_on_decision")
    ]

    assert "periodic_applied_code_confirmation_seen = false;" in manual_start
    assert (
        "health->applied_code == transaction.applied_code" in health_update
    )
    confirmation = health_update.index(
        "periodic_applied_code_confirmation_seen = true;"
    )
    loss_gate = health_update.index(
        "periodic_applied_code_confirmation_seen &&"
    )
    fault = health_update.index('"confirmed_applied_code_lost"')
    assert confirmation < loss_gate < fault


def test_pre_setup_session_does_not_apply_post_setup_integrity_predicate() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    integrity = live[
        live.index("void update_active_reference_and_integrity") :
        live.index("}  // namespace")
    ]

    pre_setup_return = integrity.index(
        "if (!transaction_bound || !manual_start_confirmed) return;"
    )
    state_checks = integrity.index("const bool inactive")
    strict_integrity = integrity.index("!active_integrity_healthy(now_s)")
    assert pre_setup_return < state_checks < strict_integrity


def test_setup_ack_propagates_the_new_dac_epoch_to_all_hybrid_consumers() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    setup_ack = sketch[
        sketch.index(
            "OtisServiceMessageKind::SetupApplicationAcknowledgement"
        ) : sketch.index(
            "if (message.kind == OtisServiceMessageKind::RunControl)"
        )
    ]
    helper = sketch[
        sketch.index("void propagate_cx317_applied_epoch_to_previews") :
        sketch.index("void service_dual_core_timing_inputs")
    ]

    manual_start = setup_ack.index("otis_cx317_active_live_note_manual_start")
    propagation = setup_ack.index(
        "propagate_cx317_applied_epoch_to_previews", manual_start
    )
    confirmation = setup_ack.index(
        "otis_cx317_active_live_confirm_setup_consumers", propagation
    )
    assert manual_start < propagation < confirmation
    assert "active_status.manual_start_confirmed" in setup_ack
    assert "active_status.dac_epoch != 0u" in setup_ack
    assert "otis_cx317_preview_live_on_dac_applied_epoch" in helper
    assert "otis_phase_preview_live_update_applied_code" in helper

    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    confirm_consumers = live[
        live.index("bool otis_cx317_active_live_confirm_setup_consumers") :
        live.index("void otis_cx317_active_live_on_decision")
    ]
    frequency_consumer = confirm_consumers.index(
        "otis_cx317_preview_live_applied_epoch_exact"
    )
    phase_consumer = confirm_consumers.index(
        "otis_phase_preview_live_get_status"
    )
    engine_initialization = confirm_consumers.index(
        "otis_active_hybrid_engine_init"
    )
    state_release = confirm_consumers.index("hybrid_engine_ready = true")
    assert frequency_consumer < phase_consumer < engine_initialization < state_release

    status = live[live.index("void otis_cx317_active_live_get_status") :]
    assert "hybrid_engine_ready" in status
    assert "otis_active_hybrid_state_name(hybrid_engine.state)" in status


def test_automatic_apply_propagates_the_new_dac_epoch_before_completion() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    service = sketch[
        sketch.index("void service_cx317_active_application_outcome") : sketch.index(
            "void drain_pps_count_boundary_ring"
        )
    ]

    applied = service.index("if (active_outcome.applied)")
    propagation = service.index(
        "propagate_cx317_applied_epoch_to_previews", applied
    )
    completion = service.index(
        "otis_cx317_active_live_complete_application_evidence", propagation
    )
    assert applied < propagation < completion
    assert "active_outcome.applied_code, active_outcome.dac_epoch" in service


def test_completed_response_is_not_gated_by_preview_actionability() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    response = live[
        live.index(
            "if (transaction.state == OtisCx317ActiveState::AwaitingResponse)"
        ) : live.index(
            "if (transaction.state != OtisCx317ActiveState::Armed)"
        )
    ]

    assert "otis_cx317_active_eligibility_valid(&health)" in response
    assert "decision->control_eligible" not in response
    assert "decision->control_eligible" in live[live.index(response) + len(response) :]


def test_status_formatting_cannot_mutate_controller_state() -> None:
    source = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    emitter = source[
        source.index("void otis_cx317_active_live_emit_status") :
        source.index("const char *otis_cx317_active_live_run_identity")
    ]

    assert not re.search(r"transaction\.[A-Za-z_]+\s*=(?!=)", emitter)
    assert "otis_cx317_active_arm(" not in emitter
    assert "otis_cx317_active_make_request" not in emitter
    assert "otis_cx317_active_actuator_apply_once" not in emitter


def test_cross_core_status_preserves_full_build_identity_and_aborted_state() -> None:
    contract = (FIRMWARE / "otis_dual_core_contract.h").read_text(
        encoding="utf-8"
    )
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    capacity_match = re.search(
        r"OTIS_TELEMETRY_VALUE_CAPACITY\s*=\s*(\d+)u", contract
    )

    assert capacity_match is not None
    assert int(capacity_match.group(1)) >= 130
    assert "char value[OTIS_TELEMETRY_VALUE_CAPACITY]" in contract
    assert "telemetry value must preserve a full build identity" in contract

    status = live[live.index("void otis_cx317_active_live_get_status") :]
    dual_start = status.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION")
    dual_status = status[dual_start : status.index("#else", dual_start)]
    assert "otis_dual_core_fail_static()" in dual_status
    assert "OtisCx317ActiveState::Fault" in dual_status
    assert "OtisCx317ActiveState::Aborted" in dual_status


def test_direct_and_dual_active_status_share_one_complete_visitor() -> None:
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    visitor = active[
        active.index("void otis_cx317_active_live_visit_status") : active.index(
            "static void emit_direct_active_status"
        )
    ]
    dual = sketch[
        sketch.index("void publish_dual_core_active_status") : sketch.index(
            "void publish_dual_core_timing_health"
        )
    ]
    expected = (
        "snapshot_generation_begin",
        "snapshot_contract",
        "enabled",
        "run_identity",
        "build_identity",
        "profile_identity",
        "estimator_sha256",
        "model_sha256",
        "active_policy_sha256",
        "response_policy_sha256",
        "numerical_policy_sha256",
        "state",
        "reason",
        "evidence_pending",
        "evidence_phase",
        "capture_lease_live",
        "manual_start_confirmed",
        "arm_eligible",
        "fail_static",
        "setup_gnss_eligible",
        "setup_reference_eligible",
        "setup_partition_healthy",
        "hybrid_state",
        "hybrid_reason",
        "first_phase_checkpoint_passed",
        "phase_nonzero_application_count",
        "phase_material_application_count",
        "frequency_only_application_count",
        "session_id",
        "query_nonce",
        "uptime_s",
        "evidence_request_sequence",
        "expected_setup_code",
        "confirmed_applied_code_known",
        "confirmed_applied_code",
        "correction_count",
        "cumulative_movement_codes",
        "dac_epoch",
        "selected_interval_count",
        "automatic_retry",
        "automatic_restore",
        "snapshot_generation_complete",
    )
    visitor_keys = re.findall(r'visitor\(context, "([^"]+)"', visitor)

    assert tuple(visitor_keys) == expected
    assert "otis_cx317_active_live_visit_status(context," in active
    assert "emit_direct_active_status" in active
    assert "otis_cx317_active_live_visit_status(" in dual
    assert "publish_dual_core_active_status_field" in dual

    header = (FIRMWARE / "otis_cx317_active_live.h").read_text(
        encoding="utf-8"
    )
    status_getter = active[
        active.index("void otis_cx317_active_live_get_status") : active.index(
            "const char *otis_cx317_active_live_run_identity"
        )
    ]
    assert "bool evidence_pending;" in header
    assert "bool confirmed_applied_code_known;" in header
    assert "status->evidence_pending = evidence_phase != EvidencePhase::None;" in (
        status_getter
    )
    assert "transaction_bound && manual_start_confirmed" in status_getter
    assert '"0x%04X"' in visitor
    assert "OTIS_CX317_ACTIVE_STATUS_SNAPSHOT_CONTRACT" in visitor
    assert '"unavailable"' in visitor


def test_stage7_dual_core_authority_has_four_durable_phases_and_one_owner() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    timing_inputs = sketch[
        sketch.index("void service_dual_core_timing_inputs") :
        sketch.index("void service_dual_core_outputs")
    ]
    core0_actuator = sketch[
        sketch.index("void service_dual_core_actuator_request") :
        sketch.index("void service_dual_core_outputs")
    ]
    loop1 = sketch[sketch.index("void loop1()") : sketch.index("void loop()")]

    assert 'queue_frame("core0_accepted"' in live
    assert "EvidencePhase::Request" in live
    assert "EvidencePhase::Acceptance" in live
    assert "EvidencePhase::Application" in live
    assert "EvidencePhase::Response" in live
    assert "OtisCriticalMessageKind::ActuatorRequest" in live
    assert "OtisCriticalMessageKind::ActuatorExecute" in live
    assert "OtisServiceMessageKind::ActuatorAcknowledgement" in timing_inputs
    assert "otis_cx317_active_live_on_cross_core_ack" in timing_inputs
    assert core0_actuator.count("otis_cx317_active_actuator_apply_once") == 1
    assert "otis_actuator_guard_check_deadline" in core0_actuator
    assert "exact_release" in core0_actuator
    assert "retry" not in core0_actuator.lower()
    assert "restore" not in core0_actuator.lower()
    assert "service_cx317_active_health();" in loop1
    assert "service_cx317_active_application_outcome();" in loop1
    assert "queue_dual_core_active_control" in sketch


def test_stage7_part_b_prospective_dither_guards_are_prewrite() -> None:
    source = (FIRMWARE / "otis_cx317_active_transaction.cpp").read_text(
        encoding="utf-8"
    )
    make_request = source[
        source.index("bool otis_cx317_active_make_request") :
        source.index("bool otis_cx317_active_accept")
    ]
    assert "prospective_third_consecutive_reversal_dither_stop" in make_request
    assert "prospective_low_net_excess_path_dither_stop" in make_request
    assert make_request.index(
        "prospective_third_consecutive_reversal_dither_stop"
    ) < make_request.index("transaction->request = *request")
    assert make_request.index(
        "prospective_low_net_excess_path_dither_stop"
    ) < make_request.index("transaction->request = *request")


def test_only_supported_bounded_control_profiles_compile_active_in() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    active_profiles = {
        "cx319_tight_lower",
        "cx319_tight_upper",
        "cx319_range_part_b_lower",
        "cx319_range_part_b_upper",
        "cx319_range_part_b_upper_completion",
        "cx320_active_hybrid",
    }
    for profile in matrix["profiles"]:
        if profile["expect"] != "pass":
            continue
        enabled = profile["defines"].get(
            "OTIS_ENABLE_CX317_BOUNDED_ACTIVE", "0"
        )
        if profile["id"] in active_profiles:
            assert enabled == "1"
        else:
            assert enabled == "0"
