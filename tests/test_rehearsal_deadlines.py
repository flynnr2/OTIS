from __future__ import annotations

from pathlib import Path
import ast

import pytest

from host.otis_tools.adaptive_hybrid_contract import operational_rehearsal_timing
from host.otis_tools.adaptive_hybrid_operational_rehearsal import (
    _RehearsalProgressDeadline,
    _rehearsal_progress_facts,
    _remaining_host_seconds,
)

NS = 1_000_000_000


def test_progressing_exact_transactions_can_cross_old_90_second_cutoff():
    timing = operational_rehearsal_timing()
    watch = _RehearsalProgressDeadline(0, 0, timing)
    state = {"startup_census": {"authority_admitted": True}, "acknowledged_record_sequences": []}
    assert watch.observe(_rehearsal_progress_facts(state), 10 * NS)
    state.update(setup_confirmation={"applied_code": 43085}, setup_confirmed_utc="retained")
    assert watch.observe(_rehearsal_progress_facts(state), 30 * NS)
    for record in range(2, 10):
        state["acknowledged_record_sequences"].append(record)
        assert watch.observe(_rehearsal_progress_facts(state), (30 + record * 12) * NS)
    assert watch.last_progress_ns == 138 * NS


def test_heartbeats_unrelated_snapshots_and_repeated_written_ack_do_not_extend_stall():
    timing = operational_rehearsal_timing()
    watch = _RehearsalProgressDeadline(0, 0, timing)
    state = {"acknowledged_record_sequences": [2]}
    watch.observe(_rehearsal_progress_facts(state), NS)
    for second in range(2, timing["causal_progress_s"] + 1):
        state.update(updated_utc=str(second), snapshot_generation=second,
                     inflight_evidence_acknowledgement={"record_sequence": 3, "host_write_confirmed": True})
        assert not watch.observe(_rehearsal_progress_facts(state), second * NS)
    with pytest.raises(TimeoutError, match="stalled"):
        watch.observe(_rehearsal_progress_facts(state), (timing["causal_progress_s"] + 1) * NS)


@pytest.mark.parametrize("frontier", [[3], [2, 4], [2, 2], [True], list(range(2, 11))])
def test_progress_requires_exact_acknowledged_prefix(frontier):
    with pytest.raises(ValueError, match="exact fixture prefix"):
        _rehearsal_progress_facts({"acknowledged_record_sequences": frontier})


def test_finite_fact_set_bounds_total_duration_without_another_timer():
    timing = operational_rehearsal_timing()
    watch = _RehearsalProgressDeadline(0, 0, timing)
    facts = frozenset()
    for index in range(timing["maximum_progress_facts"]):
        facts |= {str(index)}
        assert watch.observe(facts, (index + 1) * (timing["causal_progress_s"] * NS - 1))
    assert watch.last_progress_ns < timing["transaction_sequence_s"] * NS
    with pytest.raises(ValueError, match="exceeded"):
        watch.observe(facts | {"extra"}, watch.last_progress_ns + 1)


def test_abort_submission_and_delivery_consume_same_remaining_budget(monkeypatch):
    from host.otis_tools import adaptive_hybrid_operational_rehearsal as module
    deadline = 8 * NS
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 6 * NS)
    assert _remaining_host_seconds(deadline, "abort") == 2
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: deadline)
    with pytest.raises(TimeoutError, match="shared host deadline"):
        _remaining_host_seconds(deadline, "abort")


def test_managed_pty_workers_have_no_competing_lifetime_timer():
    from host.otis_tools import adaptive_hybrid_operational_rehearsal as module
    tree = ast.parse(Path(module.__file__).read_text())
    topology = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_process_topology")
    assert not any(isinstance(n, ast.Constant) and n.value == "--duration-s" for n in ast.walk(topology))
    worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_supervisor_worker")
    durations = [n.value for n in ast.walk(worker) if isinstance(n, ast.keyword) and n.arg == "duration_s"]
    assert len(durations) == 1 and isinstance(durations[0], ast.Constant) and durations[0].value is None


def test_rehearsal_producer_and_seal_validator_share_exact_check_inventory():
    from host.otis_tools import adaptive_hybrid_operational_rehearsal as producer
    from host.otis_tools import evidence
    from host.otis_tools.adaptive_hybrid_contract import OPERATIONAL_REHEARSAL_CHECKS
    tree = ast.parse(Path(producer.__file__).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "analyze_and_seal_rehearsal")
    checks = next(node.value for node in function.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "checks" for target in node.targets))
    assert {key.value for key in checks.keys} == OPERATIONAL_REHEARSAL_CHECKS
    assert evidence.OPERATIONAL_REHEARSAL_CHECKS is producer.OPERATIONAL_REHEARSAL_CHECKS
