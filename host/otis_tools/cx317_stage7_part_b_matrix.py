"""Derive the exact Stage 7 Part B build matrix from a passed Part A2 gate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import copy
import json
import os
import tempfile

from tools.firmware_matrix import DEFAULT_MATRIX, load_matrix
from .cx317_stage7_gate_validation import part_a2_progression_gate_valid
from .cx317_counterfactual_deadband import frozen_content_binding_matches


PART_B_PROFILE = "cx317_dual_core_active_endurance_part_b"
STAGE7_PROMPT = Path(
    "docs/60_EXPERIMENTS/"
    "CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_CODEX_PROGRAMME/"
    "07_DUAL_CORE_ACTIVE_ENDURANCE_PROMPT.md"
)
STAGE7_PROMPT_SHA256 = (
    "0ab20ab75c58583789fad512f0eb326ef58bfd467e73ebb35fa2281c94efc512"
)


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def derive_part_b_matrix(
    *,
    part_a2_gate_path: Path,
    output_path: Path,
    base_matrix_path: Path = DEFAULT_MATRIX,
) -> tuple[Path, int]:
    """Write one immutable matrix whose Part B start is the passed A2 final."""
    part_a2_gate_path = part_a2_gate_path.resolve()
    output_path = output_path.resolve()
    base_matrix_path = base_matrix_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"derived matrix already exists: {output_path}")
    gate = json.loads(part_a2_gate_path.read_text(encoding="utf-8"))
    transactions = gate.get("transactions", {})
    applications = int(transactions.get("application_count", 0))
    if not part_a2_progression_gate_valid(gate):
        raise ValueError("Stage 7 Part A2 transaction gate is not passed")
    start_code = int(transactions.get("final_code", -1))
    if not 0xA800 <= start_code <= 0xAB00:
        raise ValueError("passed Part A2 final code is outside A800..AB00")

    prompt_path = DEFAULT_MATRIX.parents[2] / STAGE7_PROMPT
    if not frozen_content_binding_matches(prompt_path, STAGE7_PROMPT_SHA256):
        raise ValueError(
            "Stage 7 prompt and tracked history lack the frozen content hash"
        )
    matrix = copy.deepcopy(load_matrix(base_matrix_path))
    profiles = {
        profile["id"]: profile for profile in matrix["profiles"]
    }
    profile = profiles.get(PART_B_PROFILE)
    if profile is None:
        raise ValueError("base matrix lacks the Stage 7 Part B profile")
    profile["defines"]["OTIS_CX317_ACTIVE_START_CODE"] = (
        f"0x{start_code:04X}u"
    )
    matrix["stage7_part_b_derivation"] = {
        "schema_version": 1,
        "base_matrix_path": str(base_matrix_path),
        "base_matrix_sha256": _sha256_file(base_matrix_path),
        "stage7_prompt_path": STAGE7_PROMPT.as_posix(),
        "stage7_prompt_sha256": STAGE7_PROMPT_SHA256,
        "part_a2_gate_path": str(part_a2_gate_path),
        "part_a2_gate_sha256": _sha256_file(part_a2_gate_path),
        "part_a2_application_count": applications,
        "exact_part_b_start_code": start_code,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(matrix, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(output_path)
    descriptor = os.open(output_path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    load_matrix(output_path)
    return output_path, start_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part-a2-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-matrix", type=Path, default=DEFAULT_MATRIX)
    args = parser.parse_args(argv)
    path, start_code = derive_part_b_matrix(
        part_a2_gate_path=args.part_a2_gate,
        output_path=args.output,
        base_matrix_path=args.base_matrix,
    )
    print(f"{path}\nstart_code=0x{start_code:04X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
