from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_open_loop_scheduler import (
    CampaignPlan,
    INITIAL_SEQUENCE_CODES,
    dry_run_events,
    load_plan,
)


PLAN_PATH = Path(
    "profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json"
)


def _mapping() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def test_plan_is_non_authorizing_and_matches_initial_campaign() -> None:
    plan = load_plan(PLAN_PATH)
    assert tuple(step.code for step in plan.sequence) == INITIAL_SEQUENCE_CODES
    assert plan.min_code == 0xA800
    assert plan.max_code == 0xAB00
    assert plan.final_safe_code == 0xA950
    assert plan.automatic_restore is False
    assert plan.feedback_derived_commands is False
    assert plan.hardware_authorized is False
    assert plan.firmware_configuration_sha256 == (
        "4a6ab7595dddbb9c5856cfab51c15985b09a0b53720ad6730db82343764186d4"
    )
    assert plan.firmware_uf2_sha256 == (
        "d3484d05d3a2d75c90a84426d8487c9371aa0ff6b43876c8bee37947a2d10459"
    )
    assert plan.selected_estimator_config_sha256 == (
        "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c"
    )
    assert plan.selected_authoritative_span_s == 600
    assert plan.ack_deadline_s == pytest.approx(3.0114261680282652)
    assert plan.deadline_slack_s == pytest.approx(1.0)
    assert set(plan.provenance) == {
        "sequence",
        "warmup",
        "dwell",
        "settling_exclusion",
        "clamp",
        "dac_code_domain",
        "selected_span_fit",
        "final_safe_code",
        "deadline_slack",
        "firmware_binding",
    }
    assert "floor(1,500/600)=2" in plan.provenance["selected_span_fit"]


def test_dry_run_has_exact_timing_and_no_restore() -> None:
    plan = load_plan(PLAN_PATH)
    events = dry_run_events(plan)
    requests = [item for item in events if item["event"] == "transition_request"]
    assert [item["code"] for item in requests] == list(INITIAL_SEQUENCE_CODES)
    assert [item["planned_elapsed_s"] for item in requests] == [
        1800 + 2400 * index for index in range(9)
    ]
    assert events[-1] == {
        "event": "campaign_complete_fail_static",
        "code": 0xA950,
        "planned_elapsed_s": 23_400,
        "automatic_restore": False,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value.update(automatic_restore=True),
            "automatic restore must remain false",
        ),
        (
            lambda value: value.update(feedback_derived_commands=True),
            "feedback-derived commands must remain false",
        ),
        (
            lambda value: value["sequence"][0].update(code=0xA7FF),
            "outside the clamp",
        ),
        (
            lambda value: value["dac_clamp"].update(min_code=0),
            "initial clamp",
        ),
        (
            lambda value: value.update(final_safe_code=0xA850),
            "last campaign step",
        ),
        (
            lambda value: value.update(selected_authoritative_span_s=1501),
            "does not fit",
        ),
    ],
)
def test_plan_rejects_unsafe_or_inconsistent_changes(mutation, message: str) -> None:
    value = deepcopy(_mapping())
    mutation(value)
    with pytest.raises(ValueError, match=message):
        CampaignPlan.from_mapping(value)


def test_hardware_binding_is_complete_but_never_self_authorizes() -> None:
    plan = load_plan(PLAN_PATH)
    plan.require_hardware_binding()


def test_fully_bound_plan_still_cannot_self_authorize_hardware() -> None:
    value = _mapping()
    value["selected_estimator_config_sha256"] = "a" * 64
    value["selected_authoritative_span_s"] = 600
    value["ack_deadline_s"] = 2.0
    value["deadline_slack_s"] = 1.0
    plan = CampaignPlan.from_mapping(value)
    plan.require_hardware_binding()
    value["hardware_authorized"] = True
    with pytest.raises(ValueError, match="hardware authorization must remain false"):
        CampaignPlan.from_mapping(value)
