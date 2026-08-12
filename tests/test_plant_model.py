from __future__ import annotations

import copy
import json
from pathlib import Path

from host.otis_tools.plant_model import (
    ModelApplicabilityContext,
    assess_control_eligibility,
    assess_evidence_availability,
    assess_model_applicability,
    estimator_contract_definition_hash,
    load_plant_model,
    validate_plant_model_semantics,
    validate_plant_model_structure,
)


MODEL = Path("profiles/plant_models/cx317_pps_gated_v2.json")


def _data() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


def test_current_plant_model_preserves_deployed_identity_and_envelope() -> None:
    model = load_plant_model(MODEL)
    assert (model.model_id, model.model_version) == ("cx317_pps_gated_bench", 2)
    assert model.nominal_code == 0xA950
    assert model.automatic_control_range == (0xA800, 0xAB00)
    assert model.applicability_range == (0xA800, 0xAB00)
    assert not model.control_ready
    assert not model.actuation_enabled


def test_current_model_is_structurally_and_semantically_valid() -> None:
    data = _data()
    assert validate_plant_model_structure(data).valid
    assert validate_plant_model_semantics(data).valid
    assert list(Path("profiles/plant_models").glob("*.json")) == [MODEL]


def test_estimator_contract_hash_is_canonical_and_exact() -> None:
    contract = _data()["plant_response"]["applicability"][
        "estimator_method_contract"
    ]
    assert contract["method_definition_hash"] == estimator_contract_definition_hash(
        contract
    )


def test_changed_control_or_range_claims_fail_closed() -> None:
    data = _data()
    enabled = copy.deepcopy(data)
    enabled["status"]["control_ready"] = True
    assert not validate_plant_model_semantics(enabled).valid

    outside = copy.deepcopy(data)
    outside["dac"]["automatic_control_range_codes"]["min"] = 0xA700
    assert not validate_plant_model_semantics(outside).valid


def test_current_applicability_requires_exact_clock_domain_contract() -> None:
    model = load_plant_model(MODEL)
    data = model.data
    applicability = data["plant_response"]["applicability"]
    context = ModelApplicabilityContext(
        hardware_topology_id=data["hardware_topology"]["topology_id"],
        measurement_backend=applicability["measurement_backend"],
        estimator_method=applicability["estimator_method_contract"],
        dac_code=0xA950,
        gate_duration_s=600,
        temperature_c=29.0,
        required_model_version=2,
    )
    assessment = assess_model_applicability(model, context)
    assert assessment.applicable
    assert not assessment.unverified_conditions

    mismatch = assess_model_applicability(
        model,
        ModelApplicabilityContext(
            **{**context.__dict__, "measurement_backend": "cpu_timestamped"}
        ),
    )
    assert not mismatch.applicable
    assert "plant_model_backend_mismatch" in mismatch.reasons


def test_source_evidence_availability_is_explicit_and_never_grants_control() -> None:
    model = load_plant_model(MODEL)
    evidence = assess_evidence_availability(model)
    applicability = assess_model_applicability(
        model,
        ModelApplicabilityContext(
            hardware_topology_id=model.data["hardware_topology"]["topology_id"],
            measurement_backend=model.data["plant_response"]["applicability"][
                "measurement_backend"
            ],
            estimator_method=model.data["plant_response"]["applicability"][
                "estimator_method_contract"
            ],
            dac_code=0xA950,
            gate_duration_s=600,
            temperature_c=29.0,
        ),
    )
    eligibility = assess_control_eligibility(
        model, evidence=evidence, applicability=applicability
    )
    assert not eligibility.eligible
    assert "plant_model_not_control_ready" in eligibility.reasons
    assert "plant_model_actuation_disabled" in eligibility.reasons
