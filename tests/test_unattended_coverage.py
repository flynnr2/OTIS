"""Output coverage loss cannot create instrument mode authority."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from host.otis_tools import unattended


def test_prolonged_status_loss_retains_coverage_finding_without_hold(
    tmp_path: Path, monkeypatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(
        unattended, "time",
        SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)),
    )
    plan = unattended.Plan(
        device="/dev/cu.fixture", run_dir=tmp_path,
        shared_output_dir=tmp_path.parent / "shared", expected_session=42,
        expected_build_identity="a" * 64 + ":" + "b" * 64,
        expected_policy_sha256="c" * 64, auto_dwell_s=10,
        poll_interval_s=1, startup_deadline_s=30, command_deadline_s=10,
        endpoint_grace_s=5, minimum_free_bytes=0, keep_awake=False,
    )
    owner = unattended.Coordinator(plan, "d" * 64)
    owner.auto_sequence = 1
    owner.end_ticks = 10_000_000
    owner.last_write_sequence = 1
    owner.recorder = SimpleNamespace(poll=lambda: None, pid=1234)
    owner.monitor = SimpleNamespace(poll=lambda: None, pid=1235)
    owner.capture_progress = lambda state: True
    owner.submit_review_hold = lambda state: (_ for _ in ()).throw(
        AssertionError("status delivery loss must not request HOLD")
    )

    def instrument_state(mode: str, tick: int) -> dict:
        instrument = {
            "session": 42, "build_identity": plan.expected_build_identity,
            "policy_identity": plan.expected_policy_sha256,
            "mode": mode, "requested_mode": mode, "state": mode,
            "applied_code": 43085, "applied_code_known": True,
            "dac_epoch": 1, "last_command_sequence": 1,
            "completed_command_sequence": 1,
            "fields": {
                "instrument_ticks": str(tick), "operating_end_ticks": (
                    "0" if mode == "OBSERVE_HOLD" else "10000000"
                ),
                "instrument_ticks_domain": "rp2040_timer_us64",
                "write_state": "0", "write_sequence": "1", "fault": "none",
            },
        }
        return {"instrument_fresh": True, "writer_fresh": True,
                "instrument": instrument, "pending_command": None,
                "observed_record_counts": {"REF": 10, "SNP": 10, "CNT": 10}}

    owner.observe = lambda: (
        None if clock[0] < 31 else
        instrument_state("AUTO_DISCIPLINE", 1_000_000) if clock[0] < 32 else
        instrument_state("OBSERVE_HOLD", 11_000_000)
    )
    closed = []
    owner.close_and_finalize = lambda state: closed.append(state)
    try:
        owner.run_observation()
    finally:
        owner.journal.close()
    assert len(closed) == 1
    assert owner.review_reason is None
    assert not owner.hold_submitted
    assert owner.coverage_escalations == ["decision_status_prolonged_stale_coverage"]
    journal = [json.loads(line) for line in (tmp_path / unattended.EVENTS).read_text().splitlines()]
    assert [item["event"] for item in journal].count("coverage_escalation") == 1
    assert "review_required" not in {item["event"] for item in journal}
