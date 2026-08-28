from __future__ import annotations

import ast
from pathlib import Path

import pytest

from host.otis_tools import sustained_hybrid_mode_separation_study as study


@pytest.fixture(scope="module")
def report() -> dict:
    return study.create_comparison_report()


def test_contract_is_frozen_offline_and_uses_differential_gain_model() -> None:
    contract = study.load_contract()

    assert contract["contract_sha256"] == (
        "c02ce352d5224b5ed395d48d62a2ddc8a99654d08b95ad23a182186a716a37eb"
    )
    assert contract["authority"]["offline_analysis"] is True
    assert set(contract["authority"].values()) == {False, True}
    assert contract["model"][
        "continuous_nonzero_code_difference_offset_forbidden"
    ] is True
    assert contract["model"]["calibrated_or_combined_uncertainty_claim"] is False


def test_mode_architectures_preserve_phase_priority_and_reset_support() -> None:
    one_count = study.MaintenanceArchitecture(
        "phase_priority_one_count_hold_v1"
    )
    phase_value, phase_reason = one_count.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        phase_material=True,
        capture_session=1,
        dac_epoch=1,
        source_first=0,
        source_last=600,
    )
    maintenance_value, maintenance_reason = one_count.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        phase_material=False,
        capture_session=1,
        dac_epoch=1,
        source_first=600,
        source_last=1200,
    )
    assert phase_value == 1 / 600
    assert phase_reason == "phase_material_full_combined_law"
    assert maintenance_value == 0.0
    assert maintenance_reason == "maintenance_one_count_hold"

    aggregate = study.MaintenanceArchitecture(
        "phase_priority_1200s_maintenance_v1"
    )
    first, first_reason = aggregate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        phase_material=False,
        capture_session=1,
        dac_epoch=1,
        source_first=0,
        source_last=600,
    )
    second, second_reason = aggregate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        phase_material=False,
        capture_session=1,
        dac_epoch=1,
        source_first=600,
        source_last=1200,
    )
    assert first == 0.0
    assert first_reason == "maintenance_1200s_support_incomplete"
    assert second == 1 / 600
    assert second_reason == "maintenance_1200s_aggregate_ready"

    aggregate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        phase_material=False,
        capture_session=1,
        dac_epoch=1,
        source_first=1200,
        source_last=1800,
    )
    reset, reset_reason = aggregate.effective_frequency_error(
        frequency_error_hz=1 / 600,
        counts=1,
        tight_state=study.TIGHT_INSIDE,
        phase_material=False,
        capture_session=1,
        dac_epoch=2,
        source_first=1800,
        source_last=2400,
    )
    assert reset == 0.0
    assert reset_reason == "maintenance_1200s_support_incomplete"


@pytest.mark.historical
def test_comparison_preserves_early_phase_path_and_rejects_all_candidates(
    report: dict,
) -> None:
    assert report["status"] == "passed"
    assert report["terminal"] == "no_mode_separated_architecture_selected"
    assert report["selected_candidate_id"] is None
    assert report["exact_v1_baseline"]["exact"] is True
    assert report["mode_classifier_replay"]["phase_material_sequences"] == [
        6,
        9,
        11,
        13,
        16,
        19,
        21,
    ]
    assert report["mode_classifier_replay"][
        "frequency_only_maintenance_sequences"
    ] == [25, 28, 44, 48]
    comparisons = report["candidate_comparisons"]
    assert [item["candidate_id"] for item in comparisons] == [
        "phase_priority_one_count_hold_v1",
        "separated_fll_pll_maintenance_v1",
        "phase_priority_1200s_maintenance_v1",
    ]
    assert all(item["selectable"] is False for item in comparisons)
    assert all(
        item["first_discriminating_failure"]
        == "minimum:frequency_behavior_preserved"
        for item in comparisons
    )
    for comparison in comparisons:
        for scenario in comparison["scenarios"]:
            assert scenario["selection_checks"][
                "first_seven_phase_material_applications_exact"
            ] is True
            assert scenario["phase_metrics"]["pass"] is True
            assert scenario["frequency_metrics"]["pass"] is False
            assert scenario["summary"]["natural_path_codes"] > 27
    assert report["decision"]["next_gate"] == (
        "estimator_state_and_uncertainty_architecture_revision"
    )
    unsigned = {
        key: value for key, value in report.items() if key != "report_sha256"
    }
    assert report["report_sha256"] == study._canonical_sha256(unsigned)


def test_comparator_has_no_live_or_actuator_import_surface() -> None:
    source_path = Path(study.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden_fragments = {
        "serial",
        "active_hybrid_run",
        "active_hybrid_live",
        "firmware_upload",
        "i2c",
    }
    assert not {
        name
        for name in imports
        if any(fragment in name for fragment in forbidden_fragments)
    }
