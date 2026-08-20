"""Create and validate the exact non-authorizing CX320 programme bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_hybrid_policy import DEFAULT_POLICY, load_policy


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "cx320_active_hybrid_exact_bundle_v1"
BUNDLE_ID = "cx320_active_hybrid_12h_qualified_16h_wall_bundle_v1"
PROFILE_ID = "cx320_active_hybrid"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
RUNTIME_RUN_IDENTITY = "cx320_active_hybrid:3200001"
EXPECTED_BOARD_SERIAL = "503533748A919118"
REQUIRED_FALSE_AUTHORITY = (
    "effective",
    "firmware_flash",
    "reset",
    "serial_access",
    "command_fifo",
    "setup_stimulus",
    "dac_write",
    "control_arm",
    "physical_rehearsal",
    "live_acquisition",
)
TOOL_PATHS = {
    "bundle": Path(__file__),
    "controller_reference": Path(__file__).with_name("active_hybrid_policy.py"),
    "predecessor_audit": Path(__file__).with_name("active_hybrid_evidence_audit.py"),
    "frozen_evidence_replay": Path(__file__).with_name("active_hybrid_replay.py"),
    "host_supervisor_contract": Path(__file__).with_name("active_hybrid_supervisor.py"),
    "response_replay_guard": Path(__file__).with_name("active_hybrid_evidence_guard.py"),
    "authority_proposal_validator": Path(__file__).with_name("active_hybrid_proposal.py"),
    "structural_preflight": Path(__file__).with_name("active_hybrid_preflight.py"),
    "operational_rehearsal": Path(__file__).with_name("active_hybrid_rehearsal.py"),
    "analyzer": Path(__file__).with_name("active_hybrid_analyze.py"),
    "finalizer_and_sealer": Path(__file__).with_name("active_hybrid_finalize.py"),
    "capture": Path(__file__).with_name("capture_device.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "active_transaction_supervisor": Path(__file__).with_name("active_transactions.py"),
    "active_transport_supervisor": Path(__file__).with_name("active_control_supervisor.py"),
    "priority_abort": Path(__file__).with_name("abort_transport.py"),
    "logical_rotation": Path(__file__).with_name("capture_segment_rotation.py"),
    "contract_validator": Path(__file__).with_name("contracts.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "registration": Path(__file__).with_name("evidence_index.py"),
    "live_activation_and_manifest": Path(__file__).with_name("active_hybrid_activation.py"),
    "live_supervisor": Path(__file__).with_name("active_hybrid_live_supervisor.py"),
    "live_runner": Path(__file__).with_name("active_hybrid_run.py"),
    "live_analyzer_and_sealer": Path(__file__).with_name("active_hybrid_live_analyze.py"),
    "live_topology_rehearsal": Path(__file__).with_name("active_hybrid_live_rehearsal.py"),
    "live_monitor": Path(__file__).with_name("active_hybrid_monitor.py"),
}


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"CX320 bound file is unavailable: {path}")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_build(build_manifest_path: Path) -> dict[str, Any]:
    manifest = _read_object(build_manifest_path)
    provenance = manifest.get("provenance", {})
    configuration = provenance.get("configuration", {})
    source = provenance.get("source", {})
    target = provenance.get("target", {})
    toolchain = provenance.get("toolchain", {})
    if configuration.get("profile_id") != PROFILE_ID:
        raise ValueError("firmware build is not the exact CX320 profile")
    defines = configuration.get("defines", {})
    expected_defines = {
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_CX317_ACTIVE_CAMPAIGN": "OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID",
        "OTIS_CX317_ACTIVE_START_CODE": "0xA83Cu",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "4u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "84u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
        "OTIS_DAC_MIN_CODE": "0xA800u",
        "OTIS_DAC_MAX_CODE": "0xAB00u",
        "OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED": "1",
    }
    if any(defines.get(name) != value for name, value in expected_defines.items()):
        raise ValueError("firmware build CX320 compile-time envelope differs")
    configuration_sha256 = configuration.get("sha256")
    source_sha256 = source.get("sha256")
    if not all(
        isinstance(value, str) and len(value) == 64
        for value in (configuration_sha256, source_sha256)
    ):
        raise ValueError("firmware build lacks exact source/configuration identity")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("firmware build artifact list is unavailable")
    uf2 = [item for item in artifacts if item.get("name", "").endswith(".uf2")]
    if len(uf2) != 1:
        raise ValueError("firmware build must bind exactly one UF2")
    uf2_path = build_manifest_path.parent / uf2[0]["name"]
    if not uf2_path.is_file() or _sha256_file(uf2_path) != uf2[0].get("sha256"):
        raise ValueError("firmware UF2 identity differs from the build manifest")
    if target.get("fqbn") != "rp2040:rp2040:arduino_nano_connect:freq=133":
        raise ValueError("firmware target differs")
    if not toolchain.get("compiler_identity") or not toolchain.get("installed_sha256"):
        raise ValueError("firmware toolchain identity is incomplete")
    if source.get("state") != "clean":
        raise ValueError("exact CX320 live firmware build requires clean source state")
    return {
        "profile_id": PROFILE_ID,
        "build_manifest": _binding(build_manifest_path),
        "source_revision": source.get("git_commit"),
        "source_state": source.get("state"),
        "source_sha256": source_sha256,
        "configuration_sha256": configuration_sha256,
        "build_identity": f"{source_sha256}:{configuration_sha256}",
        "uf2": _binding(uf2_path),
        "fqbn": target["fqbn"],
        "toolchain": toolchain,
        "defines": defines,
    }


def _validate_replay(replay_path: Path, policy_sha256: str) -> dict[str, Any]:
    replay = _read_object(replay_path)
    claimed = replay.pop("report_sha256", None)
    observed = _canonical_sha256(replay)
    replay["report_sha256"] = claimed
    if claimed != observed:
        raise ValueError("CX320 replay semantic report identity differs")
    current_tool = Path(__file__).with_name("active_hybrid_replay.py")
    if (
        replay.get("status") != "passed"
        or replay.get("selected_candidate_id") != "p21600_cap1_tight_active_v1"
        or replay.get("policy_sha256") != policy_sha256
        or replay.get("tool_sha256") != _sha256_file(current_tool)
        or not all(replay.get("selection_checks", {}).values())
    ):
        raise ValueError("CX320 replay selection or current tool binding differs")
    return {
        **_binding(replay_path),
        "report_sha256": claimed,
        "selected_candidate_id": replay["selected_candidate_id"],
        "selection_checks": replay["selection_checks"],
    }


def create_bundle(
    *, build_manifest_path: Path, replay_path: Path
) -> dict[str, Any]:
    policy = load_policy()
    policy_document = _read_object(DEFAULT_POLICY)
    firmware = _validate_build(build_manifest_path.resolve())
    replay = _validate_replay(replay_path.resolve(), policy.policy_sha256)
    authority = {name: False for name in REQUIRED_FALSE_AUTHORITY}
    authority.update(
        {
            "offline_preparation": True,
            "separate_exact_bundle_operator_decision_required": True,
            "consumed_by_first_physical_terminal": True,
        }
    )
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": BUNDLE_ID,
        "programme_id": PROGRAMME_ID,
        "tool": TOOL_ID,
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "frozen_non_effective_physical_proposal_input",
        "run_identity": RUNTIME_RUN_IDENTITY,
        "policy": {
            **_binding(DEFAULT_POLICY),
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
        },
        "firmware": firmware,
        "offline_replay": replay,
        "host_tools": {name: _binding(path) for name, path in TOOL_PATHS.items()},
        "topology": {
            "sole_reference_input": "D14",
            "sole_oscillator_count_input": "D8",
            "independent_event_input_not_authority": "D10",
            "gnss_role": "same_receiver_D14_qualification_metadata_only",
            "D9_GPOUT0": "deferred_unchanged",
            "serial_owner_count": 1,
            "serial_owner": "capture_device",
            "normal_and_priority_abort_fifos_distinct": True,
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
        },
        "setup": {
            "exact_code": 0xA83C,
            "exact_code_hex": "0xA83C",
            "physical_applied_code_before_setup": "unknown",
            "one_setup_application": True,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_acknowledgement_required": True,
            "consumer_epoch_propagation_required": [
                "frequency_estimator",
                "phase_estimator",
                "controller",
                "preview_replay",
                "recorder",
                "response_classifier",
            ],
        },
        "finite_limits": {
            "qualified_duration_s": 43_200,
            "qualified_origin": "first_complete_fresh_authoritative_600s_estimate_after_exact_setup_support_and_common_health_qualification",
            "absolute_wall_clock_limit_s": 57_600,
            "wall_clock_origin": "sole_capture_owner_records_exact_run_identity_before_setup_submission",
            "maximum_total_automatic_applications": 4,
            "maximum_combined_step_codes": 21,
            "maximum_cumulative_absolute_movement_codes": 84,
            "minimum_applied_cadence_s": 1_800,
            "minimum_code": 0xA800,
            "maximum_code": 0xAB00,
            "maximum_outstanding_requests": 1,
            "automatic_retry": False,
            "automatic_restoration": False,
            "live_extension": False,
        },
        "prospective_metrics": policy_document["prospective_metrics"],
        "progressive_authority": {
            "states": [
                "FREQUENCY_ACQUIRE",
                "PHASE_QUALIFY",
                "FIRST_PHASE_TRANSACTION",
                "HYBRID_TRACKING",
                "PHASE_DEGRADED_FREQUENCY_ONLY",
                "FAIL_STATIC",
            ],
            "first_phase_application_limit_before_checkpoint": 1,
            "first_response_acknowledgement_requires_durable_AHY_and_ACT": True,
            "first_response_acknowledgement_requires_exact_host_replay": True,
            "later_authority_requires_healthy_response_and_tight_reacquisition": True,
        },
        "command_envelope": {
            "identity_queries_before_setup": ["CONFIG?", "DUALCORE?", "DAC?", "ACTIVE?"],
            "setup": "ACTIVE SETUP <authorization> <generation> <nonce> <expiry> <session> 0xA83C 1 <configuration_sha256>",
            "arm": "ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>",
            "evidence_acknowledgement": "ACTIVE EVIDENCE <request_sequence> <phase_1_to_4>",
            "priority_abort_only": "ACTIVE ABORT",
            "normal_command_max_age_s": 2.0,
            "normal_write_timeout_s": 1.0,
            "command_ack_timeout_s": 3.0,
            "priority_abort_delivery_required_before_capture_close": True,
        },
        "stop_conditions": [
            "qualified_duration_complete",
            "absolute_wall_clock_limit",
            "phase_only_degradation_active_hybrid_nonpass",
            "shared_D14_or_D8_qualification_loss",
            "ambiguous_DAC_epoch_or_identity",
            "capture_or_evidence_discontinuity",
            "transaction_or_acknowledgement_fault",
            "wrong_absent_late_or_right_censored_response",
            "range_cadence_count_or_cumulative_budget_breach",
            "serial_owner_loss_or_transport_obstruction",
            "priority_abort_delivery_failure",
            "operator_abort",
        ],
        "terminal_requirements": {
            "one_confirmed_static_code": True,
            "outstanding_request": False,
            "outstanding_response": False,
            "latent_authority": False,
            "every_terminal_analyzed_sealed_and_registered": True,
        },
        "authority": authority,
    }
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    return bundle


def validate_bundle(path: Path) -> dict[str, Any]:
    path = path.resolve()
    bundle = _read_object(path)
    claimed = bundle.pop("bundle_sha256", None)
    observed = _canonical_sha256(bundle)
    bundle["bundle_sha256"] = claimed
    if claimed != observed:
        raise ValueError("CX320 bundle semantic identity differs")
    if (
        bundle.get("bundle_id") != BUNDLE_ID
        or bundle.get("programme_id") != PROGRAMME_ID
        or bundle.get("status") != "frozen_non_effective_physical_proposal_input"
        or bundle.get("run_identity") != RUNTIME_RUN_IDENTITY
        or bundle.get("topology", {}).get("expected_board_serial")
        != EXPECTED_BOARD_SERIAL
        or bundle.get("command_envelope", {}).get("arm")
        != "ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>"
    ):
        raise ValueError("unexpected CX320 bundle identity")
    if any(bundle.get("authority", {}).get(name) is not False for name in REQUIRED_FALSE_AUTHORITY):
        raise ValueError("CX320 bundle contains effective physical authority")
    if set(bundle.get("host_tools", {})) != set(TOOL_PATHS):
        raise ValueError("CX320 bundle does not bind the complete current host path")
    for section, bindings in (("host_tools", bundle.get("host_tools", {})),):
        if not isinstance(bindings, dict):
            raise ValueError(f"CX320 {section} bindings are unavailable")
        for name, binding in bindings.items():
            bound = Path(str(binding.get("path", "")))
            if not bound.is_file() or _sha256_file(bound) != binding.get("sha256"):
                raise ValueError(f"CX320 {section} binding differs: {name}")
    policy_binding = bundle["policy"]
    policy_path = Path(policy_binding["path"])
    if _sha256_file(policy_path) != policy_binding["sha256"]:
        raise ValueError("CX320 policy file binding differs")
    policy = load_policy(policy_path)
    if policy.policy_sha256 != policy_binding["policy_sha256"]:
        raise ValueError("CX320 semantic policy binding differs")
    policy_document = _read_object(policy_path)
    if bundle.get("prospective_metrics") != policy_document.get(
        "prospective_metrics"
    ):
        raise ValueError("CX320 prospective scientific metrics differ from policy")
    _validate_build(Path(bundle["firmware"]["build_manifest"]["path"]))
    _validate_replay(Path(bundle["offline_replay"]["path"]), policy.policy_sha256)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args(argv)
    if args.validate is not None:
        result = validate_bundle(args.validate)
    else:
        if args.build_manifest is None or args.replay is None:
            parser.error("bundle creation requires --build-manifest and --replay")
        result = create_bundle(
            build_manifest_path=args.build_manifest,
            replay_path=args.replay,
        )
        if args.output is not None:
            if args.output.exists():
                parser.error(f"refusing to overwrite CX320 bundle: {args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
