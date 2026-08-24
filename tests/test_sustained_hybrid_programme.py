from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.active_hybrid_policy import load_policy
from host.otis_tools.active_hybrid_analyze import (
    _scenario_terminal_classifications,
)
from host.otis_tools.active_hybrid_evidence_guard import (
    replay_active_hybrid_history,
)
from host.otis_tools.active_hybrid_live_rehearsal import (
    _sustained_multi_transaction_fixture,
)
from host.otis_tools.active_hybrid_live_analyze import (
    _response_dependent_consumer_propagation,
)
from host.otis_tools.active_hybrid_programme_contract import (
    SUSTAINED_HYBRID_PROGRAMME,
)
from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_CONTRACT_KEYS,
    SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
)
from host.otis_tools.contracts import ACTIVE_HYBRID_DECISION_V1_FIELDS
from host.otis_tools.sustained_hybrid_synthesis import synthesize


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
POLICY = ROOT / "profiles/discipline/otis_sustained_hybrid_regulation_v1.json"


def test_sustained_policy_freezes_separate_natural_and_physical_budgets() -> None:
    policy = load_policy(POLICY)
    assert policy.policy_id == SUSTAINED_HYBRID_PROGRAMME.programme_id
    assert policy.maximum_applications == 12
    assert policy.maximum_physical_applications == 13
    assert policy.maximum_cumulative_movement_codes == 84
    assert policy.reversal_challenge_enabled
    assert policy.natural_reversal_window_s == 43_200
    assert policy.challenge_latest_s == 50_400
    assert policy.challenge_step_codes == 21


def test_sustained_snapshot_contract_requires_every_decision_identity() -> None:
    required = ACTIVE_STATUS_CONTRACT_KEYS[
        SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT
    ]
    assert {
        "automatic_application_count",
        "natural_reversal_observed",
        "deliberate_challenge_applied",
        "deliberate_challenge_recovery_applied",
        "deliberate_challenge_code",
        "deliberate_challenge_dac_epoch",
        "deliberate_challenge_application_ticks",
    } <= set(required)


def test_full_multi_transaction_sequence_reaches_first_recovery_consumer() -> None:
    policy = load_policy(POLICY)
    bundle = {
        "programme_id": SUSTAINED_HYBRID_PROGRAMME.programme_id,
        "firmware": {"build_identity": "test-build-identity"},
        "policy": {
            "path": str(POLICY),
            "policy_sha256": policy.policy_sha256,
        },
    }
    ahy, transactions, summary = _sustained_multi_transaction_fixture(bundle)
    assert len(transactions) == 17  # setup plus four complete ACT transactions
    assert [item["request_sequence"] for item in summary["applications"]] == [
        1,
        2,
        3,
        4,
    ]
    assert [item["reason"] for item in summary["applications"]] == [
        "phase_material_request_ready",
        "phase_material_request_ready",
        "deliberate_reversal_challenge_request_ready",
        "deliberate_reversal_challenge_recovery_request_ready",
    ]
    assert summary["final_snapshot"]["correction_count"] == 4
    assert summary["final_snapshot"]["automatic_application_count"] == 3
    assert summary["final_snapshot"]["natural_reversal_observed"] is True
    assert summary["final_snapshot"][
        "deliberate_challenge_recovery_applied"
    ] is True
    assert int(ahy[-1]["decision_sequence"]) == summary[
        "first_post_recovery_consumer_decision_sequence"
    ]
    propagation = _response_dependent_consumer_propagation(transactions, ahy)
    assert propagation["exact"] is True
    assert len(propagation["comparisons"]) == 4
    assert all(item["exact"] for item in propagation["comparisons"])
    replay = replay_active_hybrid_history(
        ahy,
        transactions,
        policy_path=POLICY,
        expected_run_identity=SUSTAINED_HYBRID_PROGRAMME.runtime_run_identity,
        expected_build_identity="test-build-identity",
        expected_profile_identity=SUSTAINED_HYBRID_PROGRAMME.profile_id,
        expected_active_policy_sha256=policy.policy_sha256,
    )
    assert replay["exact"] is True
    assert all(
        comparison["response_evidence_exact"]
        for comparison in replay["comparisons"]
        if comparison["response_horizon"]
    )


def test_synthetic_sensitivity_is_characterization_not_an_entry_failure(
    tmp_path: Path,
) -> None:
    output = tmp_path / "synthesis.json"
    report = synthesize(
        predecessor_run=(
            ROOT
            / "runs/cx322_bounded_hybrid_fact_gathering"
            / "stage5_live_attempt7_20260822T1921Z"
        ),
        policy_path=POLICY,
        output_path=output,
    )
    assert report["status"] == "passed"
    assert any(
        abs(case["final_21600s_OLS_phase_slope_cycles_per_s"]) > 1.0 / 3600.0
        for case in report["sensitivity_matrix"]["cases"]
        if case["final_21600s_OLS_phase_slope_cycles_per_s"] is not None
    )


def test_accelerated_sustained_scenarios_do_not_claim_physical_success() -> None:
    classifications = _scenario_terminal_classifications(
        SUSTAINED_HYBRID_PROGRAMME
    )
    assert classifications["modeled_phase_transaction"] == (
        "right_censored_incomplete"
    )
    assert set(classifications.values()) <= (
        SUSTAINED_HYBRID_PROGRAMME.terminal_decisions
    )


def test_sustained_proposal_does_not_claim_duration_is_unchanged() -> None:
    source = (ROOT / "host/otis_tools/active_hybrid_proposal.py").read_text(
        encoding="utf-8"
    )
    assert "natural_controller_mathematics_unchanged" in source
    assert (
        "scientific_limits_and_duration_changed_by_current_"
        "prospectively_frozen_programme"
    ) in source


def test_firmware_executes_challenge_and_first_recovery_consumer(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "sustained_hybrid"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS=12u",
            "-DOTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE=1",
            str(ROOT / "tests/cpp/sustained_hybrid_policy_engine_harness.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True)


def test_firmware_serializes_each_retained_response_through_first_consumer(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "dependent_response_identity"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/dependent_response_identity_harness.cpp"),
            str(FIRMWARE / "otis_active_hybrid_decision_format.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    completed = subprocess.run(
        [str(executable)], check=True, text=True, capture_output=True
    )
    rows = list(
        csv.DictReader(
            completed.stdout.splitlines(),
            fieldnames=ACTIVE_HYBRID_DECISION_V1_FIELDS,
        )
    )
    assert len(rows) == 4
    assert [row["request_sequence"] for row in rows] == ["1", "2", "3", "4"]
    assert [row["application_sequence"] for row in rows] == [
        "11",
        "12",
        "13",
        "14",
    ]
    assert [row["response_class"] for row in rows] == [
        "healthy_indeterminate_near_resolution",
        "healthy_indeterminate_near_resolution",
        "inside_deadband",
        "healthy_indeterminate_near_resolution",
    ]
    assert [row["actual_applied_code"] for row in rows] == [
        "43063",
        "43062",
        "43061",
        "43060",
    ]
    assert [row["actual_dac_epoch"] for row in rows] == ["2", "3", "4", "5"]


def test_firmware_natural_direction_history_remains_sliding() -> None:
    source = (
        FIRMWARE / "otis_active_hybrid_policy_engine.cpp"
    ).read_text(encoding="utf-8")
    assert "engine->direction_history[0] = engine->direction_history[1]" in source
    assert "engine->direction_history[3] = direction" in source


def test_campaign_selector_and_authority_limits_are_source_guarded() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    assert "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION must be 0 or 1" in config
    assert "OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 13u" in config
    assert "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS != 12u" in config
    assert "OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE != 1" in config
    assert (
        "Sustained hybrid regulation requires its exact descriptive "
        "CX322-derived profile"
    ) in config
