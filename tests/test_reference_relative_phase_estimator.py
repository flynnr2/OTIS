from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from hashlib import sha256

import pytest
from jsonschema import Draft202012Validator

from host.otis_tools.reference_relative_phase_estimator import (
    CandidateSuite,
    RelativePhaseAccumulator,
    Snapshot,
    corrective_frequency_direction,
    deterministic_digest,
    load_profile,
)
from host.otis_tools.relative_phase_candidate_replay import (
    DEFAULT_CORPUS,
    _declared_runs,
    replay_run,
)


TIMER_HZ = 100
NOMINAL_EDGES = 10
CONFIG_SHA256 = "a" * 64
MODULUS = 1 << 32


def _snapshot(
    sequence: int,
    counter: int,
    *,
    session: int = 1,
    ticks: int | None = None,
    status: int = 0,
) -> Snapshot:
    return Snapshot(
        session=session,
        snapshot_sequence=sequence,
        cumulative_down_counter=counter,
        reference_sequence=sequence,
        reference_timestamp_ticks=(
            sequence * TIMER_HZ if ticks is None else ticks
        ),
        status=status,
    )


def _engine(*, nominal_edges: int = NOMINAL_EDGES) -> RelativePhaseAccumulator:
    return RelativePhaseAccumulator(
        nominal_edges=nominal_edges,
        timer_ticks_per_second=TIMER_HZ,
        period_ns_per_cycle=100,
        configuration_sha256=CONFIG_SHA256,
    )


def _run_edges(
    edges: list[int], *, dac_epochs: list[int] | None = None
) -> list:
    engine = _engine()
    counter = 1000
    records = [
        engine.process(_snapshot(1, counter), counted_edges=None, dac_epoch=0)
    ]
    for index, interval_edges in enumerate(edges, start=2):
        counter = (counter - interval_edges) % MODULUS
        records.append(
            engine.process(
                _snapshot(index, counter),
                counted_edges=interval_edges,
                dac_epoch=(
                    dac_epochs[index - 2] if dac_epochs is not None else 0
                ),
            )
        )
    return records


def test_candidate_profile_is_frozen_source_bound_and_non_actionable() -> None:
    profile, digest = load_profile()

    assert len(digest) == 64
    assert profile["raw_boundary"]["candidate_id"].endswith("RAW_ACCUMULATOR_V1")
    assert profile["rolling_regression"]["window_intervals"] == [600, 1800, 3600]
    assert [
        (item["alpha"], item["beta"])
        for item in profile["alpha_beta"]["parameter_grid"]
    ] == [(0.2, 0.02), (0.05, 0.001), (0.01, 0.00005)]
    assert all(value is False for value in profile["authority"].values())
    assert "serial" not in Path(
        "host/otis_tools/reference_relative_phase_estimator.py"
    ).read_text(encoding="utf-8").split("dependency.", 1)[1].lower()


def test_nominal_positive_negative_and_corrective_sign() -> None:
    nominal = _run_edges([10, 10, 10])
    positive = _run_edges([11, 11, 11])
    negative = _run_edges([9, 9, 9])

    assert [record.relative_phase_cycles for record in nominal] == [0, 0, 0, 0]
    assert positive[-1].relative_phase_cycles == 3
    assert positive[-1].relative_phase_time_ns == 300
    assert negative[-1].relative_phase_cycles == -3
    assert corrective_frequency_direction(positive[-1].relative_phase_cycles) == -1
    assert corrective_frequency_direction(negative[-1].relative_phase_cycles) == 1
    assert corrective_frequency_direction(0) == 0


def test_counter_wrap_is_exact() -> None:
    engine = _engine(nominal_edges=4)
    engine.process(_snapshot(1, 2), counted_edges=None)
    record = engine.process(_snapshot(2, 0xFFFFFFFE), counted_edges=4)

    assert record.interval_edges == 4
    assert record.edge_error_cycles == 0
    assert record.relative_phase_cycles == 0


def test_rp2040_reference_timestamp_wrap_is_not_a_phase_discontinuity() -> None:
    engine = RelativePhaseAccumulator(
        nominal_edges=NOMINAL_EDGES,
        timer_ticks_per_second=TIMER_HZ,
        period_ns_per_cycle=100,
        configuration_sha256=CONFIG_SHA256,
        reference_timestamp_modulus_ticks=1000,
    )
    engine.process(_snapshot(1, 1000, ticks=950), counted_edges=None)
    record = engine.process(_snapshot(2, 990, ticks=50), counted_edges=10)

    assert record.accepted is True
    assert record.phase_epoch == 1
    assert record.discontinuity_reason is None


def test_one_and_multi_cycle_steps_ramp_drift_and_alternating_quantization() -> None:
    steps = _run_edges([10, 11, 10, 13])
    drift = _run_edges([10, 10, 11, 11, 12, 12])
    alternating = _run_edges([11, 9, 11, 9, 11, 9])

    assert [record.relative_phase_cycles for record in steps] == [0, 0, 1, 1, 4]
    assert steps[-1].phase_epoch == steps[0].phase_epoch
    assert drift[-1].relative_phase_cycles == 6
    assert alternating[-1].relative_phase_cycles == 0


def test_gap_duplicate_short_long_and_association_mismatch_fail_closed() -> None:
    gap = _engine()
    first = gap.process(_snapshot(1, 1000), counted_edges=None)
    gap_record = gap.process(_snapshot(3, 980), counted_edges=20)
    assert gap_record.phase_epoch == first.phase_epoch + 1
    assert gap_record.qualification_state == "epoch_open"
    assert gap_record.discontinuity_reason == "snapshot_or_reference_sequence_gap"

    duplicate = _engine()
    duplicate.process(_snapshot(1, 1000), counted_edges=None)
    duplicate_record = duplicate.process(_snapshot(1, 990), counted_edges=10)
    assert duplicate_record.qualification_state == "invalid"
    assert duplicate_record.discontinuity_reason == "snapshot_reordered_or_duplicate"

    short = _engine()
    short.process(_snapshot(1, 1000, ticks=100), counted_edges=None)
    short_record = short.process(_snapshot(2, 990, ticks=150), counted_edges=10)
    assert short_record.discontinuity_reason == "reference_pps_short_interval"

    long = _engine()
    long.process(_snapshot(1, 1000, ticks=100), counted_edges=None)
    long_record = long.process(_snapshot(2, 990, ticks=250), counted_edges=10)
    assert long_record.discontinuity_reason == "reference_pps_long_interval"

    mismatch = _engine()
    mismatch.process(_snapshot(1, 1000), counted_edges=None)
    mismatch_record = mismatch.process(_snapshot(2, 990), counted_edges=11)
    assert mismatch_record.discontinuity_reason == "snapshot_count_association_mismatch"
    assert mismatch_record.relative_phase_cycles == 0


def test_session_reset_gnss_loss_stale_recovery_and_long_loss_open_new_epochs() -> None:
    session = _engine()
    opening = session.process(_snapshot(1, 1000), counted_edges=None)
    changed = session.process(
        _snapshot(2, 990, session=2), counted_edges=10
    )
    assert changed.phase_epoch == opening.phase_epoch + 1
    assert changed.discontinuity_reason == "capture_session_change"

    reset = session.process(
        _snapshot(3, 980, session=2), counted_edges=10, reset=True
    )
    assert reset.discontinuity_reason == "reset"
    assert reset.qualification_state == "epoch_open"

    gnss = _engine()
    gnss.process(_snapshot(1, 1000), counted_edges=None)
    invalid = gnss.process(
        _snapshot(2, 990), counted_edges=10, reference_qualified=False
    )
    recovered = gnss.process(_snapshot(3, 980), counted_edges=10)
    assert invalid.qualification_state == "invalid"
    assert invalid.discontinuity_reason == "reference_invalid_or_stale"
    assert recovered.qualification_state == "epoch_open"
    assert recovered.phase_epoch == invalid.phase_epoch + 1

    loss = _engine()
    loss.process(_snapshot(1, 1000, ticks=100), counted_edges=None)
    returned = loss.process(_snapshot(2, 950, ticks=600), counted_edges=50)
    assert returned.discontinuity_reason == "reference_pps_long_interval"
    assert returned.qualification_state == "epoch_open"


def test_dac_epoch_preserves_raw_phase_and_reseeds_derived_candidates() -> None:
    profile, _ = load_profile()
    records = _run_edges([11, 11], dac_epochs=[0, 1])
    assert records[-1].phase_epoch == records[-2].phase_epoch
    assert records[-1].relative_phase_cycles == 2

    suite = CandidateSuite(profile)
    first = suite.process(records[0])
    before = suite.process(records[1])
    after = suite.process(records[2])
    assert first and before and after
    assert all(item.raw_relative_phase_cycles == 2 for item in after)
    assert all(item.qualification_state == "initializing" for item in after)


def test_candidate_frequency_outputs_match_constant_offset_after_600_intervals() -> None:
    profile, _ = load_profile()
    records = _run_edges([11] * 600)
    suite = CandidateSuite(profile)
    latest = []
    for record in records:
        latest = suite.process(record)
    by_id = {item.candidate_id: item for item in latest}

    assert by_id[
        "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"
    ].estimated_frequency_error_hz == pytest.approx(1.0)
    assert by_id[
        "CX318_RELATIVE_PHASE_ROLLING_OLS_V1_600S"
    ].estimated_frequency_error_hz == pytest.approx(1.0)
    assert by_id[
        "CX318_RELATIVE_PHASE_ALPHA_BETA_V1_alpha_beta_fast"
    ].estimated_frequency_error_hz == pytest.approx(1.0, abs=1e-5)


def test_malformed_reordered_and_invalid_snapshot_inputs_do_not_bridge() -> None:
    engine = _engine()
    with pytest.raises(ValueError, match="malformed"):
        engine.process(_snapshot(-1, 1000), counted_edges=None)

    engine.process(_snapshot(1, 1000, ticks=100), counted_edges=None)
    reordered = engine.process(
        _snapshot(2, 990, ticks=90), counted_edges=10
    )
    assert reordered.qualification_state == "invalid"
    assert reordered.discontinuity_reason == "reference_timestamp_reordered"

    opened = engine.process(_snapshot(3, 980, ticks=300), counted_edges=10)
    assert opened.qualification_state == "epoch_open"
    bad_status = engine.process(
        _snapshot(4, 970, ticks=400, status=1), counted_edges=10
    )
    assert bad_status.qualification_state == "invalid"
    assert bad_status.discontinuity_reason == "snapshot_status_invalid"


def test_repeated_replay_is_deterministic() -> None:
    profile, _ = load_profile()

    def replay() -> tuple[list, list]:
        records = _run_edges([10, 11, 9, 12, 8] * 150)
        suite = CandidateSuite(profile)
        estimates = [
            estimate
            for record in records
            for estimate in suite.process(record)
        ]
        return records, estimates

    records_a, estimates_a = replay()
    records_b, estimates_b = replay()
    assert deterministic_digest(records_a, estimates_a) == deterministic_digest(
        records_b, estimates_b
    )
    assert [asdict(record) for record in records_a] == [
        asdict(record) for record in records_b
    ]


def test_injected_phase_step_exposes_candidate_lag_and_gain_sensitivity() -> None:
    profile, _ = load_profile()
    engine = _engine()
    suite = CandidateSuite(profile)
    counter = 100_000
    responses: dict[str, list[tuple[int, object]]] = {}

    for sequence in range(1, 4_102):
        counted_edges = None
        if sequence > 1:
            counted_edges = 15 if sequence == 102 else 10
            counter = (counter - counted_edges) % MODULUS
        record = engine.process(
            _snapshot(sequence, counter), counted_edges=counted_edges
        )
        if sequence < 102:
            suite.process(record)
            continue
        for estimate in suite.process(record):
            responses.setdefault(estimate.candidate_id, []).append(
                (sequence - 102, estimate)
            )

    def first_frequency(candidate_id: str) -> int:
        return next(
            elapsed
            for elapsed, estimate in responses[candidate_id]
            if estimate.estimated_frequency_error_hz is not None
        )

    def peak_frequency(candidate_id: str) -> float:
        return max(
            abs(estimate.estimated_frequency_error_hz or 0.0)
            for _, estimate in responses[candidate_id]
        )

    def final_frequency_settle(candidate_id: str) -> int:
        violations = [
            elapsed
            for elapsed, estimate in responses[candidate_id]
            if estimate.estimated_frequency_error_hz is None
            or abs(estimate.estimated_frequency_error_hz) > 5e-5
        ]
        return max(violations) + 1 if violations else 0

    raw = "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"
    ols600 = "CX318_RELATIVE_PHASE_ROLLING_OLS_V1_600S"
    ols1800 = "CX318_RELATIVE_PHASE_ROLLING_OLS_V1_1800S"
    ols3600 = "CX318_RELATIVE_PHASE_ROLLING_OLS_V1_3600S"
    fast = "CX318_RELATIVE_PHASE_ALPHA_BETA_V1_alpha_beta_fast"
    balanced = "CX318_RELATIVE_PHASE_ALPHA_BETA_V1_alpha_beta_balanced"
    slow = "CX318_RELATIVE_PHASE_ALPHA_BETA_V1_alpha_beta_slow"

    assert all(
        estimate.filtered_relative_phase_cycles
        == estimate.raw_relative_phase_cycles
        for _, estimate in responses[raw]
    )
    assert [first_frequency(item) for item in (raw, ols600, ols1800, ols3600)] == [
        499,
        499,
        1699,
        3499,
    ]
    assert final_frequency_settle(raw) == 600
    assert peak_frequency(fast) > peak_frequency(balanced) > peak_frequency(slow)
    assert (
        final_frequency_settle(fast)
        < final_frequency_settle(balanced)
        < final_frequency_settle(slow)
    )


def test_frozen_corpus_includes_every_stage7_attempt_and_explicit_missing_case() -> None:
    corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    declared = _declared_runs(corpus)
    paths = {item["path"] for item in declared}
    stage7_root = Path(corpus["discovered_run_groups"][0]["directory"])
    expected_stage7 = {
        child.as_posix()
        for child in stage7_root.glob("*")
        if child.is_dir()
    }

    assert expected_stage7 <= paths
    assert len(declared) == len(paths)
    assert all(value is False for value in corpus["authority"].values())


def test_small_historical_replay_is_source_preserving_and_deterministic() -> None:
    corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    profile, profile_sha256 = load_profile()
    item = next(
        value
        for value in corpus["explicit_runs"]
        if value["class"] == "phase5_pseudo_clean"
    )

    first = replay_run(
        item,
        corpus=corpus,
        candidate_profile=profile,
        configuration_sha256=profile_sha256,
    )
    second = replay_run(
        item,
        corpus=corpus,
        candidate_profile=profile,
        configuration_sha256=profile_sha256,
    )

    assert first["status"] == "replayed"
    assert first["sources_unchanged"] is True
    assert first["false_continuity_count"] == 0
    assert first["false_recovery_count"] == 0
    assert first["raw_phase_records_sha256"] == second["raw_phase_records_sha256"]
    assert first["candidate_estimates_sha256"] == second["candidate_estimates_sha256"]


def test_selected_profile_is_schema_valid_bound_and_retains_zero_authority() -> None:
    profile_path = Path(
        "profiles/estimators/cx318_relative_phase_selected_v1.json"
    )
    schema_path = Path(
        "schemas/cx318_relative_phase_selected_v1.schema.json"
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)

    for binding in profile["bindings"].values():
        source = Path(binding["path"])
        assert source.is_file()
        assert sha256(source.read_bytes()).hexdigest() == binding["sha256"]
    assert profile["oscillator_identity"] == "CX317"
    assert profile["programme_label"] == "CX318"
    assert profile["selection"]["raw_phase_method"].endswith("RAW_ACCUMULATOR_V1")
    assert all(value is False for value in profile["authority"].values())
