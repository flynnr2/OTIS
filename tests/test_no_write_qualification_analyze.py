from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools.no_write_qualification_analyze import (
    ANALYSIS_PATH,
    _authority_false_or_absent,
    _command_allowed,
    _post_abort_health_exact,
    seal,
)


def test_analyzer_command_boundary_includes_only_priority_abort_beyond_normal() -> None:
    assert _command_allowed("CONFIG?")
    assert _command_allowed("ACTIVE LEASE 12")
    assert _command_allowed("ACTIVE ABORT")
    assert not _command_allowed("DAC SET 0xA808")
    assert not _command_allowed("ACTIVE ARM 1 2 3")
    assert not _command_allowed("ACTIVE LEASE 4294967296")


def test_seal_cannot_promote_failed_analysis(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="failed analysis"):
        seal(tmp_path, {"status": "fail"})


def test_q3_seal_records_physical_no_write_qualification(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "COMPLETE").write_text("complete\n", encoding="utf-8")
    (tmp_path / "evidence_manifest.json").write_text(
        json.dumps(
            {
                "snapshot_digest": "a" * 64,
                "run_state": "complete",
            }
        ),
        encoding="utf-8",
    )
    analysis = {
        "status": "pass",
        "leg": "A",
        "profile_id": "cx319_tight_lower",
        "qualification_sequence_gate": "Q3",
        "analysis_sha256": "b" * 64,
        "bindings": {
            "bundle_sha256": "c" * 64,
            "uf2_sha256": "d" * 64,
        },
    }
    (tmp_path / ANALYSIS_PATH).write_text(
        json.dumps(analysis), encoding="utf-8"
    )

    value = seal(tmp_path, analysis)

    assert value["seal_type"] == (
        "cx319_q3_physical_no_write_qualification_seal_v1"
    )
    assert value["qualification_sequence_gate"] == "Q3"
    assert value["qualification_evidence"] is True


def test_transition_zero_authority_accepts_absence_but_not_true(
    tmp_path: Path,
) -> None:
    path = tmp_path / "preview.csv"
    path.write_text(
        "actionable,actuation_authorized,authorization_consumed\n",
        encoding="utf-8",
    )
    assert _authority_false_or_absent(path)

    path.write_text(
        "actionable,actuation_authorized,authorization_consumed\n"
        "true,false,false\n",
        encoding="utf-8",
    )
    assert not _authority_false_or_absent(path)


def test_abort_health_is_verified_across_the_segment_boundary() -> None:
    primary = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "fail_static"): "false",
    }
    transition = {
        ("cx317_active", "state"): "ABORTED",
        ("cx317_active", "reason"): "device_abort_command_via_core0",
        ("cx317_active", "fail_static"): "true",
    }

    assert _post_abort_health_exact(primary, transition)
    transition[("cx317_active", "reason")] = "capture_lease_expired"
    assert not _post_abort_health_exact(primary, transition)


def test_abort_health_accepts_exact_core1_critical_ack_before_rotation() -> None:
    primary = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "fail_static"): "false",
    }
    rows = [
        {
            "status_seq": "66674",
            "component": "cx317_active",
            "status_key": "abort",
            "status_value": "queued_to_core1",
        },
        {
            "status_seq": "66675",
            "component": "cx317_active",
            "status_key": "critical_record",
            "status_value": "abort_accepted_on_core1",
        },
    ]

    assert _post_abort_health_exact(primary, {}, rows)
    rows[1]["status_value"] = "abort_rejected_on_core1"
    assert not _post_abort_health_exact(primary, {}, rows)
