"""Execute three mapping-informed CX319 Part B legs with sealed handoffs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .bounded_tight_deadband_activation import create_activation
from .bounded_tight_deadband_leg import RANGE_LOWER, RANGE_UPPER
from .bounded_tight_deadband_operational_rehearsal import run as run_rehearsal
from .bounded_tight_deadband_run import (
    _locate_board_by_serial,
    run_bounded_tight_deadband_qualification,
)
from .conditional_part_b_bundle import create_proposal
from .evidence_index import DEFAULT_INDEX


TOOL_ID = "cx319_conditional_part_b_campaign_v1"
EXPECTED_BOARD_SERIAL = "503533748A919118"


def _require_physical_runtime_dependencies() -> None:
    """Reject an unprovisioned launcher before creating campaign artifacts."""

    if importlib.util.find_spec("serial") is None:
        raise RuntimeError(
            "conditional Part B physical execution requires pyserial in the "
            "campaign interpreter; use the provisioned repository environment "
            "(.venv/bin/python)"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def run_campaign(
    *,
    part_a_readiness_path: Path,
    lower_build_manifest_path: Path,
    lower_uf2_path: Path,
    upper_build_manifest_path: Path,
    upper_uf2_path: Path,
    output_root: Path,
    evidence_index_path: Path,
    operator_instruction_ref: str,
    arduino_cli: str,
) -> dict[str, Any]:
    _require_physical_runtime_dependencies()
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"conditional Part B output root must be empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "conditional_part_b_campaign_state_v1.json"
    state: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "active",
        "started_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "part_a_readiness": str(part_a_readiness_path.resolve()),
        "current_sequence_index": None,
        "completed_legs": [],
        "terminal": None,
    }
    _write_state(state_path, state)
    predecessor_seal: Path | None = None
    sequence = (
        (1, "lower_acquisition", RANGE_LOWER, lower_build_manifest_path, lower_uf2_path),
        (2, "upper_acquisition", RANGE_UPPER, upper_build_manifest_path, upper_uf2_path),
        (3, "lower_reacquisition", RANGE_LOWER, lower_build_manifest_path, lower_uf2_path),
    )
    try:
        for index, name, selected, build_manifest, uf2 in sequence:
            leg_root = output_root / f"leg_{index}_{name}"
            leg_root.mkdir()
            proposal_path = leg_root / selected.proposal_filename
            rehearsal_dir = leg_root / "operational_rehearsal"
            activation_path = leg_root / selected.activation_filename
            run_dir = leg_root / f"live_{name}"
            state.update(
                current_sequence_index=index,
                current_leg=name,
                current_gate=selected.gate,
                current_phase="freezing_proposal",
                updated_utc=_utc_now(),
            )
            _write_state(state_path, state)
            proposal = create_proposal(
                sequence_index=index,
                part_a_readiness_path=part_a_readiness_path,
                predecessor_seal_path=predecessor_seal,
                build_manifest_path=build_manifest,
                uf2_path=uf2,
                output_path=proposal_path,
            )
            state.update(current_phase="operational_rehearsal", updated_utc=_utc_now())
            _write_state(state_path, state)
            rehearsal = run_rehearsal(
                proposal_path=proposal_path, output_dir=rehearsal_dir
            )
            if rehearsal.get("status") != "passed":
                raise RuntimeError(f"conditional Part B leg {index} rehearsal failed")
            device, _ = _locate_board_by_serial(
                EXPECTED_BOARD_SERIAL, arduino_cli=arduino_cli
            )
            state.update(current_phase="activation", serial_device=device, updated_utc=_utc_now())
            _write_state(state_path, state)
            activation = create_activation(
                proposal_path=proposal_path,
                operational_rehearsal_path=(
                    rehearsal_dir / f"{selected.prefix}_operational_rehearsal_v1.json"
                ),
                serial_device=device,
                operator_instruction_ref=(
                    f"{operator_instruction_ref}; conditional Part B sequence {index}/3"
                ),
                output_path=activation_path,
                leg_name=selected.leg,
            )
            state.update(
                current_phase="physical_qualification",
                proposal_bundle_sha256=proposal["bundle_sha256"],
                activation_sha256=activation["activation_sha256"],
                run_dir=str(run_dir),
                updated_utc=_utc_now(),
            )
            _write_state(state_path, state)
            result = run_bounded_tight_deadband_qualification(
                activation_path=activation_path,
                run_dir=run_dir,
                evidence_index_path=evidence_index_path,
                arduino_cli=arduino_cli,
            )
            predecessor_seal = Path(result["analysis_and_seal"])
            completed = {
                "sequence_index": index,
                "leg_id": name,
                "gate": selected.gate,
                "status": result["status"],
                "run_dir": result["run_dir"],
                "seal": result["analysis_and_seal"],
                "seal_sha256": result["seal_sha256"],
                "evidence_content_sha256": result["evidence_content_sha256"],
                "completed_utc": _utc_now(),
            }
            state["completed_legs"].append(completed)
            state.update(current_phase="leg_sealed", updated_utc=_utc_now())
            _write_state(state_path, state)
        state.update(
            status="complete",
            current_phase="complete",
            completed_utc=_utc_now(),
            updated_utc=_utc_now(),
            terminal={
                "result": "healthy_stop",
                "reason": "three_fresh_frequency_only_legs_sealed",
            },
        )
        _write_state(state_path, state)
        return state
    except Exception as exc:
        state.update(
            status="failed",
            current_phase="failed",
            updated_utc=_utc_now(),
            terminal={
                "result": "aborted",
                "reason": "part_b_sequence_failure",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        _write_state(state_path, state)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part-a-readiness", type=Path, required=True)
    parser.add_argument("--lower-build-manifest", type=Path, required=True)
    parser.add_argument("--lower-uf2", type=Path, required=True)
    parser.add_argument("--upper-build-manifest", type=Path, required=True)
    parser.add_argument("--upper-uf2", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--operator-instruction-ref", required=True)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    result = run_campaign(
        part_a_readiness_path=args.part_a_readiness,
        lower_build_manifest_path=args.lower_build_manifest,
        lower_uf2_path=args.lower_uf2,
        upper_build_manifest_path=args.upper_build_manifest,
        upper_uf2_path=args.upper_uf2,
        output_root=args.output_root,
        evidence_index_path=args.evidence_index,
        operator_instruction_ref=args.operator_instruction_ref,
        arduino_cli=args.arduino_cli,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
