"""Discover a powered instrument, then start the frozen open-ended recorder.

This entry tool is optional experiment scaffolding. It never resets or flashes,
and it does not retry an ambiguous mode request or an unsuccessful entry.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from host.otis_tools.instrument_recorder import (
    InstrumentRecorder,
    RecorderConfig,
)
from host.otis_tools.unattended import MAX_CODE, MIN_CODE, Plan, start


def begin(template_path: Path, device: str, run_root: Path, shared_output: Path) -> dict:
    template = json.loads(template_path.read_bytes())
    workspace = run_root.resolve() / (
        "open-ended-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    document = dict(template, device=device, run_dir=str(workspace / "acquisition"),
                    shared_output_dir=str(shared_output.resolve()), expected_session=1)
    plan = Plan.load(json.dumps(document).encode())  # Validate before opening a device.
    if document.get("observation_kind") != "open_ended":
        raise ValueError("entry requires an open_ended plan template")
    if not run_root.is_absolute() or run_root.name != "runs":
        raise ValueError("run-root must be an absolute local runs directory")
    if ROOT == run_root or ROOT in run_root.parents:
        raise ValueError("acquisition must be outside the frozen source bundle")
    if shutil.disk_usage(run_root.parent).free < plan.minimum_free_bytes:
        raise OSError("insufficient free disk reserve before discovery")
    workspace.mkdir(parents=True)
    discovery = workspace / "discovery"
    state = InstrumentRecorder(RecorderConfig(device=device, run_dir=discovery, duration_s=30)).run()
    (workspace / "discovery-result.json").write_text(json.dumps(state, indent=2) + "\n")
    instrument = state.get("instrument") or {}
    fields = instrument.get("fields") or {}
    if (not state.get("instrument_fresh") or state.get("recording_error") or
            instrument.get("build_identity") != document["expected_build_identity"] or
            instrument.get("policy_identity") != document["expected_policy_sha256"] or
            not instrument.get("applied_code_known") or
            not MIN_CODE <= instrument.get("applied_code", -1) <= MAX_CODE or
            fields.get("fault") != "none" or fields.get("write_state") != "0" or
            state.get("pending_command") is not None or
            any((state.get("observed_record_counts") or {}).get(tag, 0) < 2
                for tag in ("REF", "SNP", "CNT")) or
            instrument.get("last_command_sequence") != instrument.get("completed_command_sequence") or
            instrument.get("mode") != instrument.get("requested_mode") or
            instrument.get("mode") not in {"OBSERVE_HOLD", "AUTO_DISCIPLINE"} or
            fields.get("operating_end_ticks") != "0"):
        return {"error": "passive discovery requires review; no mode request issued",
                "workspace": str(workspace), "discovery": state}
    document["expected_session"] = instrument["session"]
    document["provenance"] = dict(document.get("provenance") or {},
                                  python_version=sys.version,
                                  runtime_versions={name: importlib.metadata.version(name)
                                                    for name in ("pyserial", "jsonschema")},
                                  discovery_mode=instrument["mode"],
                                  attachment_gap="between closed discovery and acquisition; unobserved history")
    plan_path = workspace / "plan.json"
    plan_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    os.chdir(ROOT)
    result = start(plan_path)
    run_dir = Path(document["run_dir"])
    if run_dir.is_dir():
        shutil.copytree(discovery, run_dir / "attachment-discovery")
        shutil.copy2(workspace / "discovery-result.json", run_dir / "attachment-discovery-result.json")
    result["workspace"] = str(workspace)
    (workspace / "entry-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-template", required=True, type=Path)
    parser.add_argument("--device", required=True)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--shared-output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = begin(args.plan_template.resolve(), args.device, args.run_root, args.shared_output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("state", {}).get("phase") == "running" else 2


if __name__ == "__main__":
    raise SystemExit(main())
