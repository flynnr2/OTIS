from __future__ import annotations

from pathlib import Path
import argparse
import csv
import sys

from .contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from .run_loader import load_manifest

KNOWN_BRINGUP_MODES = {
    "SW1_SYNTHETIC_USB",
    "SW1_GPIO_LOOPBACK",
    "SW1_GPS_PPS",
    "SW1_TCXO_OBSERVE",
}

KNOWN_H0_CHANNELS = {0, 1, 2}
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
        if channel_id not in KNOWN_H0_CHANNELS:
            failures.append(f"run_manifest.json: channel_id {channel_id} is not valid for H0")
        if not channel.get("role"):
            failures.append(f"run_manifest.json: channel_id {channel_id} missing role")
        if not channel.get("record_family"):
            failures.append(f"run_manifest.json: channel_id {channel_id} missing record_family")

    return failures


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


def _validate_count_sanity(count_rows: list[dict[str, str]], template: bool) -> list[str]:
    if template:
        return []
    failures: list[str] = []
    for index, row in enumerate(count_rows, start=1):
        if row.get("channel_id") != "2":
            failures.append(f"count_observations.csv: row {index} uses channel_id {row.get('channel_id')!r}; H0 counts belong on CH2")
        try:
            counted_edges = _int(row["counted_edges"])
            flags = int(row.get("flags", "0"), 10)
        except (KeyError, TypeError, ValueError):
            continue
        if counted_edges == 0 and flags == 0:
            failures.append(f"count_observations.csv: row {index} has zero counted_edges without an explicit flag")
        if row.get("source_domain") != "h0_tcxo_16mhz":
            failures.append(f"count_observations.csv: row {index} source_domain must be 'h0_tcxo_16mhz'")
    return failures


def validate_run(run_dir: Path) -> int:
    manifest = load_manifest(run_dir)
    failures: list[str] = _validate_manifest(run_dir, manifest)
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

        context = CsvValidationContext(
            contract=contract,
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            template=manifest.is_template,
        )
        result = validate_csv(run_dir / rel_path, context)
        files_by_contract[contract] = run_dir / rel_path
        if result.ok:
            print(f"OK {rel_path}: {result.row_count} rows")
        else:
            for error in result.errors:
                failures.append(f"{rel_path}: {error}")

    nominal_hz_by_domain = {
        str(domain["name"]): float(domain["nominal_hz"])
        for domain in manifest.data.get("domains", [])
        if "name" in domain and "nominal_hz" in domain
    }
    raw_rows = _read_csv(files_by_contract.get("raw_events_v1", Path("__missing__")))
    count_rows = _read_csv(files_by_contract.get("count_observations_v1", Path("__missing__")))
    failures.extend(_validate_pps_cadence(raw_rows, nominal_hz_by_domain, manifest.is_template))
    failures.extend(_validate_count_sanity(count_rows, manifest.is_template))

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
