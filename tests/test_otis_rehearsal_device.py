from __future__ import annotations

"""Engineering-only deterministic rehearsal device boundary."""

import os
import pty
import threading
import time
from pathlib import Path

from host.otis_tools.active_status_contract import ACTIVE_STATUS_KEYS
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    INHIBITED_ZERO_WRITE,
)
from host.otis_tools.contracts import ACTIVE_HYBRID_DECISION_V3_FIELDS
from host.otis_tools.run_spec import create_run_record
from tests.run_spec_fixtures import build_synthetic_spec
from tools import otis_rehearsal_device as device


def _read_pty(descriptor: int, done: threading.Event | None = None) -> bytes:
    os.set_blocking(descriptor, False)
    deadline = time.monotonic() + 2
    chunks = []
    while time.monotonic() < deadline:
        try:
            payload = os.read(descriptor, 65536)
            if payload:
                chunks.append(payload)
                continue
        except BlockingIOError:
            pass
        if done is None or done.is_set():
            break
        time.sleep(0.001)
    assert chunks
    return b"".join(chunks)


def test_fixture_and_initial_snapshot_emit_over_a_real_pty():
    transaction = device.TransactionFixture(*({} for _ in range(7)))
    fixture = device.LifecycleFixture({}, {}, transaction, {}, {}, {}, {}, {}, {}, transaction)
    assert len(fixture.decisions) == 6

    master, slave = pty.openpty()
    try:
        instrument = object.__new__(device.DeterministicPtyInstrument)
        instrument.master_fd = master
        instrument._lock = threading.RLock()
        instrument.programme = ADAPTIVE_HYBRID_PROGRAMME
        instrument.accepted_boundary_ordinal = 1
        instrument.raw_snapshot_sequence = 1
        instrument.raw_reference_event_sequence = 1002
        instrument.raw_cumulative_down_counter = 0xFFFFFFFF - 10_000_000
        instrument.status_sequence = 0
        instrument.generation = 0
        instrument.latest_event_timestamp_ticks = 0
        instrument.raw_interval_adjustments = {}
        instrument.reference_acceptance_binding = {"policy_sha256": "fixture"}
        instrument._emit_initial_observations()
        initial = _read_pty(slave)
        assert b"REF," in initial and b"SNP," in initial and b"CNT," in initial
        instrument._active_health = lambda: {("adaptive_hybrid", key): "fixture" for key in ACTIVE_STATUS_KEYS}
        complete = threading.Event()
        worker = threading.Thread(target=lambda: (instrument._emit_snapshot(), complete.set()))
        worker.start()
        snapshot = _read_pty(slave, complete)
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert b"adaptive_hybrid,snapshot_generation_begin,1" in snapshot
        assert b"adaptive_hybrid,snapshot_generation_complete,1" in snapshot
    finally:
        os.close(master)
        os.close(slave)


def test_device_has_no_runner_dependency_and_exposes_runtime_programme_api():
    assert "adaptive_hybrid_operational_rehearsal" not in device.__doc__
    assert tuple(device.DeterministicPtyInstrument.__init__.__annotations__) == ("master_fd", "runtime", "programme", "return")
    assert ACTIVE_HYBRID_DECISION_V3_FIELDS


def test_pre_setup_reason_matches_source_verified_firmware_contract(monkeypatch, tmp_path):
    """Keep the public rehearsal producer on the firmware pre-setup branch."""
    firmware = Path(__file__).parents[1] / (
        "firmware/arduino/otis_nano_rp2040_connect/"
        "otis_adaptive_hybrid_regulation_live.cpp"
    )
    source = firmware.read_text(encoding="utf-8")
    assert 'status->hybrid_state = "SETUP_PENDING";' in source
    assert 'status->hybrid_reason = "setup_consumers_pending";' in source
    spec = build_synthetic_spec(monkeypatch, tmp_path, purpose=INHIBITED_ZERO_WRITE)
    master, slave = pty.openpty()
    try:
        record = create_run_record(
            spec,
            execution_kind="simulated",
            run_id="reason-binding",
            started_at_utc="2026-09-12T10:00:00Z",
            serial_device=os.ttyname(slave),
            output_path=tmp_path / "run_manifest.json",
        )
        instrument = device.DeterministicPtyInstrument(
            master, spec.runtime_manifest(record), ADAPTIVE_HYBRID_PROGRAMME
        )
        health = instrument._active_health()
        assert health[("adaptive_hybrid", "hybrid_state")] == "SETUP_PENDING"
        assert health[("adaptive_hybrid", "hybrid_reason")] == "setup_consumers_pending"
    finally:
        os.close(master)
        os.close(slave)
