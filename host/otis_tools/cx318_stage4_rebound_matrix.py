"""Derive the exact nonactuating CX318 Stage 4 matrix from sealed setup evidence."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import copy
import json
import os
import tempfile

from tools.firmware_matrix import DEFAULT_MATRIX, load_matrix
from .cx318_stage4_static_code_preflight import validate_setup_run


PROFILE_ID = "cx318_stage4_nonactuating_preview"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def derive_rebound_matrix(
    *, setup_run_dir: Path, output_path: Path,
    base_matrix_path: Path = DEFAULT_MATRIX,
) -> tuple[Path, int, int]:
    output_path = output_path.resolve()
    base_matrix_path = base_matrix_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"derived matrix already exists: {output_path}")
    evidence = validate_setup_run(setup_run_dir)
    base_matrix = load_matrix(base_matrix_path)
    tracked_matrix = load_matrix(DEFAULT_MATRIX.resolve())
    if base_matrix != tracked_matrix:
        raise ValueError("base matrix differs from the exact tracked firmware matrix")
    matrix = copy.deepcopy(base_matrix)
    profiles = {item["id"]: item for item in matrix["profiles"]}
    profile = profiles.get(PROFILE_ID)
    if profile is None or profile.get("expect") != "pass":
        raise ValueError("base matrix lacks the supported Stage 4 profile")
    original_defines = dict(profile["defines"])
    if original_defines.get("OTIS_ENABLE_CX318_STAGE4_PREVIEW") != "1":
        raise ValueError("base Stage 4 profile is not the preview profile")
    profile["defines"]["OTIS_CX318_STAGE4_STATIC_CODE"] = (
        f"0x{evidence.confirmed_code:04X}u"
    )
    profile["defines"]["OTIS_CX318_STAGE4_DAC_EPOCH"] = f"{evidence.dac_epoch}u"
    changed = {
        key
        for key in set(original_defines) | set(profile["defines"])
        if original_defines.get(key) != profile["defines"].get(key)
    }
    if changed != {
        "OTIS_CX318_STAGE4_STATIC_CODE",
        "OTIS_CX318_STAGE4_DAC_EPOCH",
    }:
        raise ValueError(f"derived matrix changed unexpected defines: {sorted(changed)}")
    matrix["cx318_stage4_rebound_derivation"] = {
        "schema_version": 1,
        "base_matrix_path": str(base_matrix_path),
        "base_matrix_sha256": _sha256_file(base_matrix_path),
        "setup_run_path": evidence.source_run_path,
        "setup_source_identities": evidence.source_identities,
        "premise_amendment": "operator_authorized_single_setup_write",
        "exact_static_code": evidence.confirmed_code,
        "exact_static_code_hex": f"0x{evidence.confirmed_code:04X}",
        "exact_dac_epoch": evidence.dac_epoch,
        "changed_defines": sorted(changed),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent,
        prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        json.dump(matrix, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(output_path)
    load_matrix(output_path)
    return output_path, evidence.confirmed_code, evidence.dac_epoch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-matrix", type=Path, default=DEFAULT_MATRIX)
    args = parser.parse_args(argv)
    path, code, epoch = derive_rebound_matrix(
        setup_run_dir=args.setup_run,
        output_path=args.output,
        base_matrix_path=args.base_matrix,
    )
    print(f"{path}\nstatic_code=0x{code:04X}\ndac_epoch={epoch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
