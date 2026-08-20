"""Validate the machine-readable non-effective CX320 authority proposal."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from .active_hybrid_bundle import REQUIRED_FALSE_AUTHORITY, validate_bundle


TOOL_ID = "cx320_active_hybrid_authority_proposal_validator_v1"
PROPOSAL_ID = "cx320_active_hybrid_physical_authority_proposal_v1"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
ROOT_BUNDLE_SHA256 = "62ee48c2e8e20e78f30b5c77d7457b37f6f8495b0a536a6b349f59c777d50fae"
ROOT_PROPOSAL_SHA256 = "153577ae94dce4faaf5942a80b4118cd51817e9e291f496b80d75e0a200d38f4"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"CX320 proposal binding is unavailable: {path}")
    return {
        "path": str(path),
        "file_sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable CX320 proposal write: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _semantic_object(path: Path, field: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"CX320 lineage artifact is not an object: {path}")
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    if claimed != _canonical_sha256(unsigned):
        raise ValueError(f"CX320 lineage semantic identity differs: {path}")
    return value


def _progressive_envelope() -> dict[str, Any]:
    return {
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
    }


def create_successor_proposal(
    *,
    bundle_path: Path,
    parent_proposal_path: Path,
    operator_authority_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create a non-effective successor under the already-authorized root."""

    bundle_path = bundle_path.resolve()
    parent_proposal_path = parent_proposal_path.resolve()
    operator_authority_path = operator_authority_path.resolve()
    bundle = validate_bundle(bundle_path)
    parent = _semantic_object(parent_proposal_path, "proposal_sha256")
    authority = json.loads(operator_authority_path.read_text(encoding="utf-8"))
    if (
        parent.get("proposal_sha256") != ROOT_PROPOSAL_SHA256
        or parent.get("exact_bundle", {}).get("bundle_sha256")
        != ROOT_BUNDLE_SHA256
        or not isinstance(authority, dict)
        or authority.get("authority_type")
        != "cx320_explicit_operator_authority_v1"
        or authority.get("named_bundle_sha256") != ROOT_BUNDLE_SHA256
        or authority.get("named_proposal_sha256") != ROOT_PROPOSAL_SHA256
        or authority.get("stage_5_effective") is not True
        or authority.get("expanded_recovery_authority", {}).get("effective")
        is not True
        or authority.get("frozen_scientific_boundary", {}).get(
            "controller_thresholds_may_change_without_new_decision"
        )
        is not False
    ):
        raise ValueError("CX320 successor proposal authority lineage differs")
    authority_fields = {name: False for name in REQUIRED_FALSE_AUTHORITY}
    authority_fields.update(
        {
            "offline_preparation": True,
            "separate_exact_bundle_operator_decision_required": True,
            "consumed": False,
        }
    )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "proposal_id": PROPOSAL_ID,
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "non_effective_awaiting_separate_operator_decision",
        "programme_id": PROGRAMME_ID,
        "run_identity": bundle["run_identity"],
        "exact_bundle": {
            **_binding(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "policy_sha256": bundle["policy"]["policy_sha256"],
        "build_identity": bundle["firmware"]["build_identity"],
        "firmware_uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "progressive_envelope": _progressive_envelope(),
        "requested_after_separate_decision": {
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
        },
        "authority": authority_fields,
        "claim_boundary": {
            "offline_replay_is_not_observed_physical_response": True,
            "operational_rehearsal_is_not_physical_plant_qualification": True,
            "current_physical_actions_authorized": 0,
            "current_DAC_writes_authorized": 0,
        },
        "lineage": {
            "root_authorized_bundle_sha256": ROOT_BUNDLE_SHA256,
            "root_authorized_proposal_sha256": ROOT_PROPOSAL_SHA256,
            "parent_proposal": {
                **_binding(parent_proposal_path),
                "proposal_sha256": parent["proposal_sha256"],
            },
            "operator_authority": _binding(operator_authority_path),
            "successor_reason": (
                "pre-entry materiality-counterfactual and live-path platform "
                "repairs under expanded recovery authority"
            ),
            "scientific_thresholds_criteria_and_duration_unchanged": True,
            "automatic_controller_retry": False,
            "automatic_restoration": False,
        },
    }
    proposal = {
        **unsigned,
        "proposal_sha256": _canonical_sha256(unsigned),
    }
    _atomic_new_json(output_path, proposal)
    return proposal


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
    if proposal.get("progressive_envelope") != _progressive_envelope():
        raise ValueError("CX320 proposal progressive envelope differs")
    lineage = proposal.get("lineage")
    if lineage is not None:
        if not isinstance(lineage, dict):
            raise ValueError("CX320 proposal lineage is malformed")
        parent = lineage.get("parent_proposal", {})
        operator = lineage.get("operator_authority", {})
        parent_path = Path(str(parent.get("path", ""))).resolve()
        operator_path = Path(str(operator.get("path", ""))).resolve()
        parent_value = _semantic_object(parent_path, "proposal_sha256")
        authority_value = json.loads(operator_path.read_text(encoding="utf-8"))
        if (
            lineage.get("root_authorized_bundle_sha256")
            != ROOT_BUNDLE_SHA256
            or lineage.get("root_authorized_proposal_sha256")
            != ROOT_PROPOSAL_SHA256
            or parent.get("file_sha256") != _sha256_file(parent_path)
            or parent.get("size_bytes") != parent_path.stat().st_size
            or parent.get("proposal_sha256") != ROOT_PROPOSAL_SHA256
            or parent_value.get("proposal_sha256") != ROOT_PROPOSAL_SHA256
            or operator.get("file_sha256") != _sha256_file(operator_path)
            or operator.get("size_bytes") != operator_path.stat().st_size
            or authority_value.get("named_bundle_sha256")
            != ROOT_BUNDLE_SHA256
            or authority_value.get("named_proposal_sha256")
            != ROOT_PROPOSAL_SHA256
            or authority_value.get("stage_5_effective") is not True
            or lineage.get(
                "scientific_thresholds_criteria_and_duration_unchanged"
            )
            is not True
            or lineage.get("automatic_controller_retry") is not False
            or lineage.get("automatic_restoration") is not False
        ):
            raise ValueError("CX320 successor proposal lineage differs")
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path, nargs="?")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--parent-proposal", type=Path)
    parser.add_argument("--operator-authority", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.create:
        if None in (
            args.bundle,
            args.parent_proposal,
            args.operator_authority,
            args.output,
        ):
            parser.error(
                "--create requires --bundle, --parent-proposal, "
                "--operator-authority and --output"
            )
        result = create_successor_proposal(
            bundle_path=args.bundle,
            parent_proposal_path=args.parent_proposal,
            operator_authority_path=args.operator_authority,
            output_path=args.output,
        )
    else:
        if args.proposal is None:
            parser.error("proposal path is required for validation")
        result = validate_proposal(args.proposal)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
