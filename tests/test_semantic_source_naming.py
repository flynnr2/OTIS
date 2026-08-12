from __future__ import annotations

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host" / "otis_tools"
FIRMWARE = ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"

SEMANTIC_HOST_MODULES = {
    "abort_transport",
    "active_control_policy",
    "active_control_supervisor",
    "active_transactions",
    "measurement_replay",
    "frequency_control_replay",
    "reference_relative_phase_estimator",
    "phase_frequency_hybrid_preview",
    "capture_segment_rotation",
    "capture_owner_handoff",
    "integer_count_tight_deadband",
    "tight_deadband_policy",
    "prewrite_readiness_contract",
    "frequency_control_supervisor",
    "campaign_finalization",
    "control_evidence_replay",
    "host_attach_health_contract",
    "no_write_prewrite_readiness_contract",
    "stabilized_tight_deadband_offline_gate",
    "no_write_qualification_analyze",
    "no_write_qualification_bundle",
    "no_write_qualification_operational_rehearsal",
    "no_write_qualification_preflight",
    "no_write_qualification_run",
    "no_write_qualification_supervisor",
    "bounded_tight_deadband_rehearsal_analyze",
    "bounded_tight_deadband_bundle",
    "bounded_tight_deadband_outcome_contract",
    "bounded_tight_deadband_activation",
    "bounded_tight_deadband_live_analyze",
    "bounded_tight_deadband_operational_rehearsal",
    "bounded_tight_deadband_preflight",
    "bounded_tight_deadband_run",
    "bounded_tight_deadband_prewrite_contract",
    "bounded_tight_deadband_supervisor",
    "active_control_supervisor",
    "selected_preview_firmware_parity",
}

RETIRED_HOST_MODULES = {
    "phase4_boundary_estimator",
    "phase4_replay",
    "cx318_relative_phase",
    "cx318_hybrid_preview",
    "cx318_capture_segment",
    "cx318_capture_handoff",
    "cx318_stage5_tight_deadband",
    "cx318_stage5_tight_replay",
    "cx318_stage5_runtime_contract",
    "cx318_stage5_supervisor",
    "cx318_stage5_manifest",
    "cx318_stage5_rehearsal_analyze",
    "cx318_stage5_live_analyze",
    "cx319_runtime_contract",
    "cx319_host_attach_contract",
    "cx319_offline_gate",
    "cx319_g1_analyze",
    "cx319_g1_bundle",
    "cx319_g1_operational_rehearsal",
    "cx319_g1_preflight",
    "cx319_g1_rehearsal",
    "cx319_g1_supervisor",
    "cx319_g2_analyze",
    "cx319_g2_bundle",
    "cx319_g2_contract",
    "cx319_g2_live",
    "cx319_g2_live_analyze",
    "cx319_g2_operational_rehearsal",
    "cx319_g2_preflight",
    "cx319_g2_run",
    "cx319_g2_runtime_contract",
    "cx319_g2_supervisor",
    "cx317_stage7_supervisor",
    "cx317_stage6_live_analyze",
    "cx318_stage1_handoff",
    "cx318_stage2_replay",
    "cx318_stage3_replay",
    "cx318_stage4_firmware_parity",
    "cx317_stage7_shadow",
    "cx317_frequency_preview_live_analyze",
    "frequency_control_handoff_reconstruction",
    "relative_phase_candidate_replay",
    "hybrid_preview_candidate_replay",
    "cx317_counterfactual_deadband",
    "observe_only_discipline_replay",
    "pps_boundary_frequency_estimator",
    "tight_deadband_manifest",
}

SEMANTIC_FIRMWARE_UNITS = {
    "otis_pps_boundary_frequency_estimator",
    "otis_observe_only_discipline_engine",
    "otis_observe_only_discipline_live",
    "otis_phase_preview_format",
    "otis_phase_preview_live",
    "otis_phase_preview_transport",
    "otis_selected_phase_frequency_preview_engine",
    "otis_integer_count_tight_deadband",
}

RETIRED_FIRMWARE_UNITS = {
    "otis_phase4_boundary_estimator",
    "otis_phase4_engine",
    "otis_phase4_observe_preview",
    "otis_cx318_preview_format",
    "otis_cx318_preview_live",
    "otis_cx318_preview_transport",
    "otis_cx318_selected_preview_engine",
    "otis_cx318_stage5_tight_deadband",
}

CHRONOLOGICAL_IDENTIFIER = re.compile(
    r"(?:phase4|cx318|cx319|stage[0-9]+)", re.IGNORECASE
)


def test_reusable_modules_and_firmware_units_use_semantic_filenames() -> None:
    for module in SEMANTIC_HOST_MODULES:
        assert (HOST / f"{module}.py").is_file()
    for module in RETIRED_HOST_MODULES:
        assert not (HOST / f"{module}.py").exists()

    for unit in SEMANTIC_FIRMWARE_UNITS:
        assert (FIRMWARE / f"{unit}.h").is_file()
        assert (FIRMWARE / f"{unit}.cpp").is_file()
    for unit in RETIRED_FIRMWARE_UNITS:
        assert not (FIRMWARE / f"{unit}.h").exists()
        assert not (FIRMWARE / f"{unit}.cpp").exists()


def test_current_python_imports_and_primary_symbols_are_semantic() -> None:
    failures: list[str] = []
    for module in sorted(SEMANTIC_HOST_MODULES):
        path = HOST / f"{module}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        top_level_nodes = set(tree.body)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if CHRONOLOGICAL_IDENTIFIER.search(node.name):
                    failures.append(f"{module}:{node.lineno}:definition:{node.name}")
            elif isinstance(node, ast.Assign) and node in top_level_nodes:
                for target in node.targets:
                    if isinstance(target, ast.Name) and CHRONOLOGICAL_IDENTIFIER.search(target.id):
                        failures.append(f"{module}:{node.lineno}:assignment:{target.id}")
            elif (
                isinstance(node, ast.AnnAssign)
                and node in top_level_nodes
                and isinstance(node.target, ast.Name)
            ):
                if CHRONOLOGICAL_IDENTIFIER.search(node.target.id):
                    failures.append(
                        f"{module}:{node.lineno}:assignment:{node.target.id}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_module = node.module.rsplit(".", 1)[-1]
                if CHRONOLOGICAL_IDENTIFIER.search(imported_module):
                    failures.append(
                        f"{module}:{node.lineno}:import:{imported_module}"
                    )
            elif isinstance(node, ast.Import):
                for imported in node.names:
                    imported_module = imported.name.rsplit(".", 1)[-1]
                    if CHRONOLOGICAL_IDENTIFIER.search(imported_module):
                        failures.append(
                            f"{module}:{node.lineno}:import:{imported_module}"
                        )
    assert failures == []


def test_current_firmware_primary_api_has_no_programme_sequence_prefix() -> None:
    source = "\n".join(
        (FIRMWARE / f"{unit}.{suffix}").read_text(encoding="utf-8")
        for unit in sorted(SEMANTIC_FIRMWARE_UNITS)
        for suffix in ("h", "cpp")
    )
    forbidden_api = re.compile(
        r"\b(?:Otis|otis_|OTIS_|kOtis)[A-Za-z0-9_]*"
        r"(?:Phase4|phase4|PHASE4|Cx318|cx318|CX318|Cx319|cx319|CX319|"
        r"Stage[0-9]|stage[0-9]|STAGE[0-9])[A-Za-z0-9_]*\b"
    )
    assert forbidden_api.findall(source) == []


def _string_assignment(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise AssertionError(f"missing string assignment {name} in {path}")


def test_current_provenance_bearing_tool_ids_remain_exact_wire_identities() -> None:
    expected = {
        "capture_owner_handoff": "cx318_capture_handoff_v1",
        "stabilized_tight_deadband_offline_gate": "cx319_offline_gate_v1",
        "no_write_qualification_analyze": "cx319_g1_analyze_v1",
        "no_write_qualification_bundle": "cx319_g1_bundle_v1",
        "no_write_qualification_operational_rehearsal": "cx319_g1_no_flash_operational_rehearsal_v1",
        "no_write_qualification_preflight": "cx319_g1_offline_preflight_v1",
        "no_write_qualification_run": "cx319_g1_rehearsal_v1",
        "no_write_qualification_supervisor": "cx319_g1_supervisor_v1",
        "bounded_tight_deadband_rehearsal_analyze": "cx319_g2_accelerated_analyzer_v1",
        "bounded_tight_deadband_bundle": "cx319_g2_proposal_bundle_v1",
        "bounded_tight_deadband_activation": "cx319_g2_live_activation_v1",
        "bounded_tight_deadband_live_analyze": "cx319_g2_live_analyze_v1",
        "bounded_tight_deadband_operational_rehearsal": "cx319_g2_accelerated_operational_rehearsal_v1",
        "bounded_tight_deadband_preflight": "cx319_g2_offline_preflight_v1",
        "bounded_tight_deadband_run": "cx319_g2_run_v1",
        "bounded_tight_deadband_supervisor": "cx319_g2_supervisor_v1",
    }
    observed = {
        module: _string_assignment(HOST / f"{module}.py", "TOOL_ID")
        for module in expected
    }
    assert observed == expected


def test_provenance_bearing_replay_and_wire_identities_are_unchanged() -> None:
    replay_contract = (
        ROOT / "profiles/discipline/current_frequency_control_replay_v1.json"
    ).read_text(encoding="utf-8")
    assert '"CX317_POST_CAMPAIGN_FREQUENCY_CONTROL_POLICY_V1"' in replay_contract
    assert '"compatibility_floor": "CX319_EVIDENCE_EPOCH_1"' in replay_contract

    partition = (FIRMWARE / "otis_dual_core_partition.cpp").read_text(
        encoding="utf-8"
    )
    assert 'return "cx318_preview_queue_exhausted";' in partition
    assert 'return "cx318_preview_processing_fault";' in partition
