from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools.adaptive_steering_contract import load_analysis_contract


STUDY_ROOT = (
    Path(__file__).parents[1]
    / "docs/60_EXPERIMENTS/OTIS_CROSS_CAMPAIGN_ADAPTIVE_STEERING_OFFLINE_STUDY"
)
CONTRACT_V2 = STUDY_ROOT / "analysis_contract_v2.json"


def test_v2_materializes_preserved_v1_with_exact_source_additions() -> None:
    contract = load_analysis_contract(CONTRACT_V2)

    assert contract["schema_version"] == 2
    assert contract["contract_sha256"] == (
        "b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f"
    )
    assert contract["authority"]["offline_analysis"] is True
    assert contract["normalization_v2"]["d10_policy"].startswith("never_joined")
    assert contract["normalization_v2"]["control_eligibility"][
        "historical_decision_state"
    ] == "unavailable_evidence_cadence_insufficient"
    sources = {item["source_id"]: item for item in contract["sources"]}
    assert "csv/phase_estimator_outputs_v1.csv" not in sources[
        "cx317_fll_baseline"
    ]["consumed_files"]
    assert sources["cx322_coherent"]["consumed_files"][
        "csv/phase_estimator_outputs_v1.csv"
    ] == "6f4390fa6792bb58965c53d39527dee1c92cad314f60c523f85350d57ed8c491"
    assert contract["environment_analysis"]["secondary"]["role"] == (
        "pressure_reference"
    )


def test_v2_rejects_overlay_digest_mismatch(tmp_path: Path) -> None:
    value = json.loads(CONTRACT_V2.read_text(encoding="utf-8"))
    value["normalization_v2"]["control_eligibility"][
        "gnss_metadata_freshness_limit_s"
    ] = 4
    changed = tmp_path / "analysis_contract_v2.json"
    changed.write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "analysis_contract_v1.json").write_bytes(
        (STUDY_ROOT / "analysis_contract_v1.json").read_bytes()
    )

    with pytest.raises(ValueError, match="contract semantic identity differs"):
        load_analysis_contract(changed)
