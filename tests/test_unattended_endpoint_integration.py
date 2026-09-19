"""Accelerated closure after repeated real host transactions; no duration claim."""
import json
import os
import pty
import threading

import pytest

from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    UNATTENDED_72_HOUR_HYBRID_CONTROL,
)
from host.otis_tools.adaptive_hybrid_supervisor import AdaptiveHybridSupervisor
from host.otis_tools.live_run import run_experiment
from host.otis_tools.offline import finish_run
from host.otis_tools.run_spec import create_run_record
from tests.run_spec_fixtures import build_synthetic_spec
from tools.otis_rehearsal_device import DeterministicPtyInstrument
from tools.rehearse_host import (
    _capture_command,
    _owner_second_response_confirmed,
    _utc_now,
)


@pytest.mark.parametrize("pending_review", [False, True])
def test_scheduled_endpoint_closes_after_second_response_without_abort(tmp_path, monkeypatch, pending_review):
    spec = build_synthetic_spec(monkeypatch, tmp_path, purpose=UNATTENDED_72_HOUR_HYBRID_CONTROL)
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    record = create_run_record(spec, execution_kind="simulated", run_id=tmp_path.name,
                              started_at_utc=_utc_now(), serial_device=device,
                              output_path=tmp_path / "run_manifest.json")
    instrument = DeterministicPtyInstrument(master, spec.runtime_manifest(record), ADAPTIVE_HYBRID_PROGRAMME)
    original = AdaptiveHybridSupervisor._maybe_finish

    def accelerate(owner, health, now_ns):
        if _owner_second_response_confirmed(tmp_path):
            if pending_review and owner.state.get("host_verification_hold") is None:
                owner._enter_host_verification_hold(ValueError("retained diagnostic at scheduled endpoint"))
            owner._wall_deadline_monotonic_ns = now_ns
        original(owner, health, now_ns)

    monkeypatch.setattr(AdaptiveHybridSupervisor, "_maybe_finish", accelerate)
    os.close(slave)

    def on_ready(experiment):
        thread = instrument.start()
        finished = threading.Event()
        def bounded_abort():
            if not finished.wait(120):
                experiment.submit_explicit_abort()
        guard = threading.Thread(target=bounded_abort, daemon=True)
        guard.start()
        def cleanup():
            finished.set()
            guard.join(timeout=2)
            instrument.stop()
            thread.join(timeout=2)
        return cleanup

    try:
        live = run_experiment(manifest_path=tmp_path / "run_manifest.json", device=device,
                              physical=False, capture_command=_capture_command(device, tmp_path),
                              on_ready=on_ready)
    finally:
        os.close(master)
    assert instrument.error is None
    assert live["terminal"]["reason"] == ("adaptive_hybrid_scheduled_stop_review_required" if pending_review else "adaptive_hybrid_endurance_complete")
    assert live["capture_exit"] == 0
    assert "ACTIVE ABORT" not in instrument.commands
    window = live["terminal"]["observation_window"]
    assert window["observed_terminal_monotonic_ns"] < window["deadline_monotonic_ns"]
    packaged = finish_run(tmp_path)
    assert packaged["capture"]["integrity"] == "complete"
    # The recorded deadline exposes acceleration; this cannot claim seven days.
    assert packaged["analysis"]["outcome"] == "undetermined"
    report = json.loads((tmp_path / "reports/offline_analysis_v2.json").read_text())
    assert report["checks"]["transactions_exact"] is True
    assert report["checks"]["scientific_outcome_determined"] is False
