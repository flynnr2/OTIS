"""Finite command-boundary tests of the real unattended coordinator.

Recorder snapshots/socket replies are doubles; these tests establish host
admission and confirmation behavior, not firmware or physical DAC behavior.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from host.otis_tools import unattended

SESSION = 18446744073709551601
SEQUENCE = 7
RECEIPT_TICKS = (1 << 40) + 123
DWELL = 259200
ADMISSION_WAIT = "fresh instrument status required before a mode request"


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    plan = unattended.Plan.load(json.dumps({
        "schema_version": 1, "device": "/dev/test-no-io",
        "run_dir": str(run_dir), "shared_output_dir": str(tmp_path / "shared"),
        "expected_session": SESSION,
        "expected_build_identity": "a" * 64 + ":" + "b" * 64,
        "expected_policy_sha256": "c" * 64,
        "auto_dwell_s": DWELL, "poll_interval_s": 1,
        "command_deadline_s": 5, "keep_awake": False,
    }).encode())
    clock = SimpleNamespace(now=0.0)

    def sleep(seconds):
        assert 0 <= seconds <= 1
        clock.now += seconds
        assert clock.now <= 5, "a nested wait renewed the fixed command deadline"

    monkeypatch.setattr(unattended, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=sleep))
    owner = unattended.Coordinator(plan, "d" * 64)
    yield owner, clock
    owner.journal.close()


def snapshot(owner, *, mode=0, ticks=RECEIPT_TICKS):
    mode_name = "AUTO_DISCIPLINE" if mode == 0 else "OBSERVE_HOLD"
    return {
        "instrument_fresh": True, "writer_fresh": True, "pending_command": None,
        "last_command_receipt": {
            "session": SESSION, "sequence": SEQUENCE, "mode": mode,
            "code": 0, "dwell_s": DWELL if mode == 0 else 0,
            "result": "ACCEPTED", "ticks": RECEIPT_TICKS,
        },
        "instrument": {
            "session": SESSION, "mode": mode_name, "requested_mode": mode_name,
            "last_command_sequence": SEQUENCE, "completed_command_sequence": SEQUENCE,
            "build_identity": owner.plan.expected_build_identity,
            "policy_identity": owner.plan.expected_policy_sha256,
            "applied_code": 43085, "applied_code_known": True, "dac_epoch": 3,
            "fields": {
                "write_state": "0", "write_sequence": "3", "fault": "none",
                "instrument_ticks": str(ticks),
                "operating_end_ticks": str(RECEIPT_TICKS + DWELL * 1_000_000),
            },
        },
    }


def events(owner):
    return [json.loads(line) for line in
            (owner.plan.run_dir / unattended.EVENTS).read_text().splitlines()]


def submitted():
    return {"submission": "written_unconfirmed", "session": SESSION,
            "sequence": SEQUENCE}


def test_auto_binds_full_72_hours_to_exact_receipt(coordinator, monkeypatch):
    owner, clock = coordinator
    state = snapshot(owner, ticks=RECEIPT_TICKS + 3_000_000)
    calls = []
    monkeypatch.setattr(owner, "observe", lambda: state)
    monkeypatch.setattr(unattended, "request", lambda path, value:
                        (calls.append(copy.deepcopy(value)) or submitted()))
    assert owner.preload_auto()
    assert owner.end_ticks == RECEIPT_TICKS + 259_200_000_000
    assert calls == [{"operation": "mode", "expected_session": SESSION,
                      "mode": 0, "code": 0, "dwell_s": DWELL}]
    assert clock.now == 0


@pytest.mark.parametrize("defect", [
    "short_by_one_tick", "long_by_one_tick", "status_precedes_receipt",
    "wrong_receipt_mode", "wrong_receipt_code", "wrong_receipt_dwell",
    "wrong_receipt_session", "wrong_receipt_sequence", "duplicate_receipt",
    "later_unrequested_command",
])
def test_auto_counterexamples_never_renew_or_confirm(coordinator, monkeypatch, defect):
    owner, clock = coordinator
    state = snapshot(owner)
    receipt, active = state["last_command_receipt"], state["instrument"]
    fields = active["fields"]
    if defect in {"short_by_one_tick", "long_by_one_tick"}:
        fields["operating_end_ticks"] = str(int(fields["operating_end_ticks"]) +
                                             (-1 if defect == "short_by_one_tick" else 1))
    elif defect == "status_precedes_receipt":
        fields["instrument_ticks"] = str(RECEIPT_TICKS - 1)
    elif defect == "duplicate_receipt":
        receipt["result"] = "DUPLICATE"
    elif defect == "later_unrequested_command":
        active["last_command_sequence"] = active["completed_command_sequence"] = SEQUENCE + 1
    else:
        key = defect.removeprefix("wrong_receipt_")
        receipt[key if key != "dwell" else "dwell_s"] += 1
    calls = []
    review_holds = []
    monkeypatch.setattr(owner, "observe", lambda: state)
    # The separate tests below exercise the real review-HOLD path. Isolate
    # AUTO here so an authorized HOLD cannot obscure an unintended AUTO retry.
    monkeypatch.setattr(owner, "submit_review_hold", lambda value: review_holds.append(value))
    monkeypatch.setattr(unattended, "request", lambda path, value:
                        (calls.append(copy.deepcopy(value)) or submitted()))
    assert not owner.preload_auto()
    assert owner.end_ticks is None
    assert len(calls) == 1 and calls[0]["mode"] == 0
    assert owner.review_reason and len(review_holds) == 1
    assert clock.now <= owner.plan.command_deadline_s


def test_hold_retries_only_known_not_written_cohort_race(coordinator, monkeypatch):
    owner, clock = coordinator
    initial = snapshot(owner)
    held = snapshot(owner, mode=1, ticks=RECEIPT_TICKS + 1)
    attempts, writes = [], []

    def request(path, value):
        attempts.append(copy.deepcopy(value))
        if len(attempts) == 1:
            return {"error": ADMISSION_WAIT}
        writes.append(copy.deepcopy(value))
        return submitted()

    monkeypatch.setattr(unattended, "request", request)
    monkeypatch.setattr(owner, "observe", lambda: held)
    owner.submit_review_hold(initial)
    owner.submit_review_hold(initial)  # Later polling cannot replay the command.
    assert len(attempts) == 2 and len(writes) == 1
    assert writes[0] == {"operation": "mode", "expected_session": SESSION,
                         "mode": 1, "code": 0, "dwell_s": 0}
    assert clock.now == 1
    assert [e["event"] for e in events(owner)].count("hold_effective") == 1


def test_hold_admission_wait_has_one_fixed_deadline(coordinator, monkeypatch):
    owner, clock = coordinator
    state = snapshot(owner)
    calls = []
    monkeypatch.setattr(owner, "observe", lambda: state)
    monkeypatch.setattr(unattended, "request", lambda path, value:
                        (calls.append(value) or {"error": ADMISSION_WAIT}))
    owner.submit_review_hold(state)
    assert clock.now == owner.plan.command_deadline_s
    assert len(calls) == 5
    assert not owner.hold_submitted
    assert events(owner)[-1]["reason"] == "local_admission_deadline"


@pytest.mark.parametrize("outcome", ["lost_socket_reply", "incomplete_serial_write"])
def test_hold_ambiguous_submission_is_never_replayed(coordinator, monkeypatch, outcome):
    owner, clock = coordinator
    state = snapshot(owner)
    calls = []

    def request(path, value):
        calls.append(value)
        if outcome == "lost_socket_reply":
            raise OSError("socket reply lost after potential serial submission")
        return {"error": "mode command was not fully submitted"}

    monkeypatch.setattr(unattended, "request", request)
    owner.submit_review_hold(state)
    owner.submit_review_hold(state)
    assert len(calls) == 1 and owner.hold_submitted
    assert clock.now == 0
    assert "hold_effective" not in [e["event"] for e in events(owner)]


@pytest.mark.parametrize("tick_offset", [-1, 0, 1])
def test_hold_requires_status_at_or_after_exact_receipt(coordinator, monkeypatch, tick_offset):
    owner, clock = coordinator
    initial = snapshot(owner)
    held = snapshot(owner, mode=1, ticks=RECEIPT_TICKS + tick_offset)
    calls = []
    monkeypatch.setattr(owner, "observe", lambda: held)
    monkeypatch.setattr(unattended, "request", lambda path, value:
                        (calls.append(value) or submitted()))
    owner.submit_review_hold(initial)
    names = [e["event"] for e in events(owner)]
    assert len(calls) == 1
    assert ("hold_effective" in names) == (tick_offset >= 0)
    if tick_offset < 0:
        assert "hold_delivery_or_completion_unresolved" in names
        assert clock.now == owner.plan.command_deadline_s

