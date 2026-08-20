"""No-I/O structural preflight for one exact CX320 bundle and proposal."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_hybrid_bundle import validate_bundle
from .active_hybrid_evidence_audit import audit_predecessor
from .active_hybrid_proposal import validate_proposal
from .programme_status import OFFLINE_PREPARATION, load_programme_status
from .serial_commands import parse_serial_command


TOOL_ID = "cx320_active_hybrid_structural_preflight_v1"


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def preflight(*, bundle_path: Path, proposal_path: Path) -> dict[str, Any]:
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path)
    predecessor = audit_predecessor()
    status = load_programme_status()
    current = status["programmes"].get("cx320_bounded_active_hybrid", {})
    if (
        status.get("active_programme") != "cx320_bounded_active_hybrid"
        or current.get("allowed_operations") != [OFFLINE_PREPARATION]
        or current.get("physical_authority_effective") is not False
    ):
        raise ValueError("programme status does not permit only CX320 offline preparation")
    if proposal["exact_bundle"]["bundle_sha256"] != bundle["bundle_sha256"]:
        raise ValueError("preflight proposal and bundle identities differ")
    configuration_sha256 = bundle["firmware"]["configuration_sha256"]
    commands = [
        "CONFIG?",
        "DUALCORE?",
        "DAC?",
        "ACTIVE?",
        f"ACTIVE SETUP 1 1 1 100 1 0xA83C 1 {configuration_sha256}",
        "ACTIVE ARM 1 1 1",
        "ACTIVE EVIDENCE 1 1",
        "ACTIVE EVIDENCE 1 4",
        "ACTIVE ABORT",
    ]
    normalized = [parse_serial_command(command).normalized for command in commands]
    checks = {
        "predecessor_programme_seal_and_bound_evidence": predecessor["status"] == "passed",
        "exact_bundle_valid": True,
        "proposal_non_effective": proposal["authority"]["effective"] is False,
        "programme_status_offline_only": True,
        "exact_policy_profile_build_and_UF2_bound": True,
        "frozen_replay_passed": all(bundle["offline_replay"]["selection_checks"].values()),
        "command_envelope_parses": len(normalized) == len(commands),
        "one_setup_code": "0xA83C" in normalized[4],
        "normal_and_abort_paths_distinct": bundle["topology"]["normal_and_priority_abort_fifos_distinct"],
        "no_physical_actions_performed": True,
    }
    if not all(checks.values()):
        raise ValueError(f"CX320 structural preflight failed: {checks}")
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "cx320_active_hybrid_structural_preflight_v1",
        "tool": TOOL_ID,
        "tool_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "passed",
        "bundle_path": str(bundle_path.resolve()),
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_path": str(proposal_path.resolve()),
        "proposal_sha256": proposal["proposal_sha256"],
        "policy_sha256": bundle["policy"]["policy_sha256"],
        "build_identity": bundle["firmware"]["build_identity"],
        "firmware_uf2_sha256": bundle["firmware"]["uf2"]["sha256"],
        "predecessor_programme_seal_sha256": predecessor["programme_seal"]["seal_sha256"],
        "normalized_command_rehearsal": normalized,
        "checks": checks,
        "claim_boundary": {
            "structural_only": True,
            "serial_device_access": False,
            "command_fifo_access": False,
            "firmware_flash": False,
            "reset": False,
            "DAC_write": False,
            "control_arm": False,
        },
    }
    report["preflight_sha256"] = _canonical_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = preflight(bundle_path=args.bundle, proposal_path=args.proposal)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        if args.output.exists():
            parser.error(f"refusing to overwrite CX320 preflight: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
