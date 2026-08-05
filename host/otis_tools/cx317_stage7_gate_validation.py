"""Shared fail-closed validation for Stage 7 progression gates."""

from __future__ import annotations

from typing import Any


PART_A_COMPOSITE_TEST = (
    "part_a_composite_fixed_code_stability_and_completed_transaction_prefix_v1"
)


def part_a2_progression_gate_valid(gate: dict[str, Any]) -> bool:
    transactions = gate.get("transactions", {})
    base_valid = (
        gate.get("status") == "pass"
        and gate.get("part") == "part_a"
        and 1 <= int(transactions.get("application_count", 0)) <= 4
        and transactions.get(
            "all_response_classifications_replay_exactly"
        )
        is True
        and 0xA800 <= int(transactions.get("final_code", -1)) <= 0xAB00
    )
    if not base_valid:
        return False
    if gate.get("test") != PART_A_COMPOSITE_TEST:
        return True

    criteria = gate.get("criteria", {})
    source = gate.get("source_a2_disposition", {})
    repair = gate.get("repair_rehearsal", {})
    return (
        bool(criteria)
        and all(value is True for value in criteria.values())
        and gate.get("qualification_evidence") is True
        and gate.get("stage7_progression_authority") is True
        and source.get("source_exit_status") == "fail"
        and source.get("source_run_state") == "partial"
        and source.get("source_run_relabelled_as_pass") is False
        and repair.get("status") == "pass"
        and repair.get("diagnostic_only") is True
        and repair.get("qualification_evidence") is False
        and repair.get("evidence_snapshot_valid") is True
    )
