"""Execute, close, analyze, seal and register one bounded-control leg.

The lower leg reuses its qualified image without flashing.  The matched upper
leg performs exactly one manifest-bound upload before capture and records the
resulting board re-enumeration as evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
from typing import Any

from .board_identity import read_board_identity
from .no_write_qualification_run import _wait_until
from .bounded_tight_deadband_outcome_contract import QUALIFICATION_DEADLINE_S
from .bounded_tight_deadband_activation import (
    create_run_manifest,
    validate_activation,
    validate_frozen_run_manifest,
    validate_run_manifest,
)
from .bounded_tight_deadband_leg import (
    BoundedTightDeadbandLeg,
    LOWER,
    leg_for,
    leg_for_manifest,
)
from .bounded_tight_deadband_outcome_contract import canonical_sha256
from .bounded_tight_deadband_live_analyze import analyze
from .evidence import (
    EVIDENCE_MANIFEST,
    create_evidence_snapshot,
    validate_evidence_snapshot,
)
from .evidence_index import DEFAULT_INDEX, package_identity, register_package
from .evidence_finalization import (
    advance_phase,
    begin_finalization,
    journal_path_for,
    record_failure,
    recover_registration,
    set_registration_intent,
)
from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .run_loader import load_manifest
from .serial_commands import send_timestamped_command_to_fifo


TOOL_ID = "cx319_g2_run_v1"
CAPTURE_LOG = Path("reports/cx319_g2_capture_launcher.log")
SUPERVISOR_LOG = Path("reports/cx319_g2_supervisor.log")
ORCHESTRATION_FAILURE = Path("reports/cx319_g2_orchestration_failure_v1.json")
TERMINAL_ABORT_DELIVERY_TIMEOUT_S = 15.0
COMPLETED_INDEX_CLASSIFICATION = "completed_campaign"
INTERRUPTED_INDEX_CLASSIFICATION = "interrupted_campaign"
FINALIZATION_RECOVERY_TOOL_ID = "cx319_bounded_leg_finalization_recovery_v1"
EVIDENCE_EPOCH_PROFILE_FAILURE = (
    "manifest does not satisfy CX319_EVIDENCE_EPOCH_1"
)


def _capture_log(selected: BoundedTightDeadbandLeg) -> Path:
    return Path(f"reports/{selected.prefix}_capture_launcher.log")


def _supervisor_log(selected: BoundedTightDeadbandLeg) -> Path:
    return Path(f"reports/{selected.prefix}_supervisor.log")


def _orchestration_failure(selected: BoundedTightDeadbandLeg) -> Path:
    return Path(f"reports/{selected.prefix}_orchestration_failure_v1.json")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    from .bounded_tight_deadband_activation import _atomic_new_json as write

    write(path, value)


def _copy_immutable(source: Path, destination: Path) -> None:
    payload = source.resolve().read_bytes()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError(
                f"short immutable copy: expected {len(payload)}, wrote {written}"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _locate_board_by_serial(
    expected_serial: str, *, arduino_cli: str
) -> tuple[str, dict[str, str]]:
    listing = json.loads(
        subprocess.run(
            [arduino_cli, "board", "list", "--format", "json"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    addresses = [
        str(item.get("port", {}).get("address", ""))
        for item in listing.get("detected_ports", [])
        if item.get("port", {}).get("properties", {}).get("serialNumber")
        == expected_serial
    ]
    if len(addresses) != 1:
        raise ValueError(
            f"expected exactly one board with serial {expected_serial}, got {len(addresses)}"
        )
    return addresses[0], read_board_identity(addresses[0], arduino_cli=arduino_cli)


def _flash_exact_upper(
    *,
    run_dir: Path,
    selected: BoundedTightDeadbandLeg,
    proposal: dict[str, Any],
    activation: dict[str, Any],
    device: str,
    board_before: dict[str, str],
    arduino_cli: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    if not selected.firmware_flash or selected.flash_record_filename is None:
        return device, board_before, {}
    firmware = proposal["firmware"]
    command = [
        arduino_cli,
        "upload",
        "--port",
        device,
        "--fqbn",
        str(firmware["fqbn"]),
        "--input-file",
        str(firmware["uf2"]["path"]),
    ]
    started_utc = _utc_now()
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    board_after: dict[str, str] | None = None
    device_after: str | None = None
    reappearance_error = ""
    if completed.returncode == 0:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                device_after, board_after = _locate_board_by_serial(
                    activation["device"]["expected_board_serial"],
                    arduino_cli=arduino_cli,
                )
                break
            except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                reappearance_error = str(exc)
                time.sleep(0.5)
    passed = (
        completed.returncode == 0
        and board_after is not None
        and device_after is not None
        and board_before.get("serial_number")
        == board_after.get("serial_number")
        == activation["device"]["expected_board_serial"]
    )
    unsigned = {
        "schema_version": 1,
        "tool": f"{selected.prefix}_run_v1",
        "operation": f"exact_cx319_{selected.gate.lower()}_firmware_flash",
        "status": "passed" if passed else "failed",
        "gate": selected.gate,
        "leg": selected.leg,
        "started_utc": started_utc,
        "completed_utc": _utc_now(),
        "firmware_flash_count": 1,
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(completed.stderr.encode()).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "expected_board_serial": activation["device"]["expected_board_serial"],
        "board_identity_confirmed_before": True,
        "board_identity_confirmed_after": passed,
        "usb_reenumerated": board_after is not None,
        "device_before": device,
        "device_after": device_after,
        "serial_path_changed": device_after not in {None, device},
        "board_before": board_before,
        "board_after": board_after,
        "board_reappearance_error": reappearance_error,
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "build_manifest_sha256": firmware["build_manifest"]["sha256"],
        "uf2_sha256": firmware["uf2"]["sha256"],
        "profile_id": firmware["profile_id"],
        "dac_boot_operation": "i2c_address_probe_only",
        "dac_value_write_attempts": 0,
    }
    record = {**unsigned, "record_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(run_dir / selected.flash_record_filename, record)
    if not passed:
        raise RuntimeError(
            f"exact {selected.gate} upload or board re-enumeration failed; no retry is authorized"
        )
    return device_after, board_after, record


def _terminal(run_dir: Path) -> dict[str, Any] | None:
    state = _read_json(run_dir / "reports/cx317_active_supervisor_state.json")
    terminal = state.get("terminal") if state else None
    return terminal if isinstance(terminal, dict) else None


def _terminal_expected(terminal: dict[str, Any] | None) -> bool:
    if terminal is None:
        return False
    return (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason")
        == "required_direction_and_two_estimate_tight_entry"
    ) or (
        terminal.get("result") == "aborted"
        and terminal.get("reason")
        in {
            "stage5_qualification_deadline_expired",
            "stage5_finite_qualified_endpoint_nonpass",
        }
    )


def _wait_for_terminal_abort_delivery(
    run_dir: Path, terminal: dict[str, Any]
) -> None:
    """Keep capture alive until a terminal abort has reached the device path."""

    if terminal.get("result") != "aborted":
        return

    def delivered() -> bool:
        state = _read_json(run_dir / "reports/capture_device_state.json")
        if state is None:
            return False
        return (
            state.get("capture_active") is True
            and state.get("emergency_abort_latched") is True
            and int(state.get("emergency_aborts_sent", 0)) == 1
        )

    _wait_until(
        delivered,
        TERMINAL_ABORT_DELIVERY_TIMEOUT_S,
        "terminal independent abort delivery before capture close",
    )


def _write_complete(
    run_dir: Path, terminal: dict[str, Any], selected: BoundedTightDeadbandLeg
) -> None:
    payload = (
        json.dumps(
            {
                "completed_utc": _utc_now(),
                "completion": f"{selected.prefix}_finite_physical_leg",
                "terminal": terminal,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        run_dir / "COMPLETE", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _graceful_capture_stop(capture: subprocess.Popen[str]) -> int:
    if capture.poll() is None:
        capture.send_signal(signal.SIGINT)
    try:
        return capture.wait(timeout=30.0)
    except subprocess.TimeoutExpired:
        capture.send_signal(signal.SIGINT)
        try:
            return capture.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            capture.terminate()
            return capture.wait(timeout=5.0)


def _best_effort_emergency_abort(
    emergency_fifo: Path, capture: subprocess.Popen[str]
) -> None:
    """Try the independent abort without masking the primary live-run failure."""

    if not emergency_fifo.exists() or capture.poll() is not None:
        return
    try:
        send_timestamped_command_to_fifo(emergency_fifo, "ACTIVE ABORT")
        time.sleep(0.5)
    except (OSError, SystemExit, TimeoutError, ValueError):
        pass


def _retain_failure(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    evidence_index_path: Path,
    error: Exception,
) -> dict[str, Any]:
    selected = leg_for(activation.get("gate"), activation.get("leg"))
    failure = {
        "schema_version": 1,
        "report_type": f"{selected.prefix}_orchestration_failure_v1",
        "tool": f"{selected.prefix}_run_v1",
        "programme_id": selected.programme_id,
        "gate": selected.gate,
        "leg": selected.leg,
        "attempt_classification": INTERRUPTED_INDEX_CLASSIFICATION,
        "failure_class": "platform_or_live_stop_rule_failure",
        "recorded_utc": _utc_now(),
        "error_type": type(error).__name__,
        "error": str(error),
        "terminal": _terminal(run_dir),
        "activation_sha256": activation["activation_sha256"],
        "claims_boundary": (
            f"Retained failed {selected.gate} evidence only; this grants no retry, "
            "phase, hybrid, or later-programme authority."
        ),
    }
    _atomic_new_json(run_dir / _orchestration_failure(selected), failure)
    return register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision=selected.prefix + "-activation:" + activation["activation_sha256"],
        build_identity=activation["proposal"]["bundle_sha256"],
        profile_identity=selected.profile_id,
        attempt_classification=INTERRUPTED_INDEX_CLASSIFICATION,
        result_or_failure_reason=f"CX319 {selected.gate} orchestration failed: {error}",
        analyzer_identity=_sha256_file(Path(__file__)),
    )


def _retain_finalization_failure(
    *,
    run_dir: Path,
    activation: dict[str, Any],
    proposal: dict[str, Any],
    evidence_index_path: Path,
    error: Exception,
) -> dict[str, Any]:
    """Register a closed run even when snapshot/analyzer finalization fails.

    If no evidence snapshot exists yet, the ordinary retained-failure report is
    safe to add.  Once a snapshot exists, do not mutate the captured package;
    preserve the reason in the external evidence index instead.
    """

    if not (run_dir / EVIDENCE_MANIFEST).is_file():
        return _retain_failure(
            run_dir=run_dir,
            activation=activation,
            evidence_index_path=evidence_index_path,
            error=error,
        )
    selected = leg_for(activation.get("gate"), activation.get("leg"))
    return register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        source_revision=proposal["source_revision"],
        build_identity=proposal["firmware"]["build_manifest"]["sha256"],
        profile_identity=proposal["leg_spec"]["profile_id"],
        attempt_classification=INTERRUPTED_INDEX_CLASSIFICATION,
        result_or_failure_reason=f"CX319 {selected.gate} finalization failed: {error}",
        analyzer_identity=_sha256_file(Path(__file__)),
    )


def run_bounded_tight_deadband_qualification(
    *,
    activation_path: Path,
    run_dir: Path,
    evidence_index_path: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    activation_path = activation_path.resolve()
    activation, proposal = validate_activation(activation_path)
    selected = leg_for(activation.get("gate"), activation.get("leg"))
    maximum_wall_s = QUALIFICATION_DEADLINE_S + selected.maximum_qualified_duration_s
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError(f"CX319 {selected.gate} run already exists: {run_dir}")
    device = str(activation["device"]["path"])
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    board = read_board_identity(device, arduino_cli=arduino_cli)
    if (
        board.get("serial_number")
        != activation["device"]["expected_board_serial"]
    ):
        raise ValueError(f"connected board serial differs from {selected.gate} activation")

    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    run_activation = run_dir / selected.activation_filename
    run_proposal = run_dir / selected.proposal_filename
    _copy_immutable(activation_path, run_activation)
    _copy_immutable(Path(activation["proposal"]["path"]), run_proposal)
    try:
        device, board, _ = _flash_exact_upper(
            run_dir=run_dir,
            selected=selected,
            proposal=proposal,
            activation=activation,
            device=device,
            board_before=board,
            arduino_cli=arduino_cli,
        )
    except Exception as exc:
        try:
            indexed = _retain_failure(
                run_dir=run_dir,
                activation=activation,
                evidence_index_path=evidence_index_path,
                error=exc,
            )
        except Exception as registration_error:
            raise RuntimeError(
                f"CX319 {selected.gate} firmware entry failed; retained unregistered evidence "
                f"at {run_dir}: {exc}; registration also failed: {registration_error}"
            ) from exc
        raise RuntimeError(
            f"CX319 {selected.gate} firmware entry failed; retained evidence "
            f"{indexed['content_sha256']}: {exc}"
        ) from exc
    manifest_path = run_dir / "run_manifest.json"
    create_run_manifest(
        activation_path=run_activation,
        proposal_path=run_proposal,
        run_dir=run_dir,
        output_path=manifest_path,
        serial_device=device,
    )
    validate_run_manifest(manifest_path)
    finalization_journal = begin_finalization(
        run_dir=run_dir,
        index_path=evidence_index_path,
        required_seal=selected.live_seal_filename,
        registration={
            "source_revision": proposal["source_revision"],
            "build_identity": proposal["firmware"]["build_manifest"]["sha256"],
            "profile_identity": proposal["leg_spec"]["profile_id"],
            "attempt_classification": INTERRUPTED_INDEX_CLASSIFICATION,
            "result_or_failure_reason": f"pending CX319 {selected.gate} finalization",
            "analyzer_identity": _sha256_file(Path(__file__)),
        },
    )

    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    host_abort_fifo = run_dir / "control/host_abort.fifo"
    capture_log = (run_dir / _capture_log(selected)).open("x", encoding="utf-8")
    supervisor_log = (run_dir / _supervisor_log(selected)).open("x", encoding="utf-8")
    capture_args = [
        sys.executable,
        "-m",
        "host.otis_tools.capture_device",
        "--device",
        device,
        "--run-dir",
        str(run_dir),
        "--duration-s",
        str(maximum_wall_s + 180.0),
        "--status-interval",
        "5",
        "--command-fifo",
        str(normal_fifo),
        "--emergency-command-fifo",
        str(emergency_fifo),
        "--write-timeout-s",
        "1",
        "--normal-command-max-age-s",
        "2",
    ]
    capture = subprocess.Popen(
        capture_args,
        cwd=Path(__file__).resolve().parents[2],
        stdout=capture_log,
        stderr=capture_log,
        text=True,
    )
    supervisor: subprocess.Popen[str] | None = None
    orchestration_error: Exception | None = None
    try:
        _wait_until(
            lambda: (
                capture.poll() is None
                and normal_fifo.exists()
                and emergency_fifo.exists()
                and stat.S_ISFIFO(normal_fifo.stat().st_mode)
                and stat.S_ISFIFO(emergency_fifo.stat().st_mode)
                and _capture_state_ready(run_dir, capture.pid)
            ),
            20.0,
            f"{selected.gate} sole capture ownership and bounded command paths",
        )
        expected_build = (
            proposal["firmware"]["source_sha256"]
            + ":"
            + proposal["firmware"]["configuration_sha256"]
        )
        supervisor_args = [
            sys.executable,
            "-m",
            "host.otis_tools.bounded_tight_deadband_supervisor",
            "--manifest",
            str(manifest_path),
            "--run-dir",
            str(run_dir),
            "--command-fifo",
            str(normal_fifo),
            "--emergency-command-fifo",
            str(emergency_fifo),
            "--abort-fifo",
            str(host_abort_fifo),
            "--expected-build-identity",
            expected_build,
            "--duration-s",
            str(maximum_wall_s + 120.0),
        ]
        supervisor = subprocess.Popen(
            supervisor_args,
            cwd=Path(__file__).resolve().parents[2],
            stdout=supervisor_log,
            stderr=supervisor_log,
            text=True,
        )
        _wait_until(
            lambda: supervisor.poll() is None and host_abort_fifo.exists(),
            15.0,
            f"{selected.gate} supervisor and independent host abort",
        )
        _wait_until(
            lambda: _terminal(run_dir) is not None or supervisor.poll() is not None,
            maximum_wall_s + 120.0,
            f"finite {selected.gate} supervisor terminal",
        )
        terminal = _terminal(run_dir)
        if not _terminal_expected(terminal):
            raise RuntimeError(
                f"{selected.gate} supervisor reached a non-canonical terminal: "
                + json.dumps(terminal, sort_keys=True)
            )
        expected_exit = 0 if terminal["result"] == "healthy_stop" else 2
        try:
            supervisor_exit = supervisor.wait(timeout=15.0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{selected.gate} supervisor did not exit at its finite terminal") from exc
        if supervisor_exit != expected_exit:
            raise RuntimeError(
                f"{selected.gate} supervisor exited {supervisor_exit}, expected {expected_exit}"
            )
        _wait_for_terminal_abort_delivery(run_dir, terminal)
        capture_exit = _graceful_capture_stop(capture)
        if capture_exit != 0:
            raise RuntimeError(f"{selected.gate} capture exited with status {capture_exit}")
        advance_phase(
            finalization_journal,
            "capture_closed",
            {"capture_exit": capture_exit},
        )
    except Exception as exc:
        orchestration_error = exc
        _best_effort_emergency_abort(emergency_fifo, capture)
        _graceful_capture_stop(capture)
    finally:
        capture_log.close()
        supervisor_log.close()
        if supervisor is not None and supervisor.poll() is None:
            supervisor.terminate()
            try:
                supervisor.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor.wait(timeout=5.0)
        if capture.poll() is None:
            capture.terminate()
            capture.wait(timeout=5.0)

    if orchestration_error is not None:
        record_failure(
            finalization_journal,
            phase="capture_closed",
            error=orchestration_error,
        )
        try:
            indexed = _retain_failure(
                run_dir=run_dir,
                activation=activation,
                evidence_index_path=evidence_index_path,
                error=orchestration_error,
            )
        except Exception as registration_error:
            raise RuntimeError(
                f"CX319 {selected.gate} orchestration failed; retained unregistered evidence "
                f"at {run_dir}: {orchestration_error}; evidence registration "
                f"also failed: {registration_error}"
            ) from orchestration_error
        raise RuntimeError(
            f"CX319 {selected.gate} orchestration failed; retained evidence "
            f"{indexed['content_sha256']}: {orchestration_error}"
        ) from orchestration_error

    try:
        terminal = _terminal(run_dir)
        assert terminal is not None
        _write_complete(run_dir, terminal, selected)
        advance_phase(finalization_journal, "completion", {"terminal": terminal})
        snapshot_path = create_evidence_snapshot(run_dir)
        loaded = load_manifest(run_dir)
        failures, warnings = validate_evidence_snapshot(run_dir, loaded)
        if failures or warnings:
            raise RuntimeError(
                f"CX319 {selected.gate} evidence snapshot validation failed: "
                + json.dumps({"failures": failures, "warnings": warnings})
            )
        advance_phase(
            finalization_journal,
            "snapshot",
            {"path": str(snapshot_path)},
        )
        seal_path, seal = analyze(run_dir)
        advance_phase(
            finalization_journal,
            "analysis",
            {"status": seal["status"], "tool_sha256": seal["tool_sha256"]},
        )
        advance_phase(
            finalization_journal,
            "seal",
            {"path": str(seal_path), "seal_sha256": seal["seal_sha256"]},
        )
    except Exception as exc:
        phase = next(
            (
                name
                for name in (
                    "completion",
                    "snapshot",
                    "analysis",
                    "seal",
                )
                if json.loads(finalization_journal.read_text())["phases"][name]
                is None
            ),
            "seal",
        )
        record_failure(finalization_journal, phase=phase, error=exc)
        try:
            indexed = _retain_finalization_failure(
                run_dir=run_dir,
                activation=activation,
                proposal=proposal,
                evidence_index_path=evidence_index_path,
                error=exc,
            )
        except Exception as registration_error:
            raise RuntimeError(
                f"CX319 {selected.gate} finalization failed; retained unregistered evidence "
                f"at {run_dir}: {exc}; evidence registration also failed: "
                f"{registration_error}"
            ) from exc
        raise RuntimeError(
            f"CX319 {selected.gate} finalization failed; retained evidence "
            f"{indexed['content_sha256']}: {exc}"
        ) from exc
    classification = (
        COMPLETED_INDEX_CLASSIFICATION
        if seal["status"] in {"passed", "bounded_nonpass"}
        else INTERRUPTED_INDEX_CLASSIFICATION
    )
    registration = {
        "source_revision": proposal["source_revision"],
        "build_identity": proposal["firmware"]["build_manifest"]["sha256"],
        "profile_identity": proposal["leg_spec"]["profile_id"],
        "attempt_classification": classification,
        "result_or_failure_reason": f"CX319 {selected.gate} {seal['status']}",
        "analyzer_identity": seal["tool_sha256"],
    }
    set_registration_intent(
        finalization_journal,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    try:
        indexed = recover_registration(finalization_journal)
    except Exception as exc:
        record_failure(finalization_journal, phase="registration", error=exc)
        raise RuntimeError(
            f"CX319 {selected.gate} sealed package is valid but registration failed; "
            f"recover with evidence_finalization {finalization_journal}: {exc}"
        ) from exc
    if seal["status"] == "failed":
        raise RuntimeError(
            f"CX319 {selected.gate} integrity analysis failed; retained evidence "
            f"{indexed['content_sha256']}"
        )
    return {
        "status": seal["status"],
        "run_dir": str(run_dir),
        "activation_sha256": activation["activation_sha256"],
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "firmware_flashes": int(selected.firmware_flash),
        "analysis_and_seal": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "evidence_snapshot": str(snapshot_path),
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(evidence_index_path.expanduser().resolve()),
        "board": board,
    }


def recover_bounded_tight_deadband_finalization(
    *, run_dir: Path
) -> dict[str, Any]:
    """Finish one unchanged live leg after the evidence-epoch reader escape.

    This path performs no device discovery, serial I/O, firmware upload, DAC
    write, control arm, retry, or restoration.  It is deliberately limited to
    the retained package whose physical acquisition already reached a canonical
    finite terminal and whose first missing phase is the evidence snapshot.
    """

    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest_value = validate_frozen_run_manifest(manifest_path)
    selected = leg_for_manifest(manifest_value)
    if selected.profile_id not in {
        "cx319_range_part_b_lower",
        "cx319_range_part_b_upper",
    }:
        raise ValueError("finalization recovery is limited to mapping-informed Part B")
    journal_path = journal_path_for(run_dir)
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    phases = journal.get("phases", {})
    primary_failure = journal.get("primary_failure", {})
    terminal = _terminal(run_dir)
    if (
        journal.get("run_dir") != str(run_dir)
        or phases.get("capture_closed") is None
        or phases.get("completion") is None
        or any(phases.get(name) is not None for name in ("snapshot", "analysis", "seal"))
        or primary_failure.get("phase") != "snapshot"
        or EVIDENCE_EPOCH_PROFILE_FAILURE not in str(primary_failure.get("error", ""))
        or not _terminal_expected(terminal)
        or not (run_dir / "COMPLETE").is_file()
        or (run_dir / "capture_in_progress.flag").exists()
        or (run_dir / EVIDENCE_MANIFEST).exists()
        or (run_dir / selected.live_seal_filename).exists()
    ):
        raise ValueError(
            "retained leg does not match the bounded evidence-epoch finalization escape"
        )

    raw_path = run_dir / "raw/serial.log"
    raw_sha256 = _sha256_file(raw_path)
    manifest_sha256 = _sha256_file(manifest_path)
    snapshot_path = create_evidence_snapshot(run_dir)
    loaded = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, loaded)
    if failures or warnings:
        raise RuntimeError(
            f"CX319 {selected.gate} recovered evidence snapshot validation failed: "
            + json.dumps({"failures": failures, "warnings": warnings})
        )
    if _sha256_file(raw_path) != raw_sha256 or _sha256_file(manifest_path) != manifest_sha256:
        raise RuntimeError("offline finalization changed frozen acquisition evidence")
    advance_phase(journal_path, "snapshot", {"path": str(snapshot_path)})

    seal_path, seal = analyze(run_dir)
    advance_phase(
        journal_path,
        "analysis",
        {"status": seal["status"], "tool_sha256": seal["tool_sha256"]},
    )
    advance_phase(
        journal_path,
        "seal",
        {"path": str(seal_path), "seal_sha256": seal["seal_sha256"]},
    )

    failure_path = run_dir / _orchestration_failure(selected)
    recovery_report_path = (
        run_dir / f"reports/{selected.prefix}_finalization_recovery_v1.json"
    )
    recovery_report = {
        "schema_version": 1,
        "tool": FINALIZATION_RECOVERY_TOOL_ID,
        "status": "offline_finalization_replayed",
        "run_dir": str(run_dir),
        "gate": selected.gate,
        "leg": selected.leg,
        "original_failure": {
            "path": str(failure_path.relative_to(run_dir)),
            "sha256": _sha256_file(failure_path),
            "error": primary_failure["error"],
        },
        "frozen_acquisition": {
            "run_manifest_sha256": manifest_sha256,
            "raw_serial_sha256": raw_sha256,
            "terminal": terminal,
        },
        "replacement": {
            "runner_sha256": _sha256_file(Path(__file__)),
            "evidence_snapshot_sha256": _sha256_file(snapshot_path),
            "seal_sha256": seal["seal_sha256"],
            "seal_status": seal["status"],
        },
        "raw_acquisition_unchanged": True,
        "physical_rerun": False,
        "device_or_actuator_io": False,
        "claims_boundary": (
            "Deterministic offline snapshot, analysis, seal, and registration "
            "of the unchanged retained physical acquisition only."
        ),
    }
    _atomic_new_json(recovery_report_path, recovery_report)

    classification = (
        COMPLETED_INDEX_CLASSIFICATION
        if seal["status"] in {"passed", "bounded_nonpass"}
        else INTERRUPTED_INDEX_CLASSIFICATION
    )
    registration = {
        "source_revision": manifest_value["firmware"]["git_commit"],
        "build_identity": manifest_value["firmware"]["build_manifest"]["sha256"],
        "profile_identity": manifest_value["cx319"]["profile_id"],
        "attempt_classification": classification,
        "result_or_failure_reason": (
            f"CX319 {selected.gate} {seal['status']} after deterministic "
            "evidence-epoch finalization replay"
        ),
        "analyzer_identity": seal["tool_sha256"],
    }
    set_registration_intent(
        journal_path,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    indexed = recover_registration(journal_path)
    if seal["status"] == "failed":
        raise RuntimeError(
            f"CX319 {selected.gate} integrity analysis failed after offline recovery; "
            f"retained evidence {indexed['content_sha256']}"
        )
    return {
        "status": seal["status"],
        "run_dir": str(run_dir),
        "activation_sha256": manifest_value["activation"]["activation_sha256"],
        "proposal_bundle_sha256": manifest_value["proposal"]["bundle_sha256"],
        "firmware_flashes": int(selected.firmware_flash),
        "analysis_and_seal": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "evidence_snapshot": str(snapshot_path),
        "evidence_content_sha256": indexed["content_sha256"],
        "evidence_index": str(Path(journal["index_path"])),
        "physical_rerun": False,
        "finalization_recovery": str(recovery_report_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    try:
        result = run_bounded_tight_deadband_qualification(
            activation_path=args.activation,
            run_dir=args.run_dir,
            evidence_index_path=args.evidence_index,
            arduino_cli=args.arduino_cli,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
