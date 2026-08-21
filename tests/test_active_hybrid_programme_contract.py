from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_activation as activation
from host.otis_tools import active_hybrid_bundle as bundle
from host.otis_tools import active_hybrid_live_supervisor as supervisor
from host.otis_tools.active_hybrid_programme_contract import (
    CX320_PROGRAMME,
    CX321_PROGRAMME,
    get_active_hybrid_programme,
    programme_from_mapping,
)


def test_cx320_remains_the_default_exact_programme() -> None:
    assert get_active_hybrid_programme() is CX320_PROGRAMME
    assert bundle.PROGRAMME_ID == CX320_PROGRAMME.programme_id
    assert bundle.PROFILE_ID == CX320_PROGRAMME.profile_id
    assert activation.PROGRAMME_ID == CX320_PROGRAMME.programme_id
    assert supervisor.PROGRAMME_ID == CX320_PROGRAMME.programme_id
    assert activation._authority() == activation._authority(CX320_PROGRAMME)
    assert CX320_PROGRAMME.capture_duration_s == 57_780
    assert CX320_PROGRAMME.supervisor_duration_s == 57_720


def test_cx321_descriptor_reuses_natural_policy_with_distinct_authority() -> None:
    programme = get_active_hybrid_programme("cx321_active_hybrid")
    assert programme is CX321_PROGRAMME
    assert programme.identification_required
    assert programme.policy_id == "CX321_BOUNDED_ACTIVE_HYBRID_PLANT_SIGN_V2"
    assert (
        programme.status_programme_id
        == "cx321_bounded_active_hybrid_successor"
    )
    assert programme.natural_policy_id == CX320_PROGRAMME.policy_id
    assert programme.policy_path != programme.natural_policy_path
    assert "PLANT_SIGN_QUALIFY" in programme.hybrid_states
    assert "FREQUENCY_ACQUIRE" not in programme.armable_hybrid_states
    assert {
        "plant_sign_qualification_not_exercised",
        "plant_sign_qualification_failed",
    } <= programme.terminal_decisions
    authority = activation._authority(programme)
    assert authority["setup_code"] == 0xA83C
    assert authority["maximum_total_automatic_applications"] == 4
    assert authority["maximum_cumulative_absolute_movement_codes"] == 84
    assert authority["minimum_phase_material_applications_for_pass"] == 2


def test_programme_mapping_requires_an_exact_supported_identity() -> None:
    assert (
        programme_from_mapping({"programme_id": CX321_PROGRAMME.programme_id})
        is CX321_PROGRAMME
    )
    assert (
        programme_from_mapping({"run_identity": CX320_PROGRAMME.runtime_run_identity})
        is CX320_PROGRAMME
    )
    with pytest.raises(ValueError, match="does not identify"):
        programme_from_mapping({"programme_id": "CX999"})


def test_cx321_exact_build_binding_accepts_its_distinct_campaign_macro(
    tmp_path: Path,
) -> None:
    uf2 = tmp_path / "cx321.uf2"
    uf2.write_bytes(b"cx321-exact-build-fixture")
    defines = {
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX321_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_CX317_ACTIVE_CAMPAIGN": (
            "OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID"
        ),
        "OTIS_CX317_ACTIVE_START_CODE": "0xA83Cu",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "4u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "84u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
        "OTIS_DAC_MIN_CODE": "0xA800u",
        "OTIS_DAC_MAX_CODE": "0xAB00u",
        "OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED": "1",
    }
    manifest = {
        "provenance": {
            "configuration": {
                "profile_id": CX321_PROGRAMME.profile_id,
                "defines": defines,
                "sha256": "1" * 64,
            },
            "source": {
                "sha256": "2" * 64,
                "state": "clean",
                "git_commit": "3" * 40,
            },
            "target": {
                "fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133"
            },
            "toolchain": {
                "compiler_identity": "fixture-compiler",
                "installed_sha256": "4" * 64,
            },
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
            }
        ],
    }
    manifest_path = tmp_path / "firmware_build_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = bundle._validate_build(manifest_path, CX321_PROGRAMME)

    assert result["profile_id"] == CX321_PROGRAMME.profile_id
    assert result["defines"]["OTIS_CX317_ACTIVE_CAMPAIGN"].endswith(
        "CX321_ACTIVE_HYBRID"
    )
