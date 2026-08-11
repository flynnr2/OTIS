from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.no_write_qualification_analyze import (
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
