from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import shutil


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "runs"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_stage(stage: str) -> tuple[str, str]:
    normalized = stage.lower()
    if normalized.startswith("h0_"):
        return "H0", normalized.removeprefix("h0_").upper()
    return "", normalized.upper()


def _rewrite_manifest(path: Path, stage_key: str, capture_type: str, run_id: str) -> None:
    h_phase, stage_name = _split_stage(stage_key)
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    manifest["run_id"] = run_id
    manifest["template"] = False
    manifest["capture_type"] = capture_type
    if stage_name:
        manifest["stage"] = stage_name
    if h_phase:
        manifest["h_phase"] = h_phase
    manifest["started_at_utc"] = _utc_now()

    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")


def _rewrite_config(path: Path, capture_type: str, run_id: str) -> None:
    replacements = {
        "OTIS_CAPTURE_TYPE=": f"OTIS_CAPTURE_TYPE={capture_type}",
        "OTIS_RUN_ID=": f"OTIS_RUN_ID={run_id}",
    }
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        for prefix, replacement in replacements.items():
            if line.startswith(prefix):
                line = replacement
                break
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def init_run(stage: str, capture_type: str, run_id: str, force: bool = False) -> Path:
    template_dir = RUNS_ROOT / stage / capture_type / "_template"
    if not template_dir.exists():
        raise FileNotFoundError(f"template directory does not exist: {template_dir}")

    run_dir = RUNS_ROOT / stage / capture_type / run_id
    if run_dir.exists():
        if not force:
            raise FileExistsError(f"run directory already exists: {run_dir}; pass --force to replace it")
        shutil.rmtree(run_dir)

    shutil.copytree(template_dir, run_dir)
    _rewrite_manifest(run_dir / "manifest.json", stage, capture_type, run_id)
    _rewrite_config(run_dir / "config.env", capture_type, run_id)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an OTIS run directory from a scaffold template.")
    parser.add_argument("--stage", required=True, help="Run stage directory, for example h0_sw1.")
    parser.add_argument("--capture-type", required=True, help="Capture type directory, for example gps_pps.")
    parser.add_argument("--run-id", required=True, help="New run directory name, for example run_001.")
    parser.add_argument("--force", action="store_true", help="Replace an existing run directory.")
    args = parser.parse_args()

    try:
        run_dir = init_run(args.stage, args.capture_type, args.run_id, args.force)
    except (FileExistsError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    print(run_dir.relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
