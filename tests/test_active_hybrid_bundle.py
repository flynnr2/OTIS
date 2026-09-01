from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_bundle as bundle
from host.otis_tools.active_hybrid_programme_contract import (
    CX322_D9_D6_72H_PROGRAMME,
    CX323_D9_D6_72H_PROGRAMME,
)


def _cx323_bundle_surface() -> dict[str, object]:
    successor = bundle._cx323_successor_binding(CX323_D9_D6_72H_PROGRAMME)
    return {
        "profile_identity": CX323_D9_D6_72H_PROGRAMME.profile_id,
        "policy": {
            "policy_id": bundle.CX323_POLICY_ID,
            "sha256": bundle.CX323_POLICY_SHA256,
            "policy_sha256": bundle.CX323_POLICY_SHA256,
        },
        "persistent_maintenance": successor,
    }


def _cx323_build_manifest(tmp_path: Path) -> Path:
    programme = CX323_D9_D6_72H_PROGRAMME
    uf2 = tmp_path / "cx323.uf2"
    uf2.write_bytes(b"cx323 exact build fixture")
    defines = {
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX322_DIRECT_HYBRID": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_CX317_ACTIVE_CAMPAIGN": programme.firmware_campaign_macro,
        "OTIS_CX317_ACTIVE_START_CODE": "0xA84Du",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "144u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "3024u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
        "OTIS_DAC_MIN_CODE": "0xA800u",
        "OTIS_DAC_MAX_CODE": "0xAB00u",
        "OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED": "1",
        "OTIS_ENABLE_D9_D6_READINESS_PROFILE": "0",
        "OTIS_ENABLE_FORWARDED_D9_OUTPUT": "1",
        "OTIS_ENABLE_FORWARDED_D6_MONITOR": "1",
        "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS": "144u",
        "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES": "3024u",
        **bundle.GNSS_OPERATIONAL_REQUIRED_DEFINES,
    }
    manifest = {
        "provenance": {
            "configuration": {
                "profile_id": programme.profile_id,
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
            {"name": uf2.name, "sha256": sha256(uf2.read_bytes()).hexdigest()}
        ],
    }
    path = tmp_path / "firmware_build_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _cx323_replay(tmp_path: Path) -> Path:
    report = bundle._cx323_progressive_replay_report(
        CX323_D9_D6_72H_PROGRAMME
    )
    report["report_sha256"] = bundle._canonical_sha256(report)
    path = tmp_path / "cx323_progressive_replay.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _rewrite_replay(path: Path, change: object) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    report.pop("report_sha256")
    change(report)
    report["report_sha256"] = bundle._canonical_sha256(report)
    path.write_text(json.dumps(report), encoding="utf-8")


def test_cx323_successor_binding_freezes_policy_ahm_and_live_identities() -> None:
    binding = bundle._cx323_successor_binding(CX323_D9_D6_72H_PROGRAMME)

    assert binding["identities"] == bundle.CX323_EXACT_IDENTITIES
    assert binding["selected_policy"] == {
        "policy_id": "CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1",
        "path": (
            "profiles/discipline/"
            "cx323_phase_priority_persistent_maintenance_v2.json"
        ),
        "sha256": (
            "24ec5210b897b3ea9dd64aa5946c69e02e277c09922f5a5208f3476d6eaba926"
        ),
    }
    assert binding["selection_and_native_boundary"] == {
        "v2_selection": {
            "path": (
                "docs/60_EXPERIMENTS/"
                "OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
                "study_contract_v2.json"
            ),
            "file_sha256": (
                "fc46b30e2bd323cdcbfdefa84fc7a35943584007120f3e1b9b96bbe98ba379af"
            ),
            "semantic_sha256": (
                "20b729dce477349704ce09e7cacf14047525450d50230c8f114f75959289d707"
            ),
        },
        "v3_native_boundary_correction": {
            "path": (
                "docs/60_EXPERIMENTS/"
                "OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
                "study_contract_v3.json"
            ),
            "file_sha256": (
                "a9915b61f295eaa743d8803ee609dd2a3f5b3136fff41d4dc6766929e6f06949"
            ),
            "semantic_sha256": (
                "32a7f47330404e1cf7ea724517643deff078e74d3e1aa50127c378bced5f4d53"
            ),
        },
    }
    assert binding["maintenance_evidence"] == {
        "record_type": "AHM",
        "record_contract": "active_hybrid_maintenance_v1",
        "normative_contract_path": (
            "docs/50_SOFTWARE/"
            "CX323_ACTIVE_HYBRID_MAINTENANCE_EVIDENCE_CONTRACT.md"
        ),
        "normative_contract_sha256": (
            "08826ada2caaca2dda624fcd2e67415978b9a21ccc3c947a9461918a5583389d"
        ),
    }


def test_cx323_successor_binding_rejects_campaign18_labels_and_policy() -> None:
    campaign18_label = replace(
        CX323_D9_D6_72H_PROGRAMME,
        profile_id=CX322_D9_D6_72H_PROGRAMME.profile_id,
    )
    with pytest.raises(ValueError, match="exact successor identities differ"):
        bundle._cx323_successor_binding(campaign18_label)

    campaign18_policy = replace(
        CX323_D9_D6_72H_PROGRAMME,
        policy_id=CX322_D9_D6_72H_PROGRAMME.policy_id,
        policy_path=CX322_D9_D6_72H_PROGRAMME.policy_path,
        natural_policy_id=CX322_D9_D6_72H_PROGRAMME.natural_policy_id,
        natural_policy_path=CX322_D9_D6_72H_PROGRAMME.natural_policy_path,
    )
    with pytest.raises(ValueError, match="selected policy identity differs"):
        bundle._cx323_successor_binding(campaign18_policy)


def test_cx323_bundle_surface_rejects_campaign18_or_changed_bindings() -> None:
    exact = _cx323_bundle_surface()
    bundle._validate_cx323_bundle_binding(
        exact, CX323_D9_D6_72H_PROGRAMME
    )

    changed = json.loads(json.dumps(exact))
    changed["persistent_maintenance"]["identities"]["profile_id"] = (
        CX322_D9_D6_72H_PROGRAMME.profile_id
    )
    with pytest.raises(ValueError, match="exact bundle successor binding differs"):
        bundle._validate_cx323_bundle_binding(
            changed, CX323_D9_D6_72H_PROGRAMME
        )

    campaign18_hash = json.loads(json.dumps(exact))
    campaign18_hash["policy"]["sha256"] = sha256(
        CX322_D9_D6_72H_PROGRAMME.policy_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="exact bundle successor binding differs"):
        bundle._validate_cx323_bundle_binding(
            campaign18_hash, CX323_D9_D6_72H_PROGRAMME
        )


def test_cx323_engineering_contract_is_exact_and_available() -> None:
    programme = CX323_D9_D6_72H_PROGRAMME
    assert programme.engineering_contract_path is not None
    assert programme.engineering_contract_path.is_file()

    binding = bundle._engineering_contract_binding(programme)

    assert binding["contract_id"] == bundle.CX323_ENGINEERING_CONTRACT_ID
    assert binding["contract_semantic_sha256"] == (
        "80b10a612d7404d96a38f63cbbf3175422ebb1f46ebd070b0e7630be8e3e2b9f"
    )
    assert binding["sha256"] == (
        "374daa65eb4ad56e615a0df7f988d8942b6bf39769b758dd74ea480c883b2060"
    )
    assert binding["persistent_maintenance"] == (
        bundle._cx323_successor_binding(programme)
    )


def test_cx323_engineering_validation_rejects_campaign18_contract() -> None:
    programme = replace(
        CX323_D9_D6_72H_PROGRAMME,
        engineering_contract_path=(
            CX322_D9_D6_72H_PROGRAMME.engineering_contract_path
        ),
    )
    with pytest.raises(
        ValueError, match="CX323 exact engineering contract semantics differ"
    ):
        bundle._engineering_contract_binding(programme)


def test_cx323_build_validation_uses_successor_start_code_and_envelope(
    tmp_path: Path,
) -> None:
    manifest_path = _cx323_build_manifest(tmp_path)

    validated = bundle._validate_build(
        manifest_path, CX323_D9_D6_72H_PROGRAMME
    )

    assert validated["profile_id"] == "cx323_d9_d6_72h_adaptive_hybrid"
    assert validated["defines"]["OTIS_CX317_ACTIVE_START_CODE"] == "0xA84Du"
    assert validated["defines"]["OTIS_CX317_ACTIVE_CORRECTION_LIMIT"] == "144u"
    assert validated["defines"]["OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS"] == "144u"
    assert validated["defines"]["OTIS_CX317_ACTIVE_CAMPAIGN"] == (
        "OTIS_CX317_ACTIVE_CAMPAIGN_CX323_D9_D6_72H_ADAPTIVE_HYBRID"
    )


def test_cx323_build_validation_rejects_campaign18_profile(
    tmp_path: Path,
) -> None:
    manifest_path = _cx323_build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["configuration"]["profile_id"] = (
        CX322_D9_D6_72H_PROGRAMME.profile_id
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="firmware build is not the exact"):
        bundle._validate_build(manifest_path, CX323_D9_D6_72H_PROGRAMME)


def test_cx323_replay_executes_progressive_tagged_debt_lifecycle(
    tmp_path: Path,
) -> None:
    replay_path = _cx323_replay(tmp_path)

    validated = bundle._validate_replay(
        replay_path,
        bundle.CX323_POLICY_SHA256,
        CX323_D9_D6_72H_PROGRAMME,
    )
    report = json.loads(replay_path.read_text(encoding="utf-8"))

    assert validated["replay_id"] == bundle.CX323_REPLAY_ID
    assert validated["selected_candidate_id"] == (
        "cx323_phase_priority_persistent_cap_tagged_debt_v1"
    )
    assert all(validated["selection_checks"].values())
    assert report["lifecycle"]["first_request"]["requested_delta_codes"] == 5
    assert report["lifecycle"]["first_application"]["tagged_debt"] == {
        "fll_picocodes": 307_504_602_373,
        "pll_picocodes": 34_167_178_042,
    }
    assert report["lifecycle"]["second_request"][
        "committed_debt_picocodes"
    ] == 341_671_780_415
    assert report["lifecycle"]["second_application"]["tagged_debt"] == {
        "fll_picocodes": 450_000_000_000,
        "pll_picocodes": 50_000_000_000,
    }
    assert report["lifecycle"]["second_response_complete"] is True


def test_cx323_public_replay_generation_is_byte_deterministic_and_consumable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    direct_path = tmp_path / "direct.json"
    cli_path = tmp_path / "cli.json"

    direct = bundle.create_cx323_progressive_replay(
        output_path=direct_path,
        programme=CX323_D9_D6_72H_PROGRAMME,
    )
    assert bundle.main(
        [
            "--generate-progressive-replay",
            "--programme",
            CX323_D9_D6_72H_PROGRAMME.key,
            "--output",
            str(cli_path),
        ]
    ) == 0
    capsys.readouterr()

    assert direct_path.read_bytes() == cli_path.read_bytes()
    assert json.loads(direct_path.read_text(encoding="utf-8")) == direct
    assert direct["report_sha256"] == bundle._canonical_sha256(
        bundle._cx323_progressive_replay_report(
            CX323_D9_D6_72H_PROGRAMME
        )
    )
    validated = bundle._validate_replay(
        cli_path,
        bundle.CX323_POLICY_SHA256,
        CX323_D9_D6_72H_PROGRAMME,
    )
    assert validated["report_sha256"] == direct["report_sha256"]
    created_bundle = bundle.create_bundle(
        build_manifest_path=_cx323_build_manifest(tmp_path),
        replay_path=cli_path,
        programme=CX323_D9_D6_72H_PROGRAMME,
    )
    assert created_bundle["offline_replay"]["report_sha256"] == direct[
        "report_sha256"
    ]

    with pytest.raises(ValueError, match="refusing to overwrite"):
        bundle.create_cx323_progressive_replay(
            output_path=direct_path,
            programme=CX323_D9_D6_72H_PROGRAMME,
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda report: report["programme_identity"].__setitem__(
            "profile_id", CX322_D9_D6_72H_PROGRAMME.profile_id
        ),
        lambda report: report["policy"].__setitem__("sha256", "0" * 64),
        lambda report: report["engineering_contract"].__setitem__(
            "contract_semantic_sha256", "0" * 64
        ),
        lambda report: report["lifecycle"]["second_request"].__setitem__(
            "committed_debt_picocodes", 0
        ),
    ],
)
def test_cx323_replay_rejects_rehashed_identity_contract_or_lifecycle_changes(
    tmp_path: Path, change: object
) -> None:
    replay_path = _cx323_replay(tmp_path)
    _rewrite_replay(replay_path, change)

    with pytest.raises(
        ValueError,
        match="CX323 replay lifecycle, identity, or contract binding differs",
    ):
        bundle._validate_replay(
            replay_path,
            bundle.CX323_POLICY_SHA256,
            CX323_D9_D6_72H_PROGRAMME,
        )


def test_cx323_replay_rejects_report_or_selected_policy_hash(
    tmp_path: Path,
) -> None:
    replay_path = _cx323_replay(tmp_path)
    report = json.loads(replay_path.read_text(encoding="utf-8"))
    report["report_sha256"] = "0" * 64
    replay_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="semantic report identity differs"):
        bundle._validate_replay(
            replay_path,
            bundle.CX323_POLICY_SHA256,
            CX323_D9_D6_72H_PROGRAMME,
        )

    with pytest.raises(ValueError, match="replay policy identity differs"):
        bundle._validate_replay(
            replay_path,
            CX322_D9_D6_72H_PROGRAMME.natural_policy_path.read_bytes().hex()[:64],
            CX323_D9_D6_72H_PROGRAMME,
        )
