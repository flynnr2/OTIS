from __future__ import annotations

from copy import deepcopy

import pytest

from host.otis_tools.tolerance_provenance import (
    CONTRACT_ID,
    render_table,
    validate_table,
)


def _row() -> dict:
    return {
        "parameter_and_units": "estimator span, s",
        "acceptance_rejection_threshold": "candidate 120 s; no selection authority",
        "disposition": "characterization reference",
        "source_hierarchy": [2, 4],
        "source_document_and_location": "sealed Stage 3 analysis and documented 1/T calculation",
        "source_conditions_and_applicability": "actual assembled CX317 rig; fixed-code evidence only",
        "calculation_or_conversion": "one-edge count increment = 1/120 Hz",
        "measurement_uncertainty_and_safety_margin": "combined uncertainty unavailable",
        "measured_result": "not selected",
        "result": "characterization-only",
        "consequences_of_failure": "reject candidate; do not bind Stage 5",
    }


def _table() -> dict:
    return {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "report_id": "stage4_estimator_selection",
        "rows": [_row()],
    }


def test_table_validates_and_renders_all_required_columns() -> None:
    result = validate_table(_table())
    assert result["rows"][0]["source_hierarchy"] == [2, 4]
    markdown = render_table(_table())
    assert "| Parameter and units |" in markdown
    assert "Source conditions and applicability to this rig" in markdown
    assert "Consequences of failure" in markdown
    assert "one-edge count increment = 1/120 Hz" in markdown


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["rows"][0].update(disposition="control requirement"),
            "disposition",
        ),
        (
            lambda value: value["rows"][0].update(result="probably pass"),
            "result",
        ),
        (
            lambda value: value["rows"][0].update(source_hierarchy=[0]),
            "integers 1..5",
        ),
        (
            lambda value: value["rows"][0].pop("consequences_of_failure"),
            "fields differ",
        ),
    ],
)
def test_table_fails_closed_on_invalid_vocabulary_or_missing_fields(
    mutation, message: str
) -> None:
    value = deepcopy(_table())
    mutation(value)
    with pytest.raises(ValueError, match=message):
        validate_table(value)


def test_hierarchy_five_requires_explicit_assumption_label() -> None:
    value = _table()
    value["rows"][0]["source_hierarchy"] = [5]
    with pytest.raises(ValueError, match="conservative engineering assumption"):
        validate_table(value)
    value["rows"][0]["source_conditions_and_applicability"] += (
        "; explicitly labelled conservative engineering assumption"
    )
    validate_table(value)


def test_pass_or_fail_cannot_use_an_unavailable_measured_result() -> None:
    value = _table()
    value["rows"][0]["result"] = "pass"
    value["rows"][0]["measured_result"] = "unavailable"
    with pytest.raises(ValueError, match="requires a measured or calculated result"):
        validate_table(value)
