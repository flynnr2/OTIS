"""Exercise the shared process owner; PTY rehearsal covers the actual serial path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from host.otis_tools import adaptive_hybrid_session as module


def _run_dir(tmp_path: Path) -> Path:
    (tmp_path / "control").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "run_manifest.json").write_text('{"test":true}\n')
    return tmp_path


def _command(code: str, run_dir: Path) -> list[str]:
    return [sys.executable, "-c", code, str(run_dir)]


def test_actual_child_dispatch_receipts_follow_launch_and_enable_only_lifecycle(monkeypatch, tmp_path):
    run_dir = _run_dir(tmp_path)
    owner = module.AdaptiveHybridSession(run_dir=run_dir, device="/dev/ttys999", physical=False)
    capture = owner.launch_capture(_command('''
import json, os, pathlib, sys, time
p=pathlib.Path(sys.argv[1])
for name in ("normal_commands.fifo", "emergency_abort.fifo"):
    os.mkfifo(p/"control"/name)
(p/"reports/capture_device_state.json").write_text(json.dumps({
    "pid":os.getpid(), "capture_active":True, "serial_open":True}))
time.sleep(20)
''', run_dir), run_dir / "reports/capture.log")
    monkeypatch.setattr(module, "_serial_owner_pids", lambda _device: {capture.pid})
    try:
        owner.wait_capture_ready(3)
        owner.launch_support(
            supervisor_command=_command('''
import os, pathlib, sys, time
from host.otis_tools.adaptive_hybrid_session import publish_supervisor_ready
p=pathlib.Path(sys.argv[1]); os.mkfifo(p/"control/host_abort.fifo")
time.sleep(.1)
publish_supervisor_ready(p,p/"run_manifest.json",census_process_nonce=17)
time.sleep(20)
''', run_dir),
            monitor_command=_command('''
import pathlib, sys, time
from host.otis_tools.adaptive_hybrid_session import _binding, publish_monitor_state, MONITOR_SAMPLES_PATH
p=pathlib.Path(sys.argv[1]); time.sleep(.1)
(p/MONITOR_SAMPLES_PATH).write_text('{"status":"review_required"}\\n')
publish_monitor_state(p,_binding(p,p/"run_manifest.json"),sample_count=1,status="review_required")
time.sleep(20)
''', run_dir),
            supervisor_log=run_dir / "reports/supervisor.log",
            monitor_log=run_dir / "reports/monitor.log",
        )
        owner.wait_support_ready(3)
        retained = json.loads((run_dir / module.SESSION_PATH).read_text())
        assert retained["phase"] == "observing"
        assert retained["control_authority"] is False
        assert retained["readiness"]["monitor"]["status"] == "review_required"
        for role, receipt in retained["readiness"].items():
            assert receipt["pid"] == owner.processes[role].pid
            assert receipt["observed_monotonic_ns"] >= owner.launched_ns[role]
        with pytest.raises(RuntimeError, match="session monitor requires review"):
            owner.wait_for_terminal(1)
        with pytest.raises(RuntimeError, match="live capture"):
            owner.close_after_capture_closed()
        assert capture.poll() is None
    finally:
        owner.close_simulated()
    assert all(process.poll() is not None for process in owner.processes.values())


def test_expected_pre_setup_monitor_state_does_not_mask_supervisor_terminal(tmp_path):
    run_dir = _run_dir(tmp_path)
    owner = module.AdaptiveHybridSession(
        run_dir=run_dir, device="/dev/ttyACM0", physical=True
    )

    class Process:
        pid = os.getpid()

        def poll(self):
            return None

    for role in ("capture", "supervisor", "monitor"):
        owner.processes[role] = Process()
        owner.launched_ns[role] = time.monotonic_ns()
    module.publish_monitor_state(
        run_dir,
        module._binding(run_dir, run_dir / "run_manifest.json"),
        sample_count=1,
        status="awaiting_expected_evidence",
    )
    terminal = {"result": "healthy_stop", "reason": "fixture"}
    (run_dir / "reports/adaptive_hybrid_supervisor_state.json").write_text(
        json.dumps({"terminal": terminal})
    )

    assert owner.wait_for_terminal(1) == terminal


@pytest.mark.parametrize("mutation", ["pid", "manifest", "before_launch", "future", "authority"])
def test_stale_or_contradictory_worker_receipt_cannot_establish_readiness(tmp_path, mutation):
    run_dir = _run_dir(tmp_path)
    owner = module.AdaptiveHybridSession(run_dir=run_dir, device="/dev/ttyACM0", physical=True)
    class Process:
        pid = os.getpid()
        def poll(self): return None
    owner.processes["supervisor"] = Process()
    owner.launched_ns["supervisor"] = time.monotonic_ns()
    module.publish_supervisor_ready(run_dir, run_dir / "run_manifest.json", census_process_nonce=4)
    path = run_dir / module.SUPERVISOR_READY_PATH
    value = json.loads(path.read_text())
    if mutation == "pid": value["pid"] += 1
    elif mutation == "manifest": value["manifest_bytes_sha256"] = "0" * 64
    elif mutation == "before_launch": value["observed_monotonic_ns"] = owner.launched_ns["supervisor"] - 1
    elif mutation == "future": value["observed_monotonic_ns"] = time.monotonic_ns() + 10**10
    else: value["control_authority"] = True
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="launched process"):
        owner._receipt("supervisor", module.SUPERVISOR_READY_PATH)


@pytest.mark.parametrize("physical,device", [(True,"/dev/ttys999"), (False,"/dev/ttyACM0")])
def test_simulated_cleanup_cannot_kill_a_physical_or_nonpty_owner(tmp_path, physical, device):
    owner = module.AdaptiveHybridSession(run_dir=_run_dir(tmp_path), device=device, physical=physical)
    class Process:
        pid = 99
        def poll(self): return None
        def terminate(self): raise AssertionError("capture must remain alive")
    owner.processes["capture"] = Process()
    with pytest.raises(RuntimeError, match="physical or non-PTY"):
        owner.close_simulated()


def test_live_physical_owner_failure_does_not_trigger_generic_cleanup(tmp_path):
    owner = module.AdaptiveHybridSession(run_dir=_run_dir(tmp_path), device="/dev/ttyACM0", physical=True)
    class Process:
        pid = 99
        def poll(self): return None
        def terminate(self): raise AssertionError("host finding has no teardown authority")
    owner.processes["capture"] = Process()
    with pytest.raises(RuntimeError, match="live capture"):
        owner.close_after_capture_closed()


def test_physical_runner_retains_partial_support_launch_then_registers_closure_diagnostic(monkeypatch, tmp_path):
    """Real runner/control flow and session processes; hardware entry is doubled."""
    from types import SimpleNamespace
    from host.otis_tools import adaptive_hybrid_run as runner
    from host.otis_tools.adaptive_hybrid_contract import ADAPTIVE_HYBRID_PROGRAMME

    source = tmp_path / "source.json"
    source.write_text('{}\n')
    activation = {
        "activation_sha256": "a" * 64,
        "bundle": {"path": str(source), "bundle_sha256": "b" * 64},
        "proposal": {"path": str(source)},
        "firmware": {"source_revision": "c" * 40, "build_identity": "d" * 64},
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
    }
    activation_path = tmp_path / "activation.json"
    activation_path.write_text(json.dumps(activation))
    monkeypatch.setattr(runner, "programme_from_mapping", lambda _: ADAPTIVE_HYBRID_PROGRAMME)
    monkeypatch.setattr(runner, "validate_activation_for_physical_entry", lambda _: (
        activation, {"firmware": activation["firmware"]}, {}, {}))
    monkeypatch.setattr(runner, "_activation_bench_attempt", lambda _: SimpleNamespace())
    monkeypatch.setattr(runner, "_reserve_activation_attempt", lambda **_: source)
    monkeypatch.setattr(runner, "_fresh_auto_detect_device", lambda: "/dev/ttyACM0")
    monkeypatch.setattr(runner, "_serial_owner_pids", lambda _: set())
    monkeypatch.setattr(runner, "read_board_identity", lambda *_, **__: {"serial_number": "fixture"})
    monkeypatch.setattr(runner, "_upload_exact_firmware", lambda **_: (
        "/dev/ttyACM0", {"serial_number": "fixture"}, {}))

    def manifest(**kwargs):
        kwargs["output_path"].write_text('{}\n')
        return {}
    monkeypatch.setattr(runner, "create_run_manifest", manifest)
    monkeypatch.setattr(runner, "load_manifest", lambda _: SimpleNamespace(data={}))
    child = [sys.executable, "-c", "import time; time.sleep(20)"]
    monkeypatch.setattr(runner, "_capture_command", lambda **_: child)
    monkeypatch.setattr(runner, "_supervisor_command", lambda **_: child)
    sessions = []

    class PartialSupportSession(module.AdaptiveHybridSession):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            sessions.append(self)
        def wait_capture_ready(self, timeout_s):
            assert self.processes["capture"].poll() is None
        def _launch(self, role, command, log_path):
            if role == "monitor":
                raise OSError("injected monitor launch failure")
            return super()._launch(role, command, log_path)
        def close_after_capture_closed(self):
            super().close_after_capture_closed()
            raise OSError("injected closure publication failure")
    monkeypatch.setattr(runner, "AdaptiveHybridSession", PartialSupportSession)
    original_hold = runner._retain_live_capture_for_host_review
    handoff = []

    def hold(**kwargs):
        # The supervisor exists even though launch_support never returned its tuple.
        assert kwargs["supervisor"] is sessions[0].processes["supervisor"]
        assert kwargs["supervisor"].poll() is None
        assert kwargs["capture"].poll() is None
        handoff.append(kwargs["supervisor"].pid)
        # Simulated explicit operator closure; production hold never performs it.
        kwargs["capture"].terminate()
        kwargs["capture"].wait(timeout=3)
        return original_hold(**kwargs)
    monkeypatch.setattr(runner, "_retain_live_capture_for_host_review", hold)
    registrations = []

    def register(**kwargs):
        assert all(process.poll() is not None for process in sessions[0].processes.values())
        assert str(kwargs["error"]) == "injected monitor launch failure"
        assert (kwargs["run_dir"] / runner.COMPLETE).is_file()
        registrations.append(kwargs)
        return {"content_sha256": "e" * 64}
    monkeypatch.setattr(runner, "_register_unfinalized", register)
    run_dir = tmp_path / "physical-flow-fixture"
    result = runner.run_adaptive_hybrid_qualification(
        activation_path=activation_path, run_dir=run_dir,
        evidence_index_path=tmp_path / "index.json",
    )
    assert result["status"] == "pending_review"
    assert handoff and len(registrations) == 1
    assert result["evidence_content_sha256"] == "e" * 64
    from host.otis_tools.evidence_finalization import journal_path_for
    journal = json.loads(journal_path_for(run_dir).read_text())
    assert journal["primary_failure"]["error"] == "injected monitor launch failure"
    assert journal["secondary_failures"][-1]["error"] == "injected closure publication failure"


def test_live_but_stalled_monitor_cannot_satisfy_session_observation(tmp_path, monkeypatch):
    owner = module.AdaptiveHybridSession(
        run_dir=_run_dir(tmp_path), device="/dev/unused", physical=True)
    receipt = {"observed_monotonic_ns": 1, "sample_count": 1, "status": "running"}
    monkeypatch.setattr(owner, "_receipt", lambda *_: receipt)
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 15_000_000_002)
    with pytest.raises(RuntimeError, match="stopped publishing"):
        owner.check_monitor()
