from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json
import sys

from .contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from .run_loader import KNOWN_SW1_CAPTURE_MODES, inspect_run_state, load_manifest

KNOWN_BRINGUP_MODES = {
    "SW1_SYNTHETIC_USB",
    "SW1_GPIO_LOOPBACK",
    "SW1_GPS_PPS",
    "SW1_TCXO_OBSERVE",
}

KNOWN_H0_CHANNELS = {0, 1, 2}
KNOWN_H0_COUNT_SOURCE_DOMAINS = {"h0_tcxo_16mhz"}
KNOWN_H1_COUNT_SOURCE_DOMAINS = {"h1_ocxo_open_loop"}
REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _int(value: str) -> int:
    return int(value, 10)


def _validate_manifest(run_dir: Path, manifest) -> list[str]:
    failures: list[str] = []
    mode = manifest.bringup_mode
    if mode is not None and mode not in KNOWN_BRINGUP_MODES:
        failures.append(f"run_manifest.json: bringup_mode {mode!r} is not a known SW1 mode")

    profile = manifest.data.get("profile")
    if manifest.stage == "SW1" or manifest.h_phase == "H0" or profile is not None:
        if not isinstance(profile, dict):
            failures.append("run_manifest.json: profile must be an object")
        else:
            profile_name = str(profile.get("name", ""))
            profile_version = profile.get("version")
            repo_profile_path = REPO_ROOT / "profiles" / f"{profile_name}.yaml"
            if not profile_name:
                failures.append("run_manifest.json: profile.name must not be empty")
            elif not repo_profile_path.exists():
                failures.append(f"run_manifest.json: profile {profile_name!r} does not match a profile file")
            if not isinstance(profile_version, int) or profile_version < 1:
                failures.append("run_manifest.json: profile.version must be a positive integer")

    for channel in manifest.data.get("channels", []):
        try:
            channel_id = int(channel["channel_id"])
        except (KeyError, TypeError, ValueError):
            failures.append("run_manifest.json: channel entry missing integer channel_id")
            continue
        if manifest.h_phase == "H0" and channel_id not in KNOWN_H0_CHANNELS:
            failures.append(f"run_manifest.json: channel_id {channel_id} is not valid for H0")
        if not channel.get("role"):
            failures.append(f"run_manifest.json: channel_id {channel_id} missing role")
        if not channel.get("record_family"):
            failures.append(f"run_manifest.json: channel_id {channel_id} missing record_family")

    return failures


def _manifest_warnings(manifest) -> list[str]:
    warnings: list[str] = []
    allowed_capture_modes = KNOWN_SW1_CAPTURE_MODES
    if manifest.stage == "SW1" and manifest.capture_mode not in allowed_capture_modes:
        warnings.append(
            f"{manifest.path.name}: SW1 capture_mode is {manifest.capture_mode!r}; expected one of {sorted(allowed_capture_modes)}"
        )
    if manifest.stage == "SW1" and not manifest.known_limitations:
        warnings.append(f"{manifest.path.name}: SW1 known_limitations is empty")
    for key in ("firmware_version", "host_tool_version", "firmware_git_commit", "host_git_commit"):
        if key in manifest.data and manifest.data.get(key) in (None, ""):
            warnings.append(f"{manifest.path.name}: {key} is not populated")
    return warnings


def _run_state_warnings(run_dir: Path, manifest) -> list[str]:
    state = inspect_run_state(run_dir)
    warnings: list[str] = []
    if state.capture_in_progress:
        warnings.append(f"{run_dir.name}: {run_dir / 'capture_in_progress.flag'} exists; capture may be partial")
    if not manifest.is_template and not state.complete:
        warnings.append(f"{run_dir.name}: COMPLETE marker is missing; run may not be ready to commit as a fixture")
    return warnings


def _validate_pps_cadence(raw_rows: list[dict[str, str]], nominal_hz_by_domain: dict[str, float], template: bool) -> list[str]:
    if template:
        return []
    failures: list[str] = []
    ticks_by_domain: dict[str, list[int]] = {}
    for row in raw_rows:
        if row.get("record_type") == "REF" and row.get("channel_id") == "1" and row.get("edge") == "R":
            try:
                ticks_by_domain.setdefault(row.get("capture_domain", ""), []).append(_int(row["timestamp_ticks"]))
            except (KeyError, TypeError, ValueError):
                continue

    for domain, ticks in ticks_by_domain.items():
        if len(ticks) < 2:
            continue
        nominal_hz = nominal_hz_by_domain.get(domain)
        if not nominal_hz:
            failures.append(f"raw_events.csv: PPS cadence cannot be checked because domain {domain!r} has no nominal_hz")
            continue
        expected = nominal_hz
        for index, (start, end) in enumerate(zip(ticks, ticks[1:]), start=1):
            interval = end - start
            if not (0.8 * expected <= interval <= 1.2 * expected):
                failures.append(
                    f"raw_events.csv: PPS interval {index} in {domain} is {interval} ticks; expected approximately {expected:.0f}"
                )
    return failures


def _validate_count_sanity(count_rows: list[dict[str, str]], manifest, template: bool) -> list[str]:
    if template:
        return []
    failures: list[str] = []
    if manifest.h_phase == "H1":
        allowed_source_domains = KNOWN_H1_COUNT_SOURCE_DOMAINS | {
            str(domain["name"])
            for domain in manifest.data.get("domains", [])
            if str(domain.get("name", "")).startswith("h1_")
        }
        phase_label = "H1"
    else:
        allowed_source_domains = KNOWN_H0_COUNT_SOURCE_DOMAINS
        phase_label = "H0"

    for index, row in enumerate(count_rows, start=1):
        if row.get("channel_id") != "2":
            failures.append(
                f"count_observations.csv: row {index} uses channel_id {row.get('channel_id')!r}; "
                f"{phase_label} counts belong on CH2"
            )
        try:
            counted_edges = _int(row["counted_edges"])
            flags = int(row.get("flags", "0"), 10)
        except (KeyError, TypeError, ValueError):
            continue
        if counted_edges == 0 and flags == 0:
            failures.append(f"count_observations.csv: row {index} has zero counted_edges without an explicit flag")
        if row.get("source_domain") not in allowed_source_domains:
            failures.append(
                f"count_observations.csv: row {index} source_domain {row.get('source_domain')!r} "
                f"must be one of {sorted(allowed_source_domains)}"
            )
    return failures


def validate_run(run_dir: Path) -> int:
    try:
        manifest = load_manifest(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {run_dir}: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = _validate_manifest(run_dir, manifest)
    warnings: list[str] = _manifest_warnings(manifest) + _run_state_warnings(run_dir, manifest)
    files_by_contract: dict[str, Path] = {}

    for file_entry in manifest.files:
        contract = file_entry.get("contract")
        rel_path = file_entry.get("path")
        if not rel_path:
            failures.append("manifest file entry missing path")
            continue
        if contract not in CONTRACT_FIELDS:
            failures.append(f"{rel_path}: unsupported or missing contract {contract!r}")
            continue

        path = run_dir / rel_path
        optional = bool(file_entry.get("optional", False))
        if optional and not path.exists():
            warnings.append(f"{rel_path}: optional expected artifact is missing")
            continue

        context = CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            template=manifest.is_template,
        )
        result = validate_csv(path, context)
        files_by_contract[contract] = path
        if result.ok:
            print(f"OK {rel_path}: {result.row_count} rows")
        else:
            for error in result.errors:
                failures.append(f"{rel_path}: {error}")
        for warning in result.warnings:
            warnings.append(f"{rel_path}: {warning}")

    for artifact in manifest.expected_artifacts:
        if artifact and not (run_dir / artifact).exists():
            warnings.append(f"{artifact}: expected artifact is missing")

    nominal_hz_by_domain = {
        str(domain["name"]): float(domain["nominal_hz"])
        for domain in manifest.data.get("domains", [])
        if "name" in domain and domain.get("nominal_hz") is not None
    }
    raw_rows = _read_csv(files_by_contract.get("raw_events_v1", Path("__missing__")))
    count_rows = _read_csv(files_by_contract.get("count_observations_v1", Path("__missing__")))
    failures.extend(_validate_pps_cadence(raw_rows, nominal_hz_by_domain, manifest.is_template))
    failures.extend(_validate_count_sanity(count_rows, manifest, manifest.is_template))

    for warning in warnings:
        print(f"WARN {warning}", file=sys.stderr)
    for failure in failures:
        print(f"ERROR {failure}", file=sys.stderr)

    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an OTIS run directory.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    raise SystemExit(validate_run(args.run_dir))


if __name__ == "__main__":
    main()
