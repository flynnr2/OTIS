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
    CX322_D9_D6_72H_PROGRAMME,
    CX322_D9_D6_INTEGRATION_PROGRAMME,
    CX323_D9_D6_72H_PROGRAMME,
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
    assert get_active_hybrid_programme(
        "cx322_d9_d6_integration_engineering"
    ) is CX322_D9_D6_INTEGRATION_PROGRAMME
    with pytest.raises(ValueError, match="does not identify"):
        programme_from_mapping({"programme_id": "CX999"})


def test_cx322_d9_d6_descriptor_is_distinct_with_unchanged_controller() -> None:
    programme = CX322_D9_D6_INTEGRATION_PROGRAMME
    assert programme.profile_id == "cx322_d9_d6_integration_engineering"
    assert programme.forwarded_output_integration
    assert programme.fresh_serial_auto_detect
    assert programme.authorized_maximum_applications == 1
    assert programme.authorized_maximum_physical_applications == 1
    assert programme.authorized_maximum_cumulative_movement_codes == 21
    assert programme.authorized_absolute_wall_limit_s == 7_200
    assert programme.terminal_after_first_response
    assert programme.response_checkpoint_observational
    assert programme.policy_id == "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1"
    assert programme.natural_policy_programme_id == (
        "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1"
    )
    assert programme.engineering_unarmed_observation_s == 1_800
    assert programme.engineering_contract_path is not None
    assert programme.engineering_contract_path.name == (
        "cx322_d9_d6_integration_engineering_contract_v1.json"
    )
    setup_provenance = activation.integrated_setup_provenance_contract(programme)
    assert activation._authority(programme)["setup_provenance"] == setup_provenance
    assert setup_provenance["authorized_setup_code"] == 0xA83C
    assert setup_provenance["prior_or_nominal_state_inferred"] is False
    assert programme.maximum_physical_applications == 4
    assert programme.maximum_cumulative_movement_codes == 84
    assert programme.maximum_step_codes == 21
    assert programme.runtime_run_identity != "cx322_direct_hybrid:3220001"


def test_campaign18_uses_72h_authority_at_every_runtime_projection() -> None:
    programme = CX322_D9_D6_72H_PROGRAMME
    authority = activation._authority(programme)

    assert programme.qualified_duration_s == 259_200
    assert programme.authorized_absolute_wall_limit_s == 280_800
    assert programme.capture_duration_s == 280_980
    assert programme.supervisor_duration_s == 280_920
    assert programme.qualified_endpoint_reason == (
        "cx322_d9_d6_72h_72h_qualified_endpoint_complete"
    )
    assert programme.authorized_maximum_applications == 144
    assert programme.authorized_maximum_physical_applications == 144
    assert programme.authorized_maximum_cumulative_movement_codes == 3_024
    assert programme.minimum_applied_cadence_s == 1_800
    assert programme.correction_response_reserve_s == 1_500
    assert authority["maximum_total_automatic_applications"] == 144
    assert authority["maximum_total_physical_control_applications"] == 144
    assert authority["maximum_cumulative_absolute_movement_codes"] == 3_024
    assert authority["qualified_duration_s"] == 259_200
    assert authority["absolute_wall_clock_limit_s"] == 280_800

    # The unchanged CX322 policy document still carries its historical
    # numerical envelope. It is controller-law provenance, not Campaign18
    # live authority; every runtime projection above must use the explicit
    # engineering overrides.
    assert programme.maximum_applications == 4
    assert programme.maximum_cumulative_movement_codes == 84


def test_cx323_72h_descriptor_is_distinct_and_exact() -> None:
    programme = CX323_D9_D6_72H_PROGRAMME

    assert get_active_hybrid_programme(programme.programme_id) is programme
    assert get_active_hybrid_programme(programme.runtime_run_identity) is programme
    assert programme.key == "cx323_d9_d6_72h"
    assert programme.profile_id == "cx323_d9_d6_72h_adaptive_hybrid"
    assert programme.runtime_run_identity == "cx323_d9_d6_72h_adaptive_hybrid:1"
    assert programme.setup_code == 0xA84D
    assert programme.qualified_duration_s == 72 * 3600
    assert programme.authorized_absolute_wall_limit_s == 78 * 3600
    assert programme.authorized_maximum_applications == 144
    assert programme.authorized_maximum_physical_applications == 144
    assert programme.authorized_maximum_cumulative_movement_codes == 3_024
    assert programme.maximum_step_codes == 21
    assert programme.maximum_deliberate_challenges == 0
    assert programme.integrated_long_run is True
    assert programme.persistent_maintenance_policy is True
    assert programme.maintenance_record_type == "AHM"
    assert programme.maintenance_record_contract == "active_hybrid_maintenance_v1"
    assert programme.controller_inhibit_acquisition_continues is True
    assert programme.gnss_metadata_hold_nonterminal is True
    assert (
        programme.qualified_endpoint_reason
        == "cx323_d9_d6_72h_qualified_hybrid_complete"
    )
    assert "cx323_d9_d6_72h_hybrid_authority_not_sustained" in programme.terminal_decisions
    assert "cx322_d9_d6_72h_qualified_engineering_complete" not in programme.terminal_decisions


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


def test_forwarded_integration_build_requires_exact_gnss_boot_policy(
    tmp_path: Path,
) -> None:
    programme = CX322_D9_D6_72H_PROGRAMME
    matrix = json.loads(
        (Path(__file__).resolve().parents[1]
         / "firmware/arduino/firmware_matrix.json").read_text(encoding="utf-8")
    )
    profile = next(
        item for item in matrix["profiles"] if item["id"] == programme.profile_id
    )
    uf2 = tmp_path / "cx322_d9_d6.uf2"
    uf2.write_bytes(b"cx322-d9-d6-exact-build-fixture")
    manifest = {
        "provenance": {
            "configuration": {
                "profile_id": programme.profile_id,
                "defines": profile["defines"],
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
            {"name": uf2.name, "sha256": sha256(uf2.read_bytes()).hexdigest()}
        ],
    }
    manifest_path = tmp_path / "firmware_build_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = bundle._validate_build(manifest_path, programme)
    assert result["defines"]["OTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION"] == "1"

    del manifest["provenance"]["configuration"]["defines"][  # type: ignore[index]
        "OTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION"
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="compile-time envelope differs"):
        bundle._validate_build(manifest_path, programme)
