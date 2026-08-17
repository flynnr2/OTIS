"""Shared verdict for bounded tight-deadband rehearsal and physical evidence."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from .bounded_tight_deadband_leg import LOWER, UPPER, leg_for


SCHEMA_VERSION = 1
CONTRACT_ID = LOWER.outcome_contract_id
UPPER_CONTRACT_ID = UPPER.outcome_contract_id
SETUP_CODE = LOWER.setup_code
UPPER_SETUP_CODE = UPPER.setup_code
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
_SNAPSHOT = re.compile(r"ACTIVE SNAPSHOT ([1-9][0-9]*)\Z")
_SETUP = re.compile(
    r"ACTIVE SETUP ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) "
    r"([1-9][0-9]*) ([1-9][0-9]*) 0x(?:A800|A808|A83C|A848|A890) 1 ([0-9a-f]{64})\Z",
    re.IGNORECASE,
)


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
    if _SNAPSHOT.fullmatch(command):
        return True
    if _SETUP.fullmatch(command):
        return True
    if _LEASE.fullmatch(command) or _ARM.fullmatch(command) or _EVIDENCE.fullmatch(
        command
    ):
        return True
    return False


def _bool_false(value: Any) -> bool:
    return value is False or value == "false"


def evaluate(transcript: dict[str, Any]) -> dict[str, Any]:
    gate = transcript.get("gate")
    leg = transcript.get("leg")
    try:
        selected_leg = leg_for(gate, leg)
    except ValueError:
        selected_leg = None
    contract_id = selected_leg.outcome_contract_id if selected_leg else None
    setup_code = selected_leg.setup_code if selected_leg else None
    required_sign = selected_leg.required_sign if selected_leg else 0
    required_name = selected_leg.required_direction if selected_leg else "unknown"
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
    setups = [
        command
        for command in command_values
        if isinstance(command, str) and _SETUP.fullmatch(command)
    ]
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
        later - earlier
        >= (selected_leg.minimum_cadence_s if selected_leg else MINIMUM_CADENCE_S)
        for earlier, later in zip(application_times, application_times[1:])
    )
    required_direction_healthy = [
        item
        for item in applications
        if int(item.get("delta_codes", 0)) * required_sign > 0
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
            and contract_id is not None
            and transcript.get("contract_id") == contract_id
            and transcript.get("programme_id")
            == (selected_leg.programme_id if selected_leg else None)
            and transcript.get("gate") == gate
            and transcript.get("leg") == leg
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
                and selected_leg is not None
                and hardware.get("firmware_flashes")
                == int(selected_leg.firmware_flash)
                and hardware.get("dac_writes") == len(transactions) + 1
                and isinstance(hardware.get("control_arms"), int)
                and hardware["control_arms"] >= len(transactions)
                and hardware["control_arms"] <= selected_leg.correction_limit
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
            and setup.get("requested_code") == setup_code
            and setup.get("applied_code") == setup_code
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
        "healthy_required_direction_automatic_transaction": bool(
            required_direction_healthy
        ),
        "automatic_limits_range_and_cadence_exact": (
            selected_leg is not None
            and len(transactions) <= selected_leg.correction_limit
            and all(0 < movement <= selected_leg.maximum_step_codes for movement in movements)
            and sum(movements) <= selected_leg.cumulative_limit_codes
            and cadence_exact
            and all(
                MINIMUM_CODE <= int(item.get("applied_code", -1)) <= MAXIMUM_CODE
                for item in transactions
                if isinstance(item, dict)
            )
            and limits
            == {
                "maximum_automatic_corrections": selected_leg.correction_limit,
                "maximum_step_codes": selected_leg.maximum_step_codes,
                "maximum_cumulative_codes": selected_leg.cumulative_limit_codes,
                "minimum_applied_cadence_s": selected_leg.minimum_cadence_s,
                "settling_exclusion_s": 900,
                "fresh_support_s": 600,
                "qualification_deadline_s": QUALIFICATION_DEADLINE_S,
                "maximum_qualified_duration_s": selected_leg.maximum_qualified_duration_s,
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
            and isinstance(host_attach.get("post_attachment_query_nonce"), int)
            and host_attach["post_attachment_query_nonce"] > 0
            and isinstance(host_attach.get("frozen_snapshot_generation"), int)
            and host_attach["frozen_snapshot_generation"] > 0
            and host_attach.get("pre_attachment_backlog_rejected") is True
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
        "contract_id": contract_id,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "observed": {
            "normal_command_count": len(normal),
            "emergency_command_count": len(emergency),
            "setup_count": len(setups),
            "arm_count": len(arms),
            "evidence_ack_count": len(evidence),
            "automatic_transaction_count": len(transactions),
            "required_direction": required_name,
            "healthy_required_direction_transaction_count": len(
                required_direction_healthy
            ),
            "cumulative_movement_codes": sum(movements),
        },
    }
