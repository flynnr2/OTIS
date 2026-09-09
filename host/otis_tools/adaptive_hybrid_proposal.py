"""Create and validate the one non-effective adaptive-hybrid authority proposal."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from .adaptive_hybrid_bundle import REQUIRED_FALSE_AUTHORITY, validate_bundle
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    AdaptiveHybridProgramme,
    integrated_setup_provenance_contract,
    progressive_checkpoint_contract,
    programme_from_mapping,
)


TOOL_ID = "adaptive_hybrid_authority_proposal_v1"
PROPOSAL_ID = "adaptive_hybrid_regulation_authority_proposal_v1"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise ValueError(f"proposal binding is unavailable: {source}")
    return {
        "path": str(source),
        "file_sha256": _sha256_file(source),
        "size_bytes": source.stat().st_size,
    }


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable proposal write: {destination}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _progressive_envelope(programme: AdaptiveHybridProgramme) -> dict[str, Any]:
    return {
        "maximum_total_automatic_applications": programme.maximum_applications,
        "maximum_total_physical_control_applications": programme.maximum_physical_applications,
        **progressive_checkpoint_contract(programme),
        "maximum_combined_step_codes": programme.maximum_step_codes,
        "maximum_cumulative_absolute_movement_codes": programme.maximum_cumulative_movement_codes,
        "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
        "minimum_code": programme.minimum_code,
        "maximum_code": programme.maximum_code,
        "qualified_duration_s": programme.qualified_duration_s,
        "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
        "retry": False,
        "extension": False,
    }


def _requested_authority(programme: AdaptiveHybridProgramme) -> dict[str, Any]:
    return {
        "firmware_flash_limit": 1,
        "reset_for_entry_or_bounded_recovery": True,
        "serial_access": True,
        "command_fifo": True,
        "exact_setup_application_limit": 1,
        "control_arm_limit": 1,
        "physical_operational_rehearsal_limit": 1,
        "live_acquisition_limit": 1,
        "authority_consumed_by_first_physical_terminal": True,
        "automatic_retry": False,
        "automatic_restoration": False,
        "setup_provenance": integrated_setup_provenance_contract(programme),
    }


def _non_effective_authority() -> dict[str, Any]:
    return {
        **{name: False for name in REQUIRED_FALSE_AUTHORITY},
        "offline_preparation": True,
        "separate_exact_bundle_operator_decision_required": True,
        "consumed": False,
    }


def create_proposal(
    *, bundle_path: Path, output_path: Path,
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    bundle = validate_bundle(bundle_path, programme)
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "proposal_id": programme.activation_id.replace("activation", "authority_proposal"),
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "non_effective_awaiting_separate_operator_decision",
        "programme_id": programme.programme_id,
        "run_identity": programme.runtime_run_identity,
        "image_identity": programme.profile_id,
        "exact_bundle": {**_binding(bundle_path), "bundle_sha256": bundle["bundle_sha256"]},
        "policy_sha256": bundle["policy"]["policy_sha256"],
        "build_identity": bundle["firmware"]["build_identity"],
        "progressive_envelope": _progressive_envelope(programme),
        "requested_after_separate_decision": _requested_authority(programme),
        "authority": _non_effective_authority(),
        "claim_boundary": {
            "offline_replay_is_not_observed_physical_response": True,
            "operational_rehearsal_is_not_physical_plant_qualification": True,
            "current_physical_actions_authorized": 0,
            "current_DAC_writes_authorized": 0,
        },
        "persistent_maintenance": bundle["persistent_maintenance"],
    }
    proposal = {**unsigned, "proposal_sha256": _canonical_sha256(unsigned)}
    _atomic_new_json(output_path, proposal)
    return proposal


def validate_proposal(
    path: Path, programme: AdaptiveHybridProgramme | None = None,
) -> dict[str, Any]:
    proposal = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(proposal, dict):
        raise ValueError("authority proposal root must be an object")
    claimed = proposal.get("proposal_sha256")
    unsigned = {key: value for key, value in proposal.items() if key != "proposal_sha256"}
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("proposal semantic identity differs")
    selected = programme or programme_from_mapping(proposal)
    binding = proposal.get("exact_bundle", {})
    bundle_path = Path(str(binding.get("path", ""))).resolve()
    bundle = validate_bundle(bundle_path, selected)
    if (
        proposal.get("proposal_id") != selected.activation_id.replace("activation", "authority_proposal")
        or proposal.get("programme_id") != selected.programme_id
        or proposal.get("run_identity") != selected.runtime_run_identity
        or proposal.get("image_identity") != selected.profile_id
        or proposal.get("status") != "non_effective_awaiting_separate_operator_decision"
        or proposal.get("authority") != _non_effective_authority()
        or binding.get("file_sha256") != _sha256_file(bundle_path)
        or binding.get("bundle_sha256") != bundle["bundle_sha256"]
        or proposal.get("policy_sha256") != bundle["policy"]["policy_sha256"]
        or proposal.get("build_identity") != bundle["firmware"]["build_identity"]
        or proposal.get("progressive_envelope") != _progressive_envelope(selected)
        or proposal.get("requested_after_separate_decision") != _requested_authority(selected)
        or proposal.get("persistent_maintenance") != bundle["persistent_maintenance"]
    ):
        raise ValueError("proposal identity, authority, or bundle binding differs")
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--bundle", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    value = (
        create_proposal(bundle_path=args.bundle, output_path=args.output)
        if args.command == "create"
        else validate_proposal(args.proposal)
    )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
