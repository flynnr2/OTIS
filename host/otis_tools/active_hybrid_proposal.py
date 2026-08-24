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
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    CX321_PROGRAMME,
    get_active_hybrid_programme,
    progressive_checkpoint_contract,
    programme_from_mapping,
)


TOOL_ID = "cx320_active_hybrid_authority_proposal_validator_v1"
PROPOSAL_ID = "cx320_active_hybrid_physical_authority_proposal_v1"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
ROOT_BUNDLE_SHA256 = "62ee48c2e8e20e78f30b5c77d7457b37f6f8495b0a536a6b349f59c777d50fae"
ROOT_PROPOSAL_SHA256 = "153577ae94dce4faaf5942a80b4118cd51817e9e291f496b80d75e0a200d38f4"
DEFAULT_SUCCESSOR_REASON = (
    "pre-entry materiality-counterfactual and live-path platform repairs "
    "under expanded recovery authority"
)


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


def _progressive_envelope(
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    return {
        "maximum_total_automatic_applications": programme.maximum_applications,
        "maximum_total_physical_control_applications": programme.maximum_physical_applications,
        "maximum_deliberate_challenges": programme.maximum_deliberate_challenges,
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


def _requested_authority() -> dict[str, Any]:
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
    }


def _non_effective_authority() -> dict[str, Any]:
    value = {name: False for name in REQUIRED_FALSE_AUTHORITY}
    value.update(
        {
            "offline_preparation": True,
            "separate_exact_bundle_operator_decision_required": True,
            "consumed": False,
        }
    )
    return value


def create_successor_proposal(
    *,
    bundle_path: Path,
    parent_proposal_path: Path,
    operator_authority_path: Path,
    output_path: Path,
    successor_reason: str = DEFAULT_SUCCESSOR_REASON,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    """Create a non-effective successor under the already-authorized root."""

    bundle_path = bundle_path.resolve()
    parent_proposal_path = parent_proposal_path.resolve()
    operator_authority_path = operator_authority_path.resolve()
    bundle = (
        validate_bundle(bundle_path)
        if programme is CX320_PROGRAMME
        else validate_bundle(bundle_path, programme)
    )
    successor_reason = successor_reason.strip()
    if not successor_reason:
        raise ValueError("CX320 successor proposal requires a concrete reason")
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
    authority_fields = _non_effective_authority()
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "proposal_id": (
            PROPOSAL_ID
            if programme is CX320_PROGRAMME
            else f"{programme.key}_active_hybrid_physical_authority_proposal_v1"
        ),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "non_effective_awaiting_separate_operator_decision",
        "programme_id": programme.programme_id,
        "run_identity": bundle["run_identity"],
        "exact_bundle": {
            **_binding(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "policy_sha256": bundle["policy"]["policy_sha256"],
        "build_identity": bundle["firmware"]["build_identity"],
        "firmware_uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "progressive_envelope": _progressive_envelope(programme),
        "requested_after_separate_decision": _requested_authority(),
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
            "successor_reason": successor_reason,
            **(
                {
                    "scientific_thresholds_criteria_and_duration_unchanged": True,
                }
                if programme is CX320_PROGRAMME
                else {
                    "natural_controller_mathematics_unchanged": True,
                    "scientific_limits_and_duration_changed_by_current_prospectively_frozen_programme": True,
                    "successor_qualification_criterion_prospectively_frozen": True,
                    "inherits_physical_authority": False,
                }
                if programme.sustained_regulation
                else {
                    "scientific_limits_and_duration_unchanged": True,
                    "successor_qualification_criterion_prospectively_frozen": True,
                    "inherits_physical_authority": False,
                }
            ),
            "automatic_controller_retry": False,
            "automatic_restoration": False,
        },
    }
    if programme.identification_required:
        unsigned["profile_identity"] = programme.profile_id
        unsigned["programme_policy_sha256"] = bundle["programme_policy"][
            "sha256"
        ]
    proposal = {
        **unsigned,
        "proposal_sha256": _canonical_sha256(unsigned),
    }
    _atomic_new_json(output_path, proposal)
    return proposal


def validate_proposal(
    path: Path,
    programme: ActiveHybridProgramme | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    proposal = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(proposal, dict):
        raise ValueError("CX320 authority proposal root must be an object")
    claimed = proposal.pop("proposal_sha256", None)
    observed = _canonical_sha256(proposal)
    proposal["proposal_sha256"] = claimed
    programme = programme or programme_from_mapping(proposal)
    expected_proposal_id = (
        PROPOSAL_ID
        if programme is CX320_PROGRAMME
        else f"{programme.key}_active_hybrid_physical_authority_proposal_v1"
    )
    if claimed != observed:
        raise ValueError("CX320 proposal semantic identity differs")
    if (
        proposal.get("proposal_id") != expected_proposal_id
        or proposal.get("programme_id") != programme.programme_id
        or proposal.get("run_identity") != programme.runtime_run_identity
        or (
            programme.identification_required
            and proposal.get("profile_identity") != programme.profile_id
        )
        or proposal.get("status") != "non_effective_awaiting_separate_operator_decision"
    ):
        raise ValueError("unexpected CX320 proposal identity")
    authority = proposal.get("authority", {})
    if authority != _non_effective_authority():
        raise ValueError("CX320 proposal contains effective physical authority")
    bundle_binding = proposal.get("exact_bundle", {})
    bundle_path = Path(str(bundle_binding.get("path", "")))
    if not bundle_path.is_file() or _sha256_file(bundle_path) != bundle_binding.get("file_sha256"):
        raise ValueError("CX320 proposal exact bundle file binding differs")
    bundle = (
        validate_bundle(bundle_path)
        if programme is CX320_PROGRAMME
        else validate_bundle(bundle_path, programme)
    )
    if bundle["bundle_sha256"] != bundle_binding.get("bundle_sha256"):
        raise ValueError("CX320 proposal exact bundle semantic identity differs")
    if proposal.get("run_identity") != bundle["run_identity"]:
        raise ValueError("CX320 proposal run identity differs")
    if proposal.get("policy_sha256") != bundle["policy"]["policy_sha256"]:
        raise ValueError("CX320 proposal policy identity differs")
    if proposal.get("build_identity") != bundle["firmware"]["build_identity"]:
        raise ValueError("CX320 proposal build identity differs")
    if proposal.get("progressive_envelope") != _progressive_envelope(programme):
        raise ValueError("CX320 proposal progressive envelope differs")
    if proposal.get("requested_after_separate_decision") != _requested_authority():
        raise ValueError("active-hybrid requested authority envelope differs")
    if programme.identification_required and proposal.get(
        "programme_policy_sha256"
    ) != bundle.get("programme_policy", {}).get("sha256"):
        raise ValueError("CX321 proposal programme-policy identity differs")
    lineage = proposal.get("lineage")
    if programme.identification_required and not isinstance(lineage, dict):
        raise ValueError("CX321 proposal requires exact operator authority lineage")
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
            or authority_value.get("authority_type")
            != "cx320_explicit_operator_authority_v1"
            or authority_value.get("stage_5_effective") is not True
            or authority_value.get("expanded_recovery_authority", {}).get(
                "effective"
            )
            is not True
            or authority_value.get("frozen_scientific_boundary", {}).get(
                "controller_thresholds_may_change_without_new_decision"
            )
            is not False
            or (
                programme is CX320_PROGRAMME
                and lineage.get(
                    "scientific_thresholds_criteria_and_duration_unchanged"
                )
                is not True
            )
            or (
                programme.identification_required
                and (
                    lineage.get("scientific_limits_and_duration_unchanged")
                    is not True
                    or lineage.get(
                        "successor_qualification_criterion_prospectively_frozen"
                    )
                    is not True
                    or lineage.get("inherits_physical_authority") is not False
                )
            )
            or (
                programme.sustained_regulation
                and (
                    lineage.get("natural_controller_mathematics_unchanged")
                    is not True
                    or lineage.get(
                        "scientific_limits_and_duration_changed_by_current_prospectively_frozen_programme"
                    )
                    is not True
                    or lineage.get(
                        "successor_qualification_criterion_prospectively_frozen"
                    )
                    is not True
                    or lineage.get("inherits_physical_authority") is not False
                )
            )
            or lineage.get("automatic_controller_retry") is not False
            or lineage.get("automatic_restoration") is not False
            or not isinstance(lineage.get("successor_reason"), str)
            or not lineage["successor_reason"].strip()
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
    parser.add_argument("--successor-reason", default=DEFAULT_SUCCESSOR_REASON)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--programme", choices=("cx320", "cx321", "cx322", "sustained_hybrid"), default="cx320"
    )
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
            successor_reason=args.successor_reason,
            programme=get_active_hybrid_programme(args.programme),
        )
    else:
        if args.proposal is None:
            parser.error("proposal path is required for validation")
        result = validate_proposal(args.proposal)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
