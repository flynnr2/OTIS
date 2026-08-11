from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.cx319_g1_analyze import _command_allowed, seal


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
