"""Create the external Stage 5 two-leg frequency-only exit gate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .cx318_stage5_manifest import (
    _canonical_digest,
    _read_object,
    _validate_live_leg_seal,
    validate_manifest,
)


TOOL_ID = "cx318_stage5_bidirectional_gate_v1"
GATE_TYPE = "cx318_stage5_bidirectional_frequency_gate_v1"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite Stage 5 gate: {path}")
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
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_gate(leg_a_path: Path, leg_b_path: Path, output: Path) -> dict[str, Any]:
    a_binding = _validate_live_leg_seal(leg_a_path, expected_leg="A")
    b_binding = _validate_live_leg_seal(leg_b_path, expected_leg="B")
    a = _read_object(leg_a_path, "Stage 5 leg A seal")
    b = _read_object(leg_b_path, "Stage 5 leg B seal")
    a_manifest = validate_manifest(Path(a["run"]["path"]) / "run_manifest.json")
    b_manifest = validate_manifest(Path(b["run"]["path"]) / "run_manifest.json")
    b_prior = b_manifest["stage5"].get("leg_a_seal", {})
    checks = {
        "leg_a_passed_and_canonical": a["status"] == "passed",
        "leg_b_passed_and_canonical": b["status"] == "passed",
        "distinct_leg_runs": Path(a["run"]["path"]).resolve() != Path(b["run"]["path"]).resolve(),
        "profiles_and_required_directions_are_opposite": (
            a["profile_id"] == "cx318_stage5_tight_lower"
            and a["required_direction"] == "positive"
            and b["profile_id"] == "cx318_stage5_tight_upper"
            and b["required_direction"] == "negative"
        ),
        "common_policy_and_stage4_prerequisite": (
            a["policy_sha256"] == b["policy_sha256"]
            and a["stage4_binding_sha256"] == b["stage4_binding_sha256"]
        ),
        "common_firmware_source_and_frequency_semantics": (
            a_manifest["firmware"]["source_sha256"]
            == b_manifest["firmware"]["source_sha256"]
            and a_manifest["policy"]["bindings"]
            == b_manifest["policy"]["bindings"]
        ),
        "leg_b_manifest_binds_exact_passed_leg_a_seal": (
            b_prior.get("seal_sha256") == a["seal_sha256"]
            and b_prior.get("sha256") == _sha256_file(leg_a_path)
        ),
        "leg_a_precedes_or_is_bound_in_same_second_as_leg_b": (
            str(a_manifest["created_utc"]) <= str(b_manifest["created_utc"])
        ),
        "hybrid_authority_remains_zero": (
            a_manifest["stage5"]["phase_and_hybrid"].get("actuation_authorized") is False
            and b_manifest["stage5"]["phase_and_hybrid"].get("actuation_authorized") is False
        ),
    }
    status = "passed" if all(checks.values()) else "failed"
    unsigned = {
        "gate_type": GATE_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "status": status,
        "leg_a": a_binding,
        "leg_b": b_binding,
        "checks": checks,
        "claims": {
            "stage5_bidirectional_frequency_gate": status == "passed",
            "stage6_frequency_only_authorized": status == "passed",
            "hybrid_actuation_authorized": False,
        },
    }
    result = {**unsigned, "gate_sha256": _canonical_digest(unsigned)}
    _atomic_new_json(output.resolve(), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leg-a-seal", type=Path, required=True)
    parser.add_argument("--leg-b-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = create_gate(args.leg_a_seal, args.leg_b_seal, args.output)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
