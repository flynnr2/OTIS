"""Seal the CX319 mapping-informed Part B decision from observed and inferred evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .conditional_part_a_mapping_readiness import validate_readiness_record
from .conditional_part_b_bundle import (
    PROGRAMME_ID,
    _validate_lower_reacquisition_predecessor,
    _validate_upper_completion_predecessor,
)
from .no_write_qualification_bundle import _git_identity
from .range_spanning_bundle import _atomic_new_json, canonical_sha256, sha256_file


SCHEMA_VERSION = 1
TOOL_ID = "cx319_mapping_informed_part_b_programme_sealer_v1"
SEAL_TYPE = "cx319_mapping_informed_part_b_programme_seal_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def create_programme_seal(
    *,
    mapping_readiness_path: Path,
    upper_path: Path,
    upper_completion_path: Path,
    output_path: Path,
    created_utc: str | None = None,
) -> dict[str, Any]:
    """Create a bounded programme decision without fabricating the unrun third leg."""

    mapping_readiness_path = mapping_readiness_path.resolve()
    upper_path = upper_path.resolve()
    upper_completion_path = upper_completion_path.resolve()
    readiness = validate_readiness_record(mapping_readiness_path)
    upper = _validate_upper_completion_predecessor(upper_path)
    completion = _validate_lower_reacquisition_predecessor(upper_completion_path)

    if completion.get("predecessor_leg_seal_sha256") != upper.get("seal_sha256"):
        raise ValueError("upper completion does not bind the exact right-censored upper leg")

    lower_path = Path(upper["lower_pass"]["path"])
    lower = _read(lower_path, "passed physical lower leg")
    lower_transactions = lower.get("transactions", {})
    if (
        lower.get("status") != "passed"
        or lower.get("scientific_outcome")
        != "required_direction_qualification_passed"
        or lower.get("terminal", {}).get("result") != "healthy_stop"
        or lower_transactions.get("application_count") != 2
        or lower_transactions.get("response_count") != 2
        or lower_transactions.get("healthy_required_direction_count") != 2
        or lower.get("tight_entry_transition_count") != 1
    ):
        raise ValueError("lower-leg evidence does not establish the exact physical pass")

    mapping = readiness.get("mapping_evaluation", {})
    transitions = mapping.get("transitions", {})
    lower_outbound = transitions.get("lower_outbound", {})
    lower_return = transitions.get("lower_return", {})
    lower_displacement = mapping.get("directional_displacement", {}).get("lower", {})
    lower_reachability = mapping.get("part_b_reachability", {}).get("lower", {})
    if (
        mapping.get("failures") != []
        or lower_outbound.get("basis") != "observed_mixed_code_distribution"
        or lower_return.get("basis") != "observed_mixed_code_distribution"
        or lower_outbound.get("transition_width_codes", 999) > 4
        or lower_return.get("transition_width_codes", 999) > 4
        or lower_displacement.get("passed") is not True
        or lower_reachability.get("passed") is not True
    ):
        raise ValueError("Part A does not support the bounded lower-repeatability inference")

    source_commit, source_state = _git_identity()
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": sha256_file(Path(__file__)),
        "created_utc": created_utc or _utc_now(),
        "source_git": {"commit": source_commit, "state": source_state},
        "programme_id": PROGRAMME_ID,
        "status": "passed",
        "decision": "programme_objective_satisfied",
        "acceptance_basis": "observed_lower_and_upper_with_inferred_lower_repeatability",
        "observed_results": {
            "part_a_transition_map": {
                "status": "passed",
                "path": str(mapping_readiness_path),
                "file_sha256": sha256_file(mapping_readiness_path),
                "readiness_sha256": readiness["readiness_sha256"],
                "lower_outbound_transition": lower_outbound,
                "lower_return_transition": lower_return,
                "lower_directional_displacement": lower_displacement,
            },
            "part_b_lower_acquisition": {
                **upper["lower_pass"],
                "status": "passed",
                "scientific_outcome": lower["scientific_outcome"],
                "terminal": lower["terminal"],
                "transactions": lower_transactions,
                "tight_entry_transition_count": lower["tight_entry_transition_count"],
            },
            "part_b_upper_traversal": {
                **upper,
                "disposition": "clean_right_censored_traversal_completed_by_bound_continuation",
            },
            "part_b_upper_completion": completion,
        },
        "lower_reacquisition": {
            "planned_sequence_index": 3,
            "physical_acquisition_performed": False,
            "disposition": "inferred_pass",
            "confidence": "high",
            "inference": (
                "Under the same characterized bench conditions and frozen frequency-only "
                "lower-leg policy, a repeated lower acquisition is expected to pass."
            ),
            "basis": [
                "Part A physically mapped the lower crossing in outbound and return directions.",
                "The observed directional displacement remained within the mapping contract.",
                "The first Part B lower acquisition physically produced two healthy required-direction responses and tight entry.",
                "The unrun leg repeats the same 0xA800 lower setup and positive frequency-only acquisition objective.",
                "No retained evidence contradicts lower reacquisition under the same conditions.",
            ],
            "novel_information_foregone": (
                "A later-time repeatability sample under the reacquisition leg's actual thermal "
                "and environmental state was not acquired."
            ),
        },
        "authority": {
            "phase_or_hybrid_actuation_used": False,
            "additional_physical_leg_required_for_this_decision": False,
        },
        "claims_boundary": (
            "This seal closes the mapping-informed Part B decision as passed. It records two "
            "physical Part B acquisitions (the upper result spans its original traversal and "
            "physical completion) and one inferred lower repeatability result. It does not claim "
            "that the lower reacquisition was physically run, does not establish its later-time "
            "repeatability sample, and must not be cited as three independently observed physical "
            "leg passes. A new lower crossing refinement or changed bench condition requires new "
            "physical evidence."
        ),
    }
    result = {**unsigned, "seal_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-readiness", type=Path, required=True)
    parser.add_argument("--upper", type=Path, required=True)
    parser.add_argument("--upper-completion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = create_programme_seal(
        mapping_readiness_path=args.mapping_readiness,
        upper_path=args.upper,
        upper_completion_path=args.upper_completion,
        output_path=args.output,
    )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
