from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "estimators" / "cx317_pps_gated_selected_v1.json"
SCHEMA = ROOT / "schemas" / "cx317_selected_estimator_profile_v1.schema.json"
BASE = ROOT / "profiles" / "estimators" / "pps_cumulative_snapshot_span_v1.json"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_selected_profile_schema_and_evidence_binding() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)

    assert profile["base_estimator"]["sha256"] == _sha256(BASE)
    assert profile["authoritative_policy"]["span_s"] == 600
    assert profile["authoritative_policy"]["output_mode"] == "non_overlapping"
    assert profile["diagnostic_policy"]["spans_s"] == [60]
    assert profile["diagnostic_policy"]["decision_authority"] is False
    assert profile["authority"] == {
        "observe_only": True,
        "actuation_authorized": False,
        "actionable": False,
        "diagnostic_bypass_permitted": False,
        "controller_ported_to_firmware": False,
    }


def test_selected_profile_freezes_fail_closed_fresh_support() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    authoritative = profile["authoritative_policy"]
    assert authoritative["output_cadence_s"] == authoritative["span_s"]
    assert authoritative["fresh_support_recovery_time_s"] == 600
    assert authoritative["calibrated_resolution_status"] == "unavailable"
    assert profile["invalidation_policy"]["recovery_policy"] == (
        "fresh_contiguous_support_required_for_each_span"
    )
    assert "dac_control_epoch" in profile["invalidation_policy"]["reset_on"]
    assert profile["selection_evidence"]["historical_gain_comparison"][
        "control_authority"
    ] is False
