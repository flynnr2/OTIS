"""Freeze one conditional CX319 Part B leg behind exact predecessor evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from tools.firmware_matrix import configuration_hash, load_matrix, source_input_hash

from .bounded_tight_deadband_bundle import _atomic_new, _binding, _load_policy
from .bounded_tight_deadband_leg import (
    RANGE_LOWER,
    RANGE_UPPER,
    RANGE_UPPER_COMPLETION,
    BoundedTightDeadbandLeg,
)
from .conditional_part_a_mapping_readiness import validate_readiness_record
from .no_write_qualification_bundle import MATRIX_PATH, POLICY_PATH, _git_identity
from .range_spanning_bundle import canonical_sha256, sha256_file


SCHEMA_VERSION = 1
TOOL_ID = "cx319_conditional_part_b_proposal_v1"
PROGRAMME_ID = "CX319_MAPPING_INFORMED_FREQUENCY_TRAVERSAL_V4"
UPPER_COMPLETION_PROGRAMME_ID = "CX319_MAPPING_INFORMED_UPPER_COMPLETION_V1"
EXPECTED_FQBN = "rp2040:rp2040:arduino_nano_connect:freq=133"
PROGRAMME_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "profiles/qualification/cx319_mapping_informed_frequency_traversal_v4.json"
)
PART_B_HYBRID_PREVIEW = (
    Path(__file__).resolve().parents[2]
    / "profiles/discipline/cx319_conditional_part_b_hybrid_observation_v1.json"
)

HOST_TOOL_PATHS = {
    "bundle": Path(__file__),
    "proposal_dispatch": Path(__file__).with_name("bounded_tight_deadband_proposal.py"),
    "leg_contract": Path(__file__).with_name("bounded_tight_deadband_leg.py"),
    "activation": Path(__file__).with_name("bounded_tight_deadband_activation.py"),
    "runner": Path(__file__).with_name("bounded_tight_deadband_run.py"),
    "campaign_runner": Path(__file__).with_name("conditional_part_b_campaign.py"),
    "supervisor": Path(__file__).with_name("bounded_tight_deadband_supervisor.py"),
    "spec_loader": Path(__file__).with_name("no_write_qualification_supervisor.py"),
    "operational_rehearsal": Path(__file__).with_name(
        "bounded_tight_deadband_operational_rehearsal.py"
    ),
    "rehearsal_analyzer": Path(__file__).with_name(
        "bounded_tight_deadband_rehearsal_analyze.py"
    ),
    "live_analyzer": Path(__file__).with_name("bounded_tight_deadband_live_analyze.py"),
    "hybrid_model": Path(__file__).with_name("phase_frequency_hybrid_preview.py"),
    "capture": Path(__file__).with_name("capture_device.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "abort_path": Path(__file__).with_name("abort_transport.py"),
    "segment_rotation": Path(__file__).with_name("capture_segment_rotation.py"),
    "runtime_contract": Path(__file__).with_name(
        "bounded_tight_deadband_prewrite_contract.py"
    ),
    "outcome_contract": Path(__file__).with_name("bounded_tight_deadband_outcome_contract.py"),
    "setup_authority": Path(__file__).with_name("setup_authority_contract.py"),
    "contracts": Path(__file__).with_name("contracts.py"),
    "time_domains": Path(__file__).with_name("time_domains.py"),
    "run_validation": Path(__file__).with_name("validate_run.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_index": Path(__file__).with_name("evidence_index.py"),
}


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


def _selected(sequence_index: int) -> BoundedTightDeadbandLeg:
    try:
        return {
            1: RANGE_LOWER,
            2: RANGE_UPPER,
            3: RANGE_LOWER,
            4: RANGE_UPPER_COMPLETION,
        }[sequence_index]
    except KeyError as exc:
        raise ValueError("conditional Part B sequence index must be 1, 2, 3, or 4") from exc


def _validated_programme() -> dict[str, Any]:
    programme = _read(PROGRAMME_PROFILE, "mapping-informed Part B programme")
    if (
        programme.get("schema_version") != 1
        or programme.get("programme_id") != PROGRAMME_ID
        or programme.get("status")
        != "offline_preparation_authorized_physical_entry_not_authorized"
        or programme.get("effective_physical_authority") is not False
    ):
        raise ValueError("mapping-informed Part B programme identity differs")
    bindings = programme.get("source_bindings", {})
    for label, binding in bindings.items():
        source = Path(__file__).resolve().parents[2] / str(binding.get("path", ""))
        if not source.is_file() or binding.get("sha256") != sha256_file(source):
            raise ValueError(f"mapping-informed Part B source differs: {label}")
    readiness_binding = bindings.get("mapping_readiness_record", {})
    readiness = validate_readiness_record(
        Path(__file__).resolve().parents[2] / readiness_binding["path"]
    )
    if readiness_binding.get("readiness_sha256") != readiness["readiness_sha256"]:
        raise ValueError("mapping-informed Part B readiness semantic identity differs")
    part_b = programme.get("part_b", {})
    expected_legs = [
        ("lower_acquisition", "cx319_range_part_b_lower", 0xA800, "positive"),
        ("upper_acquisition", "cx319_range_part_b_upper", 0xA890, "negative"),
        ("lower_reacquisition", "cx319_range_part_b_lower", 0xA800, "positive"),
    ]
    observed_legs = [
        (
            item.get("leg_id"),
            item.get("profile_id"),
            item.get("setup_code"),
            item.get("required_direction"),
        )
        for item in part_b.get("legs", [])
    ]
    if (
        observed_legs != expected_legs
        or part_b.get("maximum_step_codes") != 21
        or part_b.get("maximum_corrections_per_leg") != 9
        or part_b.get("maximum_cumulative_movement_codes_per_leg") != 189
        or part_b.get("minimum_applied_cadence_s") != 1800
        or part_b.get("phase_hybrid_authority") is not False
        or part_b.get("automatic_retry") is not False
        or part_b.get("automatic_restore") is not False
    ):
        raise ValueError("mapping-informed Part B sequence or envelope differs")
    return programme


def _validated_hybrid_binding() -> dict[str, Any]:
    profile = _read(PART_B_HYBRID_PREVIEW, "Part B observational hybrid profile")
    inherited = profile.get("inherits", {})
    inherited_path = Path(__file__).resolve().parents[2] / str(
        inherited.get("path", "")
    )
    semantics = profile.get("external_dac_epoch_semantics", {})
    if (
        profile.get("schema_version") != 1
        or profile.get("profile_id")
        != "cx319_conditional_part_b_hybrid_observation_v1"
        or profile.get("candidate_id") != "p21600_cap1_epoch_reseed_v3"
        or inherited.get("candidate_id") != "p21600_cap1_v2"
        or not inherited_path.is_file()
        or inherited.get("sha256") != sha256_file(inherited_path)
        or semantics
        != {
            "actual_applied_code_reseeds_shadow_code": True,
            "actual_applied_code_reseeds_candidate_start_code": True,
            "correction_count_resets_to_zero": True,
            "cumulative_movement_codes_resets_to_zero": True,
            "direction_history_resets_empty": True,
            "terminal_fault_lifetime_ends": True,
            "frequency_support_and_decision_cadence_reset": True,
            "reason_code": "dac_epoch_candidate_reseed",
        }
        or not isinstance(profile.get("authority"), dict)
        or not profile["authority"]
        or any(value is not False for value in profile["authority"].values())
    ):
        raise ValueError("Part B observational hybrid profile is not exact")
    return _binding(PART_B_HYBRID_PREVIEW)


def _validate_part_a_readiness(readiness_path: Path) -> dict[str, Any]:
    readiness_path = readiness_path.resolve()
    readiness = validate_readiness_record(readiness_path)
    mapping = readiness["mapping_evaluation"]
    return {
        "path": str(readiness_path),
        "file_sha256": sha256_file(readiness_path),
        "readiness_sha256": readiness["readiness_sha256"],
        "status": readiness["status"],
        "part_a_scientific_result": readiness["part_a_scientific_result"],
        "historical_v3_promotion_status": readiness[
            "historical_v3_promotion_status"
        ],
        "physical_authority_granted": readiness["physical_authority_granted"],
        "contract": readiness["contract"],
        "part_a_bundle": readiness["part_a_bundle"],
        "part_a_run": readiness["part_a_run"],
        "source_semantic_identities": readiness["source_semantic_identities"],
        "transitions": mapping["transitions"],
        "directional_displacement": mapping["directional_displacement"],
        "shared_within_direction_slope_counts_per_code": mapping[
            "shared_within_direction_slope_counts_per_code"
        ],
        "part_b_reachability": mapping["part_b_reachability"],
    }


def _validate_predecessor(path: Path, *, sequence_index: int) -> dict[str, Any]:
    path = path.resolve()
    seal = _read(path, "conditional Part B predecessor seal")
    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    expected = _selected(sequence_index - 1)
    expected_predecessor_index = sequence_index - 1
    if (
        sequence_index not in {2, 3}
        or seal.get("status") not in {"passed", "bounded_nonpass"}
        or seal.get("programme_id") != PROGRAMME_ID
        or seal.get("gate") != expected.gate
        or seal.get("leg") != expected.leg
        or seal.get("sequence_index") != expected_predecessor_index
        or seal.get("seal_sha256") != canonical_sha256(unsigned)
        or seal.get("terminal", {}).get("result") not in {"healthy_stop", "aborted"}
    ):
        raise ValueError("Part B predecessor is not the exact sealed prior leg")
    return {
        "path": str(path),
        "file_sha256": sha256_file(path),
        "seal_sha256": seal["seal_sha256"],
        "status": seal["status"],
        "gate": seal["gate"],
        "leg": seal["leg"],
        "sequence_index": seal["sequence_index"],
        "run": seal["run"],
        "terminal": seal["terminal"],
        "evidence_snapshot": seal["evidence_snapshot"],
    }


def _validate_upper_completion_predecessor(path: Path) -> dict[str, Any]:
    """Bind the clean, right-censored V4 upper result and its passed lower leg."""

    path = path.resolve()
    seal = _read(path, "V4 upper predecessor seal")
    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    transactions = seal.get("transactions", {})
    epoch_contract = seal.get("part_b_hybrid_epoch_contract", {})
    epoch_checks = epoch_contract.get("epoch_checks", [])
    checks = seal.get("checks", {})
    evidence = seal.get("evidence_snapshot", {})
    evidence_path = Path(str(evidence.get("path", ""))).resolve()
    if (
        seal.get("status") != "failed"
        or seal.get("programme_id") != PROGRAMME_ID
        or (seal.get("gate"), seal.get("leg"), seal.get("sequence_index"))
        != ("PBU", "U", 2)
        or seal.get("terminal", {}).get("result") != "aborted"
        or seal.get("terminal", {}).get("reason")
        != "stage5_finite_qualified_endpoint_nonpass"
        or seal.get("scientific_outcome") != "not_established"
        or seal.get("seal_sha256") != canonical_sha256(unsigned)
        or transactions.get("application_count") != 4
        or transactions.get("response_count") != 3
        or transactions.get("healthy_required_direction_count") != 3
        or transactions.get("path_codes") != 84
        or epoch_contract.get("exact") is not True
        or len(epoch_checks) != 5
        or any(item.get("exact") is not True for item in epoch_checks)
        or epoch_checks[-1].get("applied_code") != 0xA83C
        or epoch_checks[-1].get("dac_epoch") != 5
        or checks.get("all_declared_contracts_validate") is not True
        or checks.get("capture_closed_cleanly_with_one_owner") is not True
        or checks.get("frequency_controller_replay_and_application_binding_exact")
        is not True
        or checks.get("live_health_has_no_post_attach_telemetry_increment_or_fault")
        is not True
        or checks.get("two_estimate_tight_entry_transition_demonstrated")
        is not False
        or not evidence_path.is_file()
        or evidence.get("sha256") != sha256_file(evidence_path)
    ):
        raise ValueError("upper-completion predecessor is not the exact clean right-censored V4 result")

    campaign_root = path.parents[3]
    lower_path = (
        campaign_root
        / "leg_1_lower_acquisition/live_lower_acquisition/reports/"
        "cx319_conditional_part_b_lower_seal_v1.json"
    )
    lower = _read(lower_path, "V4 passed lower predecessor seal")
    lower_unsigned = {key: value for key, value in lower.items() if key != "seal_sha256"}
    if (
        lower.get("status") != "passed"
        or (lower.get("gate"), lower.get("leg"), lower.get("sequence_index"))
        != ("PBL", "L", 1)
        or lower.get("programme_id") != PROGRAMME_ID
        or lower.get("seal_sha256") != canonical_sha256(lower_unsigned)
        or lower.get("seal_sha256") != seal.get("predecessor_leg_seal_sha256")
    ):
        raise ValueError("upper-completion predecessor does not bind the exact passed V4 lower leg")
    return {
        "path": str(path),
        "file_sha256": sha256_file(path),
        "seal_sha256": seal["seal_sha256"],
        "status": seal["status"],
        "gate": seal["gate"],
        "leg": seal["leg"],
        "sequence_index": seal["sequence_index"],
        "terminal": seal["terminal"],
        "evidence_snapshot": evidence,
        "last_confirmed_applied_code": 0xA83C,
        "last_confirmed_dac_epoch": 5,
        "completed_applications": 4,
        "completed_healthy_responses": 3,
        "lower_pass": {
            "path": str(lower_path),
            "file_sha256": sha256_file(lower_path),
            "seal_sha256": lower["seal_sha256"],
            "evidence_snapshot": lower["evidence_snapshot"],
        },
    }


def _validate_lower_reacquisition_predecessor(path: Path) -> dict[str, Any]:
    """Bind either the original upper leg or its passed PBUC completion."""

    path = path.resolve()
    seal = _read(path, "lower-reacquisition predecessor seal")
    if (seal.get("gate"), seal.get("leg")) == ("PBU", "U"):
        return _validate_predecessor(path, sequence_index=3)

    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    checks = seal.get("checks", {})
    transactions = seal.get("transactions", {})
    evidence = seal.get("evidence_snapshot", {})
    evidence_path = Path(str(evidence.get("path", ""))).resolve()
    supersession = seal.get("analysis_supersession", {})
    superseded_path = Path(str(supersession.get("superseded_seal_path", ""))).resolve()
    if (
        seal.get("status") != "passed"
        or seal.get("programme_id") != UPPER_COMPLETION_PROGRAMME_ID
        or (seal.get("gate"), seal.get("leg"), seal.get("sequence_index"))
        != ("PBUC", "C", 4)
        or seal.get("acceptance_path")
        != "mapping_target_stable_tight_hold_without_correction"
        or seal.get("scientific_outcome")
        != "stimulus_nonactionable_stable_tight_hold"
        or seal.get("seal_sha256") != canonical_sha256(unsigned)
        or seal.get("terminal", {}).get("result") != "aborted"
        or seal.get("terminal", {}).get("reason")
        != "stage5_finite_qualified_endpoint_nonpass"
        or seal.get("terminal_abort_delivery", {}).get("exact") is not True
        or not checks
        or any(value is not True for value in checks.values())
        or transactions.get("application_count") != 0
        or transactions.get("response_count") != 0
        or seal.get("tight_entry_transition_count") != 1
        or supersession.get("raw_acquisition_unchanged") is not True
        or supersession.get("physical_rerun") is not False
        or supersession.get("superseded_status") != "bounded_nonpass"
        or not superseded_path.is_file()
        or supersession.get("superseded_seal_file_sha256")
        != sha256_file(superseded_path)
        or not evidence_path.is_file()
        or evidence.get("sha256") != sha256_file(evidence_path)
    ):
        raise ValueError(
            "lower reacquisition does not bind the exact passed upper-completion seal"
        )
    return {
        "path": str(path),
        "file_sha256": sha256_file(path),
        "seal_sha256": seal["seal_sha256"],
        "status": seal["status"],
        "gate": seal["gate"],
        "leg": seal["leg"],
        "sequence_index": seal["sequence_index"],
        "run": seal["run"],
        "terminal": seal["terminal"],
        "evidence_snapshot": evidence,
        "acceptance_path": seal["acceptance_path"],
        "predecessor_leg_seal_sha256": seal.get("predecessor_leg_seal_sha256"),
    }


def _validate_firmware(
    selected: BoundedTightDeadbandLeg, build_manifest_path: Path, uf2_path: Path
) -> dict[str, Any]:
    matrix = load_matrix(MATRIX_PATH)
    profile = next(
        (item for item in matrix["profiles"] if item.get("id") == selected.profile_id),
        None,
    )
    if not isinstance(profile, dict) or profile.get("expect") != "pass":
        raise ValueError("conditional Part B firmware profile is unavailable")
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    build = _read(build_manifest_path, "conditional Part B build manifest")
    provenance = build.get("provenance", {})
    source = provenance.get("source", {})
    configuration = provenance.get("configuration", {})
    target = provenance.get("target", {})
    current_commit, current_state = _git_identity()
    if (
        current_state != "clean"
        or source.get("state") != "clean"
        or source.get("git_commit") != current_commit
        or source.get("sha256") != source_input_hash(matrix_path=MATRIX_PATH)
        or configuration.get("profile_id") != selected.profile_id
        or configuration.get("defines") != profile["defines"]
        or configuration.get("sha256") != configuration_hash(matrix, profile)
        or target.get("fqbn") != EXPECTED_FQBN
    ):
        raise ValueError("conditional Part B build does not bind current exact source/profile")
    artifacts = build.get("artifacts", [])
    artifact = next(
        (
            item
            for item in artifacts
            if isinstance(item, dict) and item.get("name") == uf2_path.name
        ),
        None,
    )
    if (
        not isinstance(artifact, dict)
        or not uf2_path.is_file()
        or artifact.get("sha256") != sha256_file(uf2_path)
        or artifact.get("size_bytes") != uf2_path.stat().st_size
        or build.get("resource_budget", {}).get("status") != "within_budget"
    ):
        raise ValueError("conditional Part B UF2 or resource budget differs")
    return {
        "profile_id": selected.profile_id,
        "build_manifest": _binding(build_manifest_path),
        "uf2": _binding(uf2_path),
        "git_commit": source["git_commit"],
        "source_state": source["state"],
        "source_sha256": source["sha256"],
        "configuration_sha256": configuration["sha256"],
        "build_invocation_id": provenance["invocation"]["id"],
        "fqbn": target["fqbn"],
    }


def create_proposal(
    *,
    sequence_index: int,
    part_a_readiness_path: Path,
    build_manifest_path: Path,
    uf2_path: Path,
    output_path: Path,
    predecessor_seal_path: Path | None = None,
) -> dict[str, Any]:
    selected = _selected(sequence_index)
    commit, state = _git_identity()
    if state != "clean":
        raise ValueError("conditional Part B proposal requires a clean repository")
    campaign = _validated_programme()
    part_a = _validate_part_a_readiness(part_a_readiness_path)
    predecessor = None
    if sequence_index == 1:
        if predecessor_seal_path is not None:
            raise ValueError("Part B leg 1 has no predecessor leg seal")
    elif sequence_index == 4:
        if predecessor_seal_path is None:
            raise ValueError("upper completion requires the exact V4 upper predecessor seal")
        predecessor = _validate_upper_completion_predecessor(predecessor_seal_path)
    elif sequence_index == 3:
        if predecessor_seal_path is None:
            raise ValueError("Part B leg 3 requires the exact predecessor seal")
        predecessor = _validate_lower_reacquisition_predecessor(
            predecessor_seal_path
        )
    else:
        if predecessor_seal_path is None:
            raise ValueError("Part B legs 2 and 3 require the exact predecessor seal")
        predecessor = _validate_predecessor(
            predecessor_seal_path, sequence_index=sequence_index
        )
    firmware = _validate_firmware(selected, build_manifest_path, uf2_path)
    policy = _load_policy()
    policy_binding = {
        **policy,
        "path": str(POLICY_PATH),
        "sha256": sha256_file(POLICY_PATH),
    }
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_ID,
        "bundle_id": selected.proposal_bundle_id,
        "created_utc": _utc_now(),
        "source_revision": commit,
        "source_state": state,
        "programme_id": selected.programme_id,
        "programme": _binding(PROGRAMME_PROFILE),
        "gate": selected.gate,
        "leg": selected.leg,
        "sequence_index": sequence_index,
        "sequence_count": 4 if sequence_index == 4 else 3,
        "status": "proposed_not_authorized",
        "authority": {
            "effective": False,
            "required_future_operation": selected.operation,
            "frequency_only": True,
            "phase_or_hybrid_actionable": False,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "part_a_readiness": part_a,
        "predecessor_leg": predecessor,
        "firmware": firmware,
        "policy": policy_binding,
        "observational_hybrid_preview": _validated_hybrid_binding(),
        "host_tools": {
            name: _binding(path) for name, path in sorted(HOST_TOOL_PATHS.items())
        },
        "expected_device": {
            "expected_board_serial": "503533748A919118",
            "baud": 115200,
            "single_continuously_draining_owner": True,
        },
        "leg_spec": {
            "profile_id": selected.profile_id,
            "run_binding_tag": selected.run_binding_tag,
            "run_identity": selected.run_identity,
            "setup_code": selected.setup_code,
            "setup_code_hex": selected.setup_code_hex,
            "required_automatic_direction": selected.required_direction,
        },
        "intended_live_envelope": {
            "setup_writes": 1,
            "automatic_corrections": selected.correction_limit,
            "maximum_step_codes": selected.maximum_step_codes,
            "maximum_cumulative_codes": selected.cumulative_limit_codes,
            "minimum_code": campaign["part_b"]["minimum_code"],
            "maximum_code": campaign["part_b"]["maximum_code"],
            "minimum_applied_cadence_s": selected.minimum_cadence_s,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": 5400,
            "maximum_qualified_duration_s": selected.maximum_qualified_duration_s,
            "one_request_outstanding": True,
            "automatic_retry": False,
            "automatic_restore": False,
            "phase_or_hybrid_actionable": False,
        },
    }
    value = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _atomic_new(output_path.resolve(), value)
    return value


def validate_frozen_proposal(path: Path) -> dict[str, Any]:
    value = _read(path.resolve(), "conditional Part B proposal")
    selected = _selected(int(value.get("sequence_index", 0)))
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("tool") != TOOL_ID
        or value.get("bundle_id") != selected.proposal_bundle_id
        or value.get("programme_id") != selected.programme_id
        or value.get("gate") != selected.gate
        or value.get("leg") != selected.leg
        or value.get("sequence_count") != (4 if selected.leg == "C" else 3)
        or value.get("status") != "proposed_not_authorized"
        or value.get("authority", {}).get("effective") is not False
        or value.get("authority", {}).get("phase_or_hybrid_actionable") is not False
        or value.get("bundle_sha256") != canonical_sha256(unsigned)
    ):
        raise ValueError("conditional Part B proposal identity, authority, or digest differs")
    return value


def validate_proposal(path: Path) -> dict[str, Any]:
    value = validate_frozen_proposal(path)
    selected = _selected(value["sequence_index"])
    _, state = _git_identity()
    if state != "clean":
        raise ValueError("conditional Part B proposal validation requires clean source")
    _validated_programme()
    if value.get("programme") != _binding(PROGRAMME_PROFILE):
        raise ValueError("conditional Part B programme binding is stale")
    if value.get("host_tools") != {
        name: _binding(tool_path) for name, tool_path in sorted(HOST_TOOL_PATHS.items())
    }:
        raise ValueError("conditional Part B host-tool binding is stale")
    part_a = value["part_a_readiness"]
    if part_a != _validate_part_a_readiness(Path(part_a["path"])):
        raise ValueError("conditional Part B Part A readiness binding is stale")
    predecessor = value.get("predecessor_leg")
    if value["sequence_index"] == 1:
        if predecessor is not None:
            raise ValueError("conditional Part B leg 1 unexpectedly has a predecessor")
    elif value["sequence_index"] == 4:
        if predecessor != _validate_upper_completion_predecessor(Path(predecessor["path"])):
            raise ValueError("upper-completion predecessor binding is stale")
    elif value["sequence_index"] == 3:
        if predecessor != _validate_lower_reacquisition_predecessor(
            Path(predecessor["path"])
        ):
            raise ValueError("lower-reacquisition predecessor binding is stale")
    elif predecessor != _validate_predecessor(
        Path(predecessor["path"]), sequence_index=value["sequence_index"]
    ):
        raise ValueError("conditional Part B predecessor binding is stale")
    firmware = _validate_firmware(
        selected,
        Path(value["firmware"]["build_manifest"]["path"]),
        Path(value["firmware"]["uf2"]["path"]),
    )
    if value.get("firmware") != firmware:
        raise ValueError("conditional Part B firmware binding is stale")
    if value.get("policy", {}).get("sha256") != sha256_file(POLICY_PATH):
        raise ValueError("conditional Part B policy binding is stale")
    if value.get("observational_hybrid_preview") != _validated_hybrid_binding():
        raise ValueError("conditional Part B observational hybrid binding is stale")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--sequence-index", type=int, choices=(1, 2, 3, 4), required=True)
    create.add_argument("--part-a-readiness", type=Path, required=True)
    create.add_argument("--predecessor-seal", type=Path)
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--uf2", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    if args.command == "create":
        result = create_proposal(
            sequence_index=args.sequence_index,
            part_a_readiness_path=args.part_a_readiness,
            predecessor_seal_path=args.predecessor_seal,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            output_path=args.output,
        )
    else:
        result = validate_proposal(args.proposal)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
