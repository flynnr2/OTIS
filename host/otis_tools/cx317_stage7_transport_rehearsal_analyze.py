"""Analyze the exact Stage 7 saturated-normal-FIFO priority-abort rehearsal."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
from typing import Any

from .cx317_active_campaign import _latest_health
from .run_loader import CAPTURE_IN_PROGRESS_FLAG


OUTPUT = Path("reports/stage7_rehearsal_gate.json")
HOST_MARKER_PREFIX = "# OTIS_HOST "
CAPTURE_TOOL = Path(__file__).with_name("capture_device.py")
SUPERVISOR_TOOL = Path(__file__).with_name("cx317_stage7_supervisor.py")
SERIAL_COMMANDS_TOOL = Path(__file__).with_name("serial_commands.py")
INJECTION_TOOL = Path(__file__).with_name(
    "cx317_stage7_transport_fault_inject.py"
)
ANALYZER_TOOL = Path(__file__)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _host_markers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    markers: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(HOST_MARKER_PREFIX):
                markers.append(json.loads(line[len(HOST_MARKER_PREFIX) :]))
    return markers


def _one(markers: list[dict[str, Any]], event: str) -> dict[str, Any]:
    selected = [row for row in markers if row.get("event") == event]
    if len(selected) != 1:
        raise ValueError(f"expected one {event} marker, got {len(selected)}")
    return selected[0]


def analyze(
    run_dir: Path,
    *,
    build_manifest: Path,
    uf2: Path,
    saturation_report: Path,
) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    manifest = json.loads(
        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    build = json.loads(build_manifest.read_text(encoding="utf-8"))
    saturation = json.loads(saturation_report.read_text(encoding="utf-8"))
    state = json.loads(
        (run_dir / "reports/cx317_active_supervisor_state.json").read_text(
            encoding="utf-8"
        )
    )
    events = _json_lines(
        run_dir / "reports/cx317_active_supervisor_events.jsonl"
    )
    markers = _host_markers(run_dir / "raw/serial.log")
    stopped = _one(markers, "capture_stopped")
    capture_transport_state = json.loads(
        (run_dir / "reports/capture_device_state.json").read_text(
            encoding="utf-8"
        )
    )
    normal_ingress = _one(markers, "command_ingress_opened")
    emergency_ingress = _one(markers, "emergency_command_ingress_opened")
    marker_events = [str(row.get("event")) for row in markers]
    required_order = [
        "emergency_abort_latched",
        "normal_command_ingress_revoked",
        "host_command_accepted",
        "host_command_sent",
        "emergency_abort_sent",
    ]
    ordered_indices = [marker_events.index(event) for event in required_order]
    sent_commands = [
        row.get("command")
        for row in markers
        if row.get("event") == "host_command_sent"
    ]
    act_rows = _rows(run_dir / "csv/active_transactions_v1.csv")
    dac_rows = _rows(run_dir / "csv/dac_steps.csv")
    health = _latest_health(run_dir / "csv/health.csv")
    build_uf2 = next(
        item for item in build["artifacts"] if item["name"].endswith(".uf2")
    )
    terminal = state.get("terminal", {})
    supervisor_faults = [
        row for row in events if row.get("event") == "stage7_supervisor_fault"
    ]
    priority_submissions = [
        row
        for row in events
        if row.get("event") == "emergency_device_abort_submitted"
    ]
    failed_abort_submissions = [
        row
        for row in events
        if row.get("event") == "device_abort_submission_failed"
    ]

    criteria = {
        "diagnostic_identity_has_zero_progression_authority": (
            manifest.get("stage")
            == "CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL"
            and manifest.get("diagnostic_only") is True
            and manifest.get("qualification_evidence") is False
            and manifest.get("stage7_progression_authority") is False
            and manifest.get("closed_loop_control") is False
            and manifest.get("actuation_authorized") is False
        ),
        "exact_clean_build_and_uf2": (
            build["provenance"]["source"]["state"] == "clean"
            and manifest["firmware"]["source_state"] == "clean"
            and manifest["firmware"]["build_manifest_sha256"]
            == _sha256(build_manifest)
            and build_uf2["sha256"] == _sha256(uf2)
            and manifest["firmware"]["uf2_sha256"] == _sha256(uf2)
        ),
        "normal_fifo_was_saturated_while_exact_capture_was_stopped": (
            saturation.get("status") == "pass"
            and saturation.get("normal_fifo_saturated") is True
            and int(saturation.get("timestamped_config_queries_queued", 0))
            > 0
            and saturation.get("capture_resumed") is True
            and saturation.get("sole_serial_owner_verified") is True
            and saturation.get("serial_owner_pids")
            == [saturation.get("capture_pid")]
        ),
        "supervisor_fault_used_priority_abort_not_normal_fifo": (
            len(supervisor_faults) == 1
            and "Resource temporarily unavailable"
            in str(supervisor_faults[0].get("error"))
            and len(priority_submissions) == 1
            and not failed_abort_submissions
            and terminal.get("result") == "aborted"
            and "stage7_supervisor_fault" in str(terminal.get("reason"))
        ),
        "priority_abort_preceded_all_stale_normal_commands": (
            ordered_indices == sorted(ordered_indices)
            and sent_commands == ["ACTIVE ABORT"]
        ),
        "normal_ingress_was_revoked_after_abort": (
            marker_events.count("normal_command_ingress_revoked") == 1
            and stopped.get("emergency_abort_latched") is True
            and int(stopped.get("emergency_aborts_sent", -1)) == 1
        ),
        "live_transport_binding_was_exact": (
            normal_ingress.get("batch_limit") == 1
            and normal_ingress.get("normal_command_max_age_s") == 2.0
            and bool(normal_ingress.get("path"))
            and bool(emergency_ingress.get("path"))
            and normal_ingress.get("path") != emergency_ingress.get("path")
            and manifest["host"].get("capture_command_write_timeout_s")
            == 1.0
            and manifest["host"].get("normal_command_envelope")
            == "OTISQ1_MONOTONIC_NS"
        ),
        "capture_closed_cleanly_after_priority_abort": (
            not (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists()
            and all(
                int(stopped.get(key, -1)) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "reconnect_count",
                    "commands_rejected",
                )
            )
            and (run_dir / "reports/capture_device.log").is_file()
            and capture_transport_state.get("capture_active") is False
            and capture_transport_state.get("serial_open") is False
            and capture_transport_state.get("normal_command_batch_limit")
            == 1
            and capture_transport_state.get("normal_command_max_age_s")
            == 2.0
            and capture_transport_state.get("write_timeout_s") == 1.0
            and int(
                capture_transport_state.get("emergency_aborts_sent", -1)
            )
            == 1
        ),
        "zero_dac_or_active_transaction_records": (
            not dac_rows and not act_rows
        ),
        "device_confirmed_aborted_evidence_clear_without_correction": (
            health.get(("cx317_active", "state")) == "ABORTED"
            and health.get(("cx317_active", "evidence_phase"))
            == "evidence_clear"
            and health.get(("cx317_active", "correction_count")) in {None, "0"}
        ),
    }
    result = {
        "schema_version": 1,
        "tool": "cx317_stage7_transport_rehearsal_analyze_v1",
        "status": "pass" if all(criteria.values()) else "fail",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "stage7_progression_authority": False,
        "run_dir": str(run_dir),
        "criteria": criteria,
        "saturation_report": {
            "path": str(saturation_report.resolve()),
            "sha256": _sha256(saturation_report),
        },
        "bindings": {
            "capture_tool_sha256": _sha256(CAPTURE_TOOL),
            "supervisor_sha256": _sha256(SUPERVISOR_TOOL),
            "serial_commands_sha256": _sha256(SERIAL_COMMANDS_TOOL),
            "injection_tool_sha256": _sha256(INJECTION_TOOL),
            "analyzer_tool_sha256": _sha256(ANALYZER_TOOL),
        },
        "supervisor_terminal": terminal,
        "host_commands_sent": sent_commands,
        "final": {
            "active_state": health.get(("cx317_active", "state")),
            "evidence_phase": health.get(("cx317_active", "evidence_phase")),
            "correction_count": health.get(
                ("cx317_active", "correction_count")
            ),
        },
    }
    output = run_dir / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument("--saturation-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output, result = analyze(
            args.run_dir,
            build_manifest=args.build_manifest,
            uf2=args.uf2,
            saturation_report=args.saturation_report,
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
