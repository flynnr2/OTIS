from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRAMME = (
    ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
)
CONTRACT = PROGRAMME / "cx322_d9_d6_integration_engineering_contract_v1.json"
MATRIX = ROOT / "firmware/arduino/firmware_matrix.json"
CX322_POLICY = ROOT / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json"
D9_D6_CONTRACT = PROGRAMME / "d9_d6_readiness_contract_v1.json"
PROMPT02_DECISION = PROGRAMME / "prompt02_controller_decision_v1.json"


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def test_contract_semantic_identity_and_parents_are_exact() -> None:
    contract = _read(CONTRACT)
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_semantic_sha256"
    }
    assert contract["contract_semantic_sha256"] == _canonical_sha256(unsigned)

    parents = contract["semantic_parents"]
    assert parents["cx322_policy_sha256"] == sha256(
        CX322_POLICY.read_bytes()
    ).hexdigest()
    assert parents["d9_d6_readiness_contract_semantic_sha256"] == _read(
        D9_D6_CONTRACT
    )["contract_semantic_sha256"]
    assert parents["prompt02_controller_decision_semantic_sha256"] == _read(
        PROMPT02_DECISION
    )["decision_semantic_sha256"]


def test_integrated_profile_is_exact_cx322_plus_d9_d6() -> None:
    contract = _read(CONTRACT)
    matrix = _read(MATRIX)
    profiles = {item["id"]: item for item in matrix["profiles"]}
    integrated = profiles[contract["firmware_profile"]["profile_id"]]["defines"]
    base = profiles[contract["firmware_profile"]["base_profile_id"]]["defines"]
    assert integrated == {
        **base,
        **contract["firmware_profile"]["required_selector_delta"],
    }
    assert integrated["OTIS_GNSS_UART_BAUD"] == "115200u"


def test_claim_and_authority_boundary_remains_explicit() -> None:
    contract = _read(CONTRACT)
    authority = contract["authority"]
    assert authority["bundle_effective"] is False
    assert authority["operator_bench_authority_received"] is True
    assert authority["cx322_request_law_changed"] is False
    assert authority["d9_measurement_authority"] is False
    assert authority["d9_control_authority"] is False
    assert authority["d6_measurement_authority"] is False
    assert authority["d6_control_authority"] is False
    assert authority["waveform_qualified"] is False
    assert contract["device_and_transport"]["stored_device_path_permitted"] is False
    assert contract["device_and_transport"]["stored_board_serial_permitted"] is False
    assert contract["initial_bench_envelope"]["maximum_automatic_applications"] == 1
    unavailable = " ".join(contract["claim_boundary"]["engineering_tests_cannot_establish"])
    assert "waveform" in unavailable
    assert "jitter" in unavailable
