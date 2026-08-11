"""Run the exact CX318 Stage 5 contract preflight without touching hardware.

This is intentionally cheap: it validates the exact manifest/tool/build
bindings, checks the firmware status vocabulary, and exercises the same
fail-closed readiness object used by the supervisor and rehearsal seal.  It
never opens serial, creates a FIFO, sends a command, or writes a DAC.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from .cx318_stage5_manifest import REHEARSAL_STAGE, validate_manifest
from .active_status_contract import ACTIVE_STATUS_WIRE_KEYS
from .cx318_stage5_runtime_contract import (
    ACTIVE_STATUS_KEYS,
    RUNTIME_CONTRACT_ID,
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness,
)
from .cx318_stage5_supervisor import load_stage5_spec
from tools.firmware_matrix import source_input_hash


TOOL_ID = "cx318_stage5_preflight_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = REPO_ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _canonical_digest(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _firmware_status_vocabulary() -> dict[str, object]:
    direct_source = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    dual_source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    preview_source = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    visitor = direct_source[
        direct_source.index("void otis_cx317_active_live_visit_status") :
        direct_source.index("static void emit_direct_active_status")
    ]
    dual = dual_source[
        dual_source.index("void publish_dual_core_active_status") :
        dual_source.index("void publish_dual_core_timing_health")
    ]
    visitor_keys = tuple(re.findall(r'visitor\(context, "([^"]+)"', visitor))
    expected = tuple(ACTIVE_STATUS_WIRE_KEYS)
    direct_delegates = "otis_cx317_active_live_visit_status(context," in direct_source
    dual_delegates = "otis_cx317_active_live_visit_status(" in dual
    health_producers = {
        "cx317_preview.telemetry_dropped_frames": bool(
            re.search(
                r'otis_status_emit\(context,\s*"cx317_preview",\s*'
                r'"telemetry_dropped_frames"',
                preview_source,
            )
        ),
        **{
            f"dual_core.{key}": bool(
                re.search(
                    rf'emit_status(?:_u32)?\(\s*"dual_core",\s*"{key}"',
                    dual_source,
                )
            )
            for key in (
                "telemetry_dropped",
                "service_publish_failures",
                "partition_fault",
                "fail_static",
            )
        },
    }
    return {
        "expected": expected,
        "shared_visitor": visitor_keys,
        "direct_delegates": direct_delegates,
        "dual_core_delegates": dual_delegates,
        "health_producers": health_producers,
        "health_producers_present": all(health_producers.values()),
        "exact": visitor_keys == expected and direct_delegates and dual_delegates,
    }


def preflight(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = validate_manifest(manifest_path)
    if manifest.get("stage") != REHEARSAL_STAGE:
        raise ValueError("Stage 5 preflight requires an exact rehearsal manifest")
    stage5 = manifest["stage5"]
    leg_name = stage5["leg"]
    spec, identities, _ = load_stage5_spec(leg_name)
    expected_build = (
        manifest["firmware"]["source_sha256"]
        + ":"
        + manifest["firmware"]["configuration_sha256"]
    )
    identity = {
        "run_identity": spec.run_identity,
        "build_identity": expected_build,
        "profile_identity": spec.profile,
        **identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=identity,
        planned_live_stimulus_code=spec.start_code,
    )
    canonical = evaluate_prewrite_readiness(
        health,
        expected_identity=identity,
        planned_live_stimulus_code=spec.start_code,
        active_row_count=0,
        dac_row_count=0,
    )
    missing_rejected: dict[str, bool] = {}
    for key in ACTIVE_STATUS_KEYS:
        mutated = dict(health)
        del mutated[("cx317_active", key)]
        result = evaluate_prewrite_readiness(
            mutated,
            expected_identity=identity,
            planned_live_stimulus_code=spec.start_code,
            active_row_count=0,
            dac_row_count=0,
        )
        missing_rejected[key] = not result.ready

    ambiguous = dict(health)
    ambiguous[("cx317_active", "confirmed_applied_code_known")] = "true"
    ambiguous[("cx317_active", "confirmed_applied_code")] = str(
        spec.start_code
    )
    ambiguous_result = evaluate_prewrite_readiness(
        ambiguous,
        expected_identity=identity,
        planned_live_stimulus_code=spec.start_code,
        active_row_count=0,
        dac_row_count=0,
    )
    vocabulary = _firmware_status_vocabulary()
    current_firmware_source_sha256 = source_input_hash()
    checks = {
        "exact_rehearsal_manifest_and_tool_bindings": True,
        "runtime_contract_identity_exact": (
            stage5["runtime_contract"]["id"] == RUNTIME_CONTRACT_ID
        ),
        "canonical_prewrite_fixture_ready": canonical.ready,
        "every_missing_active_status_key_rejected": all(
            missing_rejected.values()
        ),
        "planned_stimulus_cannot_masquerade_as_physical_confirmation": (
            not ambiguous_result.ready
        ),
        "authority_rows_rejected": not evaluate_prewrite_readiness(
            health,
            expected_identity=identity,
            planned_live_stimulus_code=spec.start_code,
            active_row_count=1,
            dac_row_count=0,
        ).ready,
        "firmware_direct_and_dual_status_vocabulary_exact": vocabulary["exact"],
        "firmware_health_status_producers_present": vocabulary[
            "health_producers_present"
        ],
        "build_source_matches_current_contract_source": (
            manifest["firmware"]["source_sha256"]
            == current_firmware_source_sha256
        ),
        "serial_commands_attempted_is_zero": True,
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "passed" if all(checks.values()) else "failed",
        "manifest": str(manifest_path),
        "mode": "offline_no_io",
        "leg": leg_name,
        "runtime_contract": canonical.as_dict(),
        "firmware_status_vocabulary": vocabulary,
        "firmware_source": {
            "build_sha256": manifest["firmware"]["source_sha256"],
            "current_contract_source_sha256": current_firmware_source_sha256,
        },
        "missing_key_rejection": missing_rejected,
        "checks": checks,
        "serial_commands_attempted": 0,
        "dac_writes_attempted": 0,
        "fifo_creations_attempted": 0,
    }
    result["preflight_sha256"] = _canonical_digest(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = preflight(args.manifest)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
