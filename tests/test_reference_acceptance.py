from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
POLICY = json.loads((ROOT / "data_contracts/reference_acceptance_policy_v2.json").read_text())
POLICY_KEYS = (
    "nominal_interval_ticks", "tolerance_ticks", "acquisition_intervals",
    "maximum_edge_rate_hz", "allowed_reference_flags", "maximum_excluded_candidates_per_span",
    "maximum_count_span_ticks",
)
MODULUS = 1 << 32


def test_live_selection_is_shared_and_preserves_raw_production():
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    start = sketch.index("void emit_pps_count_boundary(")
    end = sketch.index("\nvoid ", start)
    boundary = sketch[start:end]
    assert boundary.count("reference_acceptance.observe(") == 1
    raw = boundary.index("otis_count_observation_on_pps_boundary(")
    derived = boundary.index("otis_reference_acceptance_format_span(")
    phase = boundary.index("otis_phase_preview_live_on_reference_selection(")
    frequency = boundary.index("otis_frequency_regulation_live_on_reference_selection(")
    assert raw < derived < phase < frequency
    assert "&selection, closing_extended_ticks" in boundary
    assert "otis_phase_preview_live_on_boundary(" not in sketch
    assert "otis_frequency_regulation_live_on_boundary(" not in sketch


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    binary = tmp_path_factory.mktemp("reference_acceptance") / "trace"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
        str(ROOT / "tests/cpp/reference_acceptance_harness.cpp"),
        "-I", str(FIRMWARE), "-o", str(binary),
    ], check=True, cwd=ROOT)
    return binary


def run(harness, commands, **policy_overrides):
    policy = POLICY | policy_overrides
    completed = subprocess.run(
        [str(harness), *(str(policy[key]) for key in POLICY_KEYS)],
        input="\n".join(commands) + "\n", capture_output=True, text=True, check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines()]


class Trace:
    def __init__(self, *, ticks=0, snapshot=100, reference=None, counter=MODULUS - 1, session=1):
        reference = snapshot if reference is None else reference
        self.ticks, self.snapshot, self.reference, self.counter, self.session = ticks, snapshot, reference, counter, session
        self.commands = []
        self.observations = []

    def observe(self, *, status=0, flags=None, uncertainty=0):
        flags = POLICY["allowed_reference_flags"] if flags is None else flags
        row = dict(session=self.session, snapshot_sequence=self.snapshot, reference_sequence=self.reference,
                   ticks=self.ticks, down_counter=self.counter, status=status, flags=flags,
                   uncertainty=uncertainty)
        self.observations.append(row)
        self.commands.append("O " + " ".join(str(value) for value in row.values()))
        return row

    def advance(self, ticks=None, *, edges=None, **kwargs):
        ticks = POLICY["nominal_interval_ticks"] if ticks is None else ticks
        edges = ticks * 10 if edges is None else edges
        self.ticks = (self.ticks + ticks) % MODULUS
        self.counter = (self.counter - edges) % MODULUS
        self.snapshot = (self.snapshot + 1) % MODULUS
        self.reference = (self.reference + 1) % MODULUS
        return self.observe(**kwargs)

    def acquire(self):
        self.observe()
        for _ in range(POLICY["acquisition_intervals"]):
            self.advance()
        return self.observations[-1]

    def expire(self, *, now, drained=None, session=None, snapshot=None, reference=None, complete=True):
        self.commands.append("E " + " ".join(map(str, [
            now % MODULUS, self.session if session is None else session,
            self.snapshot if snapshot is None else snapshot,
            self.reference if reference is None else reference,
            (now if drained is None else drained) % MODULUS, int(complete),
        ])))


def spans(results):
    return [result for result in results if result["has_span"]]


def test_acquisition_establishes_anchor_without_retroactive_promotion(harness):
    trace = Trace()
    anchor = trace.acquire()
    trace.advance(edges=10_000_003)
    results = run(harness, trace.commands)
    assert results[0]["disposition"] == "seeded"
    assert [r["acquisition_progress"] for r in results[:9]] == list(range(9))
    assert results[8]["disposition"] == "tracking_established"
    assert not any(r["has_span"] for r in results[:9])
    assert spans(results)[0]["opening"] == anchor
    assert spans(results)[0]["closing"] == trace.observations[-1]
    assert spans(results)[0]["counted_edges"] == 10_000_003
    assert spans(results)[0]["accepted_boundary_ordinal"] == 1
    assert POLICY["control_authority"] is False


def test_observed_split_uses_cumulative_endpoints_and_preserves_raw(harness):
    trace = Trace()
    anchor = trace.acquire()
    rogue = trace.advance(246_294, edges=2_462_937)
    closing = trace.advance(753_707, edges=7_537_063)
    results = run(harness, trace.commands)
    excluded, accepted = results[-2:]
    assert excluded["disposition"] == "early_excluded"
    assert excluded["candidate"] == rogue
    assert excluded["expiry_ticks"] == results[-3]["expiry_ticks"]
    assert accepted["opening"] == anchor and accepted["closing"] == closing
    assert accepted["counted_edges"] == 10_000_000
    assert accepted["interval_ticks"] == 1_000_001
    assert accepted["excluded_candidate_count"] == 1
    assert accepted["acceptance_epoch"] == results[-3]["acceptance_epoch"]


def test_repeated_early_candidates_never_move_anchor_or_expiry(harness):
    trace = Trace()
    anchor = trace.acquire()
    for _ in range(POLICY["maximum_excluded_candidates_per_span"]):
        trace.advance(100_000)
    trace.advance(200_000)
    results = run(harness, trace.commands)
    early = results[9:-1]
    assert all(r["disposition"] == "early_excluded" and r["opening"] == anchor for r in early)
    assert len({r["expiry_ticks"] for r in early}) == 1
    assert results[-1]["excluded_candidate_count"] == 8
    assert results[-1]["counted_edges"] == 10_000_000


def test_exclusion_budget_ends_epoch_and_does_not_bridge(harness):
    trace = Trace()
    trace.acquire()
    for _ in range(POLICY["maximum_excluded_candidates_per_span"] + 1):
        trace.advance(100_000)
    trace.advance(100_000)
    results = run(harness, trace.commands)
    assert results[-2]["reason"] == "exclusion_budget_exhausted"
    assert results[-2]["tracking"] is False
    assert results[-1]["disposition"] == "seeded"
    assert results[-1]["acceptance_epoch"] == 2
    assert not spans(results)


@pytest.mark.parametrize("offset", [-1250, 1250])
def test_inclusive_window_endpoints(harness, offset):
    trace = Trace()
    trace.acquire()
    trace.advance(POLICY["nominal_interval_ticks"] + offset)
    assert run(harness, trace.commands)[-1]["disposition"] == "accepted_span"


def test_uncertainty_overlap_loses_qualification_in_native_trace(harness):
    trace = Trace()
    trace.acquire()
    trace.advance(998_751, uncertainty=2)
    result = run(harness, trace.commands)[-1]
    assert result["disposition"] == "qualification_lost"
    assert result["reason"] == "observation_age_ambiguous"


def test_late_boundary_and_two_second_gap_start_fresh_acquisition(harness):
    trace = Trace()
    trace.acquire()
    trace.advance(2_000_000)
    for _ in range(POLICY["acquisition_intervals"]):
        trace.advance()
    trace.advance()
    results = run(harness, trace.commands)
    assert results[9]["reason"] == "late_boundary"
    assert results[9]["acceptance_epoch"] == 2
    assert results[-2]["disposition"] == "tracking_established"
    assert len(spans(results)) == 1
    assert spans(results)[0]["interval_ticks"] == POLICY["nominal_interval_ticks"]
    assert spans(results)[0]["accepted_boundary_ordinal"] == 1


def test_acquisition_uses_consecutive_raw_intervals(harness):
    trace = Trace()
    trace.observe()
    for _ in range(7):
        trace.advance()
    trace.advance(246_294)
    trace.advance(753_707)
    for _ in range(8):
        trace.advance()
    results = run(harness, trace.commands)
    assert results[8]["reason"] == results[9]["reason"] == "acquisition_restart"
    assert results[-2]["tracking"] is False
    assert results[-1]["disposition"] == "tracking_established"
    assert not spans(results)


@pytest.mark.parametrize("defect,reason", [
    ("snp_gap", "raw_sequence"), ("reference_gap", "raw_sequence"),
    ("duplicate", "raw_sequence"), ("same_ticks", "raw_timestamp"),
    ("backward_ticks", "raw_timestamp"),
    ("timing_status", "observation_age_ambiguous"),
    ("transport_status", "capture_integrity"),
    ("flags", "capture_integrity"), ("zero_count", "raw_count"),
    ("impossible_count", "raw_count"), ("long_counter_interval", "late_boundary"),
    ("session", "session_changed"), ("unknown_session", "unknown_session"),
])
def test_intervening_raw_defects_prevent_bridging(harness, defect, reason):
    trace = Trace()
    trace.acquire()
    if defect == "snp_gap":
        trace.snapshot += 1
    elif defect == "reference_gap":
        trace.reference += 1
    elif defect == "session":
        trace.session += 1
    elif defect == "unknown_session":
        trace.session = 0
    if defect == "duplicate":
        trace.observe()
    elif defect == "same_ticks":
        trace.advance(0, edges=1)
    elif defect == "backward_ticks":
        trace.advance(-1, edges=1)
    elif defect == "timing_status":
        trace.advance(100_000, status=1)
    elif defect == "transport_status":
        trace.advance(100_000, status=1 << 2)
    elif defect == "flags":
        trace.advance(100_000, flags=POLICY["allowed_reference_flags"] | 1)
    elif defect == "zero_count":
        trace.advance(edges=0)
    elif defect == "impossible_count":
        trace.advance(100, edges=159_600_001)
    elif defect == "long_counter_interval":
        trace.advance(33_000_000, edges=10_000_000)
    else:
        trace.advance(100_000)
    results = run(harness, trace.commands)
    assert results[-1]["disposition"] == "qualification_lost"
    assert results[-1]["reason"] == reason
    assert results[-1]["tracking"] is False
    assert not spans(results)


def test_raw_timer_counter_and_single_owner_ordinal_wrap_with_600_spans(harness):
    trace = Trace(ticks=MODULUS - 8_500_000, snapshot=MODULUS - 10,
                  counter=30_000_000)
    anchor = trace.acquire()
    for _ in range(600):
        trace.advance()
    results = run(harness, trace.commands)
    accepted = spans(results)
    assert len(accepted) == 600
    assert accepted[0]["opening"] == anchor
    assert accepted[-1]["closing"] == trace.observations[-1]
    assert [row["accepted_boundary_ordinal"] for row in accepted] == list(range(1, 601))
    assert {row["acceptance_epoch"] for row in accepted} == {1}
    assert sum(row["counted_edges"] for row in accepted) == 6_000_000_000
    assert all(a["closing"] == b["opening"] for a, b in zip(accepted, accepted[1:]))
    assert any(row["closing"]["down_counter"] > row["opening"]["down_counter"] for row in accepted)
    assert any(row["closing"]["snapshot_sequence"] == 0 for row in accepted)
    assert any(row["closing"]["reference_sequence"] == 0 for row in accepted)
    assert any(row["closing"]["ticks"] < row["opening"]["ticks"] for row in accepted)


def test_expiry_requires_drained_frontier_after_inclusive_deadline(harness):
    trace = Trace(ticks=MODULUS - 9_000_000)
    anchor = trace.acquire()
    deadline = anchor["ticks"] + POLICY["nominal_interval_ticks"] + POLICY["tolerance_ticks"]
    trace.expire(now=deadline + 1, complete=False)
    trace.expire(now=deadline + 1, drained=deadline)
    trace.expire(now=deadline + 1)
    trace.advance(2_000_000)
    results = run(harness, trace.commands)
    assert [row["disposition"] for row in results[-4:]] == [
        "expiry_pending", "expiry_pending", "qualification_lost", "seeded"]
    assert results[-2]["reason"] == "missing_boundary"
    assert results[-1]["acceptance_epoch"] == 2


@pytest.mark.parametrize("case,disposition", [
    ("session", "frontier_rejected"), ("future_ordinal", "frontier_rejected"),
    ("mismatched_ordinal", "frontier_rejected"), ("future_tick", "frontier_rejected"),
    ("stale_ordinal", "expiry_pending"), ("stale_tick", "expiry_pending"),
])
def test_frontier_cannot_discard_queued_qualifying_observation(harness, case, disposition):
    trace = Trace()
    trace.acquire()
    now = trace.ticks + 1_100_000
    kwargs = dict(now=now)
    if case == "session":
        kwargs["session"] = 2
    elif case == "future_ordinal":
        kwargs.update(snapshot=trace.snapshot + 1, reference=trace.reference + 1)
    elif case == "mismatched_ordinal":
        kwargs.update(snapshot=trace.snapshot - 1)
    elif case == "future_tick":
        kwargs["drained"] = now + 1
    elif case == "stale_ordinal":
        kwargs.update(snapshot=trace.snapshot - 1, reference=trace.reference - 1)
    elif case == "stale_tick":
        kwargs["drained"] = trace.ticks - 1
    trace.expire(**kwargs)
    trace.advance()
    results = run(harness, trace.commands)
    assert results[-2]["disposition"] == disposition
    assert results[-2]["tracking"] is True
    assert results[-1]["disposition"] == "accepted_span"


def test_early_traffic_does_not_extend_expiry(harness):
    trace = Trace()
    anchor = trace.acquire()
    for _ in range(8):
        trace.advance(100_000)
    trace.expire(now=anchor["ticks"] + 1_001_251)
    result = run(harness, trace.commands)[-1]
    assert result["reason"] == "missing_boundary"
    assert result["tracking"] is False


def test_in_band_impostor_limit_and_immutable_emitted_spans(harness):
    trace = Trace()
    trace.acquire()
    impostor = trace.advance(998_750)
    before = run(harness, trace.commands)[-1]
    trace.advance(1250)  # Later physical edge cannot retrospectively replace it.
    trace.advance(998_750)
    trace.advance(2_000_000)
    results = run(harness, trace.commands)
    assert results[9] == before
    assert before["has_span"] and before["closing"] == impostor
    assert results[10]["disposition"] == "early_excluded"
    assert results[-1]["reason"] == "late_boundary"


def test_policy_is_supplied_not_duplicated_in_kernel(harness):
    trace = Trace()
    trace.observe()
    trace.advance()
    trace.advance()
    results = run(harness, trace.commands, acquisition_intervals=1)
    assert results[1]["disposition"] == "tracking_established"
    assert results[2]["has_span"]
    results = run(harness, trace.commands, tolerance_ticks=POLICY["nominal_interval_ticks"])
    assert all(row["disposition"] == "invalid_policy" for row in results)


def test_zero_interior_delta_is_preserved_and_does_not_erase_anchor(harness):
    trace = Trace()
    anchor = trace.acquire()
    trace.advance(1, edges=0)
    trace.advance(999_999, edges=10_000_000)
    results = run(harness, trace.commands)
    assert results[-2]["disposition"] == "early_excluded"
    assert results[-2]["candidate"]["down_counter"] == anchor["down_counter"]
    assert results[-1]["counted_edges"] == 10_000_000
    assert results[-1]["opening"] == anchor


def test_zero_acquisition_interval_cannot_qualify(harness):
    trace = Trace()
    trace.observe()
    trace.advance(edges=0)
    result = run(harness, trace.commands)[-1]
    assert result["reason"] == "raw_count"
    assert result["tracking"] is False


def test_gross_bound_applies_to_whole_span_not_each_fragment_alone(harness):
    trace = Trace()
    trace.acquire()
    trace.advance(250_000, edges=100_000_000)
    trace.advance(750_000, edges=100_000_000)
    results = run(harness, trace.commands)
    assert results[-2]["disposition"] == "early_excluded"
    assert results[-1]["reason"] == "raw_count"
    assert not spans(results)


def test_short_local_interval_does_not_set_exact_physical_count_bound(harness):
    trace = Trace()
    trace.acquire()
    trace.advance(1, edges=200)
    trace.advance(999_999, edges=9_999_800)
    result = run(harness, trace.commands)[-1]
    assert result["has_span"]
    assert result["counted_edges"] == 10_000_000
