from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from host.otis_tools.conditional_part_a_bundle import create_bundle, validate_bundle
from host.otis_tools.conditional_part_a_promotion import _transition
from host.otis_tools.conditional_range_campaign import campaign_summary, load_campaign
from host.otis_tools.range_spanning_run import _adaptive_point_rows
from host.otis_tools.range_spanning_rehearsal import run as run_rehearsal


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
        "programme_id": "CX319_CONDITIONAL_FINE_MAP_AND_FREQUENCY_TRAVERSAL_V2",
        "part_a_point_count": 17,
        "part_a_minimum_observations": 64,
        "part_a_maximum_observations": 88,
        "part_a_operational_minimum_s": 63_900,
        "part_a_operational_maximum_s": 78_300,
        "part_b_leg_count": 3,
        "part_b_maximum_per_leg_s": 14_400,
        "phase_hybrid_authority": False,
    }
    assert [item["code"] for item in campaign["part_a"]["point_plan"]] == [
        0xA800,
        0xA830,
        0xA819,
        0xA81B,
        0xA81D,
        0xA81D,
        0xA81B,
        0xA819,
        0xA830,
        0xA849,
        0xA84B,
        0xA84D,
        0xA84D,
        0xA84B,
        0xA849,
        0xA830,
        0xA800,
    ]


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
    assert len(segment["point_plans"]) == 17
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
