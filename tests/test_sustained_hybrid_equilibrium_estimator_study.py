from __future__ import annotations

import ast
from fractions import Fraction
import json
from pathlib import Path

import pytest

from host.otis_tools import sustained_hybrid_equilibrium_estimator_study as study


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY/"
    "observability_report_v1.json"
)


@pytest.fixture(scope="module")
def contract() -> dict:
    return study.load_contract()


@pytest.fixture(scope="module")
def published_report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_contract_is_frozen_offline_and_numeric_before_results(contract: dict) -> None:
    assert contract["contract_sha256"] == (
        "ab2ec34269d0cb21b7895e459201e6d8c500ae050304d8f9f3bd5a829caed682"
    )
    assert contract["authority"]["offline_analysis"] is True
    assert set(contract["authority"].values()) == {False, True}
    assert contract["pre_study_status"]["active_programme"] is None
    assert contract["pre_study_status"]["all_physical_authority_false"] is True
    assert contract["usefulness_gate"][
        "maximum_equilibrium_interval_span_codes"
    ] == 18
    assert contract["usefulness_gate"][
        "minimum_nonvacuous_phase_excursion_duration_s_at_minimum_gain"
    ] == 6114
    assert contract["terminal_outcomes"] == [
        study.OBSERVABLE_TERMINAL,
        study.NOT_OBSERVABLE_TERMINAL,
        study.INVALID_TERMINAL,
    ]


def test_exact_interval_arithmetic_empty_set_and_unbounded_gain_guard() -> None:
    left = study.ClosedInterval(Fraction(1), Fraction(3))
    right = study.ClosedInterval(Fraction(2), Fraction(4))
    assert left.intersect(right) == study.ClosedInterval(Fraction(2), Fraction(3))
    assert study.intersect_all([left, right]) == study.ClosedInterval(
        Fraction(2), Fraction(3)
    )
    assert study.intersect_all(
        [left, study.ClosedInterval(Fraction(4), Fraction(5))]
    ) is None
    with pytest.raises(ValueError, match="strictly positive"):
        left.divide_positive(study.ClosedInterval(Fraction(0), Fraction(1)))


def test_gain_sign_units_and_observation_inversion_are_exact() -> None:
    observation = study.count_quantization_interval(1)
    assert observation == study.ClosedInterval(Fraction(1, 1200), Fraction(1, 400))
    gain = study.ClosedInterval(Fraction(1, 6000), Fraction(1, 6000))
    zero = study.ClosedInterval(Fraction(0), Fraction(0))
    equilibrium = study.equilibrium_interval_from_observation(
        applied_code=100,
        frequency_error_hz=observation,
        gain_hz_per_code=gain,
        nuisance_hz=zero,
    )
    assert equilibrium == study.ClosedInterval(Fraction(85), Fraction(95))
    with pytest.raises(ValueError, match="strictly positive"):
        study.equilibrium_interval_from_observation(
            applied_code=100,
            frequency_error_hz=observation,
            gain_hz_per_code=study.ClosedInterval(Fraction(-1), Fraction(-1, 2)),
            nuisance_hz=zero,
        )


def test_quantization_and_same_code_count_sensitivities() -> None:
    assert study.count_quantization_interval(0) == study.ClosedInterval(
        Fraction(-1, 1200), Fraction(1, 1200)
    )
    assert study.count_quantization_interval(0, perturbation_counts=1) == (
        study.ClosedInterval(Fraction(1, 1200), Fraction(1, 400))
    )
    assert study.count_quantization_interval(0, perturbation_counts=-1) == (
        study.ClosedInterval(Fraction(-1, 400), Fraction(-1, 1200))
    )
    with pytest.raises(ValueError, match="positive"):
        study.count_quantization_interval(0, support_seconds=0)


def test_integer_midpoint_usefulness_boundary() -> None:
    useful = study.ClosedInterval(Fraction(100), Fraction(118))
    too_wide = study.ClosedInterval(Fraction(100), Fraction(119))
    assert study.worst_integer_midpoint_return_error_codes(useful) == 9
    assert study.worst_integer_midpoint_return_error_codes(too_wide) == 10


def test_partition_identity_reset_and_phase_epoch_rules_are_frozen(
    contract: dict,
) -> None:
    partition = contract["evidence_partition"]
    assert partition["identification"]["source"].startswith("complete Stage 5")
    assert partition["held_out_validation"]["source"].startswith(
        "complete Attempt 4"
    )
    assert partition["held_out_validation"]["use"].startswith("prediction only")
    semantics = contract["nuisance_and_arithmetic_semantics"]
    assert semantics["DAC_epoch_change"] == "reset_support"
    assert semantics["capture_session_change"] == "reset_support"
    assert semantics["settling_exclusion_s"] == 900
    assert semantics["fresh_support_s"] == 600
    assert semantics["phase_epoch_join"] == "forbidden"
    assert contract["state_and_observation_semantics"]["D10_role"].endswith(
        "excluded from estimator"
    )


def test_all_frozen_model_and_nuisance_branches_are_bounded(contract: dict) -> None:
    assert [item["model_id"] for item in contract["model_hypotheses"]] == [
        "constant_equilibrium_per_stage5_thermal_segment_v1",
        "bounded_slow_drift_equilibrium_v1",
        "direction_history_conditioned_equilibrium_v1",
    ]
    required = {
        "plant_gain_minimum",
        "plant_gain_nominal",
        "plant_gain_maximum",
        "quantization_lower_and_upper_boundaries",
        "same_code_positive_one_count",
        "same_code_negative_one_count",
        "reversal_eight_code_dead_zone",
        "bounded_slow_drift",
        "settling_boundary_below_at_above",
        "DAC_epoch_change",
        "capture_session_change",
        "phase_epoch_reset",
        "temperature_context_extremes",
        "leave_one_complete_segment_out",
    }
    assert set(contract["sensitivity_cases"]) == required


def test_terminal_selection_precedence_and_tie_rule() -> None:
    terminal, reason = study.select_terminal(
        identity_failures=[{"failure_id": "required_source_missing"}],
        baseline_exact=True,
        model_evaluated=False,
        all_feasibility_checks_passed=False,
    )
    assert terminal == study.INVALID_TERMINAL
    assert reason == "required_source_missing"
    terminal, _ = study.select_terminal(
        identity_failures=[],
        baseline_exact=True,
        model_evaluated=True,
        all_feasibility_checks_passed=False,
    )
    assert terminal == study.NOT_OBSERVABLE_TERMINAL
    terminal, _ = study.select_terminal(
        identity_failures=[],
        baseline_exact=True,
        model_evaluated=True,
        all_feasibility_checks_passed=True,
    )
    assert terminal == study.OBSERVABLE_TERMINAL


@pytest.mark.historical
def test_exact_baseline_reproduction_and_stage0_terminal(
    contract: dict,
    published_report: dict,
) -> None:
    reproduced = study._reproduce_predecessors(contract)
    assert reproduced["successor_report_reproduced"] is True
    assert reproduced["mode_report_reproduced"] is True
    assert reproduced["exact_v1_baseline_reproduced"] is True
    assert reproduced["exact_v1_baseline"]["application_deltas"] == [
        -6,
        -1,
        -1,
        -6,
        -1,
        -1,
        -1,
        5,
        5,
        -5,
        5,
    ]
    assert published_report["terminal"] == study.INVALID_TERMINAL
    assert published_report["first_discriminating_failure"] == (
        "required_source_missing"
    )
    assert published_report["decision"]["equilibrium_interval_computed"] is False
    assert published_report["physical_actions_performed"] == 0
    failures = published_report["source_identity_validation"]["failures"]
    assert failures == [
        {
            "failure_id": "required_source_missing",
            "path": "profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json",
            "expected_sha256": (
                "19609f35e285d8005054f7acdf59341675ae01c1fe986a44cea296a35f95d84d"
            ),
            "actual_sha256": None,
        }
    ]
    recovered_plan = ROOT / "profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json"
    assert study._file_sha256(recovered_plan) == (
        "19609f35e285d8005054f7acdf59341675ae01c1fe986a44cea296a35f95d84d"
    )


def test_published_first_attempt_report_remains_canonical_and_immutable(
    published_report: dict,
) -> None:
    unsigned = {
        key: value
        for key, value in published_report.items()
        if key != "report_sha256"
    }
    assert published_report["report_sha256"] == study._canonical_sha256(unsigned)
    assert published_report["report_sha256"] == (
        "b98bf927170c0f8f868007cf5aa497898d3d7c65a57583b30c299dacd64547c3"
    )


def test_comparator_has_no_live_serial_firmware_or_actuator_import_surface() -> None:
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
        "dac",
        "command_fifo",
    }
    assert not {
        name
        for name in imports
        if any(fragment in name for fragment in forbidden_fragments)
    }
