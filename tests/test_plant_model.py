from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from host.otis_tools.plant_model import load_plant_model, validate_plant_model


LEGACY_MODEL = Path("profiles/plant_models/cx317_h1_bench_v1.json")
MODEL = Path("profiles/plant_models/cx317_h1_bench_v2.json")
SCHEMA = Path("schemas/plant_model_v1.schema.json")


def test_loads_historical_run_017_plant_model_unchanged() -> None:
    model = load_plant_model(LEGACY_MODEL)

    assert model.model_id == "cx317_h1_bench"
    assert model.model_version == 2
    assert model.nominal_code == 0x8000
    assert model.crossing_code is None
    assert model.applicability_range is None
    assert model.automatic_control_range == (0x7000, 0x9000)
    assert not model.control_ready
    assert not model.actuation_enabled
    assert model.data["status"]["readiness"] == "plant_model_v2_run_017_analysis_useful_no_active_actuation"
    assert model.data["dac"]["reference_voltage_v"] == pytest.approx(2.5)
    assert model.data["dac"]["nominal_code"] == 0x8000
    assert model.data["dac"]["manual_safe_range_codes"] == {"min": 0x7000, "max": 0x9000}
    slope = model.data["plant_response"]["local_slope"]
    assert slope["sign"] == "positive"
    assert 4.15 <= slope["hz_per_v"] <= 4.68
    assert slope["uncertainty"]["hz_per_v_min"] == pytest.approx(4.153638945952538)
    assert slope["uncertainty"]["hz_per_v_max"] == pytest.approx(4.67415366682314)
    reference = model.data["plant_response"]["reference_integrity"]
    assert reference["host_pps_anomalies"] == 0
    assert reference["timestamp_wrap_count"] == 16
    assert reference["d14_rejected_long_count"] == 16
    assert "rollover-safe modular timer arithmetic" in reference["d14_rejected_long_count_interpretation"]
    startup = model.data["plant_response"]["startup_control_eligibility"]
    assert startup["fc0_valid_for_control"] is True
    assert startup["invalid_count_windows"] == 0
    assert model.data["source_evidence"]["source_commits"]["model_updated_from_repo_commit"] == (
        "0ebdae3266635bc98b9518a59fcfaa68751c4024"
    )
    assert model.data["source_evidence"]["source_commits"]["run_manifest_host_git_commit"] == (
        "0ebdae3266635bc98b9518a59fcfaa68751c4024"
    )
    assert model.data["source_evidence"]["source_versions"] == {
        "run_manifest_host_tool_version": "0.0.0",
        "run_manifest_firmware_version": "SW1",
    }


def test_loads_run_020_observe_only_plant_model() -> None:
    model = load_plant_model(MODEL)

    assert model.model_id == "cx317_h1_bench"
    assert model.model_version == 3
    assert model.nominal_code == 0xA950
    assert model.crossing_code == 0xA950
    assert model.automatic_control_range == (0xA800, 0xAB00)
    assert model.applicability_range == (0xA800, 0xB400)
    assert not model.control_ready
    assert not model.actuation_enabled
    assert model.data["status"]["readiness"] == "plant_model_v3_run_020_validated_observe_only"

    slope = model.data["plant_response"]["local_slope"]
    assert slope["sign"] == "positive"
    assert slope["hz_per_code"] == pytest.approx(0.0001673035127775317)
    assert slope["hz_per_v"] == pytest.approx(4.415447480965722)
    assert slope["uncertainty"]["hz_per_v_min"] == pytest.approx(4.114661261287408)
    assert slope["uncertainty"]["hz_per_v_max"] == pytest.approx(4.9513614382035)

    crossing = model.data["plant_response"]["crossing_estimate"]
    assert crossing["code_min"] == 0xA840
    assert crossing["code_max"] == 0xAA00
    assert crossing["observed_bracket"]["below_code"] == 0xA800
    assert crossing["observed_bracket"]["above_code"] == 0xAB00

    applicability = model.data["plant_response"]["applicability"]
    assert applicability["mode"] == "observe_only"
    assert applicability["settling_exclusion_s"] == pytest.approx(900.0)
    assert applicability["excluded_count_sequences"] == [77]


def test_schema_and_canonical_source_references_are_present() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    model = load_plant_model(MODEL).data

    assert schema["properties"]["schema_version"]["const"] == 1
    assert "crossing_estimate" in schema["$defs"]["plant_response"]["properties"]
    assert "applicability" in schema["$defs"]["plant_response"]["properties"]
    artifacts = model["source_evidence"]["source_artifacts"]
    assert "docs/60_EXPERIMENTS/RUN_019_PLANT_MODEL_RESULTS.md" in artifacts
    assert "docs/60_EXPERIMENTS/RUN_020_PLANT_MODEL_RESULTS.md" in artifacts
    assert "runs/h1_open_loop/dac_manual_sweep/run_020/evidence_manifest.json" in artifacts
    assert "runs/h1_open_loop/dac_manual_sweep/run_020/reports/run_020_analysis_precis.md" in artifacts
    assert Path("docs/60_EXPERIMENTS/RUN_019_PLANT_MODEL_RESULTS.md").exists()
    assert "runs/" in Path(".gitignore").read_text(encoding="utf-8")


def test_rejects_automatic_range_outside_manual_safe_range() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["automatic_control_range_codes"]["min"] = 0xA7FF

    with pytest.raises(ValueError, match="below manual_safe_range_codes.min"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["dac"]["automatic_control_range_codes"]["max"] = 0xB401

    with pytest.raises(ValueError, match="above manual_safe_range_codes.max"):
        validate_plant_model(changed)


def test_rejects_range_that_does_not_contain_crossing_uncertainty() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["automatic_control_range_codes"]["min"] = 0xA900

    with pytest.raises(ValueError, match="does not contain crossing_estimate.code_min"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["dac"]["automatic_control_range_codes"]["max"] = 0xA980

    with pytest.raises(ValueError, match="does not contain crossing_estimate.code_max"):
        validate_plant_model(changed)


def test_rejects_nominal_code_outside_automatic_range() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["nominal_code"] = 0xA700

    with pytest.raises(ValueError, match="nominal_code is below"):
        validate_plant_model(changed)


def test_rejects_non_observe_only_applicability() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["plant_response"]["applicability"]["mode"] = "active_control"

    with pytest.raises(ValueError, match="mode must be observe_only"):
        validate_plant_model(changed)


def test_rejects_empty_string_unknowns_and_enabled_actuation() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["reference_voltage_v"] = ""

    with pytest.raises(ValueError, match="must be null when unknown"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["status"]["actuation_enabled"] = True

    with pytest.raises(ValueError, match="actuation_enabled must remain false"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["status"]["control_ready"] = True

    with pytest.raises(ValueError, match="control_ready must remain false"):
        validate_plant_model(changed)


def test_rejects_zero_slope_as_unknown_sentinel() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["plant_response"]["local_slope"]["hz_per_v"] = 0

    with pytest.raises(ValueError, match="must be null when unknown"):
        validate_plant_model(changed)
