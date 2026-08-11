"""Offline cross-surface preflight for the exact CX319 G1 bundle.

The preflight proves the no-write command boundary, boot-path DAC behavior,
finite timeline and runtime-contract fixture without opening a device, creating
a FIFO, flashing firmware or issuing a command.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .cx319_g1_bundle import (
    EMERGENCY_COMMAND,
    FORBIDDEN_COMMAND_PREFIXES,
    NORMAL_COMMAND_ALLOWLIST,
    REHEARSAL_DURATION_S,
    REPO_ROOT,
    normal_command_allowed,
    validate_bundle,
)
from .cx319_g1_supervisor import load_cx319_spec
from .cx319_runtime_contract import (
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness,
)


TOOL_ID = "cx319_g1_offline_preflight_v1"
FIRMWARE = REPO_ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        raise ValueError(f"source function is unavailable: {signature}")
    opening = source.find("{", start)
    if opening < 0:
        raise ValueError(f"source function has no body: {signature}")
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    raise ValueError(f"source function body is incomplete: {signature}")


def _boot_path_checks() -> tuple[dict[str, bool], dict[str, str]]:
    dac_path = FIRMWARE / "otis_dac_ad5693r.cpp"
    sketch_path = FIRMWARE / "otis_nano_rp2040_connect.ino"
    actuator_path = FIRMWARE / "otis_cx317_active_actuator.cpp"
    dac_source = dac_path.read_text(encoding="utf-8")
    sketch_source = sketch_path.read_text(encoding="utf-8")
    actuator_source = actuator_path.read_text(encoding="utf-8")
    begin = _function_body(dac_source, "bool otis_dac_ad5693r_begin(void)")
    peripheral_boot = _function_body(
        sketch_source, "void boot_phase_peripherals_init(void)"
    )
    preview_boot = _function_body(sketch_source, "void boot_phase_preview_init(void)")
    manual_handler = _function_body(sketch_source, "void handle_dac_set")
    checks = {
        "dac_begin_is_address_probe_only": (
            begin.count("Wire.beginTransmission(kDacAddress)") == 1
            and begin.count("Wire.endTransmission()") == 1
            and "Wire.write(" not in begin
            and "otis_dac_ad5693r_set_raw" not in begin
            and "otis_dac_ad5693r_reset" not in begin
            and "dac_applied_code_known = false" in begin
        ),
        "boot_calls_probe_not_value_write": (
            peripheral_boot.count("otis_dac_ad5693r_begin()") == 1
            and "otis_dac_ad5693r_set_raw" not in peripheral_boot
            and "otis_dac_ad5693r_reset" not in peripheral_boot
            and "otis_dac_ad5693r_set_raw" not in preview_boot
        ),
        "all_value_write_calls_are_command_or_actuator_scoped": (
            "otis_dac_ad5693r_set_raw(requested_code)" in manual_handler
            and actuator_source.count("otis_dac_ad5693r_set_raw(") == 1
            and sketch_source.count("otis_dac_ad5693r_set_raw(") == 2
        ),
    }
    return checks, {
        "dac_source_sha256": _sha256_file(dac_path),
        "sketch_source_sha256": _sha256_file(sketch_path),
        "actuator_source_sha256": _sha256_file(actuator_path),
    }


def evaluate(bundle_path: Path) -> dict[str, Any]:
    bundle = validate_bundle(bundle_path)
    leg_name = str(bundle["leg"]["leg"])
    spec, identities, _ = load_cx319_spec(leg_name)
    expected_identity = {
        "run_identity": spec.run_identity,
        "build_identity": (
            bundle["firmware"]["source_sha256"]
            + ":"
            + bundle["firmware"]["configuration_sha256"]
        ),
        "profile_identity": spec.profile,
        **identities,
    }
    fixture = canonical_prewrite_fixture(
        expected_identity=expected_identity,
        planned_live_stimulus_code=spec.start_code,
    )
    readiness = evaluate_prewrite_readiness(
        fixture,
        expected_identity=expected_identity,
        planned_live_stimulus_code=spec.start_code,
        active_row_count=0,
        dac_row_count=0,
    )
    boot_checks, source_bindings = _boot_path_checks()
    allowed_examples = {
        "CONFIG?",
        "DAC?",
        "FC0?",
        "ACTIVE?",
        "ACTIVE LEASE 1",
        "ACTIVE LEASE 4294967295",
    }
    forbidden_examples = {
        "ACTIVE LEASE 0",
        "ACTIVE LEASE 4294967296",
        "ACTIVE ABORT",
        "DAC SET 0xA808",
        "DAC MID",
        "DAC ZERO",
        "ACTIVE ARM 1 2 3",
        "ACTIVE EVIDENCE 1 1",
        "DUALCORE RECOVER",
        "SWEEP START",
        "PPSGEN START",
    }
    capture_duration_s = REHEARSAL_DURATION_S + 180
    checks = {
        **boot_checks,
        "runtime_contract_fixture_ready_without_transactions": readiness.ready,
        "normal_allowlist_accepts_only_read_queries_and_leases": (
            all(normal_command_allowed(command) for command in allowed_examples)
            and not any(
                normal_command_allowed(command) for command in forbidden_examples
            )
            and tuple(bundle["commands"]["normal_allowlist"])
            == NORMAL_COMMAND_ALLOWLIST
            and bundle["commands"]["emergency_allowlist"] == [EMERGENCY_COMMAND]
            and tuple(bundle["commands"]["forbidden_prefixes"])
            == FORBIDDEN_COMMAND_PREFIXES
        ),
        "firmware_profile_actuation_exists_but_is_not_boot_reachable": (
            bundle["firmware"]["profile_id"]
            in {"cx319_tight_lower", "cx319_tight_upper"}
            and bundle["authority"]["flash_exact_firmware"] is True
            and bundle["authority"]["dac_value_write"] is False
            and bundle["authority"]["control_arm"] is False
        ),
        "finite_timeline_has_supervision_transport_and_close_margin": (
            REHEARSAL_DURATION_S == 2700
            and capture_duration_s == 2880
            and REHEARSAL_DURATION_S - 1800 >= 600
            and capture_duration_s - REHEARSAL_DURATION_S >= 180
        ),
        "authority_overlay_is_nonpromoting_and_zero_write": (
            bundle["operator_authority"]["authority_id"]
            == "CX319_G1_NO_WRITE_BENCH_AUTHORITY_V1"
            and bundle["rehearsal"]["rehearsal_to_live_promotion"] is False
            and all(
                bundle["rehearsal"][key] == 0
                for key in (
                    "setup_writes",
                    "automatic_writes",
                    "dac_value_writes",
                    "control_arms",
                )
            )
        ),
    }
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "mode": "offline_no_io",
        "status": "passed" if all(checks.values()) else "failed",
        "bundle": {
            "path": str(bundle_path.resolve()),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "leg": leg_name,
        "checks": checks,
        "runtime_contract": readiness.as_dict(),
        "source_bindings": source_bindings,
        "timeline_s": {
            "supervisor_endpoint": REHEARSAL_DURATION_S,
            "capture_endpoint": capture_duration_s,
            "post_supervisor_margin": capture_duration_s - REHEARSAL_DURATION_S,
        },
        "hardware_operations": {
            "serial_open": 0,
            "firmware_flash": 0,
            "command_fifo_creation": 0,
            "serial_commands": 0,
            "dac_value_writes": 0,
            "control_arms": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.bundle)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if result["status"] == "passed" else 1
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
