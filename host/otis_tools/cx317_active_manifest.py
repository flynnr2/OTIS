"""Create an exact run manifest for one preserved bounded-active artifact."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json

from .cx317_active_campaign import POLICY_PATH, load_campaign_spec
from .run_paths import default_csv_files


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def create_active_manifest(
    *,
    campaign: str,
    run_dir: Path,
    build_manifest_path: Path,
    serial_device: str,
    baud: int = 115200,
) -> Path:
    if (run_dir / "run_manifest.json").exists():
        raise FileExistsError(f"run manifest already exists in {run_dir}")
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build["provenance"]
    spec, identities = load_campaign_spec(campaign)
    configuration = provenance["configuration"]
    if configuration["profile_id"] != spec.profile:
        raise ValueError("build-manifest profile does not match requested campaign")
    if provenance["source"]["state"] != "clean":
        raise ValueError("active run requires an artifact built from clean source")
    uf2 = next(
        artifact
        for artifact in build["artifacts"]
        if artifact["name"].endswith(".uf2")
    )
    files = default_csv_files()
    for entry in files:
        if entry["contract"] in {
            "pps_snapshots_v1",
            "dac_steps_v1",
            "environment_v1",
            "estimates_v2",
            "control_previews_v1",
            "active_transactions_v1",
        }:
            entry.pop("optional", None)
    required_files = [entry["path"] for entry in files if not entry.get("optional")]
    now = _utc_now()
    source = provenance["source"]
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": now,
        "started_at_utc": now,
        "stage": f"CX317_BOUNDED_ACTIVE_CAMPAIGN_{campaign}",
        "closed_loop_control": True,
        "actionable": False,
        "actuation_authorized": True,
        "board": "arduino_nano_rp2040_connect",
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "profile_id": spec.profile,
            "git_commit": source["git_commit"],
            "source_state": source["state"],
            "source_sha256": source["sha256"],
            "configuration_sha256": configuration["sha256"],
            "build_identity": f"{source['sha256']}:{configuration['sha256']}",
            "uf2_sha256": uf2["sha256"],
            "uf2_size_bytes": uf2["size_bytes"],
            "build_manifest_path": str(build_manifest_path.resolve()),
            "build_manifest_sha256": sha256(build_manifest_path.read_bytes()).hexdigest(),
        },
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "supervisor_tool": "host.otis_tools.cx317_active_campaign",
            "serial_device": serial_device,
            "baud": baud,
            "sole_serial_owner": True,
            "independent_abort_fifo_required": True,
        },
        "active_campaign": {
            "campaign": campaign,
            "run_identity": spec.run_identity,
            "start_code": spec.start_code,
            "minimum_code": spec.minimum_code,
            "maximum_code": spec.maximum_code,
            "maximum_step_codes": spec.maximum_step,
            "correction_limit": spec.correction_limit,
            "cumulative_limit_codes": spec.cumulative_limit,
            "minimum_applied_cadence_s": 1800,
            "settling_exclusion_s": 900,
            "fresh_authoritative_support_s": 600,
            **identities,
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16000000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10000000},
        ],
        "channels": [
            {
                "channel_id": 1,
                "role": "authoritative_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "role": "pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
        ],
        "contracts": {
            entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            *required_files,
            "raw/serial.log",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
        ],
        "policy": {
            "path": str(POLICY_PATH.relative_to(POLICY_PATH.parents[2])),
            "sha256": identities["active_policy_sha256"],
        },
        "known_limitations": [
            "No oscilloscope is available; analog waveform margin is not claimed.",
            "Fluke 117 calibration applicability is unavailable; voltage readings are commissioning observations.",
            "The h0_tcxo_16mhz token is historical; the connected CX317 source is nominally 10 MHz.",
            "This campaign demonstrates bounded code-domain frequency acquisition, not calibrated UTC, phase lock, or holdover.",
        ],
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_manifest.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", choices=("A", "B"), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--serial-device", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args(argv)
    print(
        create_active_manifest(
            campaign=args.campaign,
            run_dir=args.run_dir,
            build_manifest_path=args.build_manifest,
            serial_device=args.serial_device,
            baud=args.baud,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
