from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from host.otis_tools.active_hybrid_policy import (
    CX323Debt,
    CX323Observation,
    CX323PhasePriorityController,
    cx323_centre_to_picocodes,
    load_cx323_policy,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
HARNESS = ROOT / "tests/cpp/cx323_phase_priority_maintenance_harness.cpp"
SOURCE = FIRMWARE / "otis_cx323_phase_priority_maintenance.cpp"
WIDE_SOURCE = FIRMWARE / "otis_cx323_wide.cpp"
MAXIMUM_CENTRE_UNITS = 332_041_393_326_771_929_124
V3_CONTRACT = (
    ROOT
    / "docs/60_EXPERIMENTS/OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY"
    / "study_contract_v3.json"
)
V3_CONTRACT_SHA256 = (
    "32a7f47330404e1cf7ea724517643deff078e74d3e1aa50127c378bced5f4d53"
)
V3_CONTRACT_FILE_SHA256 = (
    "a9915b61f295eaa743d8803ee609dd2a3f5b3136fff41d4dc6766929e6f06949"
)
SELECTED_PROFILE = (
    ROOT
    / "profiles/discipline/cx323_phase_priority_persistent_maintenance_v2.json"
)
SELECTED_PROFILE_FILE_SHA256 = (
    "24ec5210b897b3ea9dd64aa5946c69e02e277c09922f5a5208f3476d6eaba926"
)


def _compiler() -> str:
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


@pytest.fixture(scope="session")
def cx323_native_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("cx323_native") / "maintenance"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            str(SOURCE),
            str(WIDE_SOURCE),
            "-I",
            str(FIRMWARE),
            "-o",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    return output


def _run(harness: Path, commands: list[str]) -> list[dict[str, str]]:
    completed = subprocess.run(
        [str(harness)],
        input="\n".join(commands) + "\n",
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    return list(csv.DictReader(io.StringIO(completed.stdout)))


def _controller(*, code: int = 43_085, epoch: int = 1) -> CX323PhasePriorityController:
    return CX323PhasePriorityController(
        load_cx323_policy(), setup_applied_code=code, setup_dac_epoch=epoch
    )


def _observation(
    controller: CX323PhasePriorityController,
    timestamp_s: int,
    opening: int,
    closing: int,
    *,
    counts: int = -1,
    phase: int = -4,
    **changes: object,
) -> CX323Observation:
    values: dict[str, object] = {
        "timestamp_s": timestamp_s,
        "timestamp_ticks": timestamp_s * 16_000_000,
        "capture_session": 1,
        "source_first_sequence": opening,
        "source_last_sequence": closing,
        "dac_epoch": controller.dac_epoch,
        "applied_code": controller.applied_code,
        "accumulated_edge_error_counts": counts,
        "tight_state": "TIGHT_INSIDE",
        "phase_epoch": 1,
        "relative_phase_cycles": phase,
    }
    values.update(changes)
    return CX323Observation(**values)


def _decide_command(observation: CX323Observation) -> str:
    return " ".join(
        str(value)
        for value in (
            "DECIDE",
            observation.timestamp_s,
            observation.timestamp_ticks,
            observation.capture_session,
            observation.source_first_sequence,
            observation.source_last_sequence,
            observation.dac_epoch,
            observation.applied_code,
            observation.accumulated_edge_error_counts,
            int(observation.tight_state == "TIGHT_INSIDE"),
            observation.phase_epoch,
            observation.relative_phase_cycles,
            1
            if observation.frequency_estimator_id
            == "cx317_selected_600s_nonoverlap_v1"
            else 2,
            int(observation.phase_valid),
            int(observation.authority_valid),
            int(observation.settled),
            int(observation.cadence_eligible),
            int(observation.metadata_qualified),
        )
    )


def _assert_decision_parity(
    actual: dict[str, str], expected: object, controller: CX323PhasePriorityController
) -> None:
    assert actual["ok"] == "1"
    for field in (
        "reason",
        "requested_delta_codes",
        "requested_code",
        "safe_cap_codes",
        "persistence_count",
        "raw_combined_picocodes",
        "raw_fll_picocodes",
        "raw_pll_picocodes",
        "decision_timestamp_ticks",
        "counterfactual_frequency_only_delta_codes",
        "phase_materially_influenced",
        "step_limited",
        "range_clamped",
        "cadence_limited",
        "count_limited",
        "cumulative_budget_limited",
    ):
        actual_value: object = actual[field]
        expected_value = getattr(expected, field)
        if field != "reason":
            actual_value = int(actual_value)
        if isinstance(expected_value, bool):
            actual_value = bool(actual_value)
        assert actual_value == expected_value
    assert int(actual["debt_fll_picocodes"]) == controller.debt.fll_picocodes
    assert int(actual["debt_pll_picocodes"]) == controller.debt.pll_picocodes
    assert (actual["request_pending"] == "1") is controller.request_pending
    assert (actual["response_pending"] == "1") is controller.response_pending
    assert actual["fail_static_reason"] == (controller.fail_static_reason or "")


def test_native_boundary_is_bound_to_the_prospective_v3_correction() -> None:
    contract_bytes = V3_CONTRACT.read_bytes()
    assert sha256(contract_bytes).hexdigest() == V3_CONTRACT_FILE_SHA256
    contract = json.loads(contract_bytes)
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    semantic = sha256(
        json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    assert contract["contract_sha256"] == semantic == V3_CONTRACT_SHA256
    boundary = contract["corrected_fixed_point_boundary"]
    assert boundary["maximum_positive_combined_centre_units"] == MAXIMUM_CENTRE_UNITS
    assert boundary["minimum_negative_combined_centre_units"] == (
        -332_041_393_326_771_929_088
    )
    assert boundary["maximum_rounded_absolute_picocode_result"] == (
        44_341_403_516_579_504_632_341_249_183_880
    )
    assert [case["case_id"] for case in contract["mandatory_native_parity_cases"]] == [
        "maximum_positive_combined_centre",
        "maximum_negative_combined_centre",
        "beyond_complete_combined_domain",
    ]

    profile_bytes = SELECTED_PROFILE.read_bytes()
    assert sha256(profile_bytes).hexdigest() == SELECTED_PROFILE_FILE_SHA256
    profile = json.loads(profile_bytes)
    assert profile["bindings"]["successor_study_contract_v3"] == {
        "path": (
            "docs/60_EXPERIMENTS/OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
            "study_contract_v3.json"
        ),
        "file_sha256": V3_CONTRACT_FILE_SHA256,
        "semantic_sha256": V3_CONTRACT_SHA256,
    }


def test_checked_fixed_point_rounding_conversion_and_domain_sanitizer(
    cx323_native_harness: Path,
) -> None:
    rounding = [(1, 2, 1), (-1, 2, -1), (3, 2, 2), (-3, 2, -2), (1, 3, 0), (-1, 3, 0)]
    centres = [
        0,
        1,
        -1,
        18,
        -18,
        36,
        -36,
        40,
        41,
        -40,
        -41,
        MAXIMUM_CENTRE_UNITS,
        -MAXIMUM_CENTRE_UNITS,
    ]
    rows = _run(
        cx323_native_harness,
        [*(f"ROUND {n} {d}" for n, d, _ in rounding),
         *(f"CONVERT {centre}" for centre in centres),
         f"CONVERT {MAXIMUM_CENTRE_UNITS + 1}",
         f"CONVERT {-MAXIMUM_CENTRE_UNITS - 1}"],
    )
    for row, (_, _, expected) in zip(rows, rounding):
        assert row["ok"] == "1"
        assert int(row["wide_result"]) == expected
    converted = rows[len(rounding): len(rounding) + len(centres)]
    for row, centre in zip(converted, centres):
        assert row["ok"] == "1"
        assert int(row["wide_result"]) == cx323_centre_to_picocodes(centre)
    assert [row["ok"] for row in rows[-2:]] == ["0", "0"]
    assert [row["wide_result"] for row in rows[-2:]] == ["0", "0"]


def test_target_portable_wide_decimal_round_trip_and_overflow_rejection(
    cx323_native_harness: Path,
) -> None:
    maximum = 2**127 - 1
    rows = _run(
        cx323_native_harness,
        [
            f"ROUND {maximum} 1",
            f"ROUND {-maximum} 1",
            f"ROUND {maximum + 1} 1",
            f"ROUND {-maximum - 1} 1",
        ],
    )
    assert [(row["ok"], row["wide_result"]) for row in rows] == [
        ("1", str(maximum)),
        ("1", str(-maximum)),
        ("0", "0"),
        ("0", "0"),
    ]


def test_frozen_two_transaction_debt_fixture_is_bit_exact(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    observations = [
        _observation(controller, 0, 0, 600, counts=-1, phase=-4),
        _observation(controller, 600, 600, 1200, counts=-1, phase=-4),
    ]
    first = controller.decide(observations[0])
    request = controller.decide(observations[1])
    commands = [
        "INIT 43085 1",
        _decide_command(observations[0]),
        _decide_command(observations[1]),
        "APPLY 43090 2 1",
        "RESPONSE 1",
    ]
    controller.confirm_application(
        request, applied_code=43_090, dac_epoch=2, first_consumer_exact=True
    )
    first_debt = controller.debt
    controller.complete_response(fresh_exact=True)
    next_observations = [
        _observation(controller, 1800, 1800, 2400, counts=-1, phase=-5),
        _observation(controller, 2400, 2400, 3000, counts=-1, phase=-5),
    ]
    next_first = controller.decide(next_observations[0])
    next_request = controller.decide(next_observations[1])
    commands.extend(map(_decide_command, next_observations))

    rows = _run(cx323_native_harness, commands)
    _assert_decision_parity(rows[1], first, _controller())
    pending_controller = _controller()
    pending_controller.decide(observations[0])
    pending_expected = pending_controller.decide(observations[1])
    _assert_decision_parity(rows[2], pending_expected, pending_controller)
    assert rows[3]["ok"] == "1"
    assert int(rows[3]["debt_fll_picocodes"]) == first_debt.fll_picocodes
    assert int(rows[3]["debt_pll_picocodes"]) == first_debt.pll_picocodes
    assert int(rows[3]["debt_fll_picocodes"]) + int(
        rows[3]["debt_pll_picocodes"]
    ) == 341_671_780_415
    assert rows[3]["request_pending"] == "0"
    assert rows[3]["response_pending"] == "1"
    assert rows[4]["response_pending"] == "0"
    for field in (
        "reason",
        "requested_delta_codes",
        "requested_code",
        "safe_cap_codes",
        "persistence_count",
        "raw_combined_picocodes",
        "raw_fll_picocodes",
        "raw_pll_picocodes",
    ):
        actual: object = rows[5][field]
        if field != "reason":
            actual = int(actual)
        assert actual == getattr(next_first, field)
    assert rows[5]["request_pending"] == "0"
    assert rows[5]["response_pending"] == "0"
    assert int(rows[5]["debt_fll_picocodes"]) == first_debt.fll_picocodes
    assert int(rows[5]["debt_pll_picocodes"]) == first_debt.pll_picocodes
    _assert_decision_parity(rows[6], next_request, controller)
    assert int(rows[6]["raw_combined_picocodes"]) == 5_475_213_574_925
    assert int(rows[6]["requested_delta_codes"]) == 6
    assert abs(5_475_213_574_925 - 5_000_000_000_000) == 475_213_574_925
    assert abs(
        5_475_213_574_925 + 341_671_780_415 - 6_000_000_000_000
    ) == 183_114_644_660


@pytest.mark.parametrize(
    ("counts", "expected_delta"), [(1, -4), (-1, 4)]
)
def test_one_count_no_zero_cross_cap_is_symmetric_and_bit_exact(
    cx323_native_harness: Path, counts: int, expected_delta: int
) -> None:
    controller = _controller()
    first_observation = _observation(
        controller, 0, 0, 600, counts=counts, phase=0
    )
    second_observation = _observation(
        controller, 600, 600, 1200, counts=counts, phase=0
    )
    first = controller.decide(first_observation)
    second = controller.decide(second_observation)
    rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            _decide_command(first_observation),
            _decide_command(second_observation),
        ],
    )
    assert rows[1]["reason"] == first.reason
    assert rows[2]["reason"] == second.reason
    assert int(rows[2]["safe_cap_codes"]) == second.safe_cap_codes == 4
    assert int(rows[2]["requested_delta_codes"]) == expected_delta
    assert second.requested_delta_codes == expected_delta


@pytest.mark.parametrize(
    ("code", "counts"), [(43_008, 1), (43_776, -1)]
)
def test_range_endpoint_headroom_cannot_issue_an_outward_request(
    cx323_native_harness: Path, code: int, counts: int
) -> None:
    controller = _controller(code=code)
    first_observation = _observation(
        controller, 0, 0, 600, counts=counts, phase=0
    )
    second_observation = _observation(
        controller, 600, 600, 1200, counts=counts, phase=0
    )
    controller.decide(first_observation)
    second = controller.decide(second_observation)
    rows = _run(
        cx323_native_harness,
        [
            f"INIT {code} 1",
            _decide_command(first_observation),
            _decide_command(second_observation),
        ],
    )
    assert rows[2]["reason"] == second.reason == "zero_rounded_or_range_hold"
    assert int(rows[2]["safe_cap_codes"]) == second.safe_cap_codes == 0
    assert int(rows[2]["requested_delta_codes"]) == 0
    assert rows[2]["request_pending"] == "0"


def test_frontier_hold_requalification_and_tag_transitions_match_python(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    first_observation = _observation(controller, 0, 0, 600)
    second_observation = _observation(controller, 600, 600, 1200)
    first = controller.decide(first_observation)
    request = controller.decide(second_observation)
    controller.reject_or_expire_request()
    controller.debt = CX323Debt(10, 20)
    overlap_observation = _observation(controller, 1200, 599, 1199)
    gap_observation = _observation(controller, 1800, 1201, 1801)
    overlap = controller.decide(overlap_observation)
    gap = controller.decide(gap_observation)

    commands = [
        "INIT 43085 1",
        _decide_command(first_observation),
        _decide_command(second_observation),
        "REJECT",
        "SET_DEBT 10 20",
        _decide_command(overlap_observation),
        _decide_command(gap_observation),
        "HOLD",
    ]
    controller.enter_metadata_hold()
    held_observation = _observation(controller, 2400, 1801, 2401)
    held = controller.decide(held_observation)
    commands.append(_decide_command(held_observation))
    controller.requalify_metadata(3000)
    commands.append("REQUAL 3000")
    too_early_observation = _observation(controller, 3000, 2999, 3599)
    too_early = controller.decide(too_early_observation)
    commands.append(_decide_command(too_early_observation))
    post_first_observation = _observation(controller, 3600, 3000, 3600)
    post_second_observation = _observation(controller, 4200, 3600, 4200)
    post_first = controller.decide(post_first_observation)
    post_second = controller.decide(post_second_observation)
    commands.extend(
        [_decide_command(post_first_observation), _decide_command(post_second_observation)]
    )

    rows = _run(cx323_native_harness, commands)
    expected_decisions = [first, request, overlap, gap, held, too_early, post_first, post_second]
    decision_rows = [row for row in rows if row["command"] == "DECIDE"]
    # Replay once more to compare the complete state at each decision without
    # weakening transition checks to final-state-only assertions.
    replay = _controller()
    replay_expected = [
        replay.decide(first_observation),
        replay.decide(second_observation),
    ]
    replay.reject_or_expire_request()
    replay.debt = CX323Debt(10, 20)
    replay_expected.extend(
        [replay.decide(overlap_observation), replay.decide(gap_observation)]
    )
    replay.enter_metadata_hold()
    replay_expected.append(replay.decide(held_observation))
    replay.requalify_metadata(3000)
    replay_expected.append(replay.decide(too_early_observation))
    replay_expected.extend(
        [replay.decide(post_first_observation), replay.decide(post_second_observation)]
    )
    assert [item.reason for item in expected_decisions] == [
        item.reason for item in replay_expected
    ]
    for actual, expected in zip(decision_rows, replay_expected):
        assert actual["reason"] == expected.reason
        assert int(actual["requested_delta_codes"]) == expected.requested_delta_codes
        assert int(actual["persistence_count"]) == expected.persistence_count
    assert overlap.reason == "source_overlap_hold"
    assert gap.reason == "source_gap_persistence_restart"
    assert rows[5]["debt_fll_picocodes"] == "10"
    assert rows[5]["debt_pll_picocodes"] == "20"
    assert held.reason == "metadata_hold"
    assert too_early.reason == "metadata_requalification_frontier_hold"
    assert post_first.reason == "metadata_requalification_window_hold"
    assert post_second.requested_delta_codes != 0
    assert rows[9]["metadata_hold"] == "1"
    assert rows[9]["requalification_window_count"] == "0"
    assert rows[11]["metadata_hold"] == "1"
    assert rows[11]["requalification_window_count"] == "1"
    assert rows[12]["metadata_hold"] == "0"
    assert rows[12]["requalification_window_count"] == "2"


def test_pending_observation_cannot_move_application_cadence_timestamp(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    first_observation = _observation(controller, 0, 0, 600)
    request_observation = _observation(controller, 600, 600, 1200)
    pending_observation = _observation(controller, 601, 1200, 1800)
    controller.decide(first_observation)
    request = controller.decide(request_observation)
    pending = controller.decide(pending_observation)
    assert pending.reason == "request_pending_hold"
    controller.confirm_application(
        request,
        applied_code=request.requested_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )
    assert controller.last_application_s == 600

    rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            _decide_command(first_observation),
            _decide_command(request_observation),
            _decide_command(pending_observation),
            f"APPLY_PENDING {request.requested_code} 2 1",
        ],
    )
    assert rows[3]["reason"] == "request_pending_hold"
    assert rows[4]["ok"] == "1"
    assert rows[4]["last_application_s"] == "600"


def test_metadata_requalification_overlap_gap_and_identity_restarts_match_python(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    commands = ["INIT 43085 1", "HOLD", "REQUAL 100"]
    controller.enter_metadata_hold()
    controller.requalify_metadata(100)
    observations = [
        _observation(controller, 0, 100, 700),
        _observation(controller, 600, 699, 1299),
        _observation(controller, 1200, 701, 1301),
        _observation(controller, 1800, 1301, 1901, counts=1, phase=0),
    ]
    expected: list[tuple[str, int, bool]] = []
    for observation in observations:
        decision = controller.decide(observation)
        expected.append(
            (
                decision.reason,
                controller.requalification_window_count,
                controller.metadata_hold,
            )
        )
        commands.append(_decide_command(observation))

    controller.enter_metadata_hold()
    controller.requalify_metadata(2000)
    commands.extend(["HOLD", "REQUAL 2000"])
    identity_observations = [
        _observation(
            controller, 2400, 2000, 2600, capture_session=2, phase_epoch=1
        ),
        _observation(
            controller, 3000, 2600, 3200, capture_session=2, phase_epoch=2
        ),
        _observation(
            controller, 3600, 3200, 3800, capture_session=2, phase_epoch=2
        ),
    ]
    for observation in identity_observations:
        decision = controller.decide(observation)
        expected.append(
            (
                decision.reason,
                controller.requalification_window_count,
                controller.metadata_hold,
            )
        )
        commands.append(_decide_command(observation))

    rows = _run(cx323_native_harness, commands)
    decision_rows = [row for row in rows if row["command"] == "DECIDE"]
    assert len(decision_rows) == len(expected)
    for actual, (reason, count, metadata_hold) in zip(decision_rows, expected):
        assert actual["reason"] == reason
        assert int(actual["requalification_window_count"]) == count
        assert (actual["metadata_hold"] == "1") is metadata_hold

    assert expected[0] == ("metadata_requalification_window_hold", 1, True)
    assert expected[1] == ("metadata_requalification_overlap_hold", 1, True)
    assert expected[2][1:] == (1, True)  # Gap restarts the causal pair.
    assert expected[3][1:] == (2, False)  # Opposite sign cannot actuate early.
    assert expected[4][1:] == (1, True)  # New capture session starts a pair.
    assert expected[5][1:] == (1, True)  # Phase epoch change restarts it.
    assert expected[6][1:] == (2, False)


def test_legacy_boundary_limits_chatter_and_fail_static_are_parity_checked(
    cx323_native_harness: Path,
) -> None:
    scenarios: list[tuple[CX323PhasePriorityController, CX323Observation]] = []
    nonmaterial = _controller()
    scenarios.append((nonmaterial, _observation(nonmaterial, 0, 0, 600, counts=-1, phase=-5)))
    material = _controller()
    scenarios.append((material, _observation(material, 0, 0, 600, counts=-1, phase=-6)))
    outside = _controller()
    scenarios.append((outside, _observation(outside, 0, 0, 600, counts=2, phase=0, tight_state="OUTSIDE")))
    degraded = _controller()
    degraded.debt = CX323Debt(101, 202)
    scenarios.append((degraded, _observation(degraded, 0, 0, 600, counts=-1, phase=-4, phase_valid=False)))

    commands: list[str] = []
    expected: list[object] = []
    for index, (controller, observation) in enumerate(scenarios):
        commands.append("INIT 43085 1")
        if index == 3:
            commands.append("SET_DEBT 101 202")
        expected.append(controller.decide(observation))
        commands.append(_decide_command(observation))

    limited = _controller()
    limited.application_count = limited.policy.maximum_applications
    commands.extend(["INIT 43085 1", "SET_BUDGET 144 0"])
    first_limit = _observation(limited, 0, 0, 600)
    second_limit = _observation(limited, 600, 600, 1200)
    expected.extend([limited.decide(first_limit), limited.decide(second_limit)])
    commands.extend([_decide_command(first_limit), _decide_command(second_limit)])

    chatter = _controller()
    chatter.direction_history = [1, -1, 1]
    commands.extend(["INIT 43085 1", "SET_DIRECTIONS 3 1 -1 1 43085"])
    chatter_observation = _observation(chatter, 0, 0, 600, counts=4, phase=0, tight_state="OUTSIDE")
    expected.append(chatter.decide(chatter_observation))
    commands.append(_decide_command(chatter_observation))

    inefficient = _controller()
    inefficient.application_count = 1
    inefficient.cumulative_movement_codes = 21
    inefficient.direction_history = [1]
    inefficient.chatter_origin_code = 43_064
    commands.extend(
        [
            "INIT 43085 1",
            "SET_BUDGET 1 21",
            "SET_DIRECTIONS 1 1 0 0 43064",
        ]
    )
    inefficient_observation = _observation(
        inefficient, 0, 0, 600, counts=10, phase=0, tight_state="OUTSIDE"
    )
    expected.append(inefficient.decide(inefficient_observation))
    commands.append(_decide_command(inefficient_observation))

    rows = _run(cx323_native_harness, commands)
    decision_rows = [row for row in rows if row["command"] == "DECIDE"]
    for actual, expected_decision in zip(decision_rows, expected):
        assert actual["reason"] == expected_decision.reason
        assert int(actual["requested_delta_codes"]) == expected_decision.requested_delta_codes
        assert int(actual["safe_cap_codes"]) == expected_decision.safe_cap_codes
        assert int(actual["raw_combined_picocodes"]) == expected_decision.raw_combined_picocodes
        assert int(actual["raw_fll_picocodes"]) == expected_decision.raw_fll_picocodes
        assert int(actual["raw_pll_picocodes"]) == expected_decision.raw_pll_picocodes
    assert expected[0].reason == "persistence_first_interval_hold"
    assert expected[1].reason == "phase_material_legacy_request_ready"
    assert expected[2].reason == "outside_tight_legacy_request_ready"
    assert expected[3].reason == "phase_degraded_frequency_only_request_ready"
    assert decision_rows[-4]["reason"] == "persistence_first_interval_hold"
    assert decision_rows[-3]["reason"] == "global_application_budget_hold"
    assert decision_rows[-2]["reason"] == "prospective_repeated_alternation"
    assert decision_rows[-2]["fail_static_reason"] == "prospective_repeated_alternation"
    assert decision_rows[-1]["reason"] == "prospective_low_efficiency_path"
    assert decision_rows[-1]["fail_static_reason"] == "prospective_low_efficiency_path"


@pytest.mark.parametrize(
    ("counts", "phase"), [(-(2**63), -36), (2**63 - 1, 36)]
)
def test_signed_64_bit_maximum_count_domain_matches_python_without_overflow(
    cx323_native_harness: Path, counts: int, phase: int
) -> None:
    controller = _controller()
    first_observation = _observation(
        controller, 0, 0, 600, counts=counts, phase=phase
    )
    second_observation = _observation(
        controller, 600, 600, 1200, counts=counts, phase=phase
    )
    first = controller.decide(first_observation)
    second = controller.decide(second_observation)
    rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            _decide_command(first_observation),
            _decide_command(second_observation),
        ],
    )
    assert rows[1]["reason"] == first.reason
    assert rows[2]["reason"] == second.reason
    assert int(rows[2]["requested_delta_codes"]) == second.requested_delta_codes
    assert int(rows[2]["safe_cap_codes"]) == second.safe_cap_codes == 21
    assert int(rows[2]["raw_combined_picocodes"]) == second.raw_combined_picocodes
    assert int(rows[2]["raw_fll_picocodes"]) == second.raw_fll_picocodes
    assert int(rows[2]["raw_pll_picocodes"]) == second.raw_pll_picocodes
    if counts == -(2**63):
        assert int(rows[2]["raw_combined_picocodes"]) == (
            44_341_403_516_579_504_632_341_249_183_880
        )


@pytest.mark.parametrize(
    ("counts", "applied_code", "expected_residual"),
    [(-10, 43_106, 500_000_000_000), (10, 43_064, -500_000_000_000)],
)
def test_positive_and_negative_residual_clamps_and_tag_sum_are_bit_exact(
    cx323_native_harness: Path,
    counts: int,
    applied_code: int,
    expected_residual: int,
) -> None:
    controller = _controller()
    first_observation = _observation(controller, 0, 0, 600, counts=counts, phase=0)
    second_observation = _observation(controller, 600, 600, 1200, counts=counts, phase=0)
    controller.decide(first_observation)
    request = controller.decide(second_observation)
    controller.confirm_application(
        request,
        applied_code=applied_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )
    rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            _decide_command(first_observation),
            _decide_command(second_observation),
            f"APPLY {applied_code} 2 1",
        ],
    )
    assert rows[2]["requested_delta_codes"] == str(applied_code - 43_085)
    assert int(rows[3]["debt_fll_picocodes"]) == controller.debt.fll_picocodes
    assert int(rows[3]["debt_pll_picocodes"]) == controller.debt.pll_picocodes
    assert int(rows[3]["debt_fll_picocodes"]) + int(
        rows[3]["debt_pll_picocodes"]
    ) == expected_residual
    assert abs(expected_residual) == 500_000_000_000


def test_identity_authority_settling_phase_and_zero_debt_transitions(
    cx323_native_harness: Path,
) -> None:
    base = _controller()
    base.debt = CX323Debt(101, 202)
    first_observation = _observation(base, 0, 0, 600)
    first = base.decide(first_observation)
    phase_observation = _observation(base, 600, 600, 1200, phase_epoch=2)
    phase = base.decide(phase_observation)
    assert base.debt == CX323Debt(101, 0)

    commands = [
        "INIT 43085 1",
        "SET_DEBT 101 202",
        _decide_command(first_observation),
        _decide_command(phase_observation),
    ]

    session = _controller()
    session.debt = CX323Debt(303, 404)
    session_first_observation = _observation(session, 0, 0, 600)
    session_first = session.decide(session_first_observation)
    session_change_observation = _observation(
        session, 600, 600, 1200, capture_session=2
    )
    session_change = session.decide(session_change_observation)
    commands.extend(
        [
            "INIT 43085 1",
            "SET_DEBT 303 404",
            _decide_command(session_first_observation),
            _decide_command(session_change_observation),
        ]
    )

    held = _controller()
    held.debt = CX323Debt(505, 606)
    settling_observation = _observation(held, 0, 0, 600, settled=False)
    authority_observation = _observation(
        held, 600, 600, 1200, authority_valid=False
    )
    settling = held.decide(settling_observation)
    authority = held.decide(authority_observation)
    commands.extend(
        [
            "INIT 43085 1",
            "SET_DEBT 505 606",
            _decide_command(settling_observation),
            _decide_command(authority_observation),
        ]
    )

    zero = _controller()
    zero.debt = CX323Debt(707, 808)
    zero_observation = _observation(zero, 0, 0, 600, counts=0, phase=0)
    zero_decision = zero.decide(zero_observation)
    commands.extend(
        [
            "INIT 43085 1",
            "SET_DEBT 707 808",
            _decide_command(zero_observation),
        ]
    )

    rows = _run(cx323_native_harness, commands)
    decision_rows = [row for row in rows if row["command"] == "DECIDE"]
    expected = [
        first,
        phase,
        session_first,
        session_change,
        settling,
        authority,
        zero_decision,
    ]
    assert [row["reason"] for row in decision_rows] == [
        decision.reason for decision in expected
    ]
    phase_row = decision_rows[1]
    assert phase_row["debt_fll_picocodes"] == "101"
    assert phase_row["debt_pll_picocodes"] == "0"
    session_row = decision_rows[3]
    assert session_row["debt_fll_picocodes"] == "0"
    assert session_row["debt_pll_picocodes"] == "0"
    for row in decision_rows[4:6]:
        assert row["debt_fll_picocodes"] == "505"
        assert row["debt_pll_picocodes"] == "606"
    assert decision_rows[6]["reason"] == "zero_containing_interval"
    assert decision_rows[6]["debt_fll_picocodes"] == "0"
    assert decision_rows[6]["debt_pll_picocodes"] == "0"


def test_application_identity_and_first_consumer_mismatch_latches_fail_static(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    first = _observation(controller, 0, 0, 600)
    second = _observation(controller, 600, 600, 1200)
    rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            _decide_command(first),
            _decide_command(second),
            "APPLY_BAD_DECISION 43090 2 1",
            _decide_command(_observation(controller, 1200, 1200, 1800)),
        ],
    )
    assert rows[3]["ok"] == "0"
    assert rows[3]["fail_static_reason"] == "invalid_or_unexpected_application"
    assert rows[4]["reason"] == "invalid_or_unexpected_application"
    assert rows[4]["requested_delta_codes"] == "0"

    projection_rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            _decide_command(first),
            _decide_command(second),
            "APPLY_BAD_PROJECTION 43090 2 1",
        ],
    )
    assert projection_rows[3]["ok"] == "0"
    assert (
        projection_rows[3]["fail_static_reason"]
        == "invalid_or_unexpected_application"
    )


def test_exact_tick_cadence_does_not_round_through_display_seconds(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    controller.last_application_s = 600
    controller.last_application_ticks = 600 * 16_000_000 + 4_000_000

    early = _observation(
        controller,
        2400,
        0,
        600,
        counts=2,
        phase=0,
        tight_state="OUTSIDE",
        timestamp_ticks=2400 * 16_000_000,
    )
    boundary = _observation(
        controller,
        2400,
        600,
        1200,
        counts=2,
        phase=0,
        tight_state="OUTSIDE",
        timestamp_ticks=2400 * 16_000_000 + 4_000_000,
    )
    early_decision = controller.decide(early)
    boundary_decision = controller.decide(boundary)
    assert early_decision.reason == "cadence_hold"
    assert early_decision.cadence_limited is True
    assert boundary_decision.reason == "outside_tight_legacy_request_ready"
    assert boundary_decision.cadence_limited is False

    rows = _run(
        cx323_native_harness,
        [
            "INIT 43085 1",
            "SET_LAST_APPLICATION_TICKS 1 600 9604000000",
            _decide_command(early),
            _decide_command(boundary),
        ],
    )
    assert rows[2]["reason"] == early_decision.reason
    assert rows[2]["cadence_limited"] == "1"
    assert rows[2]["decision_timestamp_ticks"] == str(early.timestamp_ticks)
    assert rows[3]["reason"] == boundary_decision.reason
    assert rows[3]["cadence_limited"] == "0"
    assert rows[3]["last_application_ticks"] == "9604000000"


def test_explicit_tick_display_domain_mismatch_fails_static_identically(
    cx323_native_harness: Path,
) -> None:
    controller = _controller()
    mismatch = _observation(
        controller, 1, 0, 600, timestamp_ticks=16_000_000 - 1
    )
    expected = controller.decide(mismatch)
    rows = _run(
        cx323_native_harness,
        ["INIT 43085 1", _decide_command(mismatch)],
    )
    assert expected.reason == "observation_timestamp_domain_mismatch"
    assert rows[1]["reason"] == expected.reason
    assert rows[1]["fail_static_reason"] == expected.reason
    assert rows[1]["decision_timestamp_ticks"] == str(mismatch.timestamp_ticks)
