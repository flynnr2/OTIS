from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools.evidence import (
    EvidenceError,
    create_evidence_snapshot,
    validate_evidence_snapshot,
)
from host.otis_tools.run_loader import (
    ARCHIVAL_CHECKOUT_GUIDANCE,
    load_manifest,
)


def _write_manifest(run_dir: Path, **changes: object) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": 1,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "run_id": "cx319_current_fixture",
        "stage": "CX319_CURRENT_EVIDENCE_FIXTURE",
        "cx319": {"profile_id": "cx319_tight_lower"},
        "template": False,
        "channels": [],
        "domains": [],
        "files": [
            {
                "path": "csv/raw_events.csv",
                "contract": "raw_events_v1",
            }
        ],
    }
    value.update(changes)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(value), encoding="utf-8"
    )
    return value


def test_current_canonical_manifest_loads_without_identity_translation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "current"
    value = _write_manifest(run_dir)
    manifest = load_manifest(run_dir)
    assert manifest.data == value
    assert manifest.stage == "CX319_CURRENT_EVIDENCE_FIXTURE"


@pytest.mark.parametrize(
    "profile_id",
    (
        "cx319_range_part_b_lower",
        "cx319_range_part_b_upper",
        "cx319_range_part_b_upper_completion",
    ),
)
def test_mapping_informed_part_b_profiles_are_current_evidence_packages(
    tmp_path: Path, profile_id: str
) -> None:
    run_dir = tmp_path / profile_id
    value = _write_manifest(run_dir, cx319={"profile_id": profile_id})

    assert load_manifest(run_dir).data == value


def test_current_floor_requires_supported_cx319_profile_identity(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "unknown-profile"
    _write_manifest(run_dir, cx319={"profile_id": "cx319_unknown"})
    with pytest.raises(ValueError, match="CX319_EVIDENCE_EPOCH_1"):
        load_manifest(run_dir)


def test_cx320_active_hybrid_is_a_current_evidence_package(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "cx320"
    value = _write_manifest(
        run_dir,
        run_id="cx320_active_hybrid_live_fixture",
        stage="CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE",
        cx319=None,
        cx320={"profile_id": "cx320_active_hybrid"},
    )

    assert load_manifest(run_dir).data == value


def test_cx321_active_hybrid_is_a_current_evidence_package(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "cx321"
    value = _write_manifest(
        run_dir,
        compatibility_floor="CX321_EVIDENCE_EPOCH_1",
        run_id="cx321_active_hybrid_live_fixture",
        stage="CX321_BOUNDED_ACTIVE_HYBRID_PLANT_SIGN_LIVE",
        cx319=None,
        cx321={"profile_id": "cx321_active_hybrid"},
    )

    assert load_manifest(run_dir).data == value


def test_legacy_manifest_filename_is_rejected_with_revision_guidance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "legacy"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="recorded Git revision"):
        load_manifest(run_dir)


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "SW1", "h_phase": "H0"},
        {"stage": "CX317_STAGE7_PART_B"},
        {"stage": "CX318_STAGE4_LIVE"},
        {"stage": "PHASE5_PPS_BACKEND_QUALIFICATION"},
    ],
)
def test_retired_epochs_are_rejected_at_load_time(
    tmp_path: Path, changes: dict
) -> None:
    run_dir = tmp_path / "retired"
    _write_manifest(run_dir, **changes)
    with pytest.raises(ValueError, match="archival checkout") as raised:
        load_manifest(run_dir)
    assert ARCHIVAL_CHECKOUT_GUIDANCE in str(raised.value)


def test_current_owner_handoff_preserves_deployed_transition_identity(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "transition"
    _write_manifest(
        run_dir,
        run_id="g1_owner_handoff_transition",
        stage="CX318_STAGE5_TRANSITION_SPOOL",
    )
    assert load_manifest(run_dir).stage == "CX318_STAGE5_TRANSITION_SPOOL"


def test_current_non_template_package_requires_evidence_snapshot(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "unsealed"
    _write_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, load_manifest(run_dir))
    assert failures == ["evidence_manifest.json: immutable evidence snapshot is required"]
    assert warnings == []


def test_legacy_root_raw_log_is_not_silently_normalized(tmp_path: Path) -> None:
    run_dir = tmp_path / "legacy_raw"
    _write_manifest(run_dir)
    csv_path = run_dir / "csv/raw_events.csv"
    csv_path.parent.mkdir()
    csv_path.write_text(
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags\n",
        encoding="utf-8",
    )
    (run_dir / "raw_serial.log").write_text("legacy", encoding="utf-8")
    (run_dir / "COMPLETE").touch()
    with pytest.raises(EvidenceError, match="archival checkout"):
        create_evidence_snapshot(run_dir)
