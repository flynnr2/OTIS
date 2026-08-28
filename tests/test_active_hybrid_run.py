from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import active_hybrid_run as runner
from host.otis_tools.active_hybrid_programme_contract import (
    CX322_D9_D6_INTEGRATION_PROGRAMME,
)


class FakeProcess:
    def __init__(self, pid: int, *, exit_code: int = 0) -> None:
        self.pid = pid
        self.exit_code = exit_code
        self.returned: int | None = None
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.returned

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returned = self.exit_code
        return self.exit_code

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)

    def terminate(self) -> None:
        self.returned = -15

    def kill(self) -> None:
        self.returned = -9


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _activation(tmp_path: Path) -> tuple[Path, dict, dict]:
    bundle_path = tmp_path / "source-bundle.json"
    proposal_path = tmp_path / "source-proposal.json"
    _write(bundle_path, {"bundle": "exact"})
    _write(proposal_path, {"proposal": "non-effective"})
    firmware = {
        "profile_id": "cx320_active_hybrid",
        "source_revision": "a" * 40,
        "source_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
        "build_identity": "b" * 64 + ":" + "c" * 64,
        "fqbn": "rp2040:test",
        "uf2": {"path": str(tmp_path / "image.uf2"), "sha256": "d" * 64},
    }
    (tmp_path / "image.uf2").write_bytes(b"uf2")
    activation = {
        "activation_sha256": "e" * 64,
        "profile_identity": "cx320_active_hybrid",
        "device": {
            "path": "/dev/cu.test",
            "expected_board_serial": runner.EXPECTED_BOARD_SERIAL,
        },
        "bundle": {"path": str(bundle_path), "bundle_sha256": "f" * 64},
        "proposal": {"path": str(proposal_path), "proposal_sha256": "1" * 64},
        "authority": {
            "effective": True,
            "firmware_flash_limit": 1,
            "automatic_retry": False,
            "automatic_restoration": False,
        },
        "firmware": firmware,
    }
    activation_path = tmp_path / "activation.json"
    _write(activation_path, activation)
    bundle = {"firmware": firmware}
    return activation_path, activation, bundle


def test_process_commands_bind_one_owner_three_fifos_and_finite_limits(
    tmp_path: Path,
) -> None:
    capture = runner._capture_command(device="/dev/cu.test", run_dir=tmp_path)
    supervisor = runner._supervisor_command(
        run_dir=tmp_path, build_identity="a" * 64 + ":" + "b" * 64
    )

    assert capture[0:3] == [runner.sys.executable, "-m", "host.otis_tools.capture_device"]
    assert capture[capture.index("--duration-s") + 1] == str(57_780)
    assert capture[capture.index("--normal-command-max-age-s") + 1] == "2"
    assert supervisor[0:3] == [
        runner.sys.executable,
        "-m",
        "host.otis_tools.active_hybrid_live_supervisor",
    ]
    assert supervisor[supervisor.index("--duration-s") + 1] == str(57_720)
    fifo_values = {
        capture[capture.index("--command-fifo") + 1],
        capture[capture.index("--emergency-command-fifo") + 1],
        supervisor[supervisor.index("--abort-fifo") + 1],
    }
    assert len(fifo_values) == 3


def test_integrated_capture_resolves_the_serial_path_fresh() -> None:
    command = runner._capture_command(
        device="/dev/cu.usbmodem-freshly-resolved",
        run_dir=Path("/tmp/integrated-fixture"),
        programme=CX322_D9_D6_INTEGRATION_PROGRAMME,
    )

    assert "--auto-detect" in command
    assert "--device" not in command
    assert command[command.index("--expected-auto-detect-device") + 1] == (
        "/dev/cu.usbmodem-freshly-resolved"
    )


def test_healthy_terminal_defers_scientific_decision_to_analyzer() -> None:
    for preliminary in runner.HEALTHY_PRELIMINARY_DECISIONS:
        assert runner._terminal_expected(
            {
                "result": "healthy_stop",
                "preliminary_decision": preliminary,
                "last_confirmed_code": 0xA83C,
            }
        )
    assert not runner._terminal_expected(
        {
            "result": "healthy_stop",
            "primary_decision": "bounded_active_hybrid_control_passed",
            "last_confirmed_code": 0xA83C,
        }
    )


def test_abort_delivery_timeout_is_recorded_before_capture_may_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = {
        "result": "aborted",
        "primary_decision": "measurement_authority_or_platform_fault",
        "last_confirmed_code": 0xA83C,
    }
    monkeypatch.setattr(
        runner,
        "_wait_until",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("bounded")),
    )

    with pytest.raises(TimeoutError, match="bounded"):
        runner._wait_for_terminal_abort_delivery(tmp_path, terminal)

    failure = json.loads(
        (tmp_path / runner.ABORT_DELIVERY_FAILURE).read_text(encoding="utf-8")
    )
    assert failure["delivery_status"] == "bounded_failure"
    assert failure["terminal"] == terminal


def test_abort_delivery_waits_for_complete_consumed_firmware_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = {
        "result": "aborted",
        "primary_decision": "measurement_authority_or_platform_fault",
        "last_confirmed_code": 0xA83C,
    }
    _write(
        tmp_path / "reports/capture_device_state.json",
        {
            "capture_active": True,
            "emergency_abort_latched": True,
            "emergency_aborts_sent": 1,
        },
    )
    live = SimpleNamespace(
        state="complete",
        health={
            ("cx317_active", "state"): "ABORTED",
            ("cx317_active", "fail_static"): "true",
            ("cx317_active", "evidence_pending"): "false",
            ("cx317_active", "evidence_phase"): "evidence_clear",
            ("cx317_active", "evidence_request_sequence"): "0",
            ("cx317_active", "confirmed_applied_code_known"): "true",
            ("cx317_active", "confirmed_applied_code"): str(0xA83C),
        },
    )
    monkeypatch.setattr(runner, "read_live_health_state", lambda _path: live)
    observed = []

    def wait(predicate, _timeout, description):  # type: ignore[no-untyped-def]
        observed.append(description)
        assert predicate()

    monkeypatch.setattr(runner, "_wait_until", wait)
    runner._wait_for_terminal_abort_delivery(tmp_path, terminal)
    assert observed == ["priority abort delivery before sole-owner capture close"]


def test_prewrite_abort_does_not_invent_a_confirmed_static_code() -> None:
    assert runner._terminal_expected(
        {
            "result": "aborted",
            "reason": "prewrite_identity_failure",
            "primary_decision": "measurement_authority_or_platform_fault",
        }
    )


def test_partial_snapshot_freezes_available_evidence_and_declares_absence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "partial"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "raw/serial.log").write_bytes(b"partial raw\n")
    _write(run_dir / runner.COMPLETE, {"orchestration_error": "prewrite"})
    _write(
        run_dir / runner.RUN_MANIFEST_PATH,
        {
            "schema_version": 1,
            "run_id": "partial",
            "stage": "CX320_ACTIVE_HYBRID_LIVE",
            "cx320": {"profile_id": "cx320_active_hybrid"},
            "files": [
                {"path": "csv/required_missing.csv", "contract": "missing_v1"}
            ],
            "evidence_artifacts": ["COMPLETE"],
        },
    )

    path = runner._create_partial_evidence_snapshot(run_dir)
    snapshot = json.loads(path.read_text(encoding="utf-8"))

    assert snapshot["run_state"] == "partial"
    paths = {entry["path"] for entry in snapshot["artifacts"]}
    assert paths == {"COMPLETE", "raw/serial.log", "run_manifest.json"}
    assert "csv/required_missing.csv" not in paths
    assert len(snapshot["snapshot_digest"]) == 64


def test_exact_upload_occurs_once_and_binds_reenumerated_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, activation, _ = _activation(tmp_path)
    (tmp_path / "reports").mkdir()
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="uploaded", stderr="")

    after = {"serial_number": runner.EXPECTED_BOARD_SERIAL, "address": "/dev/cu.after"}
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(
        runner,
        "_locate_board_by_serial",
        lambda *args, **kwargs: ("/dev/cu.after", after),
    )

    device, board, record = runner._upload_exact_firmware(
        run_dir=tmp_path,
        activation=activation,
        device="/dev/cu.before",
        board_before={"serial_number": runner.EXPECTED_BOARD_SERIAL},
        arduino_cli="arduino-cli",
    )

    assert len(calls) == 1
    assert calls[0][1] == "upload"
    assert calls[0].count("--input-file") == 1
    assert device == "/dev/cu.after"
    assert board == after
    assert record["firmware_flash_count"] == 1
    assert record["status"] == "passed"
    assert (tmp_path / runner.FLASH_RECORD).is_file()


def test_existing_run_is_rejected_before_owner_or_board_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation_path, activation, bundle = _activation(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    monkeypatch.setattr(
        runner, "validate_activation", lambda _path: (activation, bundle, {})
    )
    monkeypatch.setattr(
        runner, "require_programme_operation_allowed", lambda *args: {}
    )
    monkeypatch.setattr(
        runner,
        "_serial_owner_pids",
        lambda _device: (_ for _ in ()).throw(AssertionError("owner lookup")),
    )

    with pytest.raises(FileExistsError, match="already exists"):
        runner.run_active_hybrid_qualification(
            activation_path=activation_path,
            run_dir=existing,
            evidence_index_path=tmp_path / "index.json",
        )


def test_sustained_v1_live_operation_is_blocked_before_serial_or_board_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation_path = tmp_path / "sustained-v1-activation.json"
    activation = {
        "programme_id": "OTIS_SUSTAINED_HYBRID_REGULATION_V1",
        "device": {"path": "/dev/cu.must-not-open"},
    }
    _write(activation_path, activation)
    monkeypatch.setattr(
        runner,
        "validate_activation",
        lambda _path, *, programme: (activation, {}, {}),
    )
    monkeypatch.setattr(
        runner,
        "_serial_owner_pids",
        lambda _device: (_ for _ in ()).throw(AssertionError("serial access")),
    )
    monkeypatch.setattr(
        runner,
        "read_board_identity",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("board access")),
    )

    with pytest.raises(RuntimeError, match="otis_sustained_hybrid_regulation_live"):
        runner.run_active_hybrid_qualification(
            activation_path=activation_path,
            run_dir=tmp_path / "must-not-exist",
            evidence_index_path=tmp_path / "index.json",
        )

    assert not (tmp_path / "must-not-exist").exists()


def test_orchestration_waits_for_abort_delivery_before_capture_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation_path, activation, bundle = _activation(tmp_path)
    run_dir = tmp_path / "run"
    capture = FakeProcess(7001)
    supervisor = FakeProcess(7002, exit_code=2)
    launched: list[list[str]] = []
    events: list[str] = []

    monkeypatch.setattr(
        runner, "validate_activation", lambda _path: (activation, bundle, {})
    )
    monkeypatch.setattr(
        runner, "require_programme_operation_allowed", lambda *args: {}
    )
    owners = iter((set(), {capture.pid}))
    monkeypatch.setattr(runner, "_serial_owner_pids", lambda _device: next(owners))
    monkeypatch.setattr(
        runner,
        "read_board_identity",
        lambda *args, **kwargs: {"serial_number": runner.EXPECTED_BOARD_SERIAL},
    )
    monkeypatch.setattr(
        runner,
        "_upload_exact_firmware",
        lambda **kwargs: (
            "/dev/cu.test",
            {"serial_number": runner.EXPECTED_BOARD_SERIAL},
            {},
        ),
    )

    def manifest(**kwargs: object) -> dict[str, object]:
        _write(Path(kwargs["output_path"]), {"manifest": "live"})
        return {"manifest": "live"}

    monkeypatch.setattr(runner, "create_run_manifest", manifest)
    journal = tmp_path / "journal.json"
    _write(journal, {"phases": {}})
    monkeypatch.setattr(runner, "begin_finalization", lambda **kwargs: journal)
    monkeypatch.setattr(runner, "advance_phase", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "_capture_state_ready", lambda *args: True)

    def launch(command: list[str], log: object) -> FakeProcess:
        del log
        launched.append(command)
        return capture if "host.otis_tools.capture_device" in command else supervisor

    monkeypatch.setattr(runner, "_launch_process", launch)

    terminal = {
        "result": "aborted",
        "reason": "injected",
        "primary_decision": "measurement_authority_or_platform_fault",
        "last_confirmed_code": 0xA83C,
    }

    def wait(predicate, timeout_s, description):  # type: ignore[no-untyped-def]
        del timeout_s
        if "capture" in description and "command paths" in description:
            os.mkfifo(run_dir / runner.NORMAL_FIFO)
            os.mkfifo(run_dir / runner.EMERGENCY_FIFO)
        elif "live supervisor" in description:
            os.mkfifo(run_dir / runner.HOST_ABORT_FIFO)
        elif "terminal" in description:
            _write(run_dir / runner.SUPERVISOR_STATE, {"terminal": terminal})
        assert predicate()

    monkeypatch.setattr(runner, "_wait_until", wait)

    def abort_delivery(_run_dir: Path, _terminal: dict) -> None:
        events.append("abort_delivered")

    def close(_capture: FakeProcess) -> int:
        events.append("capture_closed")
        _capture.returned = 0
        return 0

    monkeypatch.setattr(runner, "_wait_for_terminal_abort_delivery", abort_delivery)
    monkeypatch.setattr(runner, "_graceful_capture_stop", close)
    monkeypatch.setattr(
        runner,
        "_finalize_and_register",
        lambda **kwargs: {
            "status": "bounded_nonpass",
            "primary_decision": terminal["primary_decision"],
            "evidence_content_sha256": "9" * 64,
        },
    )

    result = runner.run_active_hybrid_qualification(
        activation_path=activation_path,
        run_dir=run_dir,
        evidence_index_path=tmp_path / "index.json",
    )

    assert result["status"] == "bounded_nonpass"
    assert events == ["abort_delivered", "capture_closed"]
    assert len(launched) == 2
    assert "host.otis_tools.capture_device" in launched[0]
    assert "host.otis_tools.active_hybrid_live_supervisor" in launched[1]


def test_upload_failure_is_retained_registered_and_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation_path, activation, bundle = _activation(tmp_path)
    run_dir = tmp_path / "run"
    monkeypatch.setattr(
        runner, "validate_activation", lambda _path: (activation, bundle, {})
    )
    monkeypatch.setattr(
        runner, "require_programme_operation_allowed", lambda *args: {}
    )
    monkeypatch.setattr(runner, "_serial_owner_pids", lambda _device: set())
    monkeypatch.setattr(
        runner,
        "read_board_identity",
        lambda *args, **kwargs: {"serial_number": runner.EXPECTED_BOARD_SERIAL},
    )
    uploads = 0

    def upload(**kwargs: object) -> None:
        nonlocal uploads
        uploads += 1
        raise RuntimeError("upload failed")

    monkeypatch.setattr(runner, "_upload_exact_firmware", upload)
    registered: dict[str, object] = {}

    def register(**kwargs: object) -> dict[str, str]:
        registered.update(kwargs)
        return {"content_sha256": "8" * 64}

    monkeypatch.setattr(runner, "register_package", register)

    with pytest.raises(RuntimeError, match="retained evidence"):
        runner.run_active_hybrid_qualification(
            activation_path=activation_path,
            run_dir=run_dir,
            evidence_index_path=tmp_path / "index.json",
        )

    assert uploads == 1
    assert (run_dir / runner.ORCHESTRATION_FAILURE).is_file()
    assert registered["attempt_classification"] == "interrupted_campaign"
    assert activation["authority"]["automatic_retry"] is False


@pytest.mark.parametrize("launch_error", [OSError("capture prewrite"), KeyboardInterrupt()])
def test_capture_prewrite_failure_still_enters_offline_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launch_error: BaseException,
) -> None:
    activation_path, activation, bundle = _activation(tmp_path)
    run_dir = tmp_path / "run"
    monkeypatch.setattr(
        runner, "validate_activation", lambda _path: (activation, bundle, {})
    )
    monkeypatch.setattr(
        runner, "require_programme_operation_allowed", lambda *args: {}
    )
    monkeypatch.setattr(runner, "_serial_owner_pids", lambda _device: set())
    monkeypatch.setattr(
        runner,
        "read_board_identity",
        lambda *args, **kwargs: {"serial_number": runner.EXPECTED_BOARD_SERIAL},
    )
    monkeypatch.setattr(
        runner,
        "_upload_exact_firmware",
        lambda **kwargs: (
            "/dev/cu.test",
            {"serial_number": runner.EXPECTED_BOARD_SERIAL},
            {},
        ),
    )

    def manifest(**kwargs: object) -> dict[str, object]:
        _write(Path(kwargs["output_path"]), {"manifest": "live"})
        return {"manifest": "live"}

    monkeypatch.setattr(runner, "create_run_manifest", manifest)
    journal = tmp_path / "journal.json"
    _write(journal, {"phases": {}})
    monkeypatch.setattr(runner, "begin_finalization", lambda **kwargs: journal)
    phases: list[str] = []
    monkeypatch.setattr(
        runner,
        "advance_phase",
        lambda _journal, phase, _detail: phases.append(phase),
    )
    monkeypatch.setattr(
        runner,
        "_launch_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(launch_error),
    )
    finalized: list[Exception | None] = []

    def finalize(**kwargs: object) -> dict[str, object]:
        finalized.append(kwargs["orchestration_error"])  # type: ignore[arg-type]
        return {
            "status": "failed",
            "primary_decision": "measurement_authority_or_platform_fault",
            "evidence_content_sha256": "7" * 64,
        }

    monkeypatch.setattr(runner, "_finalize_and_register", finalize)

    with pytest.raises(RuntimeError, match="retained terminal"):
        runner.run_active_hybrid_qualification(
            activation_path=activation_path,
            run_dir=run_dir,
            evidence_index_path=tmp_path / "index.json",
        )

    assert len(finalized) == 1
    assert isinstance(finalized[0], Exception)
    assert "capture prewrite" in str(finalized[0]) or "operator interrupted" in str(
        finalized[0]
    )
    assert phases == ["capture_closed"]


def test_offline_recovery_never_calls_board_serial_or_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "retained"
    (run_dir / "raw").mkdir(parents=True)
    _write(run_dir / runner.COMPLETE, {"terminal": "retained"})
    (run_dir / "raw/serial.log").write_bytes(b"immutable raw\n")
    activation_path = run_dir / runner.RUN_ACTIVATION_PATH
    _, activation, _ = _activation(tmp_path)
    _write(activation_path, activation)
    manifest = {
        "activation": {"path": str(activation_path)},
    }
    _write(run_dir / runner.RUN_MANIFEST_PATH, manifest)
    snapshot = run_dir / runner.EVIDENCE_MANIFEST
    _write(snapshot, {"artifacts": [{"path": "raw/serial.log"}]})
    seal = {
        "status": "bounded_nonpass",
        "primary_decision": "right_censored_incomplete",
        "seal_sha256": "1" * 64,
        "tool_sha256": "2" * 64,
    }
    _write(run_dir / runner.LIVE_SEAL, seal)
    journal = runner.journal_path_for(run_dir)
    _write(
        journal,
        {
            "index_path": str(tmp_path / "index.json"),
            "phases": {
                "capture_closed": {"done": True},
                "completion": {"done": True},
                "snapshot": {"done": True},
                "analysis": {"done": True},
                "seal": {"done": True},
                "registration": None,
            },
        },
    )
    monkeypatch.setattr(runner, "validate_frozen_run_manifest", lambda _path: manifest)
    monkeypatch.setattr(runner, "set_registration_intent", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runner,
        "recover_registration",
        lambda _journal: {"content_sha256": "3" * 64},
    )
    monkeypatch.setattr(
        runner,
        "read_board_identity",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("board I/O")),
    )
    monkeypatch.setattr(
        runner,
        "_upload_exact_firmware",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("upload")),
    )
    before = (run_dir / "raw/serial.log").read_bytes()

    result = runner.recover_active_hybrid_finalization(run_dir=run_dir)

    assert result["physical_rerun"] is False
    assert result["device_or_actuator_io"] is False
    assert (run_dir / "raw/serial.log").read_bytes() == before
