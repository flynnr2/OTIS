"""Detached local supervision of finite or open-ended instrument observations.

Firmware remains the sole operating owner. This process owns no serial port: it
starts exactly one recorder, observes its atomic state, and sends at most one
preauthorized review HOLD through that recorder. It never resets, flashes,
aborts, retries AUTO, or resumes after a review hold.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .instrument_recorder import (
    UINT64_MAX,
    _atomic_json,
    read_recorder_status,
    request,
    verify_recording,
)

PLAN = "unattended_plan.json"
STATE = "unattended_state.json"
EVENTS = "unattended-events.jsonl"
MIN_CODE = 0xA800
MAX_CODE = 0xAB00
DEFAULT_MINIMUM_FREE = 5 * 1024 * 1024 * 1024
END_RECORDING = "operator_end_recording.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _recording_end_request(run_dir: Path, plan_sha256: str) -> dict:
    value = json.loads((run_dir / END_RECORDING).read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("operation") != "end_recording" or
            value.get("plan_sha256") != plan_sha256):
        raise ValueError("operator recording endpoint does not match the frozen plan")
    return value


def _int_field(document: dict, key: str, low: int, high: int, default: int | None = None) -> int:
    value = document.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} must be an integer in {low}..{high}")
    return value


@dataclass(frozen=True)
class Plan:
    device: str
    run_dir: Path
    shared_output_dir: Path
    expected_session: int
    expected_build_identity: str
    expected_policy_sha256: str
    auto_dwell_s: int
    poll_interval_s: int
    startup_deadline_s: int
    command_deadline_s: int
    endpoint_grace_s: int
    minimum_free_bytes: int
    keep_awake: bool
    observation_kind: str = "finite"

    @classmethod
    def load(cls, data: bytes) -> Plan:
        document = json.loads(data)
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ValueError("unattended plan schema_version must be 1")
        device = document.get("device")
        run_dir = document.get("run_dir")
        shared_dir = document.get("shared_output_dir")
        build = document.get("expected_build_identity")
        policy = document.get("expected_policy_sha256")
        if not isinstance(device, str) or not device.startswith("/dev/"):
            raise ValueError("device must be an absolute /dev path")
        if not isinstance(run_dir, str) or not Path(run_dir).is_absolute():
            raise ValueError("run_dir must be absolute")
        if not isinstance(shared_dir, str) or not Path(shared_dir).is_absolute():
            raise ValueError("shared_output_dir must be absolute")
        if not isinstance(build, str) or len(build.split(":")) != 2 or any(
            len(piece) != 64 or any(ch not in "0123456789abcdef" for ch in piece)
            for piece in build.split(":")
        ):
            raise ValueError("expected_build_identity must be source SHA-256:configuration SHA-256")
        if not isinstance(policy, str) or len(policy) != 64 or any(
            ch not in "0123456789abcdef" for ch in policy
        ):
            raise ValueError("expected_policy_sha256 must be a lowercase SHA-256")
        keep_awake = document.get("keep_awake", sys.platform == "darwin")
        if type(keep_awake) is not bool:
            raise ValueError("keep_awake must be Boolean")
        kind = document.get("observation_kind", "finite")
        if kind not in {"finite", "open_ended"}:
            raise ValueError("observation_kind must be finite or open_ended")
        dwell = _int_field(document, "auto_dwell_s", 0 if kind == "open_ended" else 1,
                           604800, 0 if kind == "open_ended" else 259200)
        if kind == "open_ended" and dwell != 0:
            raise ValueError("open_ended observation requires auto_dwell_s zero")
        return cls(
            device=device,
            run_dir=Path(run_dir).resolve(),
            shared_output_dir=Path(shared_dir).resolve(),
            expected_session=_int_field(document, "expected_session", 1, UINT64_MAX),
            expected_build_identity=build,
            expected_policy_sha256=policy,
            auto_dwell_s=dwell,
            poll_interval_s=_int_field(document, "poll_interval_s", 1, 60, 5),
            startup_deadline_s=_int_field(document, "startup_deadline_s", 30, 300, 30),
            command_deadline_s=_int_field(document, "command_deadline_s", 5, 300, 60),
            endpoint_grace_s=_int_field(document, "endpoint_grace_s", 5, 600, 60),
            minimum_free_bytes=_int_field(
                document, "minimum_free_bytes", 0, 1 << 50, DEFAULT_MINIMUM_FREE
            ),
            keep_awake=keep_awake,
            observation_kind=kind,
        )


class Journal:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / EVENTS
        self.handle = self.path.open("a", encoding="utf-8", buffering=1)

    def emit(self, event: str, **fields: object) -> None:
        self.handle.write(json.dumps(
            {"event": event, "observed_utc": _utc(), **fields},
            sort_keys=True, allow_nan=False,
        ) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def close(self) -> None:
        self.handle.close()


def _publish(run_dir: Path, **fields: object) -> None:
    _atomic_json(run_dir / STATE, {"schema_version": 1, "observed_utc": _utc(),
                                   "coordinator_pid": os.getpid(), **fields})


def _free_space(plan: Plan) -> None:
    for directory in (plan.run_dir.parent, plan.shared_output_dir):
        directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(directory).free < plan.minimum_free_bytes:
            raise OSError(f"less than {plan.minimum_free_bytes} bytes free at {directory}")


def start(plan_path: Path) -> dict:
    data = plan_path.read_bytes()
    plan = Plan.load(data)
    if plan.run_dir.exists():
        raise FileExistsError(f"unattended run directory already exists: {plan.run_dir}")
    _free_space(plan)
    plan.run_dir.mkdir(parents=True)
    frozen = plan.run_dir / PLAN
    with frozen.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    plan_sha = hashlib.sha256(data).hexdigest()
    _publish(plan.run_dir, phase="launching", plan_sha256=plan_sha)
    stdout = (plan.run_dir / "coordinator.stdout.log").open("wb")
    stderr = (plan.run_dir / "coordinator.stderr.log").open("wb")
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "host.otis_tools.unattended", "run", str(plan.run_dir)],
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            start_new_session=True, close_fds=True,
        )
    finally:
        stdout.close()
        stderr.close()
    deadline = time.monotonic() + plan.startup_deadline_s + plan.command_deadline_s + 5
    while time.monotonic() < deadline:
        if (plan.run_dir / STATE).is_file():
            state = json.loads((plan.run_dir / STATE).read_text(encoding="utf-8"))
            if state.get("phase") in {"running", "review_required", "failed_startup"}:
                return {"coordinator_pid": child.pid, "run_dir": str(plan.run_dir),
                        "plan_sha256": plan_sha, "state": state}
        if child.poll() is not None:
            break
        time.sleep(0.2)
    return {"error": "detached coordinator did not establish a running state",
            "coordinator_pid": child.pid, "run_dir": str(plan.run_dir),
            "plan_sha256": plan_sha}


class Coordinator:

    def __init__(self, plan: Plan, plan_sha256: str) -> None:
        self.plan = plan
        self.plan_sha256 = plan_sha256
        self.journal = Journal(plan.run_dir)
        self.recorder: subprocess.Popen | None = None
        self.monitor: subprocess.Popen | None = None
        self.caffeinate: subprocess.Popen | None = None
        self.auto_sequence: int | None = None
        self.end_ticks: int | None = None
        self.hold_submitted = False
        self.last_counts: dict[str, int] = {}
        self.capture_last_advance: dict[str, float] = {}
        self.capture_stale_reported = False
        self.last_write_sequence: int | None = None
        self.monitor_failure_reported = False
        self.stale_reported = False
        self.stale_since: float | None = None
        self.review_reason: str | None = None
        self.review_hold_pending = False
        self.coverage_escalations: list[str] = []
        self.recording_end_attempted = False

    def capture_progress(self, state: dict | None) -> bool:
        counts = (state or {}).get("observed_record_counts") or {}
        now = time.monotonic()
        for tag in ("REF", "SNP", "CNT"):
            count = counts.get(tag)
            previous = self.last_counts.get(tag)
            if type(count) is int:
                if previous is not None and count > previous:
                    self.capture_last_advance[tag] = now
                elif previous is not None and count < previous:
                    self.capture_last_advance.pop(tag, None)
                self.last_counts[tag] = count
        fresh = bool(
            state and state.get("writer_fresh") and
            len(self.capture_last_advance) == 3 and
            all(now - self.capture_last_advance[tag] <= max(5, 3 * self.plan.poll_interval_s)
                for tag in ("REF", "SNP", "CNT"))
        )
        if fresh and self.capture_stale_reported:
            self.capture_stale_reported = False
            self.journal.emit("host_observed_capture_progress_restored", counts=counts)
        elif not fresh and not self.capture_stale_reported and self.capture_last_advance:
            self.capture_stale_reported = True
            self.journal.emit("host_observed_capture_progress_stale", counts=counts)
        return fresh

    def publish(self, phase: str, **extra: object) -> None:
        _publish(
            self.plan.run_dir, phase=phase, plan_sha256=self.plan_sha256,
            recorder_pid=self.recorder.pid if self.recorder else None,
            monitor_pid=self.monitor.pid if self.monitor else None,
            expected_session=self.plan.expected_session,
            auto_sequence=self.auto_sequence, operating_end_ticks=self.end_ticks,
            hold_submitted=self.hold_submitted, review_reason=self.review_reason,
            coverage_escalations=self.coverage_escalations,
            observation_kind=self.plan.observation_kind,
            **extra,
        )

    def note_monitor_terminal(self) -> None:
        """Retain an independently observed child exit, including failed delivery."""
        if self.monitor is None or self.monitor.poll() is None:
            return
        marker = self.plan.run_dir / "monitor_terminal.json"
        if not marker.exists():
            _atomic_json(marker, {"schema_version": 1, "pid": self.monitor.pid,
                                  "exit_code": self.monitor.returncode,
                                  "observed_utc": _utc()})
            self.journal.emit("monitor_terminal_observed", pid=self.monitor.pid,
                              exit_code=self.monitor.returncode)

    def start_children(self) -> None:
        recorder_out = (self.plan.run_dir / "recorder.stdout.json").open("wb")
        recorder_err = (self.plan.run_dir / "recorder.stderr.log").open("wb")
        try:
            self.recorder = subprocess.Popen(
                [sys.executable, "-m", "host.otis_tools", "record",
                 "--device", self.plan.device, "--run-dir", str(self.plan.run_dir)],
                stdin=subprocess.DEVNULL, stdout=recorder_out, stderr=recorder_err,
                close_fds=True,
            )
        finally:
            recorder_out.close()
            recorder_err.close()
        monitor_out = (self.plan.run_dir / "monitor.stdout.json").open("wb")
        monitor_err = (self.plan.run_dir / "monitor.stderr.log").open("wb")
        try:
            self.monitor = subprocess.Popen(
                [sys.executable, "-m", "host.otis_tools", "monitor",
                 str(self.plan.run_dir), "--poll-s", str(self.plan.poll_interval_s)],
                stdin=subprocess.DEVNULL, stdout=monitor_out, stderr=monitor_err,
                close_fds=True,
            )
        finally:
            monitor_out.close()
            monitor_err.close()
        if self.plan.keep_awake:
            binary = shutil.which("caffeinate")
            if binary is None or sys.platform != "darwin":
                raise RuntimeError("caffeinate -i -w is unavailable on this host")
            self.caffeinate = subprocess.Popen(
                [binary, "-i", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True,
            )
        self.journal.emit("children_started", recorder_pid=self.recorder.pid,
                          monitor_pid=self.monitor.pid,
                          caffeinate_pid=self.caffeinate.pid if self.caffeinate else None)
        self.publish("attaching")

    def observe(self) -> dict | None:
        try:
            return read_recorder_status(self.plan.run_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _identity_valid(self, state: dict) -> bool:
        instrument = state.get("instrument") or {}
        return bool(
            state.get("instrument_fresh") and
            instrument.get("session") == self.plan.expected_session and
            instrument.get("build_identity") == self.plan.expected_build_identity and
            instrument.get("policy_identity") == self.plan.expected_policy_sha256
        )

    def initial_gate(self) -> dict | None:
        deadline = time.monotonic() + self.plan.startup_deadline_s
        while time.monotonic() < deadline:
            if self.recorder is not None and self.recorder.poll() is not None:
                self.review("recorder_exited_during_attach", None, try_hold=False)
                return None
            state = self.observe()
            if state is not None and state.get("writer_fresh"):
                counts = state.get("observed_record_counts") or {}
                capture_advanced = self.capture_progress(state)
                if state.get("instrument_fresh") and capture_advanced:
                    instrument = state["instrument"]
                    fields = instrument["fields"]
                    try:
                        code = instrument["applied_code"]
                        write_state = int(fields["write_state"])
                        write_sequence = int(fields["write_sequence"])
                        instrument_ticks = int(fields["instrument_ticks"])
                    except (KeyError, ValueError, TypeError):
                        code = -1
                        write_state = -1
                        write_sequence = -1
                        instrument_ticks = -1
                    if (
                        self._identity_valid(state) and
                        (instrument["mode"] == instrument["requested_mode"] == "OBSERVE_HOLD" or
                         (self.plan.observation_kind == "open_ended" and
                          instrument["mode"] == instrument["requested_mode"] == "AUTO_DISCIPLINE" and
                          fields["operating_end_ticks"] == "0" and
                          instrument["last_command_sequence"] == instrument["completed_command_sequence"])) and
                        instrument["applied_code_known"] and
                        MIN_CODE <= code <= MAX_CODE and
                        write_state == 0 and
                        0 <= write_sequence <= 0xFFFFFFFF and
                        0 <= instrument_ticks <= UINT64_MAX and
                        fields["fault"] == "none" and
                        state.get("pending_command") is None
                    ):
                        self.last_write_sequence = write_sequence
                        self.journal.emit(
                            "initial_gate_passed",
                            session=instrument["session"], applied_code=code,
                            dac_epoch=instrument["dac_epoch"],
                            write_sequence=self.last_write_sequence,
                            instrument_ticks=instrument_ticks,
                            build_identity=instrument["build_identity"],
                            policy_identity=instrument["policy_identity"],
                            mode=instrument["mode"],
                            record_counts={tag: counts[tag] for tag in ("REF", "SNP", "CNT")},
                        )
                        return state
                    self.review("initial_identity_mode_or_write_mismatch", state, try_hold=False)
                    return None
            time.sleep(self.plan.poll_interval_s)
        self.review("initial_fresh_capture_and_status_deadline", self.observe(), try_hold=False)
        return None

    def review(self, reason: str, state: dict | None, *, try_hold: bool) -> None:
        if self.review_reason is not None:
            return
        self.review_reason = reason
        instrument = (state or {}).get("instrument") or {}
        fields = instrument.get("fields") or {}
        self.journal.emit(
            "review_required", reason=reason, hold_authorized=try_hold,
            fresh=(state or {}).get("instrument_fresh"),
            session=instrument.get("session"), mode=instrument.get("mode"),
            requested_mode=instrument.get("requested_mode"),
            applied_code=instrument.get("applied_code"),
            dac_epoch=instrument.get("dac_epoch"),
            write_sequence=fields.get("write_sequence"),
            write_state=fields.get("write_state"),
            fault=fields.get("fault"),
            operating_end_ticks=fields.get("operating_end_ticks"),
            pending_command=(state or {}).get("pending_command"),
        )
        self.publish("review_required")
        if try_hold:
            if state is None or not state.get("instrument_fresh"):
                self.review_hold_pending = True
                self.journal.emit("hold_deferred_until_fresh_exact_status")
            else:
                self.submit_review_hold(state)

    def submit_review_hold(self, state: dict | None) -> None:
        if self.hold_submitted or state is None or not state.get("instrument_fresh"):
            self.journal.emit("hold_not_submitted", reason="fresh exact status unavailable")
            return
        instrument = state.get("instrument") or {}
        fields = instrument.get("fields") or {}
        if (
            instrument.get("build_identity") != self.plan.expected_build_identity or
            instrument.get("policy_identity") != self.plan.expected_policy_sha256 or
            fields.get("fault") != "none"
        ):
            self.journal.emit("hold_not_submitted", reason="build_policy_or_latched_fault")
            return
        if (instrument.get("mode") == "OBSERVE_HOLD" and
                instrument.get("requested_mode") == "OBSERVE_HOLD" and
                fields.get("write_state") == "0"):
            self.journal.emit("hold_already_effective", session=instrument.get("session"))
            return
        session = instrument.get("session")
        if type(session) is not int or session <= 0:
            self.journal.emit("hold_not_submitted", reason="session_identity_unavailable")
            return
        deadline = time.monotonic() + self.plan.command_deadline_s
        self.publish("review_required")
        while time.monotonic() < deadline:
            try:
                submission = request(
                    self.plan.run_dir,
                    {"operation": "mode", "expected_session": session,
                     "mode": 1, "code": 0, "dwell_s": 0},
                )
            except (OSError, ValueError) as exc:
                # The request may have reached the recorder; never replay it.
                self.hold_submitted = True
                self.journal.emit("hold_submission_unconfirmed",
                                  error=f"{type(exc).__name__}: {exc}")
                return
            if submission.get("error") != "fresh instrument status required before a mode request":
                self.hold_submitted = True
                break
            # This exact recorder admission error precedes its serial write.
            self.journal.emit("hold_local_admission_wait", reason=submission["error"])
            current = self.observe()
            if (current is not None and current.get("instrument_fresh") and
                    (current.get("instrument") or {}).get("session") != session):
                self.journal.emit("hold_not_submitted", reason="boot_session_changed")
                return
            time.sleep(min(self.plan.poll_interval_s, max(0, deadline - time.monotonic())))
        else:
            self.journal.emit("hold_not_submitted", reason="local_admission_deadline")
            return
        if submission.get("submission") != "written_unconfirmed":
            self.journal.emit("hold_submission_unconfirmed", response=submission)
            return
        sequence = submission["sequence"]
        self.journal.emit("hold_written_unconfirmed", session=session, sequence=sequence)
        while time.monotonic() < deadline:
            current = self.observe()
            if current is not None:
                receipt = current.get("last_command_receipt") or {}
                active = current.get("instrument") or {}
                values = active.get("fields") or {}
                if (receipt.get("session") == session and
                        receipt.get("sequence") == sequence and
                        receipt.get("result") == "REJECTED"):
                    self.journal.emit("hold_rejected", session=session, sequence=sequence)
                    return
                if (current.get("instrument_fresh") and active.get("session") == session and
                        receipt.get("session") == session and
                        receipt.get("sequence") == sequence and
                        receipt.get("mode") == 1 and receipt.get("code") == 0 and
                        receipt.get("dwell_s") == 0 and
                        receipt.get("result") == "ACCEPTED" and
                        active.get("last_command_sequence") == sequence and
                        active.get("completed_command_sequence") == sequence and
                        active.get("mode") == "OBSERVE_HOLD" and
                        active.get("requested_mode") == "OBSERVE_HOLD" and
                        values.get("write_state") == "0" and
                        type(receipt.get("ticks")) is int and
                        int(values.get("instrument_ticks", "-1")) >= receipt["ticks"]):
                    self.journal.emit("hold_effective", session=session, sequence=sequence,
                                      applied_code=active.get("applied_code"),
                                      dac_epoch=active.get("dac_epoch"))
                    return
            time.sleep(self.plan.poll_interval_s)
        self.journal.emit("hold_delivery_or_completion_unresolved",
                          session=session, sequence=sequence,
                          final_status=self.observe())

    def preload_auto(self) -> bool:
        deadline = time.monotonic() + self.plan.command_deadline_s
        try:
            submission = request(
                self.plan.run_dir,
                {"operation": "mode", "expected_session": self.plan.expected_session,
                 "mode": 0, "code": 0, "dwell_s": self.plan.auto_dwell_s},
            )
        except (OSError, ValueError) as exc:
            self.review("auto_submission_unconfirmed", self.observe(), try_hold=True)
            self.journal.emit("auto_submission_exception", error=f"{type(exc).__name__}: {exc}")
            return False
        if submission.get("submission") != "written_unconfirmed":
            self.review("auto_submission_not_written", self.observe(), try_hold=True)
            self.journal.emit("auto_submission_response", response=submission)
            return False
        self.auto_sequence = submission["sequence"]
        self.journal.emit("auto_written_unconfirmed",
                          session=self.plan.expected_session,
                          sequence=self.auto_sequence,
                          dwell_s=self.plan.auto_dwell_s)
        self.publish("awaiting_auto_completion")
        while time.monotonic() < deadline:
            state = self.observe()
            if state is not None:
                receipt = state.get("last_command_receipt") or {}
                instrument = state.get("instrument") or {}
                fields = instrument.get("fields") or {}
                if (receipt.get("session") == self.plan.expected_session and
                        receipt.get("sequence") == self.auto_sequence and
                        receipt.get("result") == "REJECTED"):
                    self.review("auto_rejected", state, try_hold=True)
                    return False
                if (state.get("instrument_fresh") and
                        instrument.get("session") == self.plan.expected_session and
                        receipt.get("session") == self.plan.expected_session and
                        receipt.get("sequence") == self.auto_sequence and
                        receipt.get("result") == "ACCEPTED" and
                        receipt.get("mode") == 0 and receipt.get("code") == 0 and
                        receipt.get("dwell_s") == self.plan.auto_dwell_s and
                        instrument.get("last_command_sequence") == self.auto_sequence and
                        instrument.get("completed_command_sequence") == self.auto_sequence and
                        instrument.get("mode") == "AUTO_DISCIPLINE" and
                        instrument.get("requested_mode") == "AUTO_DISCIPLINE"):
                    try:
                        end = int(fields["operating_end_ticks"])
                        now = int(fields["instrument_ticks"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    receipt_ticks = receipt.get("ticks")
                    expected_end = (0 if self.plan.observation_kind == "open_ended" else
                                    receipt_ticks + self.plan.auto_dwell_s * 1_000_000
                                    if type(receipt_ticks) is int else None)
                    if (type(receipt.get("ticks")) is not int or
                            now < receipt["ticks"] or
                            end != expected_end or
                            (self.plan.observation_kind == "finite" and not now < end)):
                        self.review("auto_effective_deadline_contradiction", state, try_hold=True)
                        return False
                    self.end_ticks = end
                    self.journal.emit("auto_effective", session=self.plan.expected_session,
                                      sequence=self.auto_sequence,
                                      operating_end_ticks=end,
                                      observed_instrument_ticks=now,
                                      applied_code=instrument["applied_code"],
                                      dac_epoch=instrument["dac_epoch"])
                    self.publish("running")
                    return True
            time.sleep(self.plan.poll_interval_s)
        self.review("auto_receipt_or_effective_status_deadline", self.observe(), try_hold=True)
        return False
    def run_observation(self) -> None:
        assert self.auto_sequence is not None and self.end_ticks is not None
        last_epoch = -1
        last_tick = -1
        next_summary = time.monotonic() + 3600
        disk_warning = False
        while True:
            if self.operator_recording_end():
                return
            if (self.plan.observation_kind == "open_ended" and not disk_warning and
                    shutil.disk_usage(self.plan.run_dir).free < self.plan.minimum_free_bytes):
                disk_warning = True
                self.coverage_escalations.append("recording_storage_reserve_low")
                self.journal.emit("coverage_escalation", reason="recording_storage_reserve_low")
                self.publish("running")
            if self.recorder is not None and self.recorder.poll() is not None:
                if (self.plan.run_dir / "recording_manifest.json").is_file():
                    self.journal.emit("recorder_closed_while_observing",
                                      exit_code=self.recorder.returncode)
                    if self.monitor is not None and self.monitor.poll() is None:
                        try:
                            self.monitor.wait(timeout=self.plan.poll_interval_s + 15)
                        except subprocess.TimeoutExpired:
                            self.journal.emit("monitor_close_deadline_after_recorder_exit")
                            self.publish("recording_closed_package_deferred")
                            return
                    self.note_monitor_terminal()
                    try:
                        result = finalize(self.plan.run_dir)
                    except (OSError, ValueError) as exc:
                        self.journal.emit("offline_finalize_failed",
                                          error=f"{type(exc).__name__}: {exc}")
                        self.publish("recording_closed_review_required")
                    else:
                        phase = ("complete" if self.plan.observation_kind == "open_ended" and
                                 self.review_reason is None and self.recorder.returncode == 0 else
                                 "recording_closed_review_required")
                        self.publish(phase, package=result)
                else:
                    self.review("recorder_lost_without_manifest", self.observe(), try_hold=False)
                    self.publish("recording_lost")
                return
            if (self.monitor is not None and self.monitor.poll() is not None and
                    not self.monitor_failure_reported):
                self.monitor_failure_reported = True
                self.note_monitor_terminal()
                self.journal.emit("monitor_exited_while_recording",
                                  exit_code=self.monitor.returncode)
                self.publish("running", monitor_delivery="failed_or_stopped")
            state = self.observe()
            capture_fresh = self.capture_progress(state)
            if state is None or not state.get("instrument_fresh"):
                if not self.stale_reported:
                    self.stale_reported = True
                    self.stale_since = time.monotonic()
                    self.journal.emit("status_unavailable_or_stale",
                                      writer_fresh=state.get("writer_fresh") if state else None)
                elif (self.stale_since is not None and
                      time.monotonic() - self.stale_since >=
                      max(30, 3 * self.plan.poll_interval_s)):
                    finding = "decision_status_prolonged_stale_coverage"
                    if finding not in self.coverage_escalations:
                        self.coverage_escalations.append(finding)
                        self.journal.emit("coverage_escalation", reason=finding,
                                          writer_fresh=state.get("writer_fresh") if state else None)
                        self.publish("running")
                time.sleep(self.plan.poll_interval_s)
                continue
            if self.stale_reported:
                self.stale_reported = False
                self.stale_since = None
                self.journal.emit("status_fresh_again")
            instrument = state["instrument"]
            fields = instrument["fields"]
            if (instrument["build_identity"] != self.plan.expected_build_identity or
                    instrument["policy_identity"] != self.plan.expected_policy_sha256):
                self.review("build_or_policy_identity_changed", state, try_hold=False)
                break
            if instrument["session"] != self.plan.expected_session:
                self.review("boot_session_changed", state, try_hold=True)
                break
            try:
                tick = int(fields["instrument_ticks"])
                end = int(fields["operating_end_ticks"])
                write_state = int(fields["write_state"])
                write_sequence = int(fields["write_sequence"])
                dac_epoch = instrument["dac_epoch"]
            except (KeyError, TypeError, ValueError):
                self.review("instrument_identity_field_malformed", state, try_hold=True)
                break
            if fields.get("instrument_ticks_domain") != "rp2040_timer_us64":
                self.review("instrument_clock_domain_changed", state, try_hold=False)
                break
            if (tick < last_tick or dac_epoch < last_epoch or
                    (self.last_write_sequence is not None and
                     write_sequence < self.last_write_sequence)):
                self.review("instrument_counter_or_epoch_regressed", state, try_hold=True)
                break
            last_tick, last_epoch = tick, dac_epoch
            self.last_write_sequence = write_sequence
            if (not instrument["applied_code_known"] or
                    not MIN_CODE <= instrument["applied_code"] <= MAX_CODE):
                self.review("applied_code_identity_unavailable_or_outside_envelope",
                            state, try_hold=True)
                break
            if fields["fault"] != "none":
                # A latched firmware fault rejects mode commands and already
                # inhibits correction. It does not imply a literal HOLD state.
                self.review("firmware_fault_inhibited", state, try_hold=False)
                break
            if instrument["last_command_sequence"] != self.auto_sequence:
                self.review("unexpected_command_sequence_during_unattended_run",
                            state, try_hold=True)
                break
            if self.plan.observation_kind == "open_ended":
                if (end != 0 or instrument["mode"] != "AUTO_DISCIPLINE" or
                        instrument["requested_mode"] != "AUTO_DISCIPLINE"):
                    self.review("indefinite_auto_mode_or_deadline_changed", state, try_hold=True)
                    break
            elif instrument["mode"] == "AUTO_DISCIPLINE":
                if end not in (0, self.end_ticks):
                    self.review("firmware_operating_deadline_changed", state, try_hold=True)
                    break
                if end == 0 and tick < self.end_ticks:
                    self.review("firmware_deadline_cleared_early", state, try_hold=True)
                    break
                if (end == 0 and
                        (instrument["requested_mode"] != "OBSERVE_HOLD" or
                         write_state not in (2, 3))):
                    self.review("firmware_deadline_cleared_without_released_write",
                                state, try_hold=True)
                    break
                if tick > self.end_ticks + self.plan.endpoint_grace_s * 1_000_000:
                    self.review("firmware_timed_hold_endpoint_overdue", state, try_hold=True)
                    break
            elif instrument["mode"] == "OBSERVE_HOLD":
                if tick < self.end_ticks:
                    self.review("hold_before_firmware_deadline", state, try_hold=False)
                    break
                if (instrument["requested_mode"] == "OBSERVE_HOLD" and
                        instrument["last_command_sequence"] == self.auto_sequence and
                        instrument["completed_command_sequence"] == self.auto_sequence and
                        state.get("pending_command") is None and
                        write_state == 0 and end == 0):
                    if not capture_fresh:
                        self.review_reason = "capture_evidence_stale_at_endpoint"
                        self.journal.emit("endpoint_capture_evidence_stale",
                                          observed_record_counts=state.get("observed_record_counts"))
                    self.journal.emit("firmware_timed_hold_endpoint",
                                      session=instrument["session"],
                                      command_completed=instrument["completed_command_sequence"],
                                      instrument_ticks=tick,
                                      expected_end_ticks=self.end_ticks,
                                      applied_code=instrument["applied_code"],
                                      dac_epoch=dac_epoch)
                    self.close_and_finalize(state)
                    return
                if tick > self.end_ticks + self.plan.endpoint_grace_s * 1_000_000:
                    self.review("hold_endpoint_write_or_command_unresolved", state, try_hold=True)
                    break
            else:
                self.review("unexpected_operating_mode", state, try_hold=True)
                break
            if time.monotonic() >= next_summary:
                self.journal.emit("periodic_observation",
                                  session=instrument["session"],
                                  mode=instrument["mode"],
                                  state=instrument["state"],
                                  instrument_ticks=tick,
                                  end_ticks=self.end_ticks,
                                  applied_code=instrument["applied_code"],
                                  dac_epoch=dac_epoch,
                                  write_state=write_state,
                                  write_sequence=write_sequence,
                                  fault=fields["fault"],
                                  reference_hold=fields["reference_hold"],
                                  metadata_hold=fields["metadata_hold"],
                                  observed_record_counts=state.get("observed_record_counts"),
                                  delivery_counters={
                                      key: fields.get(key) for key in (
                                          "observation_dropped", "evidence_dropped",
                                          "phase_preview_dropped", "telemetry_dropped",
                                          "critical_dropped", "direct_rows_dropped",
                                      )
                                  })
                next_summary = time.monotonic() + 3600
            time.sleep(self.plan.poll_interval_s)
        # A review hold is not a recording endpoint. Continue observing
        # without another command, restart, teardown, or automatic clearance.
        self.observe_review()

    def observe_review(self) -> None:
        next_summary = 0.0
        while True:
            if self.operator_recording_end():
                return
            if self.recorder is not None and self.recorder.poll() is not None:
                if (self.plan.run_dir / "recording_manifest.json").is_file():
                    if self.monitor is not None and self.monitor.poll() is None:
                        try:
                            self.monitor.wait(timeout=self.plan.poll_interval_s + 15)
                        except subprocess.TimeoutExpired:
                            self.journal.emit("monitor_close_deadline_during_review")
                            self.publish("review_recording_closed_package_deferred")
                            return
                    self.note_monitor_terminal()
                    try:
                        result = finalize(self.plan.run_dir)
                    except (OSError, ValueError) as exc:
                        self.journal.emit("review_offline_finalize_failed",
                                          error=f"{type(exc).__name__}: {exc}")
                    else:
                        self.journal.emit("review_recording_packaged", package=result)
                self.publish("review_recording_closed")
                return
            if (self.monitor is not None and self.monitor.poll() is not None and
                    not self.monitor_failure_reported):
                self.monitor_failure_reported = True
                self.note_monitor_terminal()
                self.journal.emit("monitor_exited_during_review",
                                  exit_code=self.monitor.returncode)
            state = self.observe()
            self.capture_progress(state)
            if self.review_hold_pending and state is not None and state.get("instrument_fresh"):
                self.review_hold_pending = False
                self.submit_review_hold(state)
            if time.monotonic() >= next_summary:
                self.journal.emit(
                    "review_observation",
                    reason=self.review_reason,
                    writer_fresh=state.get("writer_fresh") if state else None,
                    instrument_fresh=state.get("instrument_fresh") if state else None,
                    instrument=state.get("instrument") if state else None,
                    pending_command=state.get("pending_command") if state else None,
                    observed_record_counts=state.get("observed_record_counts") if state else None,
                )
                next_summary = time.monotonic() + 3600
            time.sleep(self.plan.poll_interval_s)

    def operator_recording_end(self) -> bool:
        if self.plan.observation_kind != "open_ended" or self.recording_end_attempted:
            return False
        marker = self.plan.run_dir / END_RECORDING
        if not marker.is_file():
            return False
        try:
            value = _recording_end_request(self.plan.run_dir, self.plan_sha256)
        except (OSError, ValueError):
            self.review("operator_recording_end_identity_mismatch", self.observe(), try_hold=False)
            return False
        self.journal.emit("operator_recording_end", request=value,
                          instrument_mode_changed=False)
        self.recording_end_attempted = True
        self.close_and_finalize(self.observe(), recording_only=True)
        return True

    def close_and_finalize(self, state: dict | None, *, recording_only: bool = False) -> None:
        instrument = (state or {}).get("instrument") or {}
        deadline = time.monotonic() + self.plan.command_deadline_s
        result: dict = {"error": "recording closure deadline"}
        while time.monotonic() < deadline:
            try:
                close_request = {"operation": "end_recording"} if recording_only else {
                    "operation": "close",
                    "expected_session": instrument["session"],
                    "expected_sequence": instrument["completed_command_sequence"],
                }
                result = request(self.plan.run_dir, close_request)
            except OSError as exc:
                # A lost socket reply is ambiguous; never assume closure or
                # resend until local state proves the recorder is still open.
                if self.recorder is not None and self.recorder.poll() is not None:
                    result = {"closure": "requested"}
                    break
                result = {"error": f"{type(exc).__name__}: {exc}"}
                break
            if result.get("closure") == "requested":
                break
            if result.get("error") != "fresh instrument status required before recording closure":
                break
            time.sleep(min(self.plan.poll_interval_s, max(0, deadline - time.monotonic())))
        if result.get("closure") != "requested":
            self.review("recorder_endpoint_close_rejected", self.observe(), try_hold=False)
            self.observe_review()
            return
        self.publish("closing")
        self.journal.emit("recording_close_requested", response=result)
        assert self.recorder is not None
        try:
            recorder_exit = self.recorder.wait(timeout=300)
        except subprocess.TimeoutExpired:
            self.review("recorder_close_deadline", self.observe(), try_hold=False)
            self.observe_review()
            return
        if recorder_exit != 0:
            self.review("recorder_close_error", self.observe(), try_hold=False)
        if self.monitor is not None:
            try:
                self.monitor.wait(timeout=self.plan.poll_interval_s + 15)
            except subprocess.TimeoutExpired:
                self.journal.emit("monitor_close_deadline",
                                  monitor_pid=self.monitor.pid)
                self.monitor_failure_reported = True
                self.publish("recording_closed_package_deferred")
                return
        self.note_monitor_terminal()
        try:
            package = finalize(self.plan.run_dir)
        except (OSError, ValueError) as exc:
            self.journal.emit("automatic_package_failed",
                              error=f"{type(exc).__name__}: {exc}")
            self.publish("package_failed")
            return
        self.journal.emit("automatic_package_complete", package=package)
        self.publish("complete" if self.review_reason is None else "complete_with_review",
                     package=package)

    def run(self) -> None:
        try:
            self.journal.emit("coordinator_started", plan_sha256=self.plan_sha256)
            self.start_children()
            initial = self.initial_gate()
            if initial is None:
                self.observe_review()
                return
            if (self.plan.observation_kind == "open_ended" and
                    initial["instrument"]["mode"] == "AUTO_DISCIPLINE"):
                self.auto_sequence = initial["instrument"]["completed_command_sequence"]
                self.end_ticks = 0
                self.journal.emit("existing_indefinite_auto_observed", instrument=initial["instrument"],
                                  prefix_history="unobserved_before_attachment")
                self.publish("running", auto_entry="existing_indefinite_auto_observed")
            elif not self.preload_auto():
                self.observe_review()
                return
            self.run_observation()
        except BaseException as exc:
            # Do not kill, reset, or restart either child on a coordinator
            # exception. If the recorder remains alive its evidence continues.
            self.journal.emit("coordinator_exception",
                              error=f"{type(exc).__name__}: {exc}")
            self.review_reason = self.review_reason or "coordinator_exception"
            self.publish("review_required")
            raise
        finally:
            self.journal.close()


def run_frozen(run_dir: Path) -> None:
    data = (run_dir / PLAN).read_bytes()
    plan = Plan.load(data)
    if plan.run_dir != run_dir.resolve():
        raise ValueError("frozen plan run_dir does not match coordinator directory")
    Coordinator(plan, hashlib.sha256(data).hexdigest()).run()


def _iter_record_lines(run_dir: Path, manifest: dict):
    pending = bytearray()
    for segment in manifest["segments"]:
        path = run_dir / segment["path"]
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                pending.extend(block)
                while True:
                    end = pending.find(b"\n")
                    if end < 0:
                        if len(pending) > 8192:
                            pending.clear()
                            yield None
                        break
                    line = bytes(pending[:end]).rstrip(b"\r")
                    del pending[:end + 1]
                    yield line
    if pending:
        yield None


def _analyze_raw(run_dir: Path, manifest: dict) -> dict:
    from .firmware_host_contract import RECORD_FIELDS, RECORD_TYPE_TO_CONTRACT

    counts: dict[str, int] = {}
    instrument_tags = {"ICM", "IWR", "IAP", "IDC", "IRS", "IST"}
    last_instrument_sequence: dict[int, int] = {}
    instrument_record_gaps = 0
    instrument_nonmonotonic = 0
    malformed_instrument_rows = 0
    instrument_domain_contradictions = 0
    oversized_or_partial_lines = 0
    source_sequence_fields = {
        "REF": "event_seq", "SNP": "snapshot_sequence", "CNT": "count_seq",
        "APS": "accepted_boundary_ordinal", "RPH": "observation_sequence",
        "PHE": "observation_sequence", "ENV": "env_seq",
    }
    # APS ordinals restart within each acceptance epoch. RPH/PHE observations
    # restart within each phase epoch, independently of acceptance changes.
    source_scope_fields = {
        "APS": ("capture_session", "acceptance_epoch"),
        "RPH": ("capture_session", "phase_epoch"),
        "PHE": ("capture_session", "phase_epoch"),
    }
    source_last_sequence: dict[str, int] = {}
    source_last_scope: dict[str, tuple[int, ...]] = {}
    source_seen_scopes: dict[str, set[tuple[int, ...]]] = {}
    source_max_epoch: dict[tuple[str, int], int] = {}
    source_coverage = {
        tag: {"gaps": 0, "nonmonotonic_or_restart": 0,
              "scope_fields": list(source_scope_fields.get(tag, ())),
              "observed_scopes": 0, "scope_transitions": 0,
              "scope_regressions": 0, "missing_phase_epochs": 0,
              "malformed_records": 0}
        for tag in source_sequence_fields
    }
    pending_write: dict | None = None
    unmatched_write_requests = 0
    unmatched_applications = 0
    matched_accepted = 0
    matched_rejected = 0
    write_contradictions: list[str] = []
    decision_reasons: dict[str, int] = {}
    response_classifications: dict[str, int] = {}
    state_reasons: dict[str, int] = {}
    for line in _iter_record_lines(run_dir, manifest):
        if line is None:
            oversized_or_partial_lines += 1
            continue
        try:
            row = next(csv.reader([line.decode("ascii")]))
        except (UnicodeError, csv.Error):
            continue
        if not row:
            continue
        tag = row[0]
        counts[tag] = counts.get(tag, 0) + 1
        contract = RECORD_TYPE_TO_CONTRACT.get(tag)
        if tag in source_sequence_fields and contract is not None:
            fields = RECORD_FIELDS[contract]
            key = source_sequence_fields[tag]
            coverage = source_coverage[tag]
            try:
                if len(row) != len(fields):
                    raise ValueError("source row width")
                sequence = int(row[fields.index(key)])
                scope = tuple(int(row[fields.index(name)])
                              for name in source_scope_fields.get(tag, ()))
                if not 0 <= sequence <= 0xFFFFFFFF or any(
                    not 0 <= value <= 0xFFFFFFFF for value in scope
                ):
                    raise ValueError("source counter range")
            except ValueError:
                coverage["malformed_records"] += 1
            else:
                seen = source_seen_scopes.setdefault(tag, set())
                previous_scope = source_last_scope.get(tag)
                new_scope = tag in source_last_scope and scope != previous_scope
                if new_scope:
                    coverage["scope_transitions"] += 1
                    epoch_key = (tag, scope[0])
                    capture_reentry = (
                        previous_scope is not None and scope[0] != previous_scope[0]
                        and epoch_key in source_max_epoch
                    )
                    if (capture_reentry or scope in seen or
                            scope[1] <= source_max_epoch.get(epoch_key, -1)):
                        coverage["scope_regressions"] += 1
                    else:
                        # Every phase increment produces a row; an absent whole
                        # phase is loss. Acceptance epochs may have no APS spans.
                        if (tag in {"RPH", "PHE"} and previous_scope is not None
                                and scope[0] == previous_scope[0]):
                            coverage["missing_phase_epochs"] += max(
                                0, scope[1] - previous_scope[1] - 1
                            )
                        # First attachment has unknown prefix coverage. At an
                        # observed new epoch APS begins at 1; phase begins at 0
                        # (anchor) or 1 (first accepted span). Neither is loss.
                        if sequence > 1:
                            coverage["gaps"] += sequence - 1
                        if tag == "APS" and sequence == 0:
                            coverage["nonmonotonic_or_restart"] += 1
                else:
                    previous = source_last_sequence.get(tag)
                    if previous is not None:
                        # Sequence arithmetic, independent of timestamp rollover.
                        delta = (sequence - previous) & 0xFFFFFFFF
                        if delta == 0 or delta > 0x7FFFFFFF:
                            coverage["nonmonotonic_or_restart"] += 1
                        elif delta > 1:
                            coverage["gaps"] += delta - 1
                seen.add(scope)
                coverage["observed_scopes"] = len(seen)
                if scope:
                    epoch_key = (tag, scope[0])
                    source_max_epoch[epoch_key] = max(
                        scope[1], source_max_epoch.get(epoch_key, -1)
                    )
                source_last_scope[tag] = scope
                source_last_sequence[tag] = sequence
        if tag in instrument_tags:
            if (contract is None or len(row) != len(RECORD_FIELDS[contract]) or
                    row[1] != "2"):
                malformed_instrument_rows += 1
                continue
            values = dict(zip(RECORD_FIELDS[contract], row))
            if ("timestamp_domain" in values and
                    values["timestamp_domain"] != "rp2040_timer_us64"):
                instrument_domain_contradictions += 1
            try:
                session = int(values["session"])
                record_sequence = int(values["record_sequence"])
            except ValueError:
                malformed_instrument_rows += 1
                continue
            previous = last_instrument_sequence.get(session)
            if previous is not None:
                if record_sequence <= previous:
                    instrument_nonmonotonic += 1
                elif record_sequence > previous + 1:
                    instrument_record_gaps += record_sequence - previous - 1
            last_instrument_sequence[session] = max(record_sequence, previous or 0)
            if tag in {"IWR", "IAP"}:
                try:
                    identity = (
                        session, int(values["capture_session"]),
                        int(values["sequence"]), int(values["dac_epoch"]),
                    )
                    requested_code = int(values["requested_code"])
                except ValueError:
                    malformed_instrument_rows += 1
                    continue
                if tag == "IWR":
                    if pending_write is not None:
                        unmatched_write_requests += 1
                    try:
                        deadline_ticks = int(values["deadline_ticks"])
                    except ValueError:
                        malformed_instrument_rows += 1
                        continue
                    pending_write = {
                        "identity": identity, "requested_code": requested_code,
                        "deadline_ticks": deadline_ticks,
                        "timestamp_domain": values["timestamp_domain"],
                    }
                    if values["timestamp_domain"] != "rp2040_timer_us64" and len(write_contradictions) < 16:
                        write_contradictions.append("IWR timestamp domain differs")
                elif pending_write is not None and pending_write["identity"] == identity:
                    try:
                        applied_code = int(values["applied_code"])
                        applied_ticks = int(values["timestamp_ticks"])
                    except ValueError:
                        malformed_instrument_rows += 1
                        continue
                    causal_mismatch = (
                        values["timestamp_domain"] != "rp2040_timer_us64" or
                        pending_write["timestamp_domain"] != "rp2040_timer_us64" or
                        requested_code != pending_write["requested_code"] or
                        applied_ticks >= pending_write["deadline_ticks"]
                    )
                    if causal_mismatch and len(write_contradictions) < 16:
                        write_contradictions.append(f"IAP identity/code/domain/deadline contradiction: {identity}")
                    if values["accepted"] == "1":
                        result_mismatch = (
                            values["attempted"] != "1" or values["ok"] != "1" or
                            values["rejection"] != "0" or applied_code != requested_code
                        )
                        if result_mismatch and len(write_contradictions) < 16:
                            write_contradictions.append(f"accepted IAP result contradiction: {identity}")
                        if not causal_mismatch and not result_mismatch:
                            matched_accepted += 1
                    else:
                        result_mismatch = (
                            values["accepted"] != "0" or
                            values["attempted"] not in {"0", "1"} or
                            values["ok"] not in {"0", "1"} or
                            values["rejection"] == "0" or
                            (values["attempted"] == "0" and values["ok"] == "1")
                        )
                        if result_mismatch and len(write_contradictions) < 16:
                            write_contradictions.append(f"IAP rejected result contradiction: {identity}")
                        if not causal_mismatch and not result_mismatch:
                            matched_rejected += 1
                    pending_write = None
                else:
                    unmatched_applications += 1
            elif tag == "IDC":
                reason = values["reason"]
                decision_reasons[reason] = decision_reasons.get(reason, 0) + 1
            elif tag == "IRS":
                classification = values["classification"]
                response_classifications[classification] = (
                    response_classifications.get(classification, 0) + 1
                )
            elif tag == "IST":
                reason = values["reason"]
                state_reasons[reason] = state_reasons.get(reason, 0) + 1
    if pending_write is not None:
        unmatched_write_requests += 1
    return {
        "observed_record_counts": counts,
        "instrument_record_gaps": instrument_record_gaps,
        "instrument_record_nonmonotonic": instrument_nonmonotonic,
        "malformed_instrument_rows": malformed_instrument_rows,
        "instrument_domain_contradictions": instrument_domain_contradictions,
        "oversized_or_partial_lines": oversized_or_partial_lines,
        "write_request_application_joins": {
            "matched_accepted": matched_accepted,
            "matched_rejected": matched_rejected,
            "contradictions": write_contradictions,
            "unmatched_requests": unmatched_write_requests,
            "unmatched_applications": unmatched_applications,
            "last_unmatched_write": pending_write,
        },
        "decision_reasons": decision_reasons,
        "response_classifications": response_classifications,
        "state_reasons": state_reasons,
        "source_sequence_coverage": source_coverage,
        "environment_record_gaps_separate_from_control": source_coverage["ENV"]["gaps"],
        "coverage_limit": (
            "Host-observed records only; gaps, USB loss, pre-attachment evidence, "
            "and physical source completeness are not reconstructed."
        ),
    }


def _event_summary(run_dir: Path) -> dict:
    counts: dict[str, int] = {}
    delivery_failures = []
    for path in sorted(run_dir.glob("monitor-events-*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    delivery_failures.append(f"invalid JSONL in {path.name}")
                    continue
                event = value.get("event")
                if isinstance(event, str):
                    counts[event] = counts.get(event, 0) + 1
    if (run_dir / "monitor_delivery_failure.json").exists():
        delivery_failures.append("monitor_delivery_failure.json is present")
    return {"event_counts": counts, "delivery_findings": delivery_failures}


def finalize(run_dir: Path, *, output_dir: Path | None = None) -> dict:
    """Offline, restartable packaging of already closed evidence; no serial I/O."""
    root = run_dir.resolve()
    data = (root / PLAN).read_bytes()
    plan = Plan.load(data)
    if root != plan.run_dir and output_dir is None:
        raise ValueError("relocated evidence requires explicit offline output_dir")
    destination = output_dir.resolve() if output_dir is not None else plan.shared_output_dir
    if destination == root or root in destination.parents:
        raise ValueError("package destination must be outside acquisition run directory")
    verification = verify_recording(root)
    monitor_result = root / "monitor.stdout.json"
    monitor_terminal = root / "monitor_terminal.json"
    if not monitor_result.is_file() or monitor_result.stat().st_size == 0:
        if not monitor_terminal.is_file():
            raise ValueError("monitor has not produced a result or proven terminal exit; package deferred")
        terminal = json.loads(monitor_terminal.read_text(encoding="utf-8"))
        if (terminal.get("schema_version") != 1 or
                type(terminal.get("pid")) is not int or terminal["pid"] <= 0 or
                type(terminal.get("exit_code")) is not int):
            raise ValueError("monitor terminal marker is malformed")
    manifest = json.loads((root / "recording_manifest.json").read_text(encoding="utf-8"))
    state = json.loads((root / "recorder_state.json").read_text(encoding="utf-8"))
    frozen_state = root / "unattended_state_at_close.json"
    live_state = root / STATE
    if not live_state.exists() and not frozen_state.exists():
        raise ValueError("coordinator terminal state is missing")
    coordinator_state = json.loads(
        (frozen_state if frozen_state.exists() else live_state).read_text(encoding="utf-8")
    )
    if not frozen_state.exists():
        _atomic_json(frozen_state, coordinator_state)
    frozen_events = root / "unattended-events-frozen.jsonl"
    if not frozen_events.exists() and (root / EVENTS).exists():
        with (root / EVENTS).open("rb") as source, frozen_events.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
    # The coordinator prints its own final result after packaging. Freeze its
    # logs alongside chronology so that this later output cannot change the
    # identity of an offline repeat against the same closed evidence.
    mutable_logs = {"coordinator.stdout.log", "coordinator.stderr.log"}
    for name in sorted(mutable_logs):
        path = root / name
        frozen_log = root / name.replace(".log", "-frozen.log")
        if path.is_file() and not frozen_log.exists():
            with path.open("rb") as source, frozen_log.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
    instrument = state.get("instrument") or {}
    fields = instrument.get("fields") or {}
    raw = _analyze_raw(root, manifest)
    monitor = _event_summary(root)
    findings = []
    if verification["recording_error"] is not None:
        findings.append("recording_error")
    if manifest.get("close_boundary_complete") is False:
        findings.append("recording_close_frame_boundary_incomplete")
    if raw["instrument_record_gaps"] or raw["instrument_record_nonmonotonic"]:
        findings.append("instrument_record_delivery_or_order_gap")
    if any(
        raw["source_sequence_coverage"][tag]["gaps"] or
        raw["source_sequence_coverage"][tag]["nonmonotonic_or_restart"] or
        raw["source_sequence_coverage"][tag]["scope_regressions"] or
        raw["source_sequence_coverage"][tag]["missing_phase_epochs"] or
        raw["source_sequence_coverage"][tag]["malformed_records"]
        for tag in ("REF", "SNP", "CNT", "APS", "RPH", "PHE")
    ):
        findings.append("canonical_source_sequence_coverage_gap")
    if raw["malformed_instrument_rows"] or raw["oversized_or_partial_lines"]:
        findings.append("instrument_record_or_line_parse_gap")
    if raw["instrument_domain_contradictions"]:
        findings.append("instrument_timestamp_domain_contradiction")
    joins = raw["write_request_application_joins"]
    if (joins["unmatched_requests"] or joins["unmatched_applications"] or
            joins["contradictions"]):
        findings.append("instrument_write_application_join_gap")
    if monitor["delivery_findings"]:
        findings.append("monitor_delivery_failure")
    if monitor_terminal.is_file():
        terminal = json.loads(monitor_terminal.read_text(encoding="utf-8"))
        if terminal.get("exit_code") != 0 or not monitor_result.is_file() or monitor_result.stat().st_size == 0:
            findings.append("monitor_failed_or_missing_terminal_result")
    if coordinator_state.get("review_reason"):
        findings.append("review_required")
    findings.extend(coordinator_state.get("coverage_escalations") or [])
    endpoint = {
        "session": instrument.get("session"),
        "mode": instrument.get("mode"),
        "requested_mode": instrument.get("requested_mode"),
        "command_completed": instrument.get("completed_command_sequence"),
        "applied_code": instrument.get("applied_code"),
        "applied_code_known": instrument.get("applied_code_known"),
        "dac_epoch": instrument.get("dac_epoch"),
        "write_state": fields.get("write_state"),
        "write_sequence": fields.get("write_sequence"),
        "instrument_ticks": fields.get("instrument_ticks"),
        "instrument_ticks_domain": fields.get("instrument_ticks_domain"),
        "operating_end_ticks": fields.get("operating_end_ticks"),
        "fault": fields.get("fault"),
        "reference_hold": fields.get("reference_hold"),
        "metadata_hold": fields.get("metadata_hold"),
        "observation_dropped": fields.get("observation_dropped"),
        "evidence_dropped": fields.get("evidence_dropped"),
        "critical_dropped": fields.get("critical_dropped"),
        "direct_rows_dropped": fields.get("direct_rows_dropped"),
    }
    endpoint_confirmed = bool(
        instrument.get("session") == plan.expected_session and
        instrument.get("mode") == instrument.get("requested_mode") == "OBSERVE_HOLD" and
        instrument.get("applied_code_known") and
        fields.get("write_state") == "0" and
        fields.get("fault") == "none" and
        fields.get("instrument_ticks_domain") == "rp2040_timer_us64" and
        coordinator_state.get("auto_sequence") is not None and
        instrument.get("completed_command_sequence") == coordinator_state["auto_sequence"] and
        instrument.get("last_command_sequence") == coordinator_state["auto_sequence"] and
        coordinator_state.get("operating_end_ticks") is not None and
        int(fields.get("instrument_ticks", "0")) >= coordinator_state["operating_end_ticks"]
    )
    if plan.observation_kind == "open_ended":
        # This boundary closes evidence only. A last status is retained state,
        # not proof of static actuation or an uninterrupted physical interval.
        endpoint_confirmed = False
        if coordinator_state.get("auto_sequence") is None:
            findings.append("indefinite_auto_entry_unconfirmed")
        try:
            _recording_end_request(root, hashlib.sha256(data).hexdigest())
        except (OSError, ValueError):
            findings.append("operator_recording_endpoint_unconfirmed")
    elif not endpoint_confirmed:
        findings.append("firmware_timed_hold_endpoint_unconfirmed")
    analysis_sha = _sha256(Path(__file__))
    evidence_paths = [
        path for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {STATE, EVENTS, *mutable_logs}
        and not path.name.startswith(".")
        and not path.name.startswith("unattended_package_result")
        and not path.name.startswith("unattended_summary-")
    ]
    if any(path.is_symlink() for path in evidence_paths):
        raise ValueError("run directory contains a symlink; package refused")
    evidence_inventory = [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
         "sha256": _sha256(path)} for path in evidence_paths
    ]
    evidence_sha = hashlib.sha256(json.dumps(
        evidence_inventory, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    summary = {
        "schema_version": 1,
        "generated_utc": _utc(),
        "analysis_sha256": analysis_sha,
        "evidence_inventory_sha256": evidence_sha,
        "original_run_dir": str(plan.run_dir),
        "analysis_run_dir": str(root),
        "plan_sha256": hashlib.sha256(data).hexdigest(),
        "raw_verification": verification,
        "raw_inventory": raw,
        "monitor": monitor,
        "endpoint": endpoint,
        "firmware_timed_hold_endpoint_confirmed": endpoint_confirmed,
        "observation_kind": plan.observation_kind,
        "endpoint_contract": ("operator_recording_cutoff_instrument_continues" if
                              plan.observation_kind == "open_ended" else "firmware_timed_hold"),
        "operational_result": (
            "completed_with_review_findings" if findings else "completed_observation"
        ),
        "review_findings": findings,
        "scientific_qualification": "not_established_by_automatic_package",
    }
    location_sha = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    summary_path = root / (
        f"unattended_summary-{analysis_sha[:8]}-{evidence_sha[:8]}-{location_sha[:8]}.json"
    )
    if not summary_path.exists():
        _atomic_json(summary_path, summary)
    else:
        recorded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        comparable = {key: value for key, value in summary.items() if key != "generated_utc"}
        recorded_comparable = {
            key: value for key, value in recorded_summary.items() if key != "generated_utc"
        }
        if recorded_comparable != comparable:
            raise ValueError("existing summary differs from current frozen evidence analysis")
        summary = recorded_summary
    destination.mkdir(parents=True, exist_ok=True)
    files = evidence_paths + [summary_path]
    input_inventory = [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
         "sha256": _sha256(path)} for path in files
    ]
    inventory_sha = hashlib.sha256(json.dumps(
        input_inventory, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    name = f"{root.name}-{summary['plan_sha256'][:8]}-{analysis_sha[:8]}-{inventory_sha[:8]}.zip"
    output = destination / name
    checksum_path = destination / f"{name}.sha256"
    if output.exists() and checksum_path.exists():
        claimed = checksum_path.read_text(encoding="utf-8").split()[0]
        if _sha256(output) == claimed:
            return {"status": "already_packaged", "zip": str(output),
                    "sha256": claimed, "summary": str(summary_path),
                    "input_inventory_sha256": inventory_sha,
                    "operational_result": summary["operational_result"]}
        raise ValueError("existing package checksum differs")
    source_bytes = sum(path.stat().st_size for path in files)
    if shutil.disk_usage(destination).free < source_bytes:
        raise OSError("shared destination lacks room for uncompressed evidence package")
    package_partial = destination / f".{name}.partial"
    if package_partial.exists():
        raise FileExistsError(package_partial)
    with zipfile.ZipFile(package_partial, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3, allowZip64=True) as archive:
        for path in files:
            archive.write(path, arcname=path.relative_to(root).as_posix())
    with zipfile.ZipFile(package_partial, "r") as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP member CRC verification failed")
        for item in input_inventory:
            digest = hashlib.sha256()
            with archive.open(item["path"]) as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError(f"ZIP member identity differs: {item['path']}")
    with package_partial.open("rb") as handle:
        os.fsync(handle.fileno())
    digest = _sha256(package_partial)
    package_partial.replace(output)
    with checksum_path.open("x", encoding="utf-8") as handle:
        handle.write(f"{digest}  {name}\n")
        handle.flush()
        os.fsync(handle.fileno())
    result = {
        "status": "packaged", "zip": str(output), "sha256": digest,
        "summary": str(summary_path),
        "input_inventory_sha256": inventory_sha,
        "operational_result": summary["operational_result"],
        "source_bytes": source_bytes,
    }
    _atomic_json(root / f"unattended_package_result-{analysis_sha[:12]}.json", result)
    return result


def status(run_dir: Path) -> dict:
    state = json.loads((run_dir / STATE).read_text(encoding="utf-8"))
    try:
        state["recorder"] = read_recorder_status(run_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        state["recorder"] = {"availability": "unavailable"}
    return state


def end_recording(run_dir: Path) -> dict:
    """Persist an explicit evidence cutoff for the detached observer."""
    data = (run_dir / PLAN).read_bytes()
    plan = Plan.load(data)
    if plan.observation_kind != "open_ended" or plan.run_dir != run_dir.resolve():
        raise ValueError("end-recording requires the original open_ended run directory")
    marker = run_dir / END_RECORDING
    if not marker.exists():
        _atomic_json(marker, {"operation": "end_recording", "requested_utc": _utc(),
                              "plan_sha256": hashlib.sha256(data).hexdigest()})
    else:
        _recording_end_request(run_dir, hashlib.sha256(data).hexdigest())
    return {"recording_end": "requested", "instrument_mode_changed": False,
            "run_dir": str(run_dir.resolve())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="otis-unattended", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("start", help="Launch detached local observation")
    launch.add_argument("--plan", required=True, type=Path)
    child = commands.add_parser("run", help=argparse.SUPPRESS)
    child.add_argument("run_dir", type=Path)
    inspect = commands.add_parser("status", help="Read durable coordinator and recorder status")
    inspect.add_argument("run_dir", type=Path)
    cutoff = commands.add_parser("end-recording", help="End open-ended recording; instrument keeps operating")
    cutoff.add_argument("run_dir", type=Path)
    finish = commands.add_parser("finalize", help="Package already closed evidence without serial I/O")
    finish.add_argument("run_dir", type=Path)
    finish.add_argument("--output-dir", type=Path,
                        help="Required when analyzing a relocated evidence copy")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start(args.plan)
        elif args.command == "run":
            run_frozen(args.run_dir)
            result = {"status": "coordinator_exited"}
        elif args.command == "status":
            result = status(args.run_dir)
        elif args.command == "end-recording":
            result = end_recording(args.run_dir)
        else:
            result = finalize(args.run_dir, output_dir=args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    if "error" in result or args.command == "start" and result.get("state", {}).get("phase") != "running":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
