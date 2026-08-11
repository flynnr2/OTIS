"""Shared semantic verdict for CX319 G2 accelerated and physical evidence."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


SCHEMA_VERSION = 1
CONTRACT_ID = "cx319_g2_leg_a_outcome_contract_v1"
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

    checks = {
        "identity_and_mode_exact": (
            transcript.get("schema_version") == SCHEMA_VERSION
            and transcript.get("contract_id") == CONTRACT_ID
            and transcript.get("programme_id")
            == "cx319_stabilized_tight_deadband"
            and transcript.get("gate") == "G2"
            and transcript.get("leg") == "A"
            and transcript.get("mode") == "accelerated_offline_no_io"
        ),
        "no_effective_physical_authority": (
            transcript.get("authority", {}).get("effective") is False
            and all(
                transcript.get("hardware_operations", {}).get(key) == 0
                for key in (
                    "serial_opens",
                    "firmware_flashes",
                    "dac_writes",
                    "control_arms",
                )
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
        "obstruction_priority_abort_and_owner_invariants": (
            transport.get("normal_path_saturated") is True
            and transport.get("priority_abort_observed") is True
            and transport.get("sole_owner") is True
            and transport.get("serial_reopened") is False
        ),
        "analysis_seal_registration_path_complete": (
            closure.get("analyzer_ran") is True
            and closure.get("seal_created") is True
            and closure.get("registration_rehearsed") is True
            and closure.get("same_owner_rotation") is True
        ),
        "emergency_path_is_abort_only": (
            len(emergency) == 1
            and emergency[0].get("command") == "ACTIVE ABORT"
            and emergency[0].get("acknowledged") is True
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
