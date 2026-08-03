from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from host.otis_tools.phase4_boundary_estimator import estimator_method_contract
from host.otis_tools.plant_model import (
    ModelApplicabilityContext,
    assess_control_eligibility,
    assess_evidence_availability,
    assess_model_applicability,
    estimator_contract_definition_hash,
    load_plant_model,
    validate_plant_model,
    validate_plant_model_semantics,
    validate_plant_model_structure,
)


LEGACY_MODEL = Path("profiles/plant_models/cx317_h1_bench_v1.json")
MODEL = Path("profiles/plant_models/cx317_h1_bench_v3.json")
PPS_GATED_MODEL = Path("profiles/plant_models/cx317_pps_gated_v1.json")
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
    assert model.model_version == 4
    assert model.nominal_code == 0xA950
    assert model.crossing_code == 0xA950
    assert model.automatic_control_range == (0xA800, 0xAB00)
    assert model.applicability_range == (0xA800, 0xB400)
    assert not model.control_ready
    assert not model.actuation_enabled
    assert (
        model.data["status"]["readiness"]
        == "plant_model_v4_boundary_interpolated_contract_observe_only"
    )

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
    method = applicability["estimator_method_contract"]
    assert method["estimator_method_id"] == (
        "LOCAL_PPS_BOUNDARY_INTERPOLATED_V1"
    )
    assert method["boundary_interpolation"] == (
        "independent_bracketing_accepted_pps_pairs"
    )
    assert method["extrapolation_policy"] == "prohibited"


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


def test_loads_stage5_pps_gated_observe_only_plant_model() -> None:
    model = load_plant_model(PPS_GATED_MODEL)

    assert model.model_id == "cx317_pps_gated_bench"
    assert model.model_version == 1
    assert model.nominal_code == 0xA950
    assert model.crossing_code == 0xA83E
    assert model.automatic_control_range == (0xA800, 0xAB00)
    assert model.applicability_range == (0xA800, 0xAB00)
    assert not model.control_ready
    assert not model.actuation_enabled

    slope = model.data["plant_response"]["local_slope"]
    assert slope["sign"] == "positive"
    assert slope["hz_per_code"] == pytest.approx(0.00017008467693813145)
    assert slope["hz_per_v"] is None

    applicability = model.data["plant_response"]["applicability"]
    assert applicability["gate_duration_s"] == 600
    assert applicability["settling_exclusion_s"] == 900
    assert applicability["estimator_method_contract"]["estimator_method_id"] == (
        "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1"
    )
    assert model.data["control_path"]["measured_control_voltage_at_nominal_v"] is None


def test_every_committed_model_is_structurally_and_semantically_valid() -> None:
    paths = sorted(Path("profiles/plant_models").glob("*.json"))
    assert paths == [
        Path("profiles/plant_models/cx317_h1_bench_v1.json"),
        Path("profiles/plant_models/cx317_h1_bench_v2.json"),
        Path("profiles/plant_models/cx317_h1_bench_v3.json"),
        Path("profiles/plant_models/cx317_pps_gated_v1.json"),
    ]
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert validate_plant_model_structure(data).valid, path
        assert validate_plant_model_semantics(data).valid, path


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

    with pytest.raises(ValueError, match="'observe_only' was expected"):
        validate_plant_model(changed)


def test_rejects_unknown_estimator_method_hash() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["plant_response"]["applicability"][
        "estimator_method_contract"
    ]["method_definition_hash"] = "0" * 64

    with pytest.raises(ValueError, match="does not match its contract definition"):
        validate_plant_model(changed)


def test_rejects_empty_string_unknowns_and_enabled_actuation() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["reference_voltage_v"] = ""

    with pytest.raises(ValueError, match="is not of type 'number', 'null'"):
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


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ((), {"unexpected_top_level": True}),
        (("dac",), {"unexpected_dac_policy": 1}),
        (("plant_response", "applicability"), {"unknown_condition": "x"}),
    ],
)
def test_unknown_fields_are_rejected_at_every_object_boundary(
    path: tuple[str, ...],
    value: dict[str, object],
) -> None:
    changed = copy.deepcopy(load_plant_model(MODEL).data)
    target = changed
    for part in path:
        target = target[part]
    target.update(value)

    result = validate_plant_model_structure(changed)

    assert not result.valid
    assert any(
        "Additional properties are not allowed" in error
        for error in result.errors
    )


def test_provenance_fields_are_structurally_and_semantically_enforced() -> None:
    model = load_plant_model(MODEL).data

    changed = copy.deepcopy(model)
    del changed["source_evidence"]["source_commits"][
        "run_manifest_firmware_git_commit"
    ]
    result = validate_plant_model_structure(changed)
    assert not result.valid
    assert any("required property" in error for error in result.errors)

    changed = copy.deepcopy(model)
    changed["source_evidence"]["source_commits"][
        "run_manifest_host_git_commit"
    ] = "not-a-commit"
    result = validate_plant_model_structure(changed)
    assert not result.valid
    assert any("not valid under any" in error for error in result.errors)

    changed = copy.deepcopy(model)
    changed["source_evidence"]["source_artifacts"][0] = "../outside"
    result = validate_plant_model_structure(changed)
    assert not result.valid
    assert any("does not match" in error for error in result.errors)

    changed = copy.deepcopy(model)
    for key in changed["source_evidence"]["source_commits"]:
        changed["source_evidence"]["source_commits"][key] = None
    assert validate_plant_model_structure(changed).valid
    semantic = validate_plant_model_semantics(changed)
    assert not semantic.valid
    assert "must contain a known commit" in semantic.errors[0]

    changed = copy.deepcopy(load_plant_model(PPS_GATED_MODEL).data)
    changed["source_evidence"]["source_hashes"].pop(
        changed["source_evidence"]["source_artifacts"][0]
    )
    assert validate_plant_model_structure(changed).valid
    semantic = validate_plant_model_semantics(changed)
    assert not semantic.valid
    assert any("keys must exactly match" in error for error in semantic.errors)


def test_source_hashes_are_verified_when_present(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.txt"
    evidence_path.write_text("sealed evidence\n", encoding="utf-8")
    changed = copy.deepcopy(load_plant_model(PPS_GATED_MODEL).data)
    changed["source_evidence"]["source_artifacts"] = ["evidence.txt"]
    changed["source_evidence"]["source_hashes"] = {
        "evidence.txt": hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    }
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(changed), encoding="utf-8")
    model = load_plant_model(model_path)

    assert assess_evidence_availability(model, tmp_path).available

    evidence_path.write_text("changed\n", encoding="utf-8")
    result = assess_evidence_availability(model, tmp_path)
    assert not result.available
    assert result.errors == ("source artifact hash mismatch: evidence.txt",)


def test_evolved_estimator_is_valid_but_not_applicable_to_current_execution(
    tmp_path: Path,
) -> None:
    changed = copy.deepcopy(load_plant_model(MODEL).data)
    method = changed["plant_response"]["applicability"][
        "estimator_method_contract"
    ]
    method["reference_time_mapping"] = "evolved_piecewise_mapping"
    method["method_definition_hash"] = estimator_contract_definition_hash(
        method
    )

    assert validate_plant_model_structure(changed).valid
    assert validate_plant_model_semantics(changed).valid
    path = tmp_path / "evolved_model.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    model = load_plant_model(path)
    applicability = assess_model_applicability(
        model,
        ModelApplicabilityContext(
            hardware_topology_id=model.data["hardware_topology"]["topology_id"],
            measurement_backend=model.data["plant_response"]["applicability"][
                "measurement_backend"
            ],
            estimator_method=estimator_method_contract(),
            dac_code=model.nominal_code,
            required_model_version=4,
        ),
    )
    assert not applicability.applicable
    assert applicability.reasons == (
        "plant_model_estimator_method_mismatch",
    )


def test_outer_and_nested_measurement_backends_must_agree() -> None:
    changed = copy.deepcopy(load_plant_model(MODEL).data)
    changed["plant_response"]["applicability"][
        "measurement_backend"
    ] = "DIFFERENT_BACKEND"

    assert validate_plant_model_structure(changed).valid
    semantic = validate_plant_model_semantics(changed)
    assert not semantic.valid
    assert any(
        "measurement_backend must equal estimator_method_contract" in error
        for error in semantic.errors
    )


def test_historical_fields_are_declared_but_prohibited_in_current_models() -> None:
    legacy = load_plant_model(LEGACY_MODEL).data
    changed = copy.deepcopy(load_plant_model(MODEL).data)
    changed["hardware_topology"]["pps_witness"] = copy.deepcopy(
        legacy["hardware_topology"]["pps_witness"]
    )

    assert validate_plant_model_structure(changed).valid
    semantic = validate_plant_model_semantics(changed)
    assert not semantic.valid
    assert any(
        "pps_witness is reserved for the retained historical model identity"
        in error
        for error in semantic.errors
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", "new_model"),
        ("model_version", 1),
    ],
)
def test_historical_reader_is_limited_to_exact_model_identity(
    field: str,
    value: object,
) -> None:
    changed = copy.deepcopy(load_plant_model(LEGACY_MODEL).data)
    changed[field] = value

    assert validate_plant_model_structure(changed).valid
    semantic = validate_plant_model_semantics(changed)
    assert not semantic.valid
    assert any(
        "reserved for the retained historical model identity" in error
        for error in semantic.errors
    )


def test_validity_evidence_applicability_and_control_eligibility_are_separate(
    tmp_path: Path,
) -> None:
    model = load_plant_model(MODEL)
    structural = validate_plant_model_structure(model.data)
    semantic = validate_plant_model_semantics(model.data)
    evidence = assess_evidence_availability(model, tmp_path)
    applicability = assess_model_applicability(
        model,
        ModelApplicabilityContext(
            hardware_topology_id=model.data["hardware_topology"]["topology_id"],
            measurement_backend=model.data["plant_response"]["applicability"][
                "measurement_backend"
            ],
            estimator_method=estimator_method_contract(),
            dac_code=model.nominal_code,
            source_run_id="unrelated_run",
            required_model_version=4,
        ),
    )
    eligibility = assess_control_eligibility(
        model,
        evidence=evidence,
        applicability=applicability,
    )

    assert structural.valid
    assert semantic.valid
    assert not evidence.available
    assert applicability.applicable
    assert applicability.unverified_conditions == (
        "gate_duration_not_observed",
        "temperature_not_observed",
    )
    assert not eligibility.eligible
    assert "plant_model_not_control_ready" in eligibility.reasons
    assert "plant_model_actuation_disabled" in eligibility.reasons
    assert "plant_model_source_evidence_unavailable" in eligibility.reasons


def test_applicability_rejects_context_and_estimator_mismatches() -> None:
    model = load_plant_model(MODEL)
    wrong_method = estimator_method_contract()
    wrong_method["method_definition_hash"] = "0" * 64
    result = assess_model_applicability(
        model,
        ModelApplicabilityContext(
            hardware_topology_id="different_topology",
            measurement_backend="different_backend",
            estimator_method=wrong_method,
            dac_code=0,
            source_run_id="run_020",
            count_sequence=77,
            gate_duration_s=1.0,
            temperature_c=100.0,
            required_model_version=3,
        ),
    )

    assert not result.applicable
    assert set(result.reasons) == {
        "plant_model_version_not_3",
        "plant_model_topology_mismatch",
        "plant_model_backend_mismatch",
        "plant_model_estimator_method_mismatch",
        "input_outside_model_applicability",
        "plant_model_excluded_count_sequence",
        "plant_model_gate_duration_mismatch",
        "input_outside_model_temperature_range",
    }
