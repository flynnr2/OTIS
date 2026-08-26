from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.targeted_equilibrium_bundle import (
    ATTEMPT2_PROGRAMME_ID,
    ATTEMPT3_PROGRAMME_ID,
    ATTEMPT4_PROGRAMME_ID,
    ATTEMPT5_PROGRAMME_ID,
    ATTEMPT6_PROGRAMME_ID,
    create_bundle,
    create_preflight,
    gnss_health_reasons,
    load_programme,
    validate_bundle,
)
from host.otis_tools.targeted_equilibrium_rehearsal import run as run_rehearsal
from host.otis_tools import targeted_equilibrium_run


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT2_PROGRAMME = (
    ROOT
    / "profiles/qualification/otis_targeted_equilibrium_characterization_attempt2_v1.json"
)
ATTEMPT3_PROGRAMME = (
    ROOT
    / "profiles/qualification/otis_targeted_equilibrium_characterization_attempt3_v1.json"
)
ATTEMPT4_PROGRAMME = (
    ROOT
    / "profiles/qualification/otis_targeted_equilibrium_characterization_attempt4_v1.json"
)
ATTEMPT5_PROGRAMME = (
    ROOT
    / "profiles/qualification/otis_targeted_equilibrium_characterization_attempt5_v1.json"
)
ATTEMPT6_PROGRAMME = (
    ROOT
    / "profiles/qualification/otis_targeted_equilibrium_characterization_attempt6_v1.json"
)


def _synthetic_build(tmp_path: Path) -> Path:
    artifacts = tmp_path / "firmware/artifacts"
    artifacts.mkdir(parents=True)
    uf2 = artifacts / "candidate.uf2"
    uf2.write_bytes(b"targeted equilibrium deterministic rehearsal UF2\n")
    elf = artifacts / "candidate.elf"
    elf.write_bytes(b"synthetic ELF\x00$PMTK251,9600*17\r\n\x00")
    defines = {
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
        "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW": "1",
        "OTIS_CX317_STARTUP_WARMUP_S": "1800u",
        "OTIS_CX317_SETTLING_EXCLUSION_S": "900u",
        "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG": "600u",
        "OTIS_DAC_MIN_CODE": "0xA800u",
        "OTIS_DAC_MAX_CODE": "0xAB00u",
        "OTIS_GNSS_UART_BAUD": "9600u",
    }
    manifest = {
        "schema_version": 1,
        "provenance": {
            "configuration": {
                "profile_id": "cx319_range_map_part_a",
                "sha256": "1" * 64,
                "defines": defines,
            },
            "target": {"fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133"},
            "source": {
                "sha256": "2" * 64,
                "state": "synthetic_rehearsal_fixture",
                "git_commit": "3" * 40,
            },
            "invocation": {"id": "4" * 64},
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
                "size_bytes": uf2.stat().st_size,
            },
            {
                "name": elf.name,
                "sha256": sha256(elf.read_bytes()).hexdigest(),
                "size_bytes": elf.stat().st_size,
            },
        ],
        "resource_budget": {"status": "within_budget"},
    }
    path = artifacts / "firmware_build_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def test_programme_freezes_the_authorized_zero_control_campaign() -> None:
    programme = load_programme()

    assert [row["code"] for row in programme["dwell_plan"]] == [
        43070,
        43046,
        43070,
        43094,
        43070,
        43046,
        43070,
        43094,
        43070,
        43046,
        43070,
        43094,
    ]
    assert [row["partition"] for row in programme["dwell_plan"]] == [
        "identification"
    ] * 7 + ["held_out"] * 5
    assert programme["operator_authority"]["frequency_control_authority"] is False
    assert programme["operator_authority"]["phase_or_hybrid_actuation"] is False
    assert programme["operator_authority"]["automatic_retry"] is False
    assert programme["operator_authority"]["automatic_restore"] is False
    assert programme["timing"]["minimum_scientific_duration_s"] == 34200


def test_bundle_binds_the_gnss_transition_and_exact_firmware(tmp_path: Path) -> None:
    path = tmp_path / "bundle.json"
    create_bundle(build_manifest_path=_synthetic_build(tmp_path), output_path=path)
    bundle = validate_bundle(path)

    assert bundle["firmware"]["profile_id"] == "cx319_range_map_part_a"
    assert bundle["firmware"]["defines"]["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "0"
    assert bundle["programme_id"] == ATTEMPT6_PROGRAMME_ID
    assert bundle["gnss_live_boundary"]["target_baud"] == 9600
    assert bundle["firmware"]["compiled_gnss_target_command"]["command"] == (
        "$PMTK251,9600*17\r\n"
    )
    assert (
        bundle["gnss_live_boundary"]["required_prewrite_health"]["confirmed_baud"]
        == "9600"
    )
    assert "investigate_the_115200_corruption_mechanism_separately" in bundle[
        "gnss_live_boundary"
    ]["future_reuse_policy"]

    preflight_path = tmp_path / "preflight.json"
    preflight = create_preflight(bundle_path=path, output_path=preflight_path)
    assert preflight["status"] == "passed"
    assert all(preflight["checks"].values())
    assert set(preflight["hardware_operations"].values()) == {0}


def test_attempt2_bundle_reuses_baud_proof_and_requires_exact_output_evidence(
    tmp_path: Path,
) -> None:
    programme = load_programme(ATTEMPT2_PROGRAMME)
    assert programme["programme_id"] == ATTEMPT2_PROGRAMME_ID
    assert (
        programme["gnss_live_boundary"]["baud_transition_qualification_state"]
        == "passed_reused_from_attempt1"
    )
    assert programme["gnss_live_boundary"]["allowed_output_confirmation_methods"] == [
        "pmtk514_exact",
        "pmtk314_ack_observed_exact",
    ]

    path = tmp_path / "attempt2_bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path),
        output_path=path,
        programme_path=ATTEMPT2_PROGRAMME,
    )
    bundle = validate_bundle(path)
    assert bundle["programme_id"] == ATTEMPT2_PROGRAMME_ID
    assert bundle["gnss_live_boundary"]["required_observed_sentence_mask"] == 7
    assert create_preflight(
        bundle_path=path, output_path=tmp_path / "attempt2_preflight.json"
    )["status"] == "passed"


def test_extended_pmtk514_evidence_reaches_first_prewrite_consumer() -> None:
    contract = {
        "required_prewrite_health": {
            "link_state": "online",
            "confirmed_baud": "115200",
            "last_identity_response_baud": "115200",
            "configuration_failure_count": "0",
        },
        "allowed_output_confirmation_methods": ["pmtk514_exact"],
        "confirmation_evidence": {
            "pmtk514_exact": {
                "output_configuration_field_count": "22",
                "output_configuration_signature": "0101100000000000000000",
            }
        },
        "runtime_qualification_policy": {
            "bounded_hold_status_keys": [
                "metadata_control_eligible",
                "raw_pps_control_eligible",
            ]
        },
    }
    health = {
        ("gnss_receiver", "link_state"): "online",
        ("gnss_receiver", "confirmed_baud"): "115200",
        ("gnss_receiver", "last_identity_response_baud"): "115200",
        ("gnss_receiver", "configuration_failure_count"): "0",
        ("gnss_receiver", "output_confirmation_method"): "pmtk514_exact",
        ("gnss_receiver", "output_configuration_field_count"): "22",
        (
            "gnss_receiver",
            "output_configuration_signature",
        ): "0101100000000000000000",
    }

    assert gnss_health_reasons(contract, health) == []
    health[("gnss_receiver", "output_configuration_signature")] = (
        "0101100000000000000001"
    )
    assert gnss_health_reasons(contract, health) == [
        "output_configuration_signature='0101100000000000000001' "
        "expected '0101100000000000000000'"
    ]


def test_attempt3_freezes_physical_response_and_continuous_entry() -> None:
    programme = load_programme(ATTEMPT3_PROGRAMME)
    gnss = programme["gnss_live_boundary"]

    assert programme["programme_id"] == ATTEMPT3_PROGRAMME_ID
    assert gnss["pmtk514_qualified_field_count"] == 22
    assert gnss["pmtk514_qualified_signature"] == "0101100000000000000000"
    assert gnss["physical_entry_path"] == (
        "single_flash_continuous_sole_owner_gnss_gate_then_science_promotion"
    )
    assert programme["operator_authority"]["physical_live_run_limit"] == 1
    assert programme["operator_authority"]["firmware_flash_limit"] == 1
    assert programme["operator_authority"]["automatic_retry"] is False


def test_attempt4_freezes_bounded_runtime_hold_and_attempt3_lineage() -> None:
    programme = load_programme(ATTEMPT4_PROGRAMME)
    gnss = programme["gnss_live_boundary"]

    assert programme["programme_id"] == ATTEMPT4_PROGRAMME_ID
    assert programme["predecessor_attempt"]["run_id"] == (
        "live_attempt3_20260825T160252Z"
    )
    assert programme["predecessor_attempt"]["dac_stimuli_issued"] == 0
    assert gnss["runtime_qualification_policy"]["bounded_hold_status_keys"] == [
        "metadata_control_eligible",
        "raw_pps_control_eligible",
    ]
    assert (
        gnss["runtime_qualification_policy"][
            "all_other_gnss_mismatches_are_immediate_invariant_failures"
        ]
        is True
    )
    assert programme["operator_authority"]["physical_live_run_limit"] == 1
    assert programme["operator_authority"]["automatic_retry"] is False


def test_attempt5_freezes_9600_return_and_attempt4_support_correction() -> None:
    programme = load_programme(ATTEMPT5_PROGRAMME)
    gnss = programme["gnss_live_boundary"]

    assert programme["programme_id"] == ATTEMPT5_PROGRAMME_ID
    assert programme["predecessor_attempt"]["run_id"] == (
        "live_attempt4_20260825T165938Z"
    )
    assert programme["firmware"]["required_defines"]["OTIS_GNSS_UART_BAUD"] == (
        "9600u"
    )
    assert gnss["candidate_baud_order"][:2] == [9600, 115200]
    assert gnss["target_baud"] == 9600
    assert gnss["target_baud_command"] == "$PMTK251,9600*17\\r\\n"
    assert gnss["required_prewrite_health"]["confirmed_baud"] == "9600"
    assert gnss["required_prewrite_health"]["last_identity_response_baud"] == (
        "9600"
    )
    assert programme["operator_authority"]["physical_live_run_limit"] == 1
    assert programme["operator_authority"]["automatic_retry"] is False


def test_attempt6_binds_attempt5_terminal_and_compiled_command_correction() -> None:
    programme = load_programme(ATTEMPT6_PROGRAMME)
    gnss = programme["gnss_live_boundary"]

    assert programme["programme_id"] == ATTEMPT6_PROGRAMME_ID
    assert programme["predecessor_attempt"]["run_id"] == (
        "live_attempt5_20260825T215009Z"
    )
    assert programme["predecessor_attempt"]["dac_stimuli_issued"] == 0
    assert programme["frozen_inputs"]["attempt5_terminal_seal"]["sha256"] == (
        "c5505d39fa27886754ae20eae1c3698ca39b08c41a88648c9ef7443231b98bd9"
    )
    assert programme["firmware"]["required_defines"]["OTIS_GNSS_UART_BAUD"] == (
        "9600u"
    )
    assert gnss["candidate_baud_order"][:2] == [9600, 115200]
    assert gnss["target_baud"] == 9600
    assert gnss["required_prewrite_health"]["last_identity_response_baud"] == (
        "9600"
    )
    assert programme["operator_authority"]["physical_live_run_limit"] == 1
    assert programme["operator_authority"]["firmware_flash_limit"] == 1
    assert programme["operator_authority"]["automatic_retry"] is False


def test_complete_operational_rehearsal_exercises_all_transactions(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path),
        output_path=bundle_path,
        programme_path=ATTEMPT6_PROGRAMME,
    )

    result = run_rehearsal(
        bundle_path=bundle_path,
        output_dir=tmp_path / "rehearsal",
    )

    assert result["status"] == "passed"
    assert all(result["real_boundaries"].values())
    assert result["real_boundaries"][
        "bounded_transient_gnss_health_hold_and_requalification"
    ] is True
    assert result["real_boundaries"][
        "recurrent_dwell_gnss_holds_preserve_d14_d8_support"
    ] is True
    assert result["recurrent_dwell_hold_count"] == 12
    assert result["hardware_operations"] == {
        "serial_opens": 0,
        "firmware_flashes": 0,
        "dac_writes": 0,
    }
    analysis = json.loads(
        (
            tmp_path
            / "rehearsal/run/reports/targeted_equilibrium_analysis_v1.json"
        ).read_text()
    )
    assert analysis["evidence_status"] == "passed"
    assert analysis["completed_dwell_count"] == 12
    assert analysis["identification_support_count"] == 21
    assert analysis["held_out_support_count"] == 15
    assert analysis["gnss_baud_transition_qualification"]["status"].startswith(
        "passed"
    )
    assert analysis["gnss_output_configuration_qualification"]["status"] == "passed"
    assert analysis["gnss_output_configuration_qualification"][
        "bounded_terminal_snapshot_holds"
    ] == ["metadata_control_eligible='false' expected 'true'"]


def test_live_runner_keeps_one_time_gnss_gate_before_first_dac_write() -> None:
    source = (ROOT / "host/otis_tools/targeted_equilibrium_run.py").read_text()

    assert source.index("_targeted_prewrite_ready") < source.index(
        'command = f"DAC SET 0x{code:04X}"'
    )
    assert "frozen 1800-second capture-owned warmup" in source
    assert "three fresh contiguous selected600 supports" in source
    assert "priority_abort_delivery" in source
    assert "automatic_restore_performed" in source
    assert "_require_gnss_stable" in source
    assert "require_qualified_health=True" not in source


def test_runtime_holds_transient_gnss_qualification_and_stops_on_invariant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = {
        "required_prewrite_health": {
            "link_state": "online",
            "link_phase": "online",
            "link_online": "true",
            "configuration_confirmed": "true",
            "confirmed_baud": "115200",
            "last_identity_response_baud": "115200",
            "rx_only": "true",
            "identity_stable": "true",
            "metadata_control_eligible": "true",
            "raw_pps_control_eligible": "true",
            "configuration_failure_count": "0",
            "transmit_failure_count": "0",
            "link_loss_count": "0",
        },
        "allowed_output_confirmation_methods": ["pmtk514_exact"],
        "confirmation_evidence": {
            "pmtk514_exact": {
                "output_configuration_field_count": "22",
                "output_configuration_signature": "0101100000000000000000",
            }
        },
        "runtime_qualification_policy": {
            "bounded_hold_status_keys": [
                "metadata_control_eligible",
                "raw_pps_control_eligible",
            ]
        },
    }
    bundle = {"gnss_live_boundary": contract}
    health = {
        ("gnss_receiver", key): value
        for key, value in contract["required_prewrite_health"].items()
    }
    health.update(
        {
            ("gnss_receiver", "output_confirmation_method"): "pmtk514_exact",
            ("gnss_receiver", "output_configuration_field_count"): "22",
            (
                "gnss_receiver",
                "output_configuration_signature",
            ): "0101100000000000000000",
        }
    )
    monkeypatch.setattr(
        targeted_equilibrium_run,
        "_latest_health",
        lambda _run_dir: health,
    )
    advanced: list[str] = []

    health[("gnss_receiver", "metadata_control_eligible")] = "false"
    assert (
        targeted_equilibrium_run._guarded(
            tmp_path, bundle, lambda: advanced.append("advanced") or "advanced"
        )
        is False
    )
    assert advanced == []

    health[("gnss_receiver", "metadata_control_eligible")] = "true"
    assert (
        targeted_equilibrium_run._guarded(
            tmp_path, bundle, lambda: advanced.append("advanced") or "advanced"
        )
        == "advanced"
    )
    assert advanced == ["advanced"]

    health[("gnss_receiver", "output_configuration_signature")] = (
        "0101100000000000000001"
    )
    with pytest.raises(RuntimeError, match="stability invariant"):
        targeted_equilibrium_run._guarded(tmp_path, bundle, lambda: "advanced")
