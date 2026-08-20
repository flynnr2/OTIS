"""Validate the machine-readable non-effective CX320 authority proposal."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_hybrid_bundle import REQUIRED_FALSE_AUTHORITY, validate_bundle


TOOL_ID = "cx320_active_hybrid_authority_proposal_validator_v1"
PROPOSAL_ID = "cx320_active_hybrid_physical_authority_proposal_v1"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_proposal(path: Path) -> dict[str, Any]:
    path = path.resolve()
    proposal = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(proposal, dict):
        raise ValueError("CX320 authority proposal root must be an object")
    claimed = proposal.pop("proposal_sha256", None)
    observed = _canonical_sha256(proposal)
    proposal["proposal_sha256"] = claimed
    if claimed != observed:
        raise ValueError("CX320 proposal semantic identity differs")
    if (
        proposal.get("proposal_id") != PROPOSAL_ID
        or proposal.get("status") != "non_effective_awaiting_separate_operator_decision"
    ):
        raise ValueError("unexpected CX320 proposal identity")
    authority = proposal.get("authority", {})
    if any(authority.get(name) is not False for name in REQUIRED_FALSE_AUTHORITY):
        raise ValueError("CX320 proposal contains effective physical authority")
    bundle_binding = proposal.get("exact_bundle", {})
    bundle_path = Path(str(bundle_binding.get("path", "")))
    if not bundle_path.is_file() or _sha256_file(bundle_path) != bundle_binding.get("file_sha256"):
        raise ValueError("CX320 proposal exact bundle file binding differs")
    bundle = validate_bundle(bundle_path)
    if bundle["bundle_sha256"] != bundle_binding.get("bundle_sha256"):
        raise ValueError("CX320 proposal exact bundle semantic identity differs")
    if proposal.get("run_identity") != bundle["run_identity"]:
        raise ValueError("CX320 proposal run identity differs")
    if proposal.get("policy_sha256") != bundle["policy"]["policy_sha256"]:
        raise ValueError("CX320 proposal policy identity differs")
    if proposal.get("build_identity") != bundle["firmware"]["build_identity"]:
        raise ValueError("CX320 proposal build identity differs")
    if proposal.get("progressive_envelope") != {
        "maximum_total_automatic_applications": 4,
        "first_phase_material_applications_before_checkpoint": 1,
        "minimum_phase_material_applications_for_pass": 2,
        "maximum_combined_step_codes": 21,
        "maximum_cumulative_absolute_movement_codes": 84,
        "minimum_applied_cadence_s": 1800,
        "minimum_code": 43008,
        "maximum_code": 43776,
        "qualified_duration_s": 43200,
        "absolute_wall_clock_limit_s": 57600,
        "retry": False,
        "extension": False,
    }:
        raise ValueError("CX320 proposal progressive envelope differs")
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(validate_proposal(args.proposal), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
