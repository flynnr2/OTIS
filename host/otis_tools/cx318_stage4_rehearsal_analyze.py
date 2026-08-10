"""Analyze the finite zero-authority rehearsal required before CX318 Stage 4."""

from __future__ import annotations

from pathlib import Path
import argparse
import json

from .cx318_stage4_live_analyze import _write_json_atomic, analyze_run


EXPECTED_STAGE = "CX318_STAGE4_NONACTUATING_REHEARSAL"
TOOL_VERSION = "cx318_stage4_rehearsal_analyze_v1"
DEFAULT_OUTPUT = Path("reports/cx318_stage4_rehearsal_analysis_v1.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze_run(
            args.run_dir,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            expected_stage=EXPECTED_STAGE,
            hard_minimum_frequency_events=1,
            hard_minimum_duration_s=600,
            tool_version=TOOL_VERSION,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    output = args.output or (args.run_dir / DEFAULT_OUTPUT)
    _write_json_atomic(output, result)
    print(json.dumps({"status": result["status"], "output": str(output)}, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
