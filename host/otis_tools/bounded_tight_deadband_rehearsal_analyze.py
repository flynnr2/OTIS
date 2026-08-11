"""Analyze an accelerated bounded tight-deadband transcript without I/O."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .bounded_tight_deadband_bundle import _sha256_file, validate_proposal
from .bounded_tight_deadband_outcome_contract import canonical_sha256, evaluate


TOOL_ID = "cx319_g2_accelerated_analyzer_v1"


def _atomic_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite G2 analysis: {path}")
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


def analyze(
    *, proposal_path: Path, transcript_path: Path, output_path: Path
) -> dict[str, Any]:
    proposal = validate_proposal(proposal_path)
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    if not isinstance(transcript, dict):
        raise ValueError("G2 transcript must be a JSON object")
    if transcript.get("proposal_bundle_sha256") != proposal["bundle_sha256"]:
        raise ValueError("G2 transcript differs from its proposal bundle")
    verdict = evaluate(transcript)
    unsigned = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": verdict["status"],
        "claims_boundary": (
            "accelerated no-I/O host operational-path evidence only; not "
            "physical setup, actuation, plant-response, or G2 live authority"
        ),
        "bindings": {
            "proposal_bundle_sha256": proposal["bundle_sha256"],
            "proposal_file_sha256": _sha256_file(proposal_path),
            "transcript_sha256": _sha256_file(transcript_path),
            "analyzer_sha256": _sha256_file(Path(__file__)),
        },
        "verdict": verdict,
    }
    result = {**unsigned, "analysis_sha256": canonical_sha256(unsigned)}
    _atomic_new(output_path.resolve(), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = analyze(
        proposal_path=args.proposal,
        transcript_path=args.transcript,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
