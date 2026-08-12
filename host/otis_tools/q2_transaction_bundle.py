"""Freeze the exact diagnostic firmware/host bundle for Q2."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_ID = "cx319_q2_inhibited_transaction"
BUNDLE_ID = "cx319_q2_inhibited_transaction_bundle_v1"
FIRMWARE_MODULE = REPO_ROOT / "firmware/arduino/otis_nano_rp2040_connect/otis_q2_transaction_rehearsal.cpp"
AUTHORITY_DOCUMENT = REPO_ROOT / "docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/16_Q1_Q3_SEQUENCE_AUTHORITY.md"
REVIEW_DOCUMENT = REPO_ROOT / "docs/10_REFERENCE_ARCHITECTURE/OTIS_ADVERSARIAL_ARCHITECTURE_REVIEW.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _binding(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"Q2 bundle input is missing: {resolved}")
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _binding_current(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return False
    path = Path(value["path"])
    return (
        path.is_file()
        and value.get("sha256") == _sha256_file(path)
        and value.get("size_bytes") == path.stat().st_size
    )


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable Q2 bundle: {path}")
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False
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


def create_bundle(
    *, build_manifest_path: Path, uf2_path: Path, serial_device: str,
    output_path: Path
) -> dict[str, Any]:
    if not serial_device.startswith("/dev/"):
        raise ValueError("Q2 requires an explicit serial device")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT, check=True, text=True, capture_output=True
    ).stdout
    if status:
        raise ValueError("Q2 exact bundle requires a clean source tree")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        text=True, capture_output=True
    ).stdout.strip()
    build = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    provenance = build.get("provenance", {})
    source = provenance.get("source", {})
    configuration = provenance.get("configuration", {})
    defines = configuration.get("defines", {})
    if (
        source.get("state") != "clean"
        or source.get("git_commit") != head
        or configuration.get("profile_id") != PROFILE_ID
        or defines.get("OTIS_CX317_ACTIVE_CAMPAIGN")
        != "OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER"
        or defines.get("OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL") != "1"
    ):
        raise ValueError("Q2 build manifest is not the clean diagnostic profile at HEAD")
    start_code_literal = str(defines.get("OTIS_CX317_ACTIVE_START_CODE", ""))
    try:
        start_code = int(start_code_literal.rstrip("uUlL"), 0)
    except ValueError as error:
        raise ValueError("Q2 build manifest has no valid active start code") from error
    if start_code != 0xA808:
        raise ValueError("Q2 diagnostic profile requires the exact A808 setup code")
    uf2_artifact = next(
        (entry for entry in build.get("artifacts", []) if str(entry.get("name", "")).endswith(".uf2")),
        None,
    )
    if uf2_artifact is None or uf2_artifact.get("sha256") != _sha256_file(uf2_path):
        raise ValueError("Q2 UF2 does not match its build manifest")
    from . import q2_transaction_analyze, q2_transaction_run
    from . import capture_device, evidence, evidence_index, serial_commands

    payload: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": BUNDLE_ID,
        "created_utc": _utc_now(),
        "gate": "Q2",
        "source_revision": head,
        "firmware": {
            "profile_id": PROFILE_ID,
            "git_commit": source["git_commit"],
            "source_state": source["state"],
            "source_sha256": source["sha256"],
            "configuration_sha256": configuration["sha256"],
            "start_code": start_code,
            "fqbn": configuration["fqbn"],
            "build_manifest": _binding(build_manifest_path),
            "uf2": _binding(uf2_path),
        },
        "device": {
            "path": serial_device,
            "expected_board_serial": "503533748A919118",
            "baud": 115200,
            "continuous_single_owner": True,
        },
        "physical_prerequisite": {
            "operator_confirmation_required_at_run": True,
            "topology": "dac_analogue_output_disconnected_from_oscillator_efc_vctrl",
            "oscillator_powered": True,
            "dac_i2c_reachable": True,
            "maximum_inhibited_window_s": 1800,
        },
        "finite_case_contract": {
            "case_count": 38,
            "nonce_bound": True,
            "physical_i2c_from_case_engine": 0,
            "injected_setup_failures": 1,
            "injected_automatic_ambiguous_outcomes": 1,
            "production_setup_physical_i2c_attempts": 1,
            "production_automatic_i2c_attempts": 0,
        },
        "commands": {
            "allowed": [
                "CONFIG?", "DAC?", "ACTIVE LEASE <sequence>",
                "ACTIVE SNAPSHOT <nonce>", "Q2 CASE <nonce> <case_id>",
                "ACTIVE SETUP <exact_current_authority>",
            ],
            "forbidden": ["ACTIVE ARM", "DAC SET", "DAC MID", "DAC ZERO", "SWEEP", "PPSGEN"],
            "write_timeout_s": 1.0,
            "normal_command_max_age_s": 5.0,
        },
        "host_tools": {
            "bundle": _binding(Path(__file__)),
            "runner": _binding(Path(q2_transaction_run.__file__)),
            "analyzer": _binding(Path(q2_transaction_analyze.__file__)),
            "capture": _binding(Path(capture_device.__file__)),
            "serial_commands": _binding(Path(serial_commands.__file__)),
            "evidence": _binding(Path(evidence.__file__)),
            "evidence_index": _binding(Path(evidence_index.__file__)),
        },
        "design_bindings": {
            "firmware_case_engine": _binding(FIRMWARE_MODULE),
            "sequence_authority": _binding(AUTHORITY_DOCUMENT),
            "adversarial_review": _binding(REVIEW_DOCUMENT),
        },
        "claims_boundary": "No physical oscillator movement and no live-control or Q4 authority",
    }
    payload["bundle_sha256"] = _canonical_sha256(payload)
    _atomic_new_json(output_path, payload)
    return payload


def validate_bundle(path: Path) -> dict[str, Any]:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    if (
        bundle.get("schema_version") != 1
        or bundle.get("bundle_id") != BUNDLE_ID
        or bundle.get("gate") != "Q2"
        or bundle.get("bundle_sha256") != _canonical_sha256(unsigned)
        or bundle.get("firmware", {}).get("profile_id") != PROFILE_ID
    ):
        raise ValueError("Q2 bundle identity is invalid")
    bindings = [
        bundle["firmware"]["build_manifest"], bundle["firmware"]["uf2"],
        *bundle["host_tools"].values(), *bundle["design_bindings"].values(),
    ]
    if not all(_binding_current(value) for value in bindings):
        raise ValueError("Q2 bundle input changed after freezing")
    return bundle
