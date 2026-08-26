"""Run one finite, actively monitored targeted equilibrium characterization."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

from .capture_runtime_checks import _capture_state_ready, _serial_owner_pids
from .evidence_index import DEFAULT_INDEX, register_package
from .range_spanning_bundle import _atomic_new_json, canonical_sha256, sha256_file
from .range_spanning_run import (
    _abort_delivery,
    _append_event,
    _create_validated_evidence_snapshot,
    _exact_estimates_present,
    _find_epoch_propagation,
    _find_exact_dac,
    _flash,
    _locate_board,
    _latest_health,
    _point_tdb_rows,
    _prewrite_ready,
    _replace_json,
    _wait,
    _write_complete,
)
from .run_paths import default_csv_files
from .serial_commands import send_timestamped_command_to_fifo
from .targeted_equilibrium_analyze import analyze
from .targeted_equilibrium_bundle import (
    gnss_health_reasons,
    split_runtime_gnss_reasons,
    validate_bundle,
)


TOOL_ID = "otis_targeted_equilibrium_run_v1"
LIVE_STAGE = "CX319_TARGETED_EQUILIBRIUM_CHARACTERIZATION_LIVE"
EVENTS = Path("reports/targeted_equilibrium_supervisor_events.jsonl")
STATE = Path("reports/targeted_equilibrium_supervisor_state.json")
ACTIVATION = Path("targeted_equilibrium_live_activation_v1.json")
CAPTURE_LOG = Path("reports/targeted_equilibrium_capture.log")
ANALYSIS = Path("reports/targeted_equilibrium_analysis_v1.json")
SEAL = Path("reports/targeted_equilibrium_seal_v1.json")
FINALIZATION_FAILURE = Path("reports/targeted_equilibrium_finalization_failure_v1.json")
ENTRY_RECORD = Path("reports/range_spanning_firmware_entry_v2.json")
POLICY_PATH = Path("profiles/discipline/cx319_stabilized_tight_deadband_v1.json")
ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("wall deadline must include a timezone")
    return parsed.astimezone(timezone.utc)


def _create_manifest(
    *, run_dir: Path, bundle_path: Path, bundle: dict[str, Any], device: str
) -> None:
    files = default_csv_files()
    evidence = [
        str(EVENTS),
        str(STATE),
        str(ENTRY_RECORD),
        str(CAPTURE_LOG),
        str(ACTIVATION),
        str(ANALYSIS),
        str(SEAL),
        "reports/capture_device_state.json",
        "COMPLETE",
    ]
    firmware = bundle["firmware"]
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "actionable": False,
        "actuation_authorized": True,
        "closed_loop_control": False,
        "control_mode": "externally_precommitted_targeted_open_loop_characterization",
        "cx319": {
            "profile_id": "cx319_range_map_part_a",
            "mode": "targeted_equilibrium_characterization",
            "authority": {
                "effective": True,
                "physical_execution": True,
                "firmware_flash": True,
                "board_reset": True,
                "serial_open": True,
                "predetermined_dac_setup_stimuli": True,
                "automatic_frequency_control": False,
                "phase_or_hybrid_actionable": False,
            },
        },
        "host": {
            "tool": TOOL_ID,
            "serial_device": device,
            "baud": bundle["device"]["baud"],
            "sole_serial_owner": True,
            "normal_command_ingress": "timestamped_bounded_fifo",
            "priority_abort_ingress": "independent_fifo",
        },
        "firmware": {
            "profile_id": firmware["profile_id"],
            "fqbn": firmware["fqbn"],
            "git_commit": firmware["git_commit"],
            "source_sha256": firmware["source_sha256"],
            "configuration_sha256": firmware["configuration_sha256"],
            "build_invocation_id": firmware["build_invocation_id"],
            "build_manifest": firmware["build_manifest"],
            "uf2": firmware["uf2"],
            "build_provenance_required": True,
        },
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "entry": bundle["entry"],
        "policy": {
            "path": str((ROOT / POLICY_PATH).resolve()),
            "sha256": sha256_file(ROOT / POLICY_PATH),
        },
        "domains": [
            {
                "name": "rp2040_timer0",
                "nominal_hz": 16_000_000,
                "counter_width_bits": 36,
                "modulus_ticks": 68_719_476_736,
                "rollover": "modular_forward",
                "maximum_unambiguous_forward_ticks": 34_359_738_368,
            },
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {
                "channel_id": 1,
                "role": "authoritative_d14_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "role": "authoritative_d8_pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
        ],
        "contracts": {
            item["contract"]: 2 if item["contract"] == "estimates_v2" else 1
            for item in files
        },
        "files": files,
        "expected_artifacts": [
            *(item["path"] for item in files if not item.get("optional")),
            "raw/serial.log",
            *evidence,
        ],
        "evidence_artifacts": evidence,
        "known_limitations": [
            "Predetermined open-loop characterization only; no frequency, phase, or hybrid control authority.",
            "D10 remains an external event input and has no PPS or control role.",
            "SHT41 is nearby-air context, not CX317 internal temperature.",
        ],
    }
    _atomic_new_json(run_dir / "run_manifest.json", manifest)


def _selected_rows(
    run_dir: Path, *, after_sequence: int, epoch: int
) -> list[dict[str, str]] | None:
    rows = _point_tdb_rows(run_dir, after_sequence=after_sequence, epoch=epoch)
    if len(rows) < 3:
        return None
    selected = rows[:3]
    if not _exact_estimates_present(run_dir, selected):
        raise RuntimeError("selected estimate identity did not reach TDB consumer")
    return selected


def _targeted_prewrite_ready(
    run_dir: Path, bundle: dict[str, Any]
) -> tuple[bool, list[str]]:
    ready, reasons = _prewrite_ready(run_dir, bundle)
    health = _latest_health(run_dir)
    reasons.extend(
        "gnss_receiver." + reason
        for reason in gnss_health_reasons(bundle["gnss_live_boundary"], health)
    )
    return ready and not reasons, reasons


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _require_gnss_stable(run_dir: Path, bundle: dict[str, Any]) -> bool:
    """Return readiness for transient gates; raise for invariant violations.

    The receiver metadata and D14 qualification flags can briefly deassert and
    requalify without changing receiver identity, configuration, or the
    authoritative hardware capture.  The caller's existing bounded wait owns
    the deadline for those two conditions.  Persistent identity, link,
    configuration, baud, and failure-counter contradictions remain immediate
    stop conditions.
    """
    health = _latest_health(run_dir)
    gnss_contract = bundle["gnss_live_boundary"]
    mismatches = gnss_health_reasons(gnss_contract, health)
    held_mismatches, invariant_mismatches = split_runtime_gnss_reasons(
        gnss_contract, mismatches
    )
    if invariant_mismatches:
        raise RuntimeError(
            f"GNSS {gnss_contract.get('target_baud', 'target-baud')} stability invariant: "
            + "; ".join(invariant_mismatches)
        )
    return not held_mismatches


def _guarded(run_dir: Path, bundle: dict[str, Any], predicate: Any) -> Any:
    if not _require_gnss_stable(run_dir, bundle):
        return False
    return predicate()


def run(
    *,
    bundle_path: Path,
    run_dir: Path,
    wall_deadline_utc: str,
    evidence_index_path: Path,
    arduino_cli: str,
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    bundle = validate_bundle(bundle_path)
    run_dir = run_dir.resolve()
    deadline = _parse_utc(wall_deadline_utc)
    if (deadline - datetime.now(timezone.utc)).total_seconds() < bundle["timing"][
        "maximum_live_wall_s"
    ]:
        raise ValueError("live deadline is shorter than the frozen maximum live wall")
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    (run_dir / "reports").mkdir()
    activation_unsigned = {
        "schema_version": 1,
        "activation_type": "otis_targeted_equilibrium_live_activation_v1",
        "created_utc": _utc_now(),
        "effective": True,
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "run_dir": str(run_dir),
        "wall_deadline_utc": deadline.isoformat().replace("+00:00", "Z"),
        "firmware_flashes_allowed": 1,
        "board_resets_allowed": 1,
        "predetermined_dac_applications_allowed": 12,
        "automatic_retry": False,
        "automatic_restore": False,
        "frequency_control_authority": False,
        "phase_or_hybrid_actuation": False,
    }
    activation = {
        **activation_unsigned,
        "activation_sha256": canonical_sha256(activation_unsigned),
    }
    _atomic_new_json(run_dir / ACTIVATION, activation)
    state: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "run_id": run_dir.name,
        "bundle_sha256": bundle["bundle_sha256"],
        "activation_sha256": activation["activation_sha256"],
        "wall_deadline_utc": wall_deadline_utc,
        "phase": "bundle_activated",
        "completed_dwells": [],
        "terminal": None,
    }
    _replace_json(run_dir / STATE, state)
    _append_event(run_dir / EVENTS, {"event": "bundle_activated", **activation})
    print(f"MILESTONE exact bundle activated {activation['activation_sha256']}", flush=True)

    device, board = _locate_board(
        bundle["device"]["expected_board_serial"], arduino_cli=arduino_cli
    )
    owners = _serial_owner_pids(device)
    if owners:
        raise ValueError(f"serial device already has owners: {sorted(owners)}")
    device, board = _flash(
        run_dir=run_dir,
        bundle=bundle,
        device=device,
        board=board,
        arduino_cli=arduino_cli,
    )
    print(
        f"MILESTONE firmware flashed profile={bundle['firmware']['profile_id']} "
        f"uf2={bundle['firmware']['uf2']['sha256']}",
        flush=True,
    )
    _create_manifest(
        run_dir=run_dir, bundle_path=bundle_path, bundle=bundle, device=device
    )
    normal_fifo = run_dir / "control/normal_commands.fifo"
    emergency_fifo = run_dir / "control/emergency_abort.fifo"
    capture_log_handle = (run_dir / CAPTURE_LOG).open("x", encoding="utf-8")
    capture = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "host.otis_tools.capture_device",
            "--device",
            device,
            "--run-dir",
            str(run_dir),
            "--duration-s",
            str(max(60.0, (deadline - datetime.now(timezone.utc)).total_seconds() + 180.0)),
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
        ],
        cwd=ROOT,
        stdout=capture_log_handle,
        stderr=capture_log_handle,
        text=True,
    )
    terminal: dict[str, Any] | None = None
    capture_ready_monotonic = time.monotonic()
    try:
        _wait(
            lambda: _capture_state_ready(run_dir, capture.pid),
            timeout_s=30,
            description="sole-owner capture start",
            run_dir=run_dir,
            wall_deadline=deadline,
            runtime_monitoring_active=False,
        )
        capture_ready_monotonic = time.monotonic()
        if _serial_owner_pids(device) != {capture.pid}:
            raise RuntimeError("capture is not the sole serial owner")
        for command in bundle["command_envelope"]["prewrite_queries"]:
            send_timestamped_command_to_fifo(normal_fifo, command)
        state["phase"] = "prewrite_gate"
        _replace_json(run_dir / STATE, state)
        print("MILESTONE serial capture established; prewrite gate running", flush=True)

        _wait(
            lambda: _targeted_prewrite_ready(run_dir, bundle)[0],
            timeout_s=720,
            description="exact firmware, GNSS, D14, D8, and partition prewrite gate",
            run_dir=run_dir,
            wall_deadline=deadline,
        )
        ready, reasons = _targeted_prewrite_ready(run_dir, bundle)
        if not ready:
            raise RuntimeError("prewrite gate regressed: " + "; ".join(reasons))
        _append_event(run_dir / EVENTS, {"event": "prewrite_gate_passed"})
        print("MILESTONE live prewrite gate passed", flush=True)
        state["phase"] = "initial_warmup"
        _replace_json(run_dir / STATE, state)
        warmup_s = float(bundle["timing"]["initial_capture_owned_warmup_s"])
        _wait(
            lambda: _guarded(
                run_dir,
                bundle,
                lambda: time.monotonic() - capture_ready_monotonic >= warmup_s,
            ),
            timeout_s=warmup_s + 120,
            description="frozen 1800-second capture-owned warmup",
            run_dir=run_dir,
            wall_deadline=deadline,
            # The targeted predicate holds on transient GNSS/D14 qualification
            # loss.  The shared runtime guard still enforces capture, queue,
            # partition, and transport faults without treating one status
            # sample as a terminal receiver contradiction.
            require_qualified_health=False,
        )
        _append_event(
            run_dir / EVENTS,
            {
                "event": "initial_warmup_complete",
                "minimum_elapsed_s": warmup_s,
                "observed_elapsed_s": time.monotonic() - capture_ready_monotonic,
                "scheduling_domain": "host_monotonic",
            },
        )
        print("MILESTONE initial 1800-second warmup complete", flush=True)
        state["phase"] = "dwell_sequence"
        _replace_json(run_dir / STATE, state)

        for dwell in bundle["dwell_plan"]:
            index = int(dwell["index"])
            code = int(dwell["code"])
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining < bundle["timing"]["minimum_remaining_wall_before_new_dwell_s"]:
                raise RuntimeError("insufficient_remaining_wall_before_frozen_dwell")
            # Read through the proven range-run helpers to bind each request to
            # new producer and consumer identities rather than merely to a write.
            prior_dac = max(
                (int(row["seq"]) for row in _read_csv(run_dir / "csv/dac_steps.csv")),
                default=-1,
            )
            prior_tdb = max(
                (
                    int(row["decision_sequence"])
                    for row in _read_csv(run_dir / "csv/tight_deadband_decisions_v1.csv")
                ),
                default=-1,
            )
            hybrid_rows = _read_csv(run_dir / "csv/hybrid_preview_decisions_v1.csv")
            prior_hybrid = max(
                (int(row["preview_sequence"]) for row in hybrid_rows), default=-1
            )
            prior_epoch = max((int(row["dac_epoch"]) for row in hybrid_rows), default=-1)
            command = f"DAC SET 0x{code:04X}"
            send_timestamped_command_to_fifo(normal_fifo, command)
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "dwell_command_sent",
                    "dwell_index": index,
                    "label": dwell["label"],
                    "code": code,
                    "partition": dwell["partition"],
                    "command": command,
                },
            )
            print(
                f"MILESTONE dwell {index + 1}/12 command sent code=0x{code:04X}",
                flush=True,
            )
            dac = _wait(
                lambda: _guarded(
                    run_dir,
                    bundle,
                    lambda: _find_exact_dac(
                        run_dir, after_sequence=prior_dac, code=code
                    ),
                ),
                timeout_s=15,
                description=f"dwell {index + 1} exact DAC acknowledgement",
                run_dir=run_dir,
                wall_deadline=deadline,
                require_qualified_health=False,
            )
            applied_monotonic = time.monotonic()
            propagation = _wait(
                lambda: _guarded(
                    run_dir,
                    bundle,
                    lambda: _find_epoch_propagation(
                        run_dir,
                        after_preview_sequence=prior_hybrid,
                        after_epoch=prior_epoch,
                        code=code,
                    ),
                ),
                timeout_s=30,
                description=f"dwell {index + 1} cross-core epoch propagation",
                run_dir=run_dir,
                wall_deadline=deadline,
                require_qualified_health=False,
            )
            epoch = int(propagation["dac_epoch"])
            _append_event(
                run_dir / EVENTS,
                {
                    "event": "dwell_application_acknowledged",
                    "dwell_index": index,
                    "code": code,
                    "dac_sequence": int(dac["seq"]),
                    "dac_epoch": epoch,
                },
            )
            print(
                f"MILESTONE dwell {index + 1}/12 applied code=0x{code:04X} epoch={epoch}",
                flush=True,
            )

            def complete_support() -> list[dict[str, str]] | None:
                def qualified_support() -> list[dict[str, str]] | None:
                    selected = _selected_rows(
                        run_dir, after_sequence=prior_tdb, epoch=epoch
                    )
                    if selected is None:
                        return None
                    if time.monotonic() - applied_monotonic < bundle["timing"][
                        "minimum_dwell_s"
                    ]:
                        return None
                    return selected

                return _guarded(run_dir, bundle, qualified_support)

            selected = _wait(
                complete_support,
                timeout_s=bundle["timing"]["dwell_wait_timeout_s"],
                description=f"dwell {index + 1} three fresh contiguous selected600 supports",
                run_dir=run_dir,
                wall_deadline=deadline,
                require_qualified_health=False,
            )
            result = {
                "dwell_index": index,
                "label": dwell["label"],
                "code": code,
                "code_hex": f"0x{code:04X}",
                "partition": dwell["partition"],
                "history_class": dwell["history_class"],
                "dac_sequence": int(dac["seq"]),
                "dac_epoch": epoch,
                "tdb_sequences": [int(row["decision_sequence"]) for row in selected],
                "integer_edge_error_counts": [
                    int(row["integer_edge_error_counts"]) for row in selected
                ],
                "minimum_elapsed_s": bundle["timing"]["minimum_dwell_s"],
                "observed_elapsed_s": time.monotonic() - applied_monotonic,
                "first_dependent_consumer_estimate_id": selected[0]["estimate_id"],
            }
            state["completed_dwells"].append(result)
            _append_event(run_dir / EVENTS, {"event": "dwell_completed", **result})
            _replace_json(run_dir / STATE, state)
            print(
                f"MILESTONE dwell {index + 1}/12 complete counts={result['integer_edge_error_counts']}",
                flush=True,
            )
        terminal = {
            "event": "terminal",
            "result": "healthy_stop",
            "reason": "targeted_characterization_complete",
            "completed_dwell_count": len(state["completed_dwells"]),
            "last_confirmed_code": state["completed_dwells"][-1]["code"],
            "automatic_restore_performed": False,
        }
    except Exception as exc:
        terminal = {
            "event": "terminal",
            "result": "aborted",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "completed_dwell_count": len(state["completed_dwells"]),
        }
        try:
            _abort_delivery(emergency_fifo, run_dir)
            terminal["priority_abort_delivery"] = "sent"
        except Exception as abort_exc:
            terminal["priority_abort_delivery"] = "failed"
            terminal["priority_abort_error"] = str(abort_exc)
    finally:
        assert terminal is not None
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            capture.wait(timeout=30)
        except subprocess.TimeoutExpired:
            capture.terminate()
            capture.wait(timeout=10)
        capture_log_handle.close()
        if capture.returncode != 0:
            terminal = {
                "event": "terminal",
                "result": "aborted",
                "reason": f"capture_process_exit_{capture.returncode}",
                "prior_terminal": terminal,
                "completed_dwell_count": len(state["completed_dwells"]),
            }
        _append_event(run_dir / EVENTS, terminal)
        state["terminal"] = terminal
        state["phase"] = "terminal"
        _replace_json(run_dir / STATE, state)

    _write_complete(run_dir, terminal)
    analysis = analyze(
        bundle_path=bundle_path,
        run_dir=run_dir,
        output_path=run_dir / ANALYSIS,
        seal_path=run_dir / SEAL,
    )
    try:
        snapshot = _create_validated_evidence_snapshot(run_dir)
        finalization: dict[str, Any] = {
            "status": "passed",
            "snapshot_digest": snapshot["snapshot_digest"],
        }
    except Exception as exc:
        unsigned = {
            "schema_version": 1,
            "tool": TOOL_ID,
            "status": "failed",
            "recorded_utc": _utc_now(),
            "run_id": run_dir.name,
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "raw_capture_preserved": (run_dir / "raw/serial.log").is_file(),
            "evidence_status": analysis["evidence_status"],
            "terminal_result": terminal["result"],
        }
        finalization = {**unsigned, "record_sha256": canonical_sha256(unsigned)}
        _atomic_new_json(run_dir / FINALIZATION_FAILURE, finalization)
    registration = register_package(
        index_path=evidence_index_path.resolve(),
        package_path=run_dir,
        source_revision=bundle["firmware"]["git_commit"],
        build_identity=bundle["firmware"]["build_manifest"]["sha256"],
        profile_identity=bundle["firmware"]["profile_id"],
        attempt_classification=(
            "completed_campaign"
            if terminal["result"] == "healthy_stop"
            and analysis["evidence_status"] == "passed"
            else "interrupted_campaign"
        ),
        result_or_failure_reason=(
            f"targeted equilibrium: {terminal['reason']}; "
            f"{analysis['scientific_terminal']}"
        ),
        analyzer_identity=sha256_file(
            Path(__file__).with_name("targeted_equilibrium_analyze.py")
        ),
    )
    print(
        f"MILESTONE run terminal result={terminal['result']} reason={terminal['reason']} "
        f"dwells={len(state['completed_dwells'])} scientific={analysis['scientific_terminal']} "
        f"evidence={registration['content_sha256']} finalization={finalization['status']}",
        flush=True,
    )
    return {
        "terminal": terminal,
        "analysis": analysis,
        "evidence_finalization": finalization,
        "evidence_index_record": registration,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--wall-deadline-utc", required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    result = run(
        bundle_path=args.bundle,
        run_dir=args.run_dir,
        wall_deadline_utc=args.wall_deadline_utc,
        evidence_index_path=args.evidence_index,
        arduino_cli=args.arduino_cli,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if (
        result["terminal"]["result"] == "healthy_stop"
        and result["analysis"]["evidence_status"] == "passed"
        and result["evidence_finalization"]["status"] == "passed"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
