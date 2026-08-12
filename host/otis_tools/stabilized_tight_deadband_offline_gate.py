"""Evaluate the stabilized tight-deadband no-hardware integration gate.

The gate crosses programme authority, policy bindings, firmware profiles,
firmware/host identity, tight-deadband replay and phase/hybrid isolation. It
does not open serial, create command FIFOs, flash firmware or issue commands.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from tools.firmware_matrix import configuration_hash, load_matrix, source_input_hash

from .integer_count_tight_deadband import (
    OUTSIDE,
    REQUALIFY_OUTSIDE,
    TIGHT_INSIDE,
    TightHystereticDeadband,
)
from .programme_status import (
    OFFLINE_PREPARATION,
    ProgrammeExecutionBlocked,
    require_programme_execution_allowed,
    require_programme_operation_allowed,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    REPO_ROOT / "profiles/discipline/cx319_stabilized_tight_deadband_v1.json"
)
MATRIX_PATH = REPO_ROOT / "firmware/arduino/firmware_matrix.json"
FIRMWARE = REPO_ROOT / "firmware/arduino/otis_nano_rp2040_connect"
PROGRAMME_ID = "cx319_stabilized_tight_deadband"
POLICY_ID = "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1"
TOOL_ID = "cx319_offline_gate_v1"
EXPECTED_POLICY_HASH = (
    "936d92a1421b7a8f3db620cd0add2c1ecd1a73dbd9aad4581beb8d8c0b8e1698"
)
EXPECTED_PROFILES = {
    "A": {
        "profile_id": "cx319_tight_lower",
        "campaign": "OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER",
        "start_code": "0xA808u",
        "run_identity": "cx319_tight_lower:3195001",
    },
    "B": {
        "profile_id": "cx319_tight_upper",
        "campaign": "OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER",
        "start_code": "0xA848u",
        "run_identity": "cx319_tight_upper:3195002",
    },
}


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = _read_object(path, "CX319 policy")
    if (
        policy.get("schema_version") != 1
        or policy.get("policy_id") != POLICY_ID
        or policy.get("status")
        != "offline_candidate_frozen_no_hardware_authority"
    ):
        raise ValueError("unexpected CX319 policy identity or status")
    if _sha256_file(path) != EXPECTED_POLICY_HASH:
        raise ValueError("CX319 policy hash differs from firmware identity")
    bindings = policy.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("CX319 policy binding map is unavailable")
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"CX319 policy binding {name} is malformed")
        relative = binding.get("path")
        expected = binding.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError(f"CX319 policy binding {name} is incomplete")
        target = REPO_ROOT / relative
        if not target.is_file() or _sha256_file(target) != expected:
            raise ValueError(f"CX319 policy binding is stale: {name}")
    base = _read_object(
        REPO_ROOT / bindings["inherited_active_policy_root"]["path"],
        "inherited active policy",
    )
    if base.get("policy_id") != "CX317_BOUNDED_ACTIVE_I_ONLY_V2":
        raise ValueError("CX319 does not inherit the current active policy root")
    authority = policy.get("authority")
    if not isinstance(authority, dict) or authority.get("allowed_operation") != (
        OFFLINE_PREPARATION
    ):
        raise ValueError("CX319 policy lacks exact offline-only authority")
    forbidden = (
        "hardware_interaction",
        "firmware_flash",
        "serial_open",
        "command_fifo_creation",
        "dac_write",
        "control_arm",
        "bench_rehearsal",
        "live_leg",
        "phase_or_hybrid_actionable",
    )
    if any(authority.get(key) is not False for key in forbidden):
        raise ValueError("CX319 offline policy exposes a hardware/live authority")
    return policy


def _profile_checks(policy: dict[str, Any]) -> dict[str, bool]:
    matrix = load_matrix(MATRIX_PATH)
    profiles = {item["id"]: item for item in matrix["profiles"]}
    checks: dict[str, bool] = {}
    for leg, expected in EXPECTED_PROFILES.items():
        profile = profiles.get(expected["profile_id"])
        if not isinstance(profile, dict):
            raise ValueError(f"CX319 leg {leg} firmware profile is unavailable")
        defines = profile["defines"]
        policy_leg = policy["legs"][leg]
        checks[f"leg_{leg.lower()}_policy_profile_identity"] = (
            policy_leg["firmware_profile"] == expected["profile_id"]
            and profile["lifecycle"] == "keep_active"
            and {"campaign", "release", "bench"}.issubset(
                profile["verification_tiers"]
            )
        )
        checks[f"leg_{leg.lower()}_exact_firmware_envelope"] = (
            defines.get("OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW") == "1"
            and defines.get("OTIS_ENABLE_CX318_STAGE5_PREVIEW") == "0"
            and defines.get("OTIS_ENABLE_CX317_BOUNDED_ACTIVE") == "1"
            and defines.get("OTIS_ENABLE_DUAL_CORE_PARTITION") == "1"
            and defines.get("OTIS_GNSS_UART_TX_ENABLED") == "0"
            and defines.get("OTIS_ENABLE_H1_DAC_SWEEP") == "0"
            and defines.get("OTIS_DAC_MIN_CODE") == "0xA800u"
            and defines.get("OTIS_DAC_MAX_CODE") == "0xAB00u"
            and defines.get("OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE") == "0xA828u"
            and defines.get("OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH") == "0u"
            and defines.get("OTIS_CX317_ACTIVE_CAMPAIGN")
            == expected["campaign"]
            and defines.get("OTIS_CX317_ACTIVE_START_CODE")
            == expected["start_code"]
            and defines.get("OTIS_CX317_ACTIVE_CORRECTION_LIMIT") == "4u"
            and defines.get("OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES")
            == "84u"
            and defines.get("OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG")
            == "600u"
            and defines.get("OTIS_CX317_SETTLING_EXCLUSION_S") == "900u"
            and defines.get("OTIS_CX317_RECOVERY_FRESH_SUPPORT_S") == "600u"
            and defines.get("OTIS_CX317_DECISION_CADENCE_S") == "1800u"
        )
    guard = profiles.get("invalid_cx319_lower_parameters", {})
    checks["current_parameter_guard_is_release_checked"] = (
        guard.get("expect") == "fail"
        and guard.get("lifecycle") == "keep_compile_only"
        and guard.get("verification_tiers") == ["release"]
    )
    return checks


def _firmware_checks() -> dict[str, bool]:
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    phase_preview = (FIRMWARE / "otis_phase_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    decision_start = preview.index("OtisCx317ActiveLiveDecision active_decision")
    decision_end = preview.index(
        "otis_cx317_active_live_on_decision", decision_start
    )
    actual_frequency_decision = preview[decision_start:decision_end].lower()
    return {
        "policy_hash_bound_by_active_and_preview": (
            EXPECTED_POLICY_HASH in active and EXPECTED_POLICY_HASH in preview
        ),
        "policy_id_bound_by_preview": POLICY_ID in preview,
        "both_new_run_identities_bound": all(
            item["run_identity"] in active for item in EXPECTED_PROFILES.values()
        ),
        "new_campaigns_are_compile_time_guarded": all(
            item["campaign"] in config for item in EXPECTED_PROFILES.values()
        ),
        "actual_frequency_decision_has_no_phase_or_hybrid_input": (
            "frequency_error_hz" in actual_frequency_decision
            and "tight_deadband.frequency_controller_eligible"
            in actual_frequency_decision
            and "phase" not in actual_frequency_decision
            and "hybrid" not in actual_frequency_decision
        ),
        "phase_preview_has_no_actuator_or_active_decision_call": (
            "otis_dac_ad5693r_set_raw" not in phase_preview
            and "otis_cx317_active_live_on_decision" not in phase_preview
        ),
    }


def _tight_replay() -> dict[str, Any]:
    policy = TightHystereticDeadband()
    observations = [3, 2, -2, 3, 4, -4]
    decisions = [
        policy.observe(
            accumulated_edge_error_counts=value,
            fresh=True,
            session=1,
            dac_epoch=1,
        )
        for value in observations
    ]
    invalid = policy.observe(
        accumulated_edge_error_counts=None,
        fresh=False,
        session=1,
        dac_epoch=1,
    )
    epoch_first = policy.observe(
        accumulated_edge_error_counts=2,
        fresh=True,
        session=1,
        dac_epoch=2,
    )
    epoch_second = policy.observe(
        accumulated_edge_error_counts=2,
        fresh=True,
        session=1,
        dac_epoch=2,
    )
    exact = (
        [decision.reason for decision in decisions]
        == [
            "three_count_outside_hold",
            "tight_entry_pending",
            "tight_entry_confirmed",
            "three_count_inside_hold",
            "loose_release_pending",
            "loose_release_confirmed",
        ]
        and decisions[0].state_after == OUTSIDE
        and decisions[2].state_after == TIGHT_INSIDE
        and decisions[5].state_after == OUTSIDE
        and invalid.state_after == REQUALIFY_OUTSIDE
        and epoch_first.state_after == OUTSIDE
        and epoch_first.entry_pending_count == 1
        and epoch_second.state_after == TIGHT_INSIDE
        and all(
            not decision.actionable
            and not decision.actuation_authorized
            and not decision.authorization_consumed
            for decision in decisions + [invalid, epoch_first, epoch_second]
        )
    )
    return {
        "exact": exact,
        "observations": observations,
        "reasons": [decision.reason for decision in decisions],
        "terminal_state": epoch_second.state_after,
        "authority": "zero",
    }


def _build_checks(path: Path) -> dict[str, bool]:
    summary = _read_object(path.resolve(), "CX319 firmware matrix summary")
    matrix = load_matrix(MATRIX_PATH)
    matrix_profiles = {item["id"]: item for item in matrix["profiles"]}
    current_source_sha256 = source_input_hash(matrix_path=MATRIX_PATH)
    result_items = [
        result
        for result in summary.get("results", [])
        if isinstance(result, dict)
    ]
    results = {
        result.get("profile_id"): result
        for result in result_items
    }
    expected = {
        "cx319_tight_lower": "pass",
        "cx319_tight_upper": "pass",
        "invalid_cx319_lower_parameters": "fail",
    }
    supported_bindings_current = True
    for profile_id in ("cx319_tight_lower", "cx319_tight_upper"):
        result = results.get(profile_id, {})
        manifest_name = result.get("build_manifest")
        if not isinstance(manifest_name, str):
            supported_bindings_current = False
            continue
        manifest_path = Path(manifest_name)
        if not manifest_path.is_file():
            supported_bindings_current = False
            continue
        manifest = _read_object(manifest_path, f"{profile_id} build manifest")
        provenance = manifest.get("provenance", {})
        source = provenance.get("source", {}) if isinstance(provenance, dict) else {}
        configuration = (
            provenance.get("configuration", {})
            if isinstance(provenance, dict)
            else {}
        )
        profile = matrix_profiles[profile_id]
        supported_bindings_current = supported_bindings_current and (
            source.get("sha256") == current_source_sha256
            and configuration.get("profile_id") == profile_id
            and configuration.get("sha256") == configuration_hash(matrix, profile)
            and manifest.get("resource_budget", {}).get("status")
            == "within_budget"
        )
    guard = results.get("invalid_cx319_lower_parameters", {})
    guard_profile = matrix_profiles["invalid_cx319_lower_parameters"]
    result_profile_ids = [result.get("profile_id") for result in result_items]
    result_set_is_valid = (
        len(result_profile_ids) == len(set(result_profile_ids))
        and set(result_profile_ids) <= set(matrix_profiles)
    )
    return {
        "matrix_all_verified": summary.get("all_verified") is True,
        # A tier-selected matrix legitimately contains other current profiles.
        # Require each decision-bearing CX319 result exactly once while also
        # rejecting duplicate or unknown profile identities in the report.
        "required_profile_set_present_once": (
            result_set_is_valid and set(expected) <= set(results)
        ),
        "supported_and_guard_outcomes_exact": all(
            results.get(profile_id, {}).get("outcome") == outcome
            and results.get(profile_id, {}).get("verified") is True
            for profile_id, outcome in expected.items()
        ),
        "supported_build_bindings_match_current_source": (
            supported_bindings_current
        ),
        "negative_guard_configuration_matches_current_matrix": (
            guard.get("config_sha256")
            == configuration_hash(matrix, guard_profile)
        ),
    }


def _binding_is_current(binding: object) -> bool:
    if not isinstance(binding, dict):
        return False
    path_value = binding.get("path")
    expected_sha256 = binding.get("sha256")
    if not isinstance(path_value, str) or not isinstance(expected_sha256, str):
        return False
    path = Path(path_value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.is_file() and _sha256_file(path) == expected_sha256


def _replay_checks(
    relative_phase_replay_path: Path,
    hybrid_preview_replay_path: Path,
    parity_path: Path,
    policy: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, Any]]:
    stage2 = _read_object(
        relative_phase_replay_path.resolve(), "historical relative-phase replay"
    )
    stage3 = _read_object(
        hybrid_preview_replay_path.resolve(), "historical hybrid-preview replay"
    )
    parity = _read_object(parity_path.resolve(), "CX319 firmware parity replay")
    corpus_path = REPO_ROOT / "profiles/replay/cx318_stage2_replay_corpus_v1.json"
    phase_candidates_path = (
        REPO_ROOT / "profiles/estimators/cx318_relative_phase_candidates_v1.json"
    )
    hybrid_candidates_path = (
        REPO_ROOT / "profiles/discipline/cx318_hybrid_preview_candidates_v1.json"
    )
    corpus_sha256 = _sha256_file(corpus_path)
    expected_counts = {"missing_or_inadequate_raw_source": 1, "replayed": 39}
    stage2_authority = stage2.get("authority")
    stage3_authority = stage3.get("authority")
    forced_zero = stage3.get("frequency_only_forced_zero_parity")
    parity_profiles = parity.get("profiles")
    firmware_sources = parity.get("firmware_sources")
    parity_source_bindings_current = (
        isinstance(firmware_sources, dict)
        and set(firmware_sources) == {"engine", "harness", "header"}
        and all(_binding_is_current(binding) for binding in firmware_sources.values())
    )
    selected_phase = policy["bindings"]["selected_relative_phase_estimator"]
    selected_hybrid = policy["bindings"]["selected_hybrid_preview"]
    checks = {
        "relative_phase_corpus_replay_exact": (
            stage2.get("schema_version") == 1
            and stage2.get("tool") == "cx318_stage2_replay_v1"
            and stage2.get("status") == "complete_with_explicit_missing_sources"
            and stage2.get("run_count") == 40
            and stage2.get("status_counts") == expected_counts
            and stage2.get("corpus", {}).get("sha256") == corpus_sha256
            and stage2.get("candidate_profile", {}).get("sha256")
            == _sha256_file(phase_candidates_path)
            and isinstance(stage2_authority, dict)
            and set(stage2_authority)
            == {
                "actionable",
                "actuation_authorized",
                "authorization_consumed",
                "hardware_access",
            }
            and all(value is False for value in stage2_authority.values())
        ),
        "hybrid_corpus_replay_exact_zero_authority": (
            stage3.get("schema_version") == 1
            and stage3.get("tool") == "cx318_stage3_hybrid_replay_v1"
            and stage3.get("status") == "complete_with_explicit_missing_sources"
            and stage3.get("run_count") == 40
            and stage3.get("status_counts") == expected_counts
            and stage3.get("corpus", {}).get("sha256") == corpus_sha256
            and stage3.get("hybrid_profile", {}).get("sha256")
            == _sha256_file(hybrid_candidates_path)
            and isinstance(stage3_authority, dict)
            and stage3_authority
            and all(value is False for value in stage3_authority.values())
            and isinstance(forced_zero, dict)
            and forced_zero.get("exact") is True
            and forced_zero.get("mismatch_count") == 0
            and forced_zero.get("phase_contribution_forced_hz") == 0.0
            and forced_zero.get("observation_count")
            == forced_zero.get("sealed_decision_count")
            and forced_zero.get("observation_count") == 151
        ),
        "selected_firmware_host_parity_exact": (
            parity.get("schema_version") == 1
            and parity.get("tool") == "cx318_stage4_firmware_parity_v1"
            and parity.get("status") == "passed"
            and parity.get("corpus", {}).get("sha256") == corpus_sha256
            and parity.get("corpus_membership_matches_accepted_stage2") is True
            and parity.get("declared_run_count") == 40
            and parity.get("eligible_run_count") == parity.get("passed_run_count")
            and parity.get("passed_run_count") == 32
            and parity.get("failed_run_count") == 0
            and parity.get("expected_missing_or_inadequate_run_count") == 1
            and parity.get("boundary_count") == parity.get("compared_record_count")
            and parity.get("compared_record_count") == 353394
            and parity.get("mismatch_count") == 0
            and isinstance(parity_profiles, dict)
            and parity_profiles.get("phase_selected", {}).get("sha256")
            == selected_phase["sha256"]
            and parity_profiles.get("hybrid_selected", {}).get("sha256")
            == selected_hybrid["sha256"]
            and parity_source_bindings_current
        ),
    }
    evidence = {
        "stage2_relative_phase_replay": {
            "path": str(relative_phase_replay_path.resolve()),
            "sha256": _sha256_file(relative_phase_replay_path),
            "tool": stage2.get("tool"),
            "status": stage2.get("status"),
            "run_count": stage2.get("run_count"),
        },
        "stage3_hybrid_replay": {
            "path": str(hybrid_preview_replay_path.resolve()),
            "sha256": _sha256_file(hybrid_preview_replay_path),
            "tool": stage3.get("tool"),
            "status": stage3.get("status"),
            "run_count": stage3.get("run_count"),
        },
        "stage4_firmware_parity": {
            "path": str(parity_path.resolve()),
            "sha256": _sha256_file(parity_path),
            "tool": parity.get("tool"),
            "status": parity.get("status"),
            "compared_record_count": parity.get("compared_record_count"),
            "mismatch_count": parity.get("mismatch_count"),
        },
    }
    return checks, evidence


def evaluate(
    matrix_summary: Path,
    relative_phase_replay: Path,
    hybrid_preview_replay: Path,
    firmware_parity: Path,
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, OFFLINE_PREPARATION)
    policy = load_policy()
    try:
        require_programme_execution_allowed(PROGRAMME_ID)
    except ProgrammeExecutionBlocked:
        live_blocked = True
    else:
        live_blocked = False
    replay = _tight_replay()
    inherited_replay_checks, inherited_replay_evidence = _replay_checks(
        relative_phase_replay,
        hybrid_preview_replay,
        firmware_parity,
        policy,
    )
    checks = {
        "programme_offline_preparation_authorized": True,
        "cx319_operational_execution_blocked": live_blocked,
        **_profile_checks(policy),
        **_firmware_checks(),
        "tight_deadband_policy_exact_zero_authority": replay["exact"],
        **inherited_replay_checks,
        **_build_checks(matrix_summary),
        "serial_commands_attempted_is_zero": True,
        "dac_writes_attempted_is_zero": True,
        "fifo_creations_attempted_is_zero": True,
        "firmware_flashes_attempted_is_zero": True,
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "policy_id": POLICY_ID,
        "policy_sha256": _sha256_file(POLICY_PATH),
        "mode": "offline_no_io",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "tight_deadband_policy": replay,
        "inherited_replay_evidence": inherited_replay_evidence,
        "matrix_summary": str(matrix_summary.resolve()),
        "hardware_operations": {
            "firmware_flashes": 0,
            "serial_opens": 0,
            "fifo_creations": 0,
            "commands": 0,
            "dac_writes": 0,
            "control_arms": 0,
        },
        "next_gate": "explicit_operator_authorization_for_bench_rehearsal",
    }
    result["report_sha256"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-summary", type=Path, required=True)
    parser.add_argument("--relative-phase-replay", type=Path, required=True)
    parser.add_argument("--hybrid-preview-replay", type=Path, required=True)
    parser.add_argument("--firmware-parity", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(
            args.matrix_summary,
            args.relative_phase_replay,
            args.hybrid_preview_replay,
            args.firmware_parity,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
