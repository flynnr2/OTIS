"""Freeze and validate the focused zero-authority CX319 Part A bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .conditional_range_campaign import DEFAULT_PROFILE, load_campaign
from .range_spanning_bundle import (
    EXPECTED_BOARD_SERIAL,
    _atomic_new_json,
    _binding,
    _firmware,
    _read,
    canonical_sha256,
    sha256_file,
)


TOOL_ID = "cx319_conditional_part_a_bundle_v2"
BUNDLE_TYPE = "cx319_conditional_fine_map_part_a_bundle_v2"

HOST_TOOL_PATHS = {
    "bundle": Path(__file__),
    "campaign": Path(__file__).with_name("conditional_range_campaign.py"),
    "rehearsal": Path(__file__).with_name("range_spanning_rehearsal.py"),
    "runner": Path(__file__).with_name("range_spanning_run.py"),
    "analyzer": Path(__file__).with_name("range_spanning_analyze.py"),
    "promotion": Path(__file__).with_name("conditional_part_a_promotion.py"),
    "capture": Path(__file__).with_name("capture_device.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "capture_checks": Path(__file__).with_name("capture_runtime_checks.py"),
    "contracts": Path(__file__).with_name("contracts.py"),
    "time_domains": Path(__file__).with_name("time_domains.py"),
    "run_validation": Path(__file__).with_name("validate_run.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_index": Path(__file__).with_name("evidence_index.py"),
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def create_bundle(*, build_manifest_path: Path, output_path: Path) -> dict[str, Any]:
    campaign = load_campaign()
    firmware = _firmware(build_manifest_path)
    point_plans = [dict(item) for item in campaign["part_a"]["point_plan"]]
    maximum_observations = max(item["maximum_observations"] for item in point_plans)
    timing = campaign["part_a"]["point_timing"]
    point_wait_timeout_s = (
        timing["two_observation_worst_case_s"]
        + (maximum_observations - 2) * timing["additional_observation_s"]
        + timing["host_margin_s"]
    )
    unsigned: dict[str, Any] = {
        "schema_version": 2,
        "bundle_type": BUNDLE_TYPE,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "programme": _binding(DEFAULT_PROFILE),
        "operator_authority": campaign["operator_authority"],
        "device": {
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
            "baud": 115200,
            "serial_path_resolution": "locate_unique_current_port_by_usb_serial",
        },
        "firmware": firmware,
        "entry": {
            "mode": "fresh_exact_firmware_flash",
            "firmware_flashes_allowed": 1,
            "board_resets_allowed": 1,
            "dac_writes_before_attachment_gate_allowed": 0,
        },
        "host_tools": {
            name: _binding(path) for name, path in sorted(HOST_TOOL_PATHS.items())
        },
        "part_a_segment": {
            "mode": "focused_boundary_map",
            "survey_prefix": [item["code"] for item in point_plans],
            "point_plans": point_plans,
            "global_point_offset": 0,
            "maximum_points": len(point_plans),
            "settling_exclusion_s": campaign["part_a"]["settling_exclusion_s"],
            "selected_estimator_span_s": campaign["part_a"]["selected_estimator_span_s"],
            "minimum_point_duration_s": 2100,
            "maximum_expected_point_duration_s": point_wait_timeout_s
            - timing["host_margin_s"],
            "point_wait_timeout_s": point_wait_timeout_s,
            "minimum_remaining_wall_before_new_point_s": point_wait_timeout_s + 180,
            "adaptive_observation_rule": campaign["part_a"]["adaptive_observation_rule"],
            "frequency_control_authority": False,
            "phase_hybrid_authority": False,
            "automatic_restore": False,
        },
        "command_envelope": {
            "prewrite_queries": ["CONFIG?", "DAC?"],
            "point_command_template": "DAC SET 0x%04X",
            "priority_abort": "ACTIVE ABORT",
            "exact_acknowledgement": "DAC manual_apply requested==applied==commanded",
            "normal_command_max_age_s": 2,
            "write_timeout_s": 1,
        },
        "prewrite_gate": {
            "exact_firmware_provenance": True,
            "sole_serial_owner": True,
            "gnss_identity_stable": True,
            "gnss_metadata_control_eligible": True,
            "d14_raw_pps_control_eligible": True,
            "dual_core_partition_fault": "none",
            "dual_core_fail_static": False,
            "d10_has_no_pps_or_control_role": True,
        },
        "point_propagation_invariant": [
            "timestamped DAC SET accepted by sole capture owner",
            "DAC manual_apply records exact requested/applied code",
            "Core 0 ManualDacApplication advances the Part A DAC epoch",
            "selected EST records current manifest and DAC source identity",
            "TDB records exactly the current session and DAC epoch",
            "phase/hybrid preview observes the same code and epoch",
            "all preview authority flags remain false",
        ],
        "terminal_policy": {
            "healthy": ["survey_prefix_complete"],
            "abort_before_write": [
                "wrong_point_order",
                "code_outside_characterized_range",
                "prewrite_gate_failure",
            ],
            "abort_fail_static": [
                "missing_exact_application_acknowledgement",
                "stale_or_cross_epoch_support",
                "queue_transport_or_partition_fault",
                "hybrid_authority_contamination",
            ],
            "automatic_restore": False,
        },
    }
    bundle = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), bundle)
    return bundle


def validate_bundle(path: Path) -> dict[str, Any]:
    value = _read(path.resolve(), "conditional Part A bundle")
    declared_hash = value.get("bundle_sha256")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != 2
        or value.get("bundle_type") != BUNDLE_TYPE
        or declared_hash != canonical_sha256(unsigned)
    ):
        raise ValueError("conditional Part A bundle identity differs")
    campaign = load_campaign(Path(value["programme"]["path"]))
    firmware = value["firmware"]
    bindings = [value["programme"], *value["host_tools"].values()]
    bindings.extend((firmware["build_manifest"], firmware["uf2"]))
    for binding in bindings:
        bound_path = Path(binding["path"])
        if (
            not bound_path.is_file()
            or sha256_file(bound_path) != binding["sha256"]
            or bound_path.stat().st_size != binding["size_bytes"]
        ):
            raise ValueError(f"bundle binding differs: {bound_path}")
    if _firmware(Path(firmware["build_manifest"]["path"])) != firmware:
        raise ValueError("bundle firmware provenance differs")
    expected_plans = campaign["part_a"]["point_plan"]
    segment = value.get("part_a_segment", {})
    if (
        segment.get("point_plans") != expected_plans
        or segment.get("survey_prefix") != [item["code"] for item in expected_plans]
        or segment.get("frequency_control_authority") is not False
        or segment.get("phase_hybrid_authority") is not False
        or value["operator_authority"].get("phase_or_hybrid_actuation") is not False
    ):
        raise ValueError("conditional Part A plan or zero-authority invariant differs")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    value = (
        create_bundle(build_manifest_path=args.build_manifest, output_path=args.output)
        if args.command == "create"
        else validate_bundle(args.bundle)
    )
    print(value["bundle_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
