"""Build the explicit sealed-evidence composite Stage 7 Part A gate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import tempfile
from typing import Any

from .cx317_stage6_dual_core_analyze import _estimator_parity, _rows_for
from .cx317_frequency_preview_live_analyze import _check_continuity
from .cx317_stage7_analyze import _controller_parity, _transactions
from .cx317_stage7_gate_validation import (
    PART_A_COMPOSITE_TEST,
    part_a2_progression_gate_valid,
)
from .cx317_bounded_active_supervisor import load_cx317_bounded_active_spec
from .evidence import validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _sealed_binding(run_dir: Path) -> tuple[bool, dict[str, Any]]:
    manifest = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    snapshot_path = run_dir / "evidence_manifest.json"
    snapshot = _read_json(snapshot_path) if snapshot_path.is_file() else {}
    binding = {
        "run_dir": str(run_dir.resolve()),
        "run_id": manifest.run_id,
        "run_state": snapshot.get("run_state"),
        "snapshot_digest": snapshot.get("snapshot_digest"),
        "evidence_manifest_sha256": (
            _sha256_file(snapshot_path) if snapshot_path.is_file() else None
        ),
        "evidence_snapshot_failures": failures,
        "evidence_snapshot_warnings": warnings,
    }
    return (
        not (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists()
        and snapshot_path.is_file()
        and not failures,
        binding,
    )


def build_composite_gate(
    *,
    part_a1_gate_path: Path,
    part_a2_run_dir: Path,
    repair_rehearsal_run_dir: Path,
    output_path: Path,
) -> tuple[Path, dict[str, Any]]:
    if output_path.exists():
        raise FileExistsError(f"composite gate already exists: {output_path}")

    part_a1_gate_path = part_a1_gate_path.resolve()
    part_a1_run_dir = part_a1_gate_path.parent.parent
    part_a2_run_dir = part_a2_run_dir.resolve()
    repair_rehearsal_run_dir = repair_rehearsal_run_dir.resolve()

    a1_gate = _read_json(part_a1_gate_path)
    a2_gate_path = part_a2_run_dir / "reports/stage7_exit_gate.json"
    a2_gate = _read_json(a2_gate_path)
    a2_state_path = (
        part_a2_run_dir / "reports/cx317_active_supervisor_state.json"
    )
    a2_state = _read_json(a2_state_path)
    repair_gate_path = (
        repair_rehearsal_run_dir / "reports/stage7_rehearsal_gate.json"
    )
    repair_gate = _read_json(repair_gate_path)
    repair_state = _read_json(
        repair_rehearsal_run_dir
        / "reports/cx317_active_supervisor_state.json"
    )

    a1_sealed, a1_binding = _sealed_binding(part_a1_run_dir)
    a2_sealed, a2_binding = _sealed_binding(part_a2_run_dir)
    repair_sealed, repair_binding = _sealed_binding(
        repair_rehearsal_run_dir
    )

    a2_manifest = load_manifest(part_a2_run_dir)
    counts = _rows_for(
        a2_manifest, part_a2_run_dir, "count_observations_v1"
    )
    snapshots = _rows_for(
        a2_manifest, part_a2_run_dir, "pps_snapshots_v1"
    )
    raw = _rows_for(a2_manifest, part_a2_run_dir, "raw_events_v1")
    estimates = _rows_for(a2_manifest, part_a2_run_dir, "estimates_v2")
    controls = _rows_for(
        a2_manifest, part_a2_run_dir, "control_previews_v1"
    )
    active = _rows_for(
        a2_manifest, part_a2_run_dir, "active_transactions_v1"
    )
    dac = _rows_for(a2_manifest, part_a2_run_dir, "dac_steps_v1")
    continuity, count_by_sequence = _check_continuity(
        counts, snapshots, raw
    )
    spec, identities = load_cx317_bounded_active_spec("part_a", 0xA800)
    estimator_check, _ = _estimator_parity(
        estimates,
        count_by_sequence,
        identities["estimator_sha256"],
        minimum_selected=3,
    )
    applications = [row for row in active if row["event"] == "application"]
    controller_check, controller_replay = _controller_parity(
        controls, estimates, applications
    )
    prefix_check, prefix_transactions = _transactions(
        active[:5],
        spec,
        identities,
        a2_manifest.data["firmware"]["build_identity"],
    )
    source_transactions = a2_gate.get("transactions", {})
    service_baseline = int(
        a2_state.get("part_a_service_load_completed_control_seq", -1)
    )
    later_controls = [
        row
        for row in controls
        if int(row["control_seq"]) > service_baseline
        and row["preview_available"] == "true"
        and row["diagnostic_health"] == "healthy"
        and row["model_applicability"] == "applicable"
    ]
    malformed = active[5] if len(active) == 6 else {}

    repair_manifest = load_manifest(repair_rehearsal_run_dir)
    repair_active = _rows_for(
        repair_manifest,
        repair_rehearsal_run_dir,
        "active_transactions_v1",
    )
    repair_controls = _rows_for(
        repair_manifest,
        repair_rehearsal_run_dir,
        "control_previews_v1",
    )
    repair_service_baseline = int(
        repair_state.get("part_a_service_load_completed_control_seq", -1)
    )
    repair_later_sequence = repair_state.get(
        "part_a_post_service_eligible_control_seq"
    )

    criteria = {
        "sealed_part_a1_fixed_code_stability": (
            a1_sealed
            and a1_binding["run_state"] == "partial"
            and a1_gate.get("status") == "pass"
            and a1_gate.get("test") == "part_a_fixed_code_stability"
            and a1_gate.get("applicable") is True
            and bool(a1_gate.get("criteria"))
            and all(value is True for value in a1_gate["criteria"].values())
        ),
        "source_a2_failure_and_partial_seal_preserved": (
            a2_sealed
            and a2_binding["run_state"] == "partial"
            and a2_gate.get("status") == "fail"
            and source_transactions.get("validated_prefix_record_count") == 5
            and source_transactions.get("first_invalid_record_sequence") == 6
            and source_transactions.get("application_count") == 1
            and source_transactions.get("final_code") == 0xA815
        ),
        "real_a2_measurement_continuity_and_estimator_replay": (
            all(check.passed for check in continuity)
            and estimator_check.passed
        ),
        "real_a2_controller_replay_at_actual_application_epoch": (
            controller_check.passed
            and all(
                item["pass"]
                for item in controller_replay["comparisons"]
            )
        ),
        "real_a2_one_exact_complete_four_phase_prefix": (
            prefix_check.passed
            and prefix_transactions["application_count"] == 1
            and prefix_transactions["complete_request_group_count"] == 1
            and prefix_transactions[
                "all_response_classifications_replay_exactly"
            ]
            is True
            and prefix_transactions["final_code"] == 0xA815
        ),
        "real_a2_only_one_physical_automatic_write": (
            len(dac) == 2
            and len(applications) == 1
            and dac[0]["event"] == "manual_apply"
            and int(dac[0]["dac_code_applied"]) == 0xA800
            and dac[1]["event"] == "active_apply"
            and int(dac[1]["dac_code_applied"]) == 0xA815
        ),
        "real_a2_service_and_later_eligible_observation_completed": (
            a2_state.get("response_count") == 1
            and a2_state.get("part_a_service_load_sent") == 60
            and a2_state.get("part_a_service_load_complete") is True
            and service_baseline == 2
            and len(later_controls) == 1
            and int(later_controls[0]["control_seq"]) == 3
            and int(later_controls[0]["current_dac_code"]) == 0xA815
        ),
        "source_second_request_rejected_before_second_write": (
            malformed.get("event") == "request_created"
            and malformed.get("request_sequence") == "2"
            and malformed.get("accepted_code") == str(0xA815)
            and malformed.get("applied_code") == str(0xA815)
            and a2_state.get("authorization_sequence") == 2
            and a2_state.get("terminal", {}).get("result") == "aborted"
            and "unaccepted cross-core request has a non-zero accepted code"
            in a2_state.get("terminal", {}).get("reason", "")
        ),
        "sealed_targeted_repair_rehearsal_passed": (
            repair_sealed
            and repair_binding["run_state"] == "complete"
            and repair_gate.get("status") == "pass"
            and repair_gate.get("diagnostic_only") is True
            and repair_gate.get("qualification_evidence") is False
            and bool(repair_gate.get("criteria"))
            and all(
                value is True
                for value in repair_gate["criteria"].values()
            )
        ),
        "repair_rehearsal_proved_consecutive_clear_and_no_rearm": (
            [row["event"] for row in repair_active]
            == [
                "manual_start",
                "request_created",
                "core0_accepted",
                "application",
                "response",
                "request_created",
                "core0_accepted",
                "application",
                "response",
            ]
            and repair_active[5]["accepted_code"] == "0"
            and repair_active[5]["accepted_timestamp_s"] == "0"
            and repair_active[5]["applied_code"] == "0"
            and repair_active[5]["application_sequence"] == "0"
            and repair_state.get("authorization_sequence") == 2
            and repair_state.get("response_count") == 2
            and repair_state.get("part_a_service_load_sent") == 60
            and repair_state.get("part_a_service_load_complete") is True
            and isinstance(repair_later_sequence, int)
            and repair_later_sequence > repair_service_baseline
            and any(
                int(row["control_seq"]) == repair_later_sequence
                and row["preview_available"] == "true"
                for row in repair_controls
            )
            and repair_state.get("terminal", {}).get("result")
            == "healthy_stop"
        ),
    }

    result = {
        "schema_version": 1,
        "tool": "cx317_stage7_part_a_composite_v1",
        "test": PART_A_COMPOSITE_TEST,
        "part": "part_a",
        "claim_scope": (
            "composite_part_a_only; source A2 remains failed diagnostic; "
            "does not replace Part B endurance"
        ),
        "status": "pass" if all(criteria.values()) else "fail",
        "qualification_evidence": True,
        "stage7_progression_authority": True,
        "criteria": criteria,
        "transactions": {
            **prefix_transactions,
            "source_total_record_count": len(active),
            "source_validated_prefix_record_count": 5,
            "source_first_invalid_record_sequence": 6,
        },
        "source_a2_disposition": {
            "source_exit_status": a2_gate.get("status"),
            "source_run_state": a2_binding["run_state"],
            "source_run_relabelled_as_pass": False,
            "terminal": a2_state.get("terminal"),
            "binding": {
                **a2_binding,
                "source_exit_gate_path": str(a2_gate_path),
                "source_exit_gate_sha256": _sha256_file(a2_gate_path),
            },
        },
        "part_a1_stability": {
            "status": a1_gate.get("status"),
            "binding": {
                **a1_binding,
                "gate_path": str(part_a1_gate_path),
                "gate_sha256": _sha256_file(part_a1_gate_path),
            },
        },
        "repair_rehearsal": {
            "status": repair_gate.get("status"),
            "diagnostic_only": repair_gate.get("diagnostic_only"),
            "qualification_evidence": repair_gate.get(
                "qualification_evidence"
            ),
            "evidence_snapshot_valid": repair_sealed,
            "binding": {
                **repair_binding,
                "gate_path": str(repair_gate_path),
                "gate_sha256": _sha256_file(repair_gate_path),
                "firmware": repair_manifest.data["firmware"],
            },
        },
        "corrected_posthoc_replay": {
            "estimator": {
                "passed": estimator_check.passed,
                "evidence": estimator_check.evidence,
                "minimum_selected_outputs": 3,
            },
            "controller": {
                "passed": controller_check.passed,
                "evidence": controller_check.evidence,
                **controller_replay,
                "dac_epoch_source": "actual_ACT_application_timestamp_s",
            },
        },
        "exact_part_b_start_code": prefix_transactions["final_code"],
    }
    if result["status"] == "pass" and not part_a2_progression_gate_valid(result):
        raise ValueError("constructed composite gate failed progression validation")
    _atomic_json(output_path, result)
    return output_path, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part-a1-gate", type=Path, required=True)
    parser.add_argument("--part-a2-run", type=Path, required=True)
    parser.add_argument("--repair-rehearsal-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    path, result = build_composite_gate(
        part_a1_gate_path=args.part_a1_gate,
        part_a2_run_dir=args.part_a2_run,
        repair_rehearsal_run_dir=args.repair_rehearsal_run,
        output_path=args.output,
    )
    print(f"{path}\nstatus={result['status']}")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
