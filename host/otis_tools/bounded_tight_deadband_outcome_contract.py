"""Shared verdict for bounded tight-deadband rehearsal and physical evidence."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


SCHEMA_VERSION = 1
CONTRACT_ID = "cx319_g2_leg_a_outcome_contract_v2"
SETUP_CODE = 0xA808
MINIMUM_CODE = 0xA800
MAXIMUM_CODE = 0xAB00
MAXIMUM_CORRECTIONS = 4
MAXIMUM_STEP_CODES = 21
MAXIMUM_CUMULATIVE_CODES = 84
MINIMUM_CADENCE_S = 1800
QUALIFICATION_DEADLINE_S = 5400
MAXIMUM_QUALIFIED_DURATION_S = 14400

_ARM = re.compile(r"ACTIVE ARM ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*)\Z")
_LEASE = re.compile(r"ACTIVE LEASE ([1-9][0-9]*)\Z")
_EVIDENCE = re.compile(r"ACTIVE EVIDENCE ([1-9][0-9]*) ([1-4])\Z")


def canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def normal_command_allowed(command: str) -> bool:
    if command in {"CONFIG?", "DAC?", "FC0?", "ACTIVE?"}:
        return True
    if _LEASE.fullmatch(command) or _ARM.fullmatch(command) or _EVIDENCE.fullmatch(
        command
    ):
        return True
    return command == "DAC SET 0xA808"


def _bool_false(value: Any) -> bool:
    return value is False or value == "false"


def evaluate(transcript: dict[str, Any]) -> dict[str, Any]:
    mode = transcript.get("mode")
    offline = mode == "accelerated_offline_no_io"
    physical = mode == "physical_frequency_only_live"
    commands = transcript.get("commands", [])
    setup = transcript.get("setup", {})
    transactions = transcript.get("automatic_transactions", [])
    tight = transcript.get("tight_entry", {})
    transport = transcript.get("transport_fault", {})
    closure = transcript.get("closure", {})
    limits = transcript.get("limits", {})
    preview = transcript.get("phase_and_hybrid", {})

    command_values = [
        item.get("command") for item in commands if isinstance(item, dict)
    ]
    normal = [
        item
        for item in commands
        if isinstance(item, dict) and item.get("path") == "normal"
    ]
    emergency = [
        item
        for item in commands
        if isinstance(item, dict) and item.get("path") == "emergency"
    ]
    setups = [command for command in command_values if command == "DAC SET 0xA808"]
    arms = [command for command in command_values if isinstance(command, str) and _ARM.fullmatch(command)]
    evidence = [command for command in command_values if isinstance(command, str) and _EVIDENCE.fullmatch(command)]

    applications = [
        item
        for item in transactions
        if isinstance(item, dict) and item.get("result") == "healthy_completed"
    ]
    movements = [
        abs(int(item.get("delta_codes", 0)))
        for item in transactions
        if isinstance(item, dict)
    ]
    application_times = [
        int(item.get("application_timestamp_s", 0))
        for item in transactions
        if isinstance(item, dict)
    ]
    cadence_exact = all(
        later - earlier >= MINIMUM_CADENCE_S
        for earlier, later in zip(application_times, application_times[1:])
    )
    positive_healthy = [
        item for item in applications if int(item.get("delta_codes", 0)) > 0
    ]
    hardware = transcript.get("hardware_operations", {})
    authority = transcript.get("authority", {})
    terminal = transcript.get("terminal", {})
    host_attach = transcript.get("host_attach_telemetry", {})
    gnss_prewrite = transcript.get("gnss_prewrite", {})
    bounded_nonpass = terminal.get("result") == "bounded_nonpass"

    checks = {
        "identity_and_mode_exact": (
            transcript.get("schema_version") == SCHEMA_VERSION
            and transcript.get("contract_id") == CONTRACT_ID
            and transcript.get("programme_id")
            == "cx319_stabilized_tight_deadband"
            and transcript.get("gate") == "G2"
            and transcript.get("leg") == "A"
            and (offline or physical)
        ),
        "authority_and_hardware_operations_match_mode": (
            (
                offline
                and authority.get("effective") is False
                and all(
                    hardware.get(key) == 0
                    for key in (
                        "serial_opens",
                        "firmware_flashes",
                        "dac_writes",
                        "control_arms",
                    )
                )
            )
            or (
                physical
                and authority.get("effective") is True
                and hardware.get("serial_opens") == 1
                and hardware.get("firmware_flashes") == 0
                and hardware.get("dac_writes") == len(transactions) + 1
                and isinstance(hardware.get("control_arms"), int)
                and hardware["control_arms"] >= len(transactions)
                and hardware["control_arms"] <= MAXIMUM_CORRECTIONS
            )
        ),
        "normal_command_envelope_exact_and_acknowledged": (
            bool(normal)
            and all(
                isinstance(item.get("command"), str)
                and normal_command_allowed(item["command"])
                and item.get("acknowledged") is True
                for item in normal
            )
        ),
        "single_exact_setup_transaction": (
            len(setups) == 1
            and setup.get("requested_code") == SETUP_CODE
            and setup.get("applied_code") == SETUP_CODE
            and setup.get("dac_epoch") == 1
            and setup.get("acknowledged") is True
        ),
        "one_shot_arm_and_durable_phase_ack_path": (
            bool(arms)
            and evidence == [
                "ACTIVE EVIDENCE 1 1",
                "ACTIVE EVIDENCE 1 2",
                "ACTIVE EVIDENCE 1 3",
                "ACTIVE EVIDENCE 1 4",
            ]
        ),
        "healthy_positive_automatic_transaction": bool(positive_healthy),
        "automatic_limits_range_and_cadence_exact": (
            len(transactions) <= MAXIMUM_CORRECTIONS
            and all(0 < movement <= MAXIMUM_STEP_CODES for movement in movements)
            and sum(movements) <= MAXIMUM_CUMULATIVE_CODES
            and cadence_exact
            and all(
                MINIMUM_CODE <= int(item.get("applied_code", -1)) <= MAXIMUM_CODE
                for item in transactions
                if isinstance(item, dict)
            )
            and limits
            == {
                "maximum_automatic_corrections": MAXIMUM_CORRECTIONS,
                "maximum_step_codes": MAXIMUM_STEP_CODES,
                "maximum_cumulative_codes": MAXIMUM_CUMULATIVE_CODES,
                "minimum_applied_cadence_s": MINIMUM_CADENCE_S,
                "settling_exclusion_s": 900,
                "fresh_support_s": 600,
                "qualification_deadline_s": QUALIFICATION_DEADLINE_S,
                "maximum_qualified_duration_s": MAXIMUM_QUALIFIED_DURATION_S,
            }
        ),
        "two_estimate_tight_entry_exact": (
            tight.get("consecutive_estimates") == 2
            and tight.get("integer_edge_error_counts") == [2, -2]
            and tight.get("terminal_state") == "TIGHT_INSIDE"
            and tight.get("current_dac_epoch") == 2
        ),
        "phase_and_hybrid_zero_authority": (
            _bool_false(preview.get("actionable"))
            and _bool_false(preview.get("actuation_authorized"))
            and _bool_false(preview.get("authorization_consumed"))
            and preview.get("frequency_controller_input") is False
        ),
        "host_attach_telemetry_baseline_stable_and_fail_closed": (
            host_attach.get("ordinary_telemetry_is_diagnostic_and_lossy") is True
            and isinstance(host_attach.get("frozen_baseline"), int)
            and host_attach["frozen_baseline"] >= 0
            and int(host_attach.get("stable_observations", 0)) >= 2
            and host_attach.get(
                "all_evidence_capture_preview_partition_and_control_gates_absolute"
            )
            is True
            and host_attach.get("post_attach_increment_rejected") is True
            and host_attach.get("first_firmware_uptime_observation_frozen")
            is True
            and host_attach.get("firmware_uptime_s") == 30
            and host_attach.get("maximum_fresh_attach_uptime_s") == 120
            and host_attach.get("late_attach_rejected") is True
        ),
        "gnss_identity_and_control_authority_exact_before_setup": (
            gnss_prewrite.get("identity_epoch") == 1
            and gnss_prewrite.get("identity_stable") is True
            and gnss_prewrite.get("metadata_control_eligible") is True
            and gnss_prewrite.get("raw_pps_control_eligible") is True
            and gnss_prewrite.get("control_eligible") is True
            and gnss_prewrite.get("epoch_2_rejected_before_setup") is True
            and gnss_prewrite.get("raw_pps_false_before_deadline_no_setup")
            is True
            and gnss_prewrite.get("raw_pps_ready_uptime_s") == 612
            and gnss_prewrite.get("qualification_deadline_s") == 660
            and gnss_prewrite.get(
                "missing_raw_pps_at_deadline_rejected"
            )
            is True
        ),
        "obstruction_priority_abort_and_owner_invariants": (
            transport.get("normal_path_saturated") is True
            and transport.get("priority_abort_observed") is True
            and transport.get("sole_owner") is True
            and transport.get("serial_reopened") is False
        ),
        "analysis_seal_registration_path_complete": (
            closure.get("analyzer_ran") is True
            and closure.get("seal_created") is True
            and (
                (offline and closure.get("registration_rehearsed") is True)
                or (physical and closure.get("registration_completed") is True)
            )
            and (
                (offline and closure.get("same_owner_rotation") is True)
                or (physical and closure.get("clean_physical_close") is True)
            )
        ),
        "emergency_path_is_abort_only": (
            (
                offline
                and len(emergency) == 1
                and emergency[0].get("command") == "ACTIVE ABORT"
                and emergency[0].get("acknowledged") is True
            )
            or (
                physical
                and not bounded_nonpass
                and not emergency
            )
            or (
                physical
                and bounded_nonpass
                and len(emergency) == 1
                and emergency[0].get("command") == "ACTIVE ABORT"
                and emergency[0].get("acknowledged") is True
            )
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "observed": {
            "normal_command_count": len(normal),
            "emergency_command_count": len(emergency),
            "setup_count": len(setups),
            "arm_count": len(arms),
            "evidence_ack_count": len(evidence),
            "automatic_transaction_count": len(transactions),
            "healthy_positive_transaction_count": len(positive_healthy),
            "cumulative_movement_codes": sum(movements),
        },
    }
