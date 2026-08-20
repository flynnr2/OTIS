"""Finalize and seal one CX320 evidence package without changing raw evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_hybrid_analyze import analyze


TOOL_ID = "cx320_active_hybrid_finalizer_and_sealer_v1"
SNAPSHOT_FILES = (
    Path("run_manifest.json"),
    Path("csv/active_hybrid_decisions_v1.csv"),
    Path("reports/operational_trace_v1.json"),
)


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to replace finalized evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def finalize(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    bindings = []
    for relative in SNAPSHOT_FILES:
        path = run_dir / relative
        if not path.is_file():
            raise ValueError(f"CX320 evidence input is missing: {relative}")
        bindings.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "snapshot_type": "cx320_active_hybrid_immutable_evidence_snapshot_v1",
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "files": bindings,
    }
    snapshot["snapshot_sha256"] = _canonical_sha256(snapshot)
    snapshot_path = run_dir / "reports/evidence_snapshot_v1.json"
    _write_new(snapshot_path, snapshot)

    analysis = analyze(run_dir)
    analysis_path = run_dir / "reports/active_hybrid_analysis_v1.json"
    _write_new(analysis_path, analysis)

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    trace = json.loads(
        (run_dir / "reports/operational_trace_v1.json").read_text(encoding="utf-8")
    )
    primary = trace["modeled_phase_transaction"]
    seal: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": "cx320_active_hybrid_operational_rehearsal_seal_v1",
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "passed",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "run_identity": manifest["run_identity"],
        "bundle_sha256": manifest["bundle_sha256"],
        "policy_sha256": manifest["policy_sha256"],
        "build_identity": manifest["build_identity"],
        "evidence_snapshot": {
            "path": "reports/evidence_snapshot_v1.json",
            "file_sha256": _sha256_file(snapshot_path),
            "snapshot_sha256": snapshot["snapshot_sha256"],
        },
        "analysis": {
            "path": "reports/active_hybrid_analysis_v1.json",
            "file_sha256": _sha256_file(analysis_path),
            "analysis_sha256": analysis["analysis_sha256"],
        },
        "modeled_application_counts": {
            "frequency_only": primary["frequency_only_application_count"],
            "phase_nonzero": primary["phase_nonzero_application_count"],
            "phase_material": primary["phase_material_application_count"],
            "total": primary["correction_count"],
        },
        "terminal": {
            "confirmed_static_code": primary["terminal_code"],
            "dac_epoch": primary["dac_epoch"],
            "outstanding_request": primary["request_outstanding"],
            "outstanding_response": primary["response_outstanding"],
            "latent_authority": False,
        },
        "claim_boundary": {
            "rehearsal_only": True,
            "observed_physical_applications": 0,
            "observed_physical_responses": 0,
            "counterfactual_or_modeled_is_not_physical_response": True,
        },
    }
    if seal["terminal"]["outstanding_request"] or seal["terminal"]["outstanding_response"]:
        raise ValueError("cannot seal an active-hybrid rehearsal with outstanding state")
    seal["seal_sha256"] = _canonical_sha256(seal)
    _write_new(run_dir / "reports/active_hybrid_rehearsal_seal_v1.json", seal)
    return seal


def validate_seal(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    seal_path = run_dir / "reports/active_hybrid_rehearsal_seal_v1.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    claimed = seal.pop("seal_sha256", None)
    observed = _canonical_sha256(seal)
    seal["seal_sha256"] = claimed
    if claimed != observed:
        raise ValueError("CX320 rehearsal semantic seal identity differs")
    for name in ("evidence_snapshot", "analysis"):
        binding = seal[name]
        path = run_dir / binding["path"]
        if not path.is_file() or _sha256_file(path) != binding["file_sha256"]:
            raise ValueError(f"CX320 sealed {name} binding differs")
    if seal.get("qualification_evidence") is not False or seal.get("physical_actions_performed") != 0:
        raise ValueError("CX320 rehearsal seal crossed the physical claim boundary")
    return seal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    result = validate_seal(args.run_dir) if args.validate else finalize(args.run_dir)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
