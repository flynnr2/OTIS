from __future__ import annotations

import ast
from fractions import Fraction
import json
from pathlib import Path

import pytest

from host.otis_tools import (
    sustained_hybrid_equilibrium_estimator_recovery_study as recovery,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY/"
    "observability_report_recovery_v2.json"
)


@pytest.fixture(scope="module")
def contract_and_parent() -> tuple[dict, dict]:
    return recovery.load_recovery_contract()


@pytest.fixture(scope="module")
def reproduced_report() -> dict:
    return recovery.create_observability_report()


def test_recovery_contract_is_separate_frozen_and_offline(
    contract_and_parent: tuple[dict, dict],
) -> None:
    contract, parent = contract_and_parent
    assert contract["contract_sha256"] == (
        "534beecf00ac09087fdbb3f1c36f03660753c29d8a7d3d4ff0756aa9c3f24f80"
    )
    assert contract["parent_contract"]["semantic_sha256"] == (
        "ab2ec34269d0cb21b7895e459201e6d8c500ae050304d8f9f3bd5a829caed682"
    )
    assert contract["unchanged_scientific_contract"]["changes"].startswith("none")
    assert contract["authority"] == parent["authority"]
    assert contract["authority"]["offline_analysis"] is True
    assert set(contract["authority"].values()) == {False, True}
    assert contract["output"]["tool"]["sha256"] == (
        "9fcfdbfdf08cecb0839fc6cbc7e32a4859dfa5908d74ab58de4939a3ed05a959"
    )


def test_exact_plan_recovery_and_raw_bindings_are_identity_validated(
    contract_and_parent: tuple[dict, dict],
) -> None:
    contract, parent = contract_and_parent
    plan = ROOT / contract["source_recovery"]["restored_path"]
    assert plan.stat().st_size == 3459
    assert recovery._file_sha256(plan) == (
        "19609f35e285d8005054f7acdf59341675ae01c1fe986a44cea296a35f95d84d"
    )
    bindings = [
        *parent["tracked_bindings"],
        *parent["attempt4"]["file_bindings"],
        *parent["plant_characterization"]["source_bindings"],
        *contract["additional_source_bindings"],
    ]
    rows, failures = recovery._binding_rows(bindings)
    assert failures == []
    assert rows and all(row["exact"] for row in rows if row["required"])


def test_stage5_supports_reconstruct_exact_counts_and_boundaries(
    reproduced_report: dict,
) -> None:
    rows = reproduced_report["evidence_inventory"][
        "stage5_identification_supports"
    ]
    assert len(rows) == 18
    assert [row["count_error"] for row in rows] == [
        28,
        27,
        2,
        3,
        -6,
        -6,
        2,
        2,
        28,
        28,
        55,
        54,
        72,
        73,
        55,
        55,
        28,
        29,
    ]
    assert rows[0]["first_snapshot_sequence"] == 3289
    assert rows[0]["last_snapshot_sequence"] == 3889
    assert all(
        row["last_reference_sequence"] - row["first_reference_sequence"] == 600
        for row in rows
    )
    assert {row["capture_session"] for row in rows} == {"1"}


def test_attempt4_remains_complete_held_out_physical_validation(
    reproduced_report: dict,
) -> None:
    rows = reproduced_report["evidence_inventory"]["attempt4_held_out_supports"]
    assert len(rows) == 52
    assert {row["evidence_source"] for row in rows} == {
        "attempt4_held_out_validation"
    }
    assert {row["dac_epoch"] for row in rows} == {
        f"live:DAC:{epoch}" for epoch in range(1, 13)
    }
    assert reproduced_report["evidence_partition"]["held_out_validation"][
        "use"
    ].startswith("prediction only")


def test_all_frozen_models_have_empty_complete_sets_at_every_gain(
    reproduced_report: dict,
) -> None:
    assert [row["model_id"] for row in reproduced_report["model_hypotheses"]] == [
        "constant_equilibrium_per_stage5_thermal_segment_v1",
        "bounded_slow_drift_equilibrium_v1",
        "direction_history_conditioned_equilibrium_v1",
    ]
    for model in reproduced_report["model_hypotheses"]:
        assert set(model["gain_cases"]) == {"minimum", "nominal", "maximum"}
        for case in model["gain_cases"].values():
            assert case["bounded"] is False
            assert case["complete_interval"] is None
            assert case["useful_span_passed"] is False
            assert case["held_out_prediction"]["passed"] is False
    constant = reproduced_report["model_hypotheses"][0]
    assert constant["gain_cases"]["minimum"]["numerical"][
        "first_empty_after_support"
    ]["last_snapshot_sequence"] == 6891
    assert constant["gain_cases"]["nominal"]["numerical"][
        "first_empty_after_support"
    ]["last_snapshot_sequence"] == 6291


def test_exact_linear_projection_rejects_an_inconsistent_bounded_drift() -> None:
    intervals = [
        recovery.original.ClosedInterval(Fraction(0), Fraction(0)),
        recovery.original.ClosedInterval(Fraction(10), Fraction(10)),
    ]
    result = recovery._linear_projection(
        intervals,
        [Fraction(0), Fraction(1)],
        slope_limit=Fraction(1),
    )
    assert result == {
        "feasible": False,
        "slope_codes_per_hour": None,
        "equilibrium_at_reference": None,
    }


def test_not_observable_terminal_and_gate_order_are_fail_closed(
    reproduced_report: dict,
) -> None:
    assert reproduced_report["terminal"] == recovery.NOT_OBSERVABLE_TERMINAL
    assert reproduced_report["first_discriminating_failure"] == (
        "identification_complete_feasible_set_nonempty"
    )
    assert reproduced_report["eligible_models_passing_every_frozen_gate"] == []
    gates = reproduced_report["feasibility_gate_checks"]
    assert [row["index"] for row in gates] == list(range(1, 11))
    assert [row["passed"] for row in gates] == [
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
    ]
    assert reproduced_report["decision"]["equilibrium_estimator_selected"] is False
    assert reproduced_report["physical_actions_performed"] == 0


def test_published_recovery_report_is_canonical_and_reproducible(
    reproduced_report: dict,
) -> None:
    published = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert published == reproduced_report
    unsigned = {
        key: value for key, value in published.items() if key != "report_sha256"
    }
    assert published["report_sha256"] == recovery._canonical_sha256(unsigned)
    assert published["report_sha256"] == (
        "dae8dcc78cd816152246e06df1886ed572e873ed2ca1fd52e38c91f80228b21b"
    )
    assert recovery._file_sha256(REPORT_PATH) == (
        "325e585290ff216203101c772b78bf20ab9e25e8a4398fe544da498b1699b91a"
    )


def test_recovery_comparator_has_no_live_or_actuator_import_surface() -> None:
    source_path = Path(recovery.__file__)
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
