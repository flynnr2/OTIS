"""Exercise the immutable activation-to-live-manifest preparation path."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_activation as activation
from host.otis_tools import adaptive_hybrid_bundle as bundle_module
from host.otis_tools import adaptive_hybrid_operational_rehearsal as rehearsal
from host.otis_tools import adaptive_hybrid_supervisor as supervisor
from host.otis_tools import run_loader
from host.otis_tools.adaptive_hybrid_bundle import create_bundle
from host.otis_tools.adaptive_hybrid_contract import (
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
)
from host.otis_tools.adaptive_hybrid_proposal import create_proposal


def _binding(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _validated_rehearsal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    """Build real immutable inputs and run the actual no-hardware PTY rehearsal."""

    inputs_dir = tmp_path / "frozen-inputs"
    build_manifest = inputs_dir / "build.json"
    uf2 = inputs_dir / "adaptive_hybrid.uf2"
    generated_header = inputs_dir / "otis_build_manifest.generated.h"
    uf2.parent.mkdir(parents=True)
    uf2.write_bytes(b"deterministic activation-preparation fixture image")
    generated_header.write_text("// activation preparation fixture\n", encoding="utf-8")
    _write_json(build_manifest, {"fixture": "activation_preparation"})
    firmware = {
        "image_id": bundle_module.ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_manifest": _binding(build_manifest),
        "source_revision": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
        "build_identity": "b" * 64 + ":" + "c" * 64,
        "build_provenance_required": False,
        "uf2": _binding(uf2),
        "generated_header": _binding(generated_header),
        "fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133",
        "toolchain": {"fixture": True},
        "binary_contract": {"fixture": True},
        "independent_binary_verification": {"fixture": True},
        "deterministic_reproduction": {"fixture": True},
    }
    monkeypatch.setattr(
        bundle_module, "_validate_build", lambda *_args, **_kwargs: firmware
    )

    bundle_path = inputs_dir / "bundle.json"
    _write_json(bundle_path, create_bundle(build_manifest_path=build_manifest))
    proposal_path = inputs_dir / "proposal.json"
    create_proposal(bundle_path=bundle_path, output_path=proposal_path)
    rehearsal_report = rehearsal.run_operational_rehearsal(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        run_dir=tmp_path / "actual-pty-rehearsal",
        evidence_index_path=tmp_path / "evidence_index_v1.json",
    )
    return bundle_path, proposal_path, rehearsal_report


def _stage_immutable_source(source: Path, destination: Path) -> None:
    """Retain identical bytes while giving the live manifest its required local path."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination)


def test_activation_validation_and_manifest_prepare_both_supported_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, proposal_path, rehearsal_report = _validated_rehearsal(
        tmp_path, monkeypatch
    )
    for purpose, actionable in (
        (INHIBITED_ZERO_WRITE, False),
        (CONTINGENT_72_HOUR_HYBRID_CONTROL, True),
    ):
        run_dir = tmp_path / purpose
        run_dir.mkdir()
        local_bundle = run_dir / activation.RUN_BUNDLE_PATH
        local_proposal = run_dir / activation.RUN_PROPOSAL_PATH
        _stage_immutable_source(bundle_path, local_bundle)
        _stage_immutable_source(proposal_path, local_proposal)
        activation_path = run_dir / activation.RUN_ACTIVATION_PATH

        created = activation.create_activation(
            bundle_path=local_bundle,
            proposal_path=local_proposal,
            operational_rehearsal_path=rehearsal_report,
            serial_device="auto-detect",
            operator_instruction_ref=(
                "offline regression only; no physical execution authorized"
            ),
            output_path=activation_path,
            bench_attempt_purpose=purpose,
        )
        validated, bundle, proposal = activation.validate_activation(
            activation_path, bundle_path=local_bundle, proposal_path=local_proposal
        )
        *_, capability = activation.validate_activation_for_physical_entry(
            activation_path, bundle_path=local_bundle, proposal_path=local_proposal
        )
        manifest = activation.create_run_manifest(
            activation_path=activation_path,
            bundle_path=local_bundle,
            proposal_path=local_proposal,
            run_dir=run_dir,
            output_path=run_dir / activation.RUN_MANIFEST_PATH,
            serial_device="/dev/tty.activation_fixture",
            _validated_current_reproduction=capability,
        )
        frozen_manifest = activation.validate_frozen_run_manifest(
            run_dir / activation.RUN_MANIFEST_PATH
        )
        loaded_manifest = run_loader.load_manifest(run_dir).data
        context = supervisor.prepare_runtime_context(frozen_manifest)

        assert created == validated
        assert bundle["bundle_sha256"] == created["bundle"]["bundle_sha256"]
        assert proposal["proposal_sha256"] == created["proposal"]["proposal_sha256"]
        assert manifest == frozen_manifest
        assert manifest == loaded_manifest
        assert context.bench_attempt is not None
        assert context.bench_attempt.purpose == purpose
        assert manifest["control_mode"] == purpose
        assert manifest["actionable"] is actionable
        assert manifest["closed_loop_control"] is actionable
        assert manifest["reference_acceptance"] == created["reference_acceptance"]
