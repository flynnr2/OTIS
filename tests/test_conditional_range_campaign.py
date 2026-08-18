from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.conditional_part_a_bundle import create_bundle, validate_bundle
from host.otis_tools.conditional_part_a_promotion import _transition
from host.otis_tools.conditional_part_b_bundle import (
    _validate_part_a_readiness,
    _validated_programme,
)
from host.otis_tools.conditional_range_campaign import campaign_summary, load_campaign
from host.otis_tools.range_spanning_run import _adaptive_point_rows
from host.otis_tools.range_spanning_rehearsal import run as run_rehearsal
from host.otis_tools.bounded_tight_deadband_live_analyze import (
    _part_b_hybrid_epoch_contract,
)
from host.otis_tools import (
    bounded_tight_deadband_operational_rehearsal as part_b_rehearsal,
    bounded_tight_deadband_rehearsal_analyze as part_b_rehearsal_analyze,
    conditional_part_b_campaign,
)
from host.otis_tools.bounded_tight_deadband_leg import RANGE_LOWER, RANGE_UPPER


def _synthetic_build(tmp_path: Path) -> Path:
    artifacts = tmp_path / "firmware/artifacts"
    artifacts.mkdir(parents=True)
    uf2 = artifacts / "candidate.uf2"
    uf2.write_bytes(b"focused CX319 rehearsal UF2 identity\n")
    manifest = {
        "schema_version": 1,
        "provenance": {
            "configuration": {
                "profile_id": "cx319_range_map_part_a",
                "sha256": "1" * 64,
                "defines": {
                    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
                    "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW": "1",
                },
            },
            "target": {"fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133"},
            "source": {
                "sha256": "2" * 64,
                "state": "synthetic_rehearsal_fixture",
                "git_commit": "3" * 40,
            },
            "invocation": {"id": "4" * 64},
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
                "size_bytes": uf2.stat().st_size,
            }
        ],
        "resource_budget": {"status": "within_budget"},
    }
    path = artifacts / "firmware_build_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _rows(counts: list[int]) -> list[dict[str, str]]:
    return [{"integer_edge_error_counts": str(value)} for value in counts]


def test_campaign_is_a_focused_zero_authority_conditional_sequence() -> None:
    campaign = load_campaign()
    assert campaign_summary() == {
        "programme_id": "CX319_CONDITIONAL_FINE_MAP_AND_FREQUENCY_TRAVERSAL_V3",
        "part_a_point_count": 27,
        "part_a_minimum_observations": 104,
        "part_a_maximum_observations": 148,
        "part_a_operational_minimum_s": 102_900,
        "part_a_operational_maximum_s": 129_300,
        "part_b_leg_count": 3,
        "part_b_maximum_per_leg_s": 14_400,
        "phase_hybrid_authority": False,
    }
    assert [item["code"] for item in campaign["part_a"]["point_plan"]] == [
        0xA800,
        0xA830,
        0xA817,
        0xA819,
        0xA81B,
        0xA81D,
        0xA81F,
        0xA821,
        0xA821,
        0xA81F,
        0xA81D,
        0xA81B,
        0xA819,
        0xA817,
        0xA830,
        0xA845,
        0xA847,
        0xA849,
        0xA84B,
        0xA84D,
        0xA84D,
        0xA84B,
        0xA849,
        0xA847,
        0xA845,
        0xA830,
        0xA800,
    ]


def test_mapping_informed_part_b_rebinds_without_rewriting_v3_promotion() -> None:
    programme = _validated_programme()
    readiness_path = Path(
        programme["source_bindings"]["mapping_readiness_record"]["path"]
    )
    readiness = _validate_part_a_readiness(readiness_path)

    assert programme["programme_id"] == "CX319_MAPPING_INFORMED_FREQUENCY_TRAVERSAL_V4"
    assert programme["effective_physical_authority"] is False
    assert readiness["status"] == "ready"
    assert readiness["part_a_scientific_result"] == "successful_transition_map"
    assert readiness["historical_v3_promotion_status"] == "not_promoted"
    assert readiness["physical_authority_granted"] is False
    assert RANGE_LOWER.prerequisite_key == "part_a_readiness"
    assert RANGE_UPPER.prerequisite_key == "part_a_readiness"


def test_part_b_campaign_rejects_missing_pyserial_before_output_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "must-not-be-created"
    monkeypatch.setattr(
        conditional_part_b_campaign.importlib.util,
        "find_spec",
        lambda name: None if name == "serial" else object(),
    )

    with pytest.raises(RuntimeError, match="requires pyserial"):
        conditional_part_b_campaign.run_campaign(
            part_a_readiness_path=tmp_path / "readiness.json",
            lower_build_manifest_path=tmp_path / "lower-manifest.json",
            lower_uf2_path=tmp_path / "lower.uf2",
            upper_build_manifest_path=tmp_path / "upper-manifest.json",
            upper_uf2_path=tmp_path / "upper.uf2",
            output_root=output_root,
            evidence_index_path=tmp_path / "index.json",
            operator_instruction_ref="fixture authority",
            arduino_cli="arduino-cli",
        )

    assert not output_root.exists()


def test_part_b_resume_seals_retained_leg_without_reexecuting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "campaign"
    lower_run = root / "leg_1_lower_acquisition/live_lower_acquisition"
    lower_run.mkdir(parents=True)
    readiness = tmp_path / "readiness.json"
    readiness.write_text("{}", encoding="utf-8")
    state_path = root / "conditional_part_b_campaign_state_v1.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": conditional_part_b_campaign.TOOL_ID,
                "status": "failed",
                "part_a_readiness": str(readiness),
                "current_sequence_index": 1,
                "current_leg": "lower_acquisition",
                "completed_legs": [],
                "run_dir": str(lower_run),
                "terminal": {
                    "error": (
                        "manifest does not satisfy CX319_EVIDENCE_EPOCH_1; "
                        "fixture finalization escape"
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    lower_seal = lower_run / RANGE_LOWER.live_seal_filename
    recovery_calls: list[Path] = []
    qualification_calls: list[Path] = []

    monkeypatch.setattr(
        conditional_part_b_campaign,
        "_require_physical_runtime_dependencies",
        lambda: None,
    )

    def fake_recovery(*, run_dir: Path) -> dict[str, object]:
        recovery_calls.append(run_dir)
        return {
            "status": "passed",
            "run_dir": str(run_dir),
            "analysis_and_seal": str(lower_seal),
            "seal_sha256": "1" * 64,
            "evidence_content_sha256": "2" * 64,
            "finalization_recovery": str(
                run_dir / "reports/cx319_pbl_finalization_recovery_v1.json"
            ),
        }

    monkeypatch.setattr(
        conditional_part_b_campaign,
        "recover_bounded_tight_deadband_finalization",
        fake_recovery,
    )
    monkeypatch.setattr(
        conditional_part_b_campaign,
        "create_proposal",
        lambda **kwargs: {"bundle_sha256": str(kwargs["sequence_index"]) * 64},
    )
    monkeypatch.setattr(
        conditional_part_b_campaign,
        "run_rehearsal",
        lambda **_kwargs: {"status": "passed"},
    )
    monkeypatch.setattr(
        conditional_part_b_campaign,
        "_locate_board_by_serial",
        lambda *_args, **_kwargs: ("/dev/cu.fixture", "fixture-board"),
    )
    monkeypatch.setattr(
        conditional_part_b_campaign,
        "create_activation",
        lambda **kwargs: {"activation_sha256": str(kwargs["leg_name"]) * 64},
    )

    def fake_qualification(*, run_dir: Path, **_kwargs) -> dict[str, object]:
        qualification_calls.append(run_dir)
        seal = run_dir / "reports/fixture_seal.json"
        return {
            "status": "passed",
            "run_dir": str(run_dir),
            "analysis_and_seal": str(seal),
            "seal_sha256": "3" * 64,
            "evidence_content_sha256": "4" * 64,
        }

    monkeypatch.setattr(
        conditional_part_b_campaign,
        "run_bounded_tight_deadband_qualification",
        fake_qualification,
    )

    result = conditional_part_b_campaign.resume_campaign(
        part_a_readiness_path=readiness,
        lower_build_manifest_path=tmp_path / "lower-manifest.json",
        lower_uf2_path=tmp_path / "lower.uf2",
        upper_build_manifest_path=tmp_path / "upper-manifest.json",
        upper_uf2_path=tmp_path / "upper.uf2",
        output_root=root,
        evidence_index_path=tmp_path / "index.json",
        operator_instruction_ref="fixture authority",
        arduino_cli="arduino-cli",
    )

    assert recovery_calls == [lower_run.resolve()]
    assert qualification_calls == [
        (root / "leg_2_upper_acquisition/live_upper_acquisition").resolve(),
        (root / "leg_3_lower_reacquisition/live_lower_reacquisition").resolve(),
    ]
    assert all(path != lower_run.resolve() for path in qualification_calls)
    assert result["status"] == "complete"
    assert len(result["completed_legs"]) == 3
    assert result["completed_legs"][0]["physical_rerun"] is False


def test_part_b_observational_hybrid_profile_resets_each_external_dac_epoch() -> None:
    path = Path(
        "profiles/discipline/cx319_conditional_part_b_hybrid_observation_v1.json"
    )
    profile = json.loads(path.read_text(encoding="utf-8"))

    assert profile["candidate_id"] == "p21600_cap1_epoch_reseed_v3"
    assert all(profile["external_dac_epoch_semantics"].values())
    assert all(value is False for value in profile["authority"].values())
    matrix = json.loads(
        Path("firmware/arduino/firmware_matrix.json").read_text(encoding="utf-8")
    )
    selected = {
        item["id"]: item
        for item in matrix["profiles"]
        if item["id"] in {"cx319_range_part_b_lower", "cx319_range_part_b_upper"}
    }
    assert set(selected) == {"cx319_range_part_b_lower", "cx319_range_part_b_upper"}
    assert all(
        item["defines"]["OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED"]
        == "1"
        for item in selected.values()
    )


def test_part_b_analyzer_rederives_hybrid_identity_and_each_dac_epoch_reset() -> None:
    path = Path(
        "profiles/discipline/cx319_conditional_part_b_hybrid_observation_v1.json"
    ).resolve()
    digest = sha256(path.read_bytes()).hexdigest()
    manifest = {
        "observational_hybrid_preview": {
            "path": str(path),
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }
    }
    dac_rows = [
        {"event": "manual_apply", "seq": "1", "dac_code_applied": "43008"},
        {"event": "active_apply", "seq": "2", "dac_code_applied": "43029"},
    ]
    hpr_rows = [
        {
            "preview_sequence": str(index),
            "candidate_id": "p21600_cap1_epoch_reseed_v3",
            "candidate_configuration_sha256": digest,
            "configuration_sha256": digest,
            "dac_epoch": str(epoch),
            "actual_applied_code": str(code),
            "shadow_code_after": str(code),
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "alternating_correction_count": "0",
            "modeled_not_observed_after_divergence": "false",
            "decision_reason": "dac_epoch_candidate_reseed",
        }
        for index, (epoch, code) in enumerate(((1, 43008), (2, 43029)))
    ]

    result = _part_b_hybrid_epoch_contract(
        manifest=manifest, hpr_rows=hpr_rows, dac_rows=dac_rows
    )

    assert result["exact"] is True
    hpr_rows[1]["correction_count"] = "1"
    assert _part_b_hybrid_epoch_contract(
        manifest=manifest, hpr_rows=hpr_rows, dac_rows=dac_rows
    )["exact"] is False


@pytest.mark.parametrize(
    ("selected", "sequence_index"), [(RANGE_LOWER, 1), (RANGE_UPPER, 2)]
)
def test_part_b_accelerated_rehearsal_crosses_dynamic_host_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected,  # type: ignore[no-untyped-def]
    sequence_index: int,
) -> None:
    proposal = {
        "gate": selected.gate,
        "leg": selected.leg,
        "sequence_index": sequence_index,
        "bundle_sha256": "1" * 64,
        "source_revision": "2" * 40,
        "firmware": {
            "source_sha256": "3" * 64,
            "configuration_sha256": "4" * 64,
            "build_manifest": {"sha256": "5" * 64},
        },
        "leg_spec": {"profile_id": selected.profile_id},
        "intended_live_envelope": {
            "automatic_corrections": 9,
            "maximum_step_codes": 21,
            "maximum_cumulative_codes": 189,
            "minimum_applied_cadence_s": 1800,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": 5400,
            "maximum_qualified_duration_s": 14400,
        },
    }
    monkeypatch.setattr(
        part_b_rehearsal, "validate_proposal", lambda _path: proposal
    )
    monkeypatch.setattr(
        part_b_rehearsal_analyze, "validate_proposal", lambda _path: proposal
    )
    proposal_path = tmp_path / "synthetic-proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    result = part_b_rehearsal.run(
        proposal_path=proposal_path,
        output_dir=tmp_path / "rehearsal",
    )

    assert result["status"] == "passed"
    assert result["sequence_index"] == sequence_index
    transcript = json.loads(
        (
            tmp_path
            / "rehearsal/artifacts"
            / f"{selected.prefix}_operational_transcript_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert transcript["programme_id"] == selected.programme_id
    assert transcript["limits"]["maximum_automatic_corrections"] == 9
    assert transcript["limits"]["maximum_cumulative_codes"] == 189


def test_adaptive_observation_rule_extends_only_a_mixed_boundary() -> None:
    selected, reason = _adaptive_point_rows(
        _rows([-2, -2, -2, -2]), minimum=4, maximum=6
    )
    assert len(selected or []) == 4
    assert reason == "minimum_unmixed"

    selected, reason = _adaptive_point_rows(
        _rows([-2, -3, -2, -3]), minimum=4, maximum=6
    )
    assert selected is None
    assert reason == "awaiting_mixed_extension"

    selected, reason = _adaptive_point_rows(
        _rows([-2, -3, -2, -3, -3, -2]), minimum=4, maximum=6
    )
    assert len(selected or []) == 6
    assert reason == "maximum_mixed_extension"

    selected, reason = _adaptive_point_rows(_rows([-6, -5]), minimum=2, maximum=2)
    assert len(selected or []) == 2
    assert reason == "fixed_minimum"


def test_promotion_transition_accepts_clear_or_honest_mixed_two_code_result() -> None:
    clear, failures = _transition(
        [
            {"code": 0xA819, "integer_edge_error_counts": [-3, -3, -3, -3]},
            {"code": 0xA81B, "integer_edge_error_counts": [-3, -3, -3, -3]},
            {"code": 0xA81D, "integer_edge_error_counts": [-2, -2, -2, -2]},
        ],
        start="outside",
        end="inside",
    )
    assert failures == []
    assert clear["transition_interval_codes"] == [0xA81B, 0xA81D]
    assert clear["transition_width_codes"] == 2

    mixed, failures = _transition(
        [
            {"code": 0xA819, "integer_edge_error_counts": [-3, -3, -3, -3]},
            {"code": 0xA81B, "integer_edge_error_counts": [-2, -3, -2, -3, -2, -3]},
            {"code": 0xA81D, "integer_edge_error_counts": [-2, -2, -2, -2]},
        ],
        start="outside",
        end="inside",
    )
    assert failures == []
    assert mixed["transition_interval_codes"] == [0xA81B, 0xA81B]
    assert mixed["basis"] == "honest_mixed_code"

    mixed_interval, failures = _transition(
        [
            {"code": 0xA817, "integer_edge_error_counts": [-3, -3, -3, -3]},
            {"code": 0xA819, "integer_edge_error_counts": [-3, -2, -3, -2, -3, -2]},
            {"code": 0xA81B, "integer_edge_error_counts": [-2, -3, -2, -3, -2, -3]},
            {"code": 0xA81D, "integer_edge_error_counts": [-2, -2, -2, -2]},
        ],
        start="outside",
        end="inside",
    )
    assert failures == []
    assert mixed_interval["transition_interval_codes"] == [0xA819, 0xA81B]
    assert mixed_interval["transition_width_codes"] == 2
    assert mixed_interval["basis"] == "honest_contiguous_mixed_interval"


def test_focused_bundle_binds_exact_plan_and_six_observation_timeout(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "focused_bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path), output_path=bundle_path
    )
    bundle = validate_bundle(bundle_path)
    segment = bundle["part_a_segment"]
    assert segment["mode"] == "focused_boundary_map"
    assert len(segment["point_plans"]) == 27
    assert segment["point_wait_timeout_s"] == 5220
    assert segment["minimum_remaining_wall_before_new_point_s"] == 5400
    assert segment["frequency_control_authority"] is False
    assert segment["phase_hybrid_authority"] is False


def test_focused_rehearsal_exercises_fixed_and_mixed_adaptive_paths(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "focused_bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path), output_path=bundle_path
    )
    result = run_rehearsal(
        bundle_path=bundle_path, output_dir=tmp_path / "rehearsal"
    )
    assert result["status"] == "passed"
    assert result["real_boundaries"]["adaptive_fixed_two_observation_path"] is True
    assert result["real_boundaries"]["adaptive_fixed_four_observation_path"] is True
    assert result["real_boundaries"]["adaptive_mixed_six_observation_extension"] is True
