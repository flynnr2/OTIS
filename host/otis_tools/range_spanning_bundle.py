"""Freeze and validate the exact CX319 Part A physical bundle."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .range_spanning_programme import DEFAULT_PROFILE, load_programme


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "cx319_range_spanning_bundle_v1"
BUNDLE_TYPE = "cx319_range_spanning_part_a_bundle_v1"
EXPECTED_PROFILE = "cx319_range_map_part_a"
EXPECTED_FQBN = "rp2040:rp2040:arduino_nano_connect:freq=133"
EXPECTED_BOARD_SERIAL = "503533748A919118"

HOST_TOOL_PATHS = {
    "bundle": Path(__file__),
    "programme": Path(__file__).with_name("range_spanning_programme.py"),
    "rehearsal": Path(__file__).with_name("range_spanning_rehearsal.py"),
    "runner": Path(__file__).with_name("range_spanning_run.py"),
    "analyzer": Path(__file__).with_name("range_spanning_analyze.py"),
    "capture": Path(__file__).with_name("capture_device.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "capture_checks": Path(__file__).with_name("capture_runtime_checks.py"),
    "contracts": Path(__file__).with_name("contracts.py"),
    "time_domains": Path(__file__).with_name("time_domains.py"),
    "run_validation": Path(__file__).with_name("validate_run.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_index": Path(__file__).with_name("evidence_index.py"),
}


def canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"bound file is unavailable: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        raise ValueError(f"cannot read predecessor CSV: {path}: {exc}") from exc


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen bundle: {path}")
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


def _firmware(build_manifest_path: Path) -> dict[str, Any]:
    build_manifest_path = build_manifest_path.resolve()
    manifest = _read(build_manifest_path, "firmware build manifest")
    provenance = manifest.get("provenance", {})
    configuration = provenance.get("configuration", {})
    target = provenance.get("target", {})
    source = provenance.get("source", {})
    invocation = provenance.get("invocation", {})
    artifacts = manifest.get("artifacts", [])
    if (
        configuration.get("profile_id") != EXPECTED_PROFILE
        or target.get("fqbn") != EXPECTED_FQBN
        or not isinstance(configuration.get("defines"), dict)
        or configuration["defines"].get("OTIS_ENABLE_CX317_BOUNDED_ACTIVE")
        != "0"
        or configuration["defines"].get("OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW")
        != "1"
    ):
        raise ValueError("firmware build is not the zero-authority Part A profile")
    uf2_entry = next(
        (
            item
            for item in artifacts
            if isinstance(item, dict)
            and str(item.get("name", "")).endswith(".uf2")
        ),
        None,
    )
    if uf2_entry is None:
        raise ValueError("firmware build manifest has no UF2 artifact")
    uf2_path = build_manifest_path.parent / str(uf2_entry["name"])
    if (
        not uf2_path.is_file()
        or sha256_file(uf2_path) != uf2_entry.get("sha256")
    ):
        raise ValueError("firmware UF2 identity differs from its manifest")
    return {
        "profile_id": EXPECTED_PROFILE,
        "fqbn": EXPECTED_FQBN,
        "configuration_sha256": configuration["sha256"],
        "source_sha256": source["sha256"],
        "source_state": source["state"],
        "git_commit": source["git_commit"],
        "build_invocation_id": invocation["id"],
        "build_manifest": _binding(build_manifest_path),
        "uf2": _binding(uf2_path),
        "defines": dict(sorted(configuration["defines"].items())),
        "resource_budget": manifest.get("resource_budget"),
    }


def _continuation(
    *, run_dir: Path, programme: dict[str, Any], firmware: dict[str, Any]
) -> dict[str, Any]:
    from .evidence import validate_evidence_snapshot
    from .run_loader import load_manifest

    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise ValueError(f"continuation predecessor is unavailable: {run_dir}")
    entry_path = run_dir / "reports/range_spanning_firmware_entry_v2.json"
    if not entry_path.is_file():
        entry_path = run_dir / "reports/range_spanning_firmware_flash_v1.json"
    paths = {
        "run_manifest": run_dir / "run_manifest.json",
        "supervisor_state": run_dir / "reports/range_spanning_supervisor_state.json",
        "analysis": run_dir / "reports/range_spanning_analysis_v1.json",
        "seal": run_dir / "reports/range_spanning_seal_v1.json",
        "firmware_entry": entry_path,
        "complete": run_dir / "COMPLETE",
        "evidence_manifest": run_dir / "evidence_manifest.json",
    }
    values = {name: _read(path, name) for name, path in paths.items()}
    manifest = values["run_manifest"]
    state = values["supervisor_state"]
    analysis = values["analysis"]
    seal = values["seal"]
    flash = values["firmware_entry"]
    complete = values["complete"]
    evidence = values["evidence_manifest"]
    points = list(programme["part_a"]["survey_point_order"])
    completed = state.get("completed_points", [])
    completed_codes = [
        int(item.get("code", -1)) for item in completed if isinstance(item, dict)
    ]
    if not completed_codes or completed_codes != points[: len(completed_codes)]:
        raise ValueError("predecessor does not contain an exact Part A survey prefix")
    if len(completed_codes) >= len(points):
        raise ValueError("predecessor already completed the Part A survey")
    terminal = state.get("terminal", {})
    if terminal != complete.get("terminal") or not (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == "finite_wall_deadline_before_next_point"
        and int(terminal.get("completed_point_count", -1)) == len(completed_codes)
    ):
        raise ValueError("predecessor did not end at a healthy finite boundary")
    if not (
        analysis.get("status") == "passed"
        and seal.get("status") == "passed"
        and seal.get("analysis_sha256") == analysis.get("analysis_sha256")
        and int(analysis.get("completed_point_count", -1)) == len(completed_codes)
        and [int(item.get("code", -1)) for item in analysis.get("point_results", [])]
        == completed_codes
    ):
        raise ValueError("predecessor analysis or seal is not an exact passing prefix")
    manifest_firmware = manifest.get("firmware", {})
    if any(
        manifest_firmware.get(key) != firmware.get(key)
        for key in (
            "profile_id",
            "fqbn",
            "git_commit",
            "source_sha256",
            "configuration_sha256",
            "build_invocation_id",
            "build_manifest",
            "uf2",
        )
    ):
        raise ValueError("predecessor firmware identity differs from continuation")
    exact_flash = (
        flash.get("operation") == "exact_range_map_firmware_flash"
        and int(flash.get("firmware_flash_count", -1)) == 1
        and flash.get("board_after", {}).get("serial_number")
        == EXPECTED_BOARD_SERIAL
    )
    confirmed_attachment = (
        flash.get("operation") == "confirmed_installed_firmware_running_attachment"
        and int(flash.get("firmware_flash_count", -1)) == 0
        and int(flash.get("board_reset_count", -1)) == 0
        and int(flash.get("ordinary_restart_count", -1)) == 0
        and flash.get("board", {}).get("serial_number") == EXPECTED_BOARD_SERIAL
    )
    if not (
        flash.get("status") == "passed"
        and (exact_flash or confirmed_attachment)
        and flash.get("uf2_sha256") == firmware["uf2"]["sha256"]
        and flash.get("profile_id") == firmware["profile_id"]
    ):
        raise ValueError("predecessor does not bind the exact installed firmware")
    evidence_failures, _warnings = validate_evidence_snapshot(
        run_dir, load_manifest(run_dir)
    )
    if evidence_failures:
        raise ValueError(
            "predecessor evidence snapshot differs: " + "; ".join(evidence_failures)
        )
    last = completed[-1]
    matching_hybrid = [
        row
        for row in _read_csv(
            run_dir / "csv/hybrid_preview_decisions_v1.csv"
        )
        if row.get("actual_applied_code") == str(int(last["code"]))
        and row.get("dac_epoch") == str(int(last["dac_epoch"]))
    ]
    if not matching_hybrid or any(
        matching_hybrid[-1].get(field) != "false"
        for field in ("actionable", "actuation_authorized", "authorization_consumed")
    ):
        raise ValueError("predecessor hybrid consumer state is absent or actionable")
    expected_state = {
        "applied_code": int(last["code"]),
        "applied_code_hex": f"0x{int(last['code']):04X}",
        "dac_epoch": int(last["dac_epoch"]),
        "band_state": str(last["state_after"]),
        "hybrid_band_state": str(matching_hybrid[-1]["band_state_after"]),
        "next_code": points[len(completed_codes)],
        "next_code_hex": f"0x{points[len(completed_codes)]:04X}",
        "global_point_offset": len(completed_codes),
    }
    predecessor_bundle = Path(str(manifest.get("bundle", {}).get("path", "")))
    if not predecessor_bundle.is_file() or sha256_file(predecessor_bundle) != manifest.get(
        "bundle", {}
    ).get("sha256"):
        raise ValueError("predecessor bundle file identity differs")
    snapshot_digest = evidence.get("snapshot_digest")
    if not (
        isinstance(snapshot_digest, str)
        and len(snapshot_digest) == 64
        and all(character in "0123456789abcdef" for character in snapshot_digest)
    ):
        raise ValueError("predecessor snapshot identity is invalid")
    return {
        "mode": "state_preserving_running_attach",
        "firmware_flashes_allowed": 0,
        "board_resets_allowed": 0,
        "dac_writes_before_attachment_gate_allowed": 0,
        "predecessor_run_id": str(state.get("run_id", "")),
        "predecessor_run_dir": str(run_dir),
        "predecessor_bundle": _binding(predecessor_bundle),
        "predecessor_bundle_sha256": str(manifest["bundle"]["bundle_sha256"]),
        "predecessor_snapshot_digest": str(evidence["snapshot_digest"]),
        "predecessor_files": {
            name: _binding(path) for name, path in sorted(paths.items())
        },
        "expected_live_state": expected_state,
    }


def create_bundle(
    *,
    build_manifest_path: Path,
    output_path: Path,
    maximum_points: int,
    continuation_run: Path | None = None,
) -> dict[str, Any]:
    programme = load_programme()
    points = list(programme["part_a"]["survey_point_order"])
    firmware = _firmware(build_manifest_path)
    continuation = (
        _continuation(run_dir=continuation_run, programme=programme, firmware=firmware)
        if continuation_run is not None
        else None
    )
    point_offset = (
        int(continuation["expected_live_state"]["global_point_offset"])
        if continuation is not None
        else 0
    )
    available_points = points[point_offset:]
    if maximum_points < 1 or maximum_points > len(available_points):
        raise ValueError("maximum_points must select a non-empty available survey prefix")
    operational_timing = programme["part_a"]["operational_point_timing"]
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "programme": _binding(DEFAULT_PROFILE),
        "operator_authority": programme["operator_authority"],
        "device": {
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
            "baud": 115200,
            "serial_path_resolution": "locate_unique_current_port_by_usb_serial",
        },
        "firmware": firmware,
        "entry": (
            continuation
            if continuation is not None
            else {
                "mode": "fresh_exact_firmware_flash",
                "firmware_flashes_allowed": 1,
                "board_resets_allowed": 1,
                "dac_writes_before_attachment_gate_allowed": 0,
            }
        ),
        "host_tools": {
            name: _binding(path) for name, path in sorted(HOST_TOOL_PATHS.items())
        },
        "part_a_segment": {
            "survey_prefix": available_points[:maximum_points],
            "global_point_offset": point_offset,
            "maximum_points": maximum_points,
            "fresh_policy_observations_per_point": 2,
            "settling_exclusion_s": 900,
            "selected_estimator_span_s": 600,
            "minimum_point_duration_s": 2100,
            "maximum_expected_point_duration_s": operational_timing[
                "worst_case_policy_bearing_duration_s"
            ],
            "point_wait_timeout_s": operational_timing["host_wait_timeout_s"],
            "minimum_remaining_wall_before_new_point_s": operational_timing[
                "minimum_remaining_wall_before_new_point_s"
            ],
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
            "healthy": [
                "survey_prefix_complete",
                "finite_wall_deadline_before_next_point",
            ],
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
    value = _read(path.resolve(), "range-spanning bundle")
    declared_hash = value.get("bundle_sha256")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("bundle_type") != BUNDLE_TYPE
        or declared_hash != canonical_sha256(unsigned)
    ):
        raise ValueError("range-spanning bundle identity differs")
    load_programme(Path(value["programme"]["path"]))
    bindings = [value["programme"], *value["host_tools"].values()]
    firmware = value["firmware"]
    bindings.extend((firmware["build_manifest"], firmware["uf2"]))
    entry = value.get("entry", {})
    if entry.get("mode") == "state_preserving_running_attach":
        bindings.extend(entry["predecessor_files"].values())
        bindings.append(entry["predecessor_bundle"])
    for binding in bindings:
        path_value = Path(binding["path"])
        if (
            not path_value.is_file()
            or sha256_file(path_value) != binding["sha256"]
            or path_value.stat().st_size != binding["size_bytes"]
        ):
            raise ValueError(f"bundle binding differs: {path_value}")
    observed_firmware = _firmware(Path(firmware["build_manifest"]["path"]))
    if observed_firmware != firmware:
        raise ValueError("bundle firmware provenance differs")
    if value["operator_authority"].get("phase_or_hybrid_actuation") is not False:
        raise ValueError("bundle must retain zero phase/hybrid authority")
    if entry.get("mode") == "state_preserving_running_attach":
        observed_entry = _continuation(
            run_dir=Path(entry["predecessor_run_dir"]),
            programme=load_programme(Path(value["programme"]["path"])),
            firmware=firmware,
        )
        if observed_entry != entry:
            raise ValueError("continuation predecessor binding differs")
    return value


def validate_bundle_for_offline_reanalysis(path: Path) -> dict[str, Any]:
    """Validate the frozen campaign identity without rebinding old host tools.

    A corrected offline analyzer must consume the exact bundle that governed
    acquisition, but it cannot truthfully satisfy that bundle's old analyzer
    and validator hashes.  The reanalysis product separately records both
    generations.  Firmware, programme, predecessor, authority, and canonical
    bundle identities remain strict here.
    """

    value = _read(path.resolve(), "range-spanning bundle")
    declared_hash = value.get("bundle_sha256")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("bundle_type") != BUNDLE_TYPE
        or declared_hash != canonical_sha256(unsigned)
    ):
        raise ValueError("range-spanning bundle identity differs")
    load_programme(Path(value["programme"]["path"]))
    firmware = value["firmware"]
    bindings = [value["programme"], firmware["build_manifest"], firmware["uf2"]]
    entry = value.get("entry", {})
    if entry.get("mode") == "state_preserving_running_attach":
        bindings.extend(entry["predecessor_files"].values())
        bindings.append(entry["predecessor_bundle"])
    for binding in bindings:
        path_value = Path(binding["path"])
        if (
            not path_value.is_file()
            or sha256_file(path_value) != binding["sha256"]
            or path_value.stat().st_size != binding["size_bytes"]
        ):
            raise ValueError(f"bundle acquisition binding differs: {path_value}")
    observed_firmware = _firmware(Path(firmware["build_manifest"]["path"]))
    if observed_firmware != firmware:
        raise ValueError("bundle firmware provenance differs")
    if value["operator_authority"].get("phase_or_hybrid_actuation") is not False:
        raise ValueError("bundle must retain zero phase/hybrid authority")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--maximum-points", type=int, required=True)
    create.add_argument("--continuation-run", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    value = (
        create_bundle(
            build_manifest_path=args.build_manifest,
            output_path=args.output,
            maximum_points=args.maximum_points,
            continuation_run=args.continuation_run,
        )
        if args.command == "create"
        else validate_bundle(args.bundle)
    )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
