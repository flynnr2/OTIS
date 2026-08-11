from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools.programme_status import (
    ProgrammeExecutionBlocked,
    load_programme_status,
    require_programme_execution_allowed,
)


def test_tracked_status_records_completion_with_no_next_programme_authorized() -> None:
    status = load_programme_status()

    assert status["active_programme"] is None
    assert status["programmes"]["platform_stabilization"] == {
        "state": "completed",
        "execution_allowed": False,
        "effective_date": "2026-08-11",
        "authority": "passed_completion_gate",
    }
    assert status["programmes"]["cx318_stage5"]["state"] == (
        "suspended_incomplete_unsealed"
    )
    assert status["programmes"]["cx318_stage5"]["execution_allowed"] is False

    with pytest.raises(ProgrammeExecutionBlocked, match="execution is blocked"):
        require_programme_execution_allowed("platform_stabilization")


def test_suspended_stage5_is_blocked_before_operational_side_effects() -> None:
    with pytest.raises(ProgrammeExecutionBlocked, match="execution is blocked"):
        require_programme_execution_allowed("cx318_stage5")


def test_status_contract_rejects_an_inactive_active_programme(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status_id": "otis_programme_status_v1",
                "active_programme": "blocked",
                "programmes": {
                    "blocked": {
                        "state": "suspended",
                        "execution_allowed": False,
                        "effective_date": "2026-08-11",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="active_programme must permit"):
        load_programme_status(path)


def test_stage5_manifest_create_cli_stops_on_programme_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from host.otis_tools import cx318_stage5_manifest

    with pytest.raises(SystemExit) as exc:
        cx318_stage5_manifest.main(
            [
                "create",
                "--mode",
                "rehearsal",
                "--leg",
                "A",
                "--run-dir",
                "/not-used",
                "--build-manifest",
                "/not-used/build.json",
                "--uf2",
                "/not-used/image.uf2",
                "--stage4-seal",
                "/not-used/seal.json",
                "--serial-device",
                "/not-used/device",
            ]
        )

    assert exc.value.code == 2
    assert "suspended_incomplete_unsealed" in capsys.readouterr().err
