"""Real detached host path over a PTY; no physical firmware or DAC claim."""
from __future__ import annotations

import hashlib
import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from host.otis_tools import unattended
from host.otis_tools.firmware_host_contract import ACTIVE_STATUS_KEYS
from host.otis_tools.instrument_recorder import read_recorder_status

ROOT = Path(__file__).resolve().parents[1]
BUILD = "a" * 64 + ":" + "b" * 64
POLICY = "c" * 64
SESSION = 18446744073709551601


def plan_document(tmp_path):
    return {"schema_version": 1, "device": "/dev/fixture", "run_dir": str(tmp_path / "run"),
            "shared_output_dir": str(tmp_path / "shared"), "expected_session": SESSION,
            "expected_build_identity": BUILD, "expected_policy_sha256": POLICY,
            "observation_kind": "open_ended", "auto_dwell_s": 0, "poll_interval_s": 1,
            "startup_deadline_s": 30, "command_deadline_s": 5, "keep_awake": False,
            "minimum_free_bytes": 0}


def test_finite_and_indefinite_deadline_contracts_are_distinct(tmp_path):
    document = plan_document(tmp_path)
    assert unattended.Plan.load(json.dumps(document).encode()).auto_dwell_s == 0
    document["auto_dwell_s"] = 10
    with pytest.raises(ValueError, match="requires.*zero"):
        unattended.Plan.load(json.dumps(document).encode())
    document.pop("observation_kind")
    assert unattended.Plan.load(json.dumps(document).encode()).observation_kind == "finite"
    document["auto_dwell_s"] = 0
    with pytest.raises(ValueError):
        unattended.Plan.load(json.dumps(document).encode())


@pytest.mark.parametrize("marker", ["{", "[]", '{"operation":"end_recording","plan_sha256":"wrong"}'])
def test_invalid_cutoff_retains_supervision_and_never_requests_closure(tmp_path, monkeypatch, marker):
    document = plan_document(tmp_path)
    run_dir = Path(document["run_dir"])
    run_dir.mkdir()
    data = json.dumps(document).encode()
    (run_dir / unattended.PLAN).write_bytes(data)
    (run_dir / unattended.END_RECORDING).write_text(marker)
    owner = unattended.Coordinator(unattended.Plan.load(data), hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(owner, "observe", lambda: None)
    monkeypatch.setattr(owner, "close_and_finalize", lambda *a, **k: pytest.fail("unverified cutoff"))
    try:
        assert not owner.operator_recording_end()
        assert not owner.recording_end_attempted
        assert not owner.hold_submitted
        assert owner.review_reason == "operator_recording_end_identity_mismatch"
        assert not owner.operator_recording_end()  # Keep the rejected request for review.
        with pytest.raises(ValueError):
            unattended.end_recording(run_dir)
        assert (run_dir / unattended.END_RECORDING).read_text() == marker
    finally:
        owner.journal.close()


class Instrument:
    def __init__(self, master, mode):
        self.master, self.mode = master, mode
        self.sequence = 0
        self.generation = self.sts = self.sample = self.record_sequence = 0
        self.end = 0
        self.commands = []
        self.error = None
        self.stale = False
        self.write_pending = False
        self.send_lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def send(self, data):
        with self.send_lock:
            view = memoryview(data)
            deadline = time.monotonic() + 2
            while view and not self.stop.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError("fixture output obstruction")
                if select.select([], [self.master], [], 0.05)[1]:
                    try:
                        count = os.write(self.master, view)
                    except OSError as exc:
                        if exc.errno == 5:  # Discovery/acquisition attachment gap.
                            time.sleep(0.01)
                            continue
                        raise
                    view = view[count:]

    def snapshot(self):
        self.generation += 1
        fields = dict.fromkeys(ACTIVE_STATUS_KEYS, "0")
        fields.update(session_id=str(SESSION), capture_session="1", mode=self.mode,
                      requested_mode=self.mode, state=self.mode, reason="fixture",
                      fault="none", applied_code="43085", confirmed_applied_code_known="true",
                      dac_epoch="1", command_sequence=str(self.sequence),
                      command_completed=str(self.sequence), build_identity=BUILD,
                      active_policy_sha256=POLICY, write_sequence="1",
                      write_state="2" if self.write_pending else "0",
                      instrument_ticks=str(time.monotonic_ns() // 1000),
                      instrument_ticks_domain="rp2040_timer_us64", operating_end_ticks=str(self.end))
        pairs = [("snapshot_generation_begin", str(self.generation)),
                 ("snapshot_contract", "OTIS_INSTRUMENT_STATUS_V2")]
        pairs.extend((key, fields[key]) for key in ACTIVE_STATUS_KEYS)
        pairs.append(("snapshot_generation_complete", str(self.generation)))
        rows = []
        for key, value in pairs:
            self.sts += 1
            rows.append(f"STS,1,{self.sts},1000000,rp2040_timer_us64,adaptive_hybrid,{key},{value},INFO,0\n")
        self.send("".join(rows).encode())

    def command(self, line):
        wire = line.decode().strip()
        self.commands.append(wire)
        prefix, verb, session, sequence, mode, code, dwell = wire.split()
        assert (prefix, verb, int(session), int(code), int(dwell)) == ("ACTIVE", "MODE", SESSION, 0, 0)
        assert int(sequence) == self.sequence + 1
        self.sequence = int(sequence)
        self.mode = "AUTO_DISCIPLINE" if int(mode) == 0 else "OBSERVE_HOLD"
        self.end = 0
        self.record_sequence += 1
        self.send(f"ICM,2,{self.record_sequence},{SESSION},{sequence},{mode},0,0,ACCEPTED,{sequence},{time.monotonic_ns() // 1000},rp2040_timer_us64\n".encode())
        self.snapshot()

    def loop(self):
        os.set_blocking(self.master, False)
        buffer = bytearray()
        next_sample = 0
        try:
            while not self.stop.is_set():
                if not self.stale and time.monotonic() >= next_sample:
                    self.sample += 1
                    self.send(b"REF,synthetic\nSNP,synthetic\nCNT,synthetic\n")
                    self.snapshot()
                    next_sample = time.monotonic() + 0.2
                if select.select([self.master], [], [], 0.02)[0]:
                    try:
                        data = os.read(self.master, 4096)
                    except BlockingIOError:
                        continue
                    except OSError as exc:
                        if exc.errno == 5:
                            time.sleep(0.01)
                            continue
                        raise
                    buffer.extend(data)
                    while b"\n" in buffer:
                        end = buffer.index(b"\n") + 1
                        line = bytes(buffer[:end])
                        del buffer[:end]
                        self.command(line)
        except OSError as exc:
            # Recorder's explicit closure makes the PTY master report EIO.
            if exc.errno != 5:
                self.error = repr(exc)
        except Exception as exc:  # noqa: BLE001 - surface fixture thread assertions
            self.error = repr(exc)


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise TimeoutError("fixture condition did not become true")


@pytest.mark.parametrize("scenario", ["held", "boot_auto", "review_monitor_loss", "stale_pending", "entry_tool"])
def test_detached_open_ended_path_and_recording_only_endpoint(tmp_path, scenario):
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    document = plan_document(tmp_path)
    document.update(device=device, keep_awake=sys.platform == "darwin")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(document))
    run_dir = Path(document["run_dir"])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([
        str(ROOT / "tests/fixtures/pty_serial"), str(ROOT)]))
    fixture = Instrument(master, "OBSERVE_HOLD" if scenario in {"held", "entry_tool"} else "AUTO_DISCIPLINE")
    launch_args = [sys.executable, "-m", "host.otis_tools.unattended", "start", "--plan", str(plan_path)]
    if scenario == "entry_tool":
        launch_args = [sys.executable, str(ROOT / "tools/start_open_ended_observation.py"),
                       "--plan-template", str(plan_path), "--device", device,
                       "--run-root", str(tmp_path / "runs"),
                       "--shared-output-dir", str(tmp_path / "shared")]
    launcher = subprocess.Popen(launch_args, cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    coordinator_pid = None
    try:
        wait_until(lambda: list(tmp_path.rglob("recorder_state.json")))
        fixture.thread.start()
        out, err = launcher.communicate(timeout=60)
        assert launcher.returncode == 0, (out, err)
        launched = json.loads(out)
        run_dir = Path(launched["run_dir"])
        assert launched["state"]["phase"] == "running"
        coordinator_pid = launched["coordinator_pid"]
        assert os.getsid(coordinator_pid) != os.getsid(0)
        assert launched["state"]["operating_end_ticks"] == 0
        if scenario in {"held", "entry_tool"}:
            assert fixture.commands == [f"ACTIVE MODE {SESSION} 1 0 0 0"]
        else:
            assert fixture.commands == []
        initial_count = read_recorder_status(run_dir)["observed_record_counts"]["REF"]
        wait_until(lambda: read_recorder_status(run_dir)["observed_record_counts"]["REF"] > initial_count + 3)
        if scenario == "review_monitor_loss":
            os.kill(launched["state"]["monitor_pid"], signal.SIGTERM)
            fixture.end = 123  # Unknown contradiction must enter one review HOLD.
            wait_until(lambda: fixture.mode == "OBSERVE_HOLD")
            wait_until(lambda: (run_dir / "monitor_terminal.json").exists())
            count = read_recorder_status(run_dir)["observed_record_counts"]["REF"]
            wait_until(lambda: read_recorder_status(run_dir)["observed_record_counts"]["REF"] > count + 3)
            assert fixture.commands == [f"ACTIVE MODE {SESSION} 1 1 0 0"]
        elif scenario == "stale_pending":
            fixture.write_pending = True
            wait_until(lambda: read_recorder_status(run_dir)["instrument"]["fields"]["write_state"] == "2")
            fixture.stale = True
            wait_until(lambda: not read_recorder_status(run_dir)["instrument_fresh"], timeout=15)
            assert fixture.commands == []
        cutoff = unattended.end_recording(run_dir)
        assert cutoff["instrument_mode_changed"] is False
        final = wait_until(lambda: (state if (state := unattended.status(run_dir))["phase"] in
                                   {"complete", "complete_with_review", "package_failed"} else None))
        assert final["phase"] != "package_failed", final
        assert fixture.error is None
        assert fixture.mode == ("OBSERVE_HOLD" if scenario == "review_monitor_loss" else "AUTO_DISCIPLINE")
        if scenario != "review_monitor_loss":
            assert len(fixture.commands) == (1 if scenario in {"held", "entry_tool"} else 0)
        package = final["package"]
        assert Path(package["zip"]).is_file()
        assert hashlib.sha256(Path(package["zip"]).read_bytes()).hexdigest() == package["sha256"]
        summary = json.loads(Path(package["summary"]).read_text())
        assert summary["endpoint_contract"] == "operator_recording_cutoff_instrument_continues"
        assert not summary["firmware_timed_hold_endpoint_confirmed"]
        assert "firmware_timed_hold_endpoint_unconfirmed" not in summary["review_findings"]
        assert summary["scientific_qualification"] == "not_established_by_automatic_package"
        if scenario == "review_monitor_loss":
            assert "review_required" in summary["review_findings"]
            assert "monitor_failed_or_missing_terminal_result" in summary["review_findings"]
        replay = unattended.finalize(run_dir)
        assert replay["status"] == "already_packaged"
        assert replay["sha256"] == package["sha256"]
        if scenario == "boot_auto":
            raw_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in run_dir.glob("serial-*.raw")}
            (run_dir / unattended.END_RECORDING).write_text('{"plan_sha256":"wrong"}')
            rejected_endpoint = unattended.finalize(run_dir)
            reviewed = json.loads(Path(rejected_endpoint["summary"]).read_text())
            assert "operator_recording_endpoint_unconfirmed" in reviewed["review_findings"]
            assert raw_hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in run_dir.glob("serial-*.raw")}
            assert fixture.commands == []
    finally:
        fixture.stop.set()
        if fixture.thread.ident:
            fixture.thread.join(2)
        if launcher.poll() is None:
            launcher.terminate()
            launcher.wait(timeout=3)
        if coordinator_pid is not None:
            try:
                os.killpg(coordinator_pid, signal.SIGTERM)  # Fixture-only cleanup.
            except ProcessLookupError:
                pass
        os.close(master)
