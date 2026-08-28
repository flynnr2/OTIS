from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
    / "d9_d6_readiness_contract_v1.json"
)
SCHEMA_PATH = ROOT / "schemas/d9_d6_readiness_contract_v1.schema.json"


def _semantic_sha256(value: dict) -> str:
    unsigned = {key: item for key, item in value.items() if key != "contract_semantic_sha256"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _load() -> tuple[dict, Draft202012Validator]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return contract, Draft202012Validator(schema)


def test_d9_d6_readiness_contract_is_schema_valid_and_semantically_bound() -> None:
    contract, validator = _load()

    validator.validate(contract)
    assert contract["contract_semantic_sha256"] == _semantic_sha256(contract)


def test_d9_d6_contract_freezes_the_non_actuating_topology_and_limits() -> None:
    contract, _ = _load()

    assert contract["signal"] == {
        "identity": "conditioned_cx317_vcocxo",
        "nominal_frequency_hz": 10_000_000,
        "authoritative_observation_gpio": "D8/GPIO20",
    }
    assert contract["d9_output"]["source"] == "GPIO20/CLOCK_GPIN0/clksrc_gpin0"
    assert contract["d9_output"]["destination"] == "D9/GPIO21/CLOCK_GPOUT0"
    assert contract["d9_output"]["divider"] == {"integer": 1, "fractional": 0}
    assert contract["d9_output"]["inversion"] is False
    assert contract["d9_output"]["electrical_envelope"]["drive_strength"] == "2mA"
    assert contract["d9_output"]["electrical_envelope"]["slew_rate"] == "slow"
    assert contract["d6_monitor"]["gpio"] == "D6/GPIO18"
    assert contract["d6_monitor"]["wiring"]["series_resistance_ohms"] == 1000
    assert contract["d6_monitor"]["count_semantics"]["expected_d8_to_d6_ratio"] == "1:1"
    assert contract["d6_monitor"]["count_semantics"]["snapshot_contract"] == (
        "forwarded_monitor_snapshots_v1"
    )
    assert contract["serial"]["firmware_host_target_baud"] == 115200
    assert contract["serial"]["device_selection"] == (
        "capture_device_--auto-detect_exactly_one_/dev/cu.usbmodem*"
    )
    assert contract["serial"]["receiver_service"] == (
        "disabled_in_readiness_strata_no_receiver_command"
    )
    assert contract["authority"] == {
        "d9_has_control_authority": False,
        "d6_has_control_authority": False,
        "may_write_dac": False,
        "may_arm_fll": False,
        "may_arm_hybrid": False,
    }


def test_d9_d6_contract_rejects_identity_drift_and_forbidden_authority() -> None:
    contract, validator = _load()

    drifted = deepcopy(contract)
    drifted["d9_output"]["divider"]["fractional"] = 1
    with pytest.raises(ValidationError):
        validator.validate(drifted)

    unauthorized = deepcopy(contract)
    unauthorized["authority"]["may_arm_fll"] = True
    with pytest.raises(ValidationError):
        validator.validate(unauthorized)

    assert _semantic_sha256(drifted) != contract["contract_semantic_sha256"]


def test_d9_d6_contract_preserves_physical_evidence_and_loss_procedure_boundaries() -> None:
    contract, _ = _load()

    assert contract["physical_state"] == {
        "bench_authority": False,
        "post_power_cycle_identity": "unknown_until_observed",
        "d9_claim_state": "unmeasured_pre_physical_qualification",
    }
    assert contract["d6_monitor"]["count_semantics"]["absence_interpretation"] == (
        "diagnostic_unavailable_not_clean_D9_result"
    )
    assert contract["loss_segment_procedure"] == {
        "status": "deferred_no_conflict_free_operator_procedure_frozen",
        "physical_execution_permitted": False,
        "required_behavior_if_later_frozen": (
            "control_disarmed_last_confirmed_code_preserved_and_fresh_causal_requalification_required"
        ),
    }
    assert "no_50_ohm_load_compatibility_claim" in contract["claims_not_made"]
    assert "no_D6_result_is_a_D9_waveform_claim" in contract["claims_not_made"]
