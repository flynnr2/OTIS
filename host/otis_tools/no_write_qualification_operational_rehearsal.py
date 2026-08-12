"""Rehearse the no-flash, no-write host path without hardware I/O.

The timing state machine is exercised with accelerated firmware uptimes. The
actual analyzer and seal then process a temporary copy of retained passing
Q1 capture/transport evidence rebound to the current exact bundle.
No serial device is opened and no firmware or DAC command is sent.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from typing import Any

from .active_status_live_state import (
    LIVE_STATE_PATH,
    reduce_health_rows,
)
from .capture_segment_rotation import prepare_transition
from .no_write_qualification_analyze import (
    ANALYSIS_PATH,
    FLASH_RECORD_PATH,
    REPORT_PATH,
    SEAL_PATH,
    _atomic_new_json,
    analyze,
    report_markdown,
    seal,
)
from .no_write_qualification_bundle import (
    RUN_BUNDLE_PATH,
    TRANSITION_RUN_DIR,
    create_run_manifest,
    validate_bundle,
)
from .no_write_qualification_supervisor import NoWriteQualificationSupervisor, load_no_write_qualification_spec
from .no_write_prewrite_readiness_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    RUNTIME_CONTRACT_ID,
    canonical_prewrite_fixture,
)
from .evidence import EVIDENCE_MANIFEST, create_evidence_snapshot
from .evidence_index import register_package, validate_index


TOOL_ID = "cx319_g1_no_flash_operational_rehearsal_v1"
RESULT_PATH = Path("cx319_g1_no_flash_operational_rehearsal_v1.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _ignore_nonregular_entries(directory: str, names: list[str]) -> list[str]:
    ignored: list[str] = []
    root = Path(directory)
    for name in names:
        mode = (root / name).lstat().st_mode
        if not (
            stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)
        ):
            ignored.append(name)
    return ignored


def _replace_json(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _replace_build_identity(path: Path, expected_build: str) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    if not fields:
        raise ValueError(f"health CSV has no header: {path}")
    replacements = 0
    for row in rows:
        if (
            row.get("record_type") == "STS"
            and row.get("component") == "cx317_active"
            and row.get("status_key") == "build_identity"
        ):
            row["status_value"] = expected_build
            replacements += 1
    if replacements == 0:
        raise ValueError(f"health CSV has no build identity: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _publish_replayed_live_state(health_path: Path, state_path: Path) -> None:
    with health_path.open(newline="", encoding="utf-8") as handle:
        state = reduce_health_rows(csv.DictReader(handle))
    if state is None or state.get("state") != "complete":
        raise ValueError(
            f"replayed health has no complete live state: {health_path}"
        )
    _replace_json(
        state_path,
        {
            **state,
            "observed_utc": _utc_now(),
            "observed_monotonic_ns": time.monotonic_ns(),
            "capture_pid": os.getpid(),
            "transport_generation": 1,
            "replay_derived": True,
            "source_health_path": str(health_path),
        },
    )


def _replace_capture_stop_target(path: Path, next_run: Path) -> None:
    prefix = "# OTIS_HOST "
    lines = path.read_text(encoding="utf-8").splitlines()
    replacements = 0
    output: list[str] = []
    for line in lines:
        if not line.startswith(prefix):
            output.append(line)
            continue
        marker = json.loads(line[len(prefix) :])
        if marker.get("event") == "capture_stopped" and marker.get(
            "logical_rotation"
        ) is True:
            marker["next_run"] = str(next_run)
            line = prefix + json.dumps(marker, sort_keys=True)
            replacements += 1
        output.append(line)
    if replacements != 1:
        raise ValueError("expected exactly one logical capture-stop marker")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _first_observation(
    path: Path, component: str, status_key: str
) -> tuple[int, int]:
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                row.get("record_type") == "STS"
                and row.get("component") == component
                and row.get("status_key") == status_key
            ):
                return int(row["status_seq"]), int(row["status_value"])
    raise ValueError(f"missing {component}.{status_key} in {path}")


def _source_exercised_q1_detach(run_dir: Path) -> bool:
    state = json.loads(
        (run_dir / "reports/capture_device_state.json").read_text(
            encoding="utf-8"
        )
    )
    reconnects = int(state.get("reconnect_count", 0))
    detaches = int(state.get("intentional_detach_count", 0))
    if reconnects != detaches:
        raise ValueError("replay source reconnect/detach evidence is inconsistent")
    return detaches > 0


def _exercise_timing_contract(bundle: dict[str, Any], root: Path) -> dict[str, Any]:
    run_dir = root / "accelerated-supervisor"
    (run_dir / "csv").mkdir(parents=True)
    spec, identities, leg = load_no_write_qualification_spec("A")
    build_identity = (
        bundle["firmware"]["source_sha256"]
        + ":"
        + bundle["firmware"]["configuration_sha256"]
    )
    sequence_gate = bundle.get("qualification_sequence_gate", "Q1")
    supervisor = NoWriteQualificationSupervisor(
        leg=leg,
        run_dir=run_dir,
        command_fifo=root / "normal.fifo",
        emergency_command_fifo=root / "emergency.fifo",
        abort_fifo=root / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=build_identity,
        duration_s=None,
        qualification_sequence_gate=sequence_gate,
    )
    supervisor.state.update(
        telemetry_drop_baseline=0,
        telemetry_drop_baseline_status_seq=2,
        host_attach_uptime_s=30,
        host_attach_uptime_status_seq=1,
    )
    expected_identity = {
        "run_identity": spec.run_identity,
        "build_identity": build_identity,
        "profile_identity": spec.profile,
        **identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected_identity,
        planned_live_stimulus_code=spec.start_code,
    )
    health[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    health[("cx317_active", "snapshot_generation_complete")] = "7"
    health[("gnss_receiver", "raw_pps_control_eligible")] = "false"
    health[("gnss_receiver", "control_eligible")] = "false"
    health[("cx317_active", "uptime_s")] = "30"
    before = supervisor._check_prewrite_contract(health, 30.0)
    health[("gnss_receiver", "raw_pps_control_eligible")] = "true"
    health[("gnss_receiver", "control_eligible")] = "true"
    health[("cx317_active", "uptime_s")] = "612"
    ready = supervisor._check_prewrite_contract(health, 612.0)

    deadline_dir = root / "accelerated-deadline"
    (deadline_dir / "csv").mkdir(parents=True)
    deadline = NoWriteQualificationSupervisor(
        leg=leg,
        run_dir=deadline_dir,
        command_fifo=root / "deadline-normal.fifo",
        emergency_command_fifo=root / "deadline-emergency.fifo",
        abort_fifo=root / "deadline-abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=build_identity,
        duration_s=None,
        qualification_sequence_gate=sequence_gate,
    )
    deadline.state.update(
        telemetry_drop_baseline=0,
        telemetry_drop_baseline_status_seq=2,
        host_attach_uptime_s=30,
        host_attach_uptime_status_seq=1,
    )
    health[("cx317_active", "query_nonce")] = str(
        deadline.state["host_attach_query_nonce"]
    )
    health[("gnss_receiver", "raw_pps_control_eligible")] = "false"
    health[("gnss_receiver", "control_eligible")] = "false"
    deadline_rejected = False
    try:
        deadline._check_prewrite_contract(
            health, RAW_PPS_QUALIFICATION_DEADLINE_S
        )
    except ValueError as exc:
        deadline_rejected = "raw_pps_control_eligible" in str(exc)

    stale = dict(health)
    stale[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    stale[("gnss_receiver", "identity_epoch")] = "2"
    epoch_two_rejected = not supervisor._prewrite_readiness(stale).ready
    supervisor.state["host_attach_uptime_s"] = 121
    health[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    late_attach_rejected = not supervisor._prewrite_readiness(health).ready
    return {
        "contract_id": RUNTIME_CONTRACT_ID,
        "incomplete_at_30s_is_nonterminal": before is not None and not before.ready,
        "ready_at_observed_612s": ready is not None and ready.ready,
        "missing_pps_at_660s_is_terminal": deadline_rejected,
        "epoch_two_rejected": epoch_two_rejected,
        "host_attach_after_120s_rejected": late_attach_rejected,
    }


def _prepare_replay(
    *, bundle_path: Path, source_run: Path, replay_run: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = validate_bundle(bundle_path)
    entry_mode = bundle.get("firmware_entry", {}).get("mode")
    if entry_mode not in {
        "single_exact_flash",
        "reuse_confirmed_installed_firmware",
    }:
        raise ValueError("operational rehearsal firmware entry is invalid")
    shutil.copytree(
        source_run,
        replay_run,
        ignore=_ignore_nonregular_entries,
    )
    for relative in (
        EVIDENCE_MANIFEST,
        ANALYSIS_PATH,
        REPORT_PATH,
        SEAL_PATH,
        replay_run / "COMPLETE",
    ):
        path = relative if isinstance(relative, Path) and relative.is_absolute() else replay_run / relative
        path.unlink(missing_ok=True)

    copied_bundle = replay_run / RUN_BUNDLE_PATH
    copied_bundle.unlink()
    shutil.copy2(bundle_path, copied_bundle)
    manifest_path = replay_run / "run_manifest.json"
    manifest_path.unlink(missing_ok=True)
    manifest = create_run_manifest(
        bundle_path=copied_bundle,
        run_dir=replay_run,
        output_path=manifest_path,
        q1_real_io=_source_exercised_q1_detach(replay_run),
    )
    sequence_gate = bundle.get("qualification_sequence_gate", "Q1")
    if sequence_gate == "Q3":
        _atomic_new_json(
            replay_run / "reports/cx319_q3_topology_confirmation_v1.json",
            {
                "schema_version": 1,
                "report_type": "cx319_q3_topology_confirmation_v1",
                "status": "operator_confirmed",
                "recorded_utc": _utc_now(),
                "qualification_sequence_gate": "Q3",
                "dac_analogue_output": (
                    "reconnected_to_oscillator_efc_vctrl"
                ),
                "oscillator_powered": True,
                "q2_inhibited_interval_ended": True,
                "physical_write_authority": False,
                "offline_rehearsal_only": True,
            },
        )
    transition = replay_run / TRANSITION_RUN_DIR
    with tempfile.TemporaryDirectory(prefix="cx319-g1-transition-") as raw_temp:
        generated = prepare_transition(manifest_path, Path(raw_temp) / "transition")
        shutil.copy2(generated, transition / "run_manifest.json")

    _replace_capture_stop_target(replay_run / "raw/serial.log", transition)
    primary_closure_path = (
        replay_run / "reports/capture_segment_closure_v1.json"
    )
    primary_closure = json.loads(
        primary_closure_path.read_text(encoding="utf-8")
    )
    primary_closure["run"] = str(replay_run)
    primary_closure["next_run"] = str(transition)
    primary_closure["run_manifest_sha256"] = _sha256_file(manifest_path)
    _replace_json(primary_closure_path, primary_closure)
    transition_closure_path = (
        transition / "reports/capture_segment_closure_v1.json"
    )
    transition_closure = json.loads(
        transition_closure_path.read_text(encoding="utf-8")
    )
    transition_closure["run"] = str(transition)
    transition_closure["run_manifest_sha256"] = _sha256_file(
        transition / "run_manifest.json"
    )
    _replace_json(transition_closure_path, transition_closure)
    transport_path = replay_run / "reports/cx319_g1_transport_rehearsal_v1.json"
    transport = json.loads(transport_path.read_text(encoding="utf-8"))
    transport["owner_handoff"]["from_run"] = str(replay_run)
    transport["owner_handoff"]["to_run"] = str(transition)
    _replace_json(transport_path, transport)

    expected_build = (
        bundle["firmware"]["source_sha256"]
        + ":"
        + bundle["firmware"]["configuration_sha256"]
    )
    for health_path in (
        replay_run / "csv/health.csv",
        transition / "csv/health.csv",
    ):
        _replace_build_identity(health_path, expected_build)
        _publish_replayed_live_state(
            health_path,
            health_path.parents[1] / LIVE_STATE_PATH,
        )

    state_path = replay_run / "reports/cx317_active_supervisor_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    attach_seq, attach_uptime = _first_observation(
        replay_run / "csv/health.csv", "cx317_active", "uptime_s"
    )
    state["host_attach_uptime_s"] = attach_uptime
    state["host_attach_uptime_status_seq"] = attach_seq
    state["qualification_sequence_gate"] = sequence_gate
    state["latest_prewrite_readiness"]["contract_id"] = RUNTIME_CONTRACT_ID
    started = datetime.fromisoformat(
        str(state["supervisor_started_utc"]).replace("Z", "+00:00")
    )
    state["prewrite_contract_ready_utc"] = (
        started + timedelta(seconds=612)
    ).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    _replace_json(state_path, state)

    entry = bundle["firmware_entry"]
    source_flash = json.loads(
        (replay_run / FLASH_RECORD_PATH).read_text(encoding="utf-8")
    )
    flash: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "pass",
        "qualification_sequence_gate": sequence_gate,
        "firmware_flashes": 0,
        "device": bundle["device"]["path"],
        "bundle_sha256": bundle["bundle_sha256"],
        "profile_id": bundle["firmware"]["profile_id"],
        "build_manifest_sha256": bundle["firmware"]["build_manifest"]["sha256"],
        "uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "dac_boot_operation": "offline_replay_no_hardware_io",
        "dac_value_write_attempts": 0,
        "setup_stimulus_attempts": 0,
        "control_arm_attempts": 0,
    }
    if entry_mode == "single_exact_flash":
        board = source_flash["board_after"]
        flash.update(
            operation="exact_cx319_g1_firmware_flash",
            attempt_count=1,
            board_before=board,
            board_after=board,
            command=["offline-operational-rehearsal", "exact-flash"],
            exit_code=0,
            offline_flash_execution=False,
        )
    else:
        board = entry["installed_board"]
        flash.update(
            operation="confirmed_installed_cx319_g1_firmware_reuse",
            attempt_count=0,
            board_before=board,
            board_after=board,
            installed_board=board,
            source_flash_record=entry["source_flash_record"],
            source_bundle=entry["source_bundle"],
            source_bundle_sha256=entry["source_bundle_sha256"],
            source_build_manifest_sha256=(
                entry["source_build_manifest_sha256"]
            ),
            installed_uf2_sha256=entry["installed_uf2_sha256"],
        )
    _replace_json(replay_run / FLASH_RECORD_PATH, flash)
    return bundle, manifest


def run(*, bundle_path: Path, source_run: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    timing = _exercise_timing_contract(
        validate_bundle(bundle_path), output_dir / "timing"
    )
    replay_run = output_dir / "replay_run"
    bundle, _manifest = _prepare_replay(
        bundle_path=bundle_path.resolve(),
        source_run=source_run.resolve(),
        replay_run=replay_run,
    )
    sequence_gate = bundle.get("qualification_sequence_gate", "Q1")
    analysis = analyze(replay_run)
    _atomic_new_json(replay_run / ANALYSIS_PATH, analysis)
    (replay_run / REPORT_PATH).write_text(
        report_markdown(analysis), encoding="utf-8"
    )
    (replay_run / "COMPLETE").write_text(
        f"CX319 {sequence_gate} offline operational replay complete\n",
        encoding="utf-8",
    )
    snapshot = create_evidence_snapshot(replay_run)
    seal_value = seal(replay_run, analysis)
    with tempfile.TemporaryDirectory(
        prefix="cx319-g1-registration-rehearsal-"
    ) as raw_temp:
        index = Path(raw_temp) / "evidence_index_v1.json"
        registered = register_package(
            index_path=index,
            package_path=replay_run,
            source_revision=bundle["host_source_revision"],
            build_identity=bundle["firmware"]["build_manifest"]["sha256"],
            profile_identity=bundle["firmware"]["profile_id"],
            attempt_classification=(
                "successful_qualification"
                if sequence_gate == "Q3"
                else "successful_rehearsal"
            ),
            result_or_failure_reason=(
                f"CX319 {sequence_gate} offline operational replay passed"
            ),
            analyzer_identity=analysis["bindings"]["analyzer_sha256"],
        )
        registration = validate_index(index)
    checks = {
        **timing,
        "actual_analyzer_passed": analysis["status"] == "pass",
        "actual_seal_passed": seal_value["status"] == "pass",
        "temporary_registration_passed": (
            registration["valid"] is True
            and registration["package_count"] == 1
        ),
        "zero_hardware_operations": True,
    }
    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "passed" if all(checks.values()) else "failed",
        "bundle_sha256": bundle["bundle_sha256"],
        "host_source_revision": bundle["host_source_revision"],
        "qualification_sequence_gate": sequence_gate,
        "installed_uf2_sha256": bundle["firmware_entry"].get(
            "installed_uf2_sha256", bundle["firmware"]["uf2"]["sha256"]
        ),
        "checks": checks,
        "analysis_sha256": analysis["analysis_sha256"],
        "analysis_file_sha256": _sha256_file(replay_run / ANALYSIS_PATH),
        "seal_sha256": seal_value["seal_sha256"],
        "seal_file_sha256": _sha256_file(replay_run / SEAL_PATH),
        "snapshot_sha256": _sha256_file(snapshot),
        "registered_content_sha256": registered["content_sha256"],
        "hardware_operations": {
            "serial_opens": 0,
            "firmware_flashes": 0,
            "commands_sent_to_device": 0,
            "dac_writes": 0,
            "control_arms": 0,
        },
        "claims_boundary": (
            "Accelerated timing-state execution plus actual analyzer, seal and "
            "temporary registration over retained passing capture/transport "
            "evidence; no current physical or scientific result."
        ),
    }
    _atomic_new_json(output_dir / RESULT_PATH, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(
        bundle_path=args.bundle,
        source_run=args.source_run,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
