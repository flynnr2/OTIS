from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_g1_rehearsal as rehearsal


def test_supervisor_terminal_requires_explicit_healthy_stop(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    state_path = reports / "cx317_active_supervisor_state.json"
    base = {
        "cx319_gate": "G1",
        "manual_start_sent": False,
        "authorization_sequence": 0,
    }
    state_path.write_text(
        json.dumps(
            {
                **base,
                "terminal": {"result": "aborted", "reason": "fault"},
            }
        ),
        encoding="utf-8",
    )
    assert rehearsal._supervisor_terminal(tmp_path) is False

    state_path.write_text(
        json.dumps(
            {
                **base,
                "terminal": {
                    "result": "healthy_stop",
                    "reason": "finite_endpoint_complete",
                },
            }
        ),
        encoding="utf-8",
    )
    assert rehearsal._supervisor_terminal(tmp_path) is True


def test_preanalysis_failure_is_recorded_and_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered: dict[str, object] = {}

    def fake_register_package(**kwargs: object) -> dict[str, str]:
        registered.update(kwargs)
        return {"content_sha256": "f" * 64}

    monkeypatch.setattr(
        rehearsal, "register_package", fake_register_package
    )
    bundle = {
        "bundle_sha256": "b" * 64,
        "leg": {"leg": "A"},
        "firmware": {
            "git_commit": "1" * 40,
            "profile_id": "cx319_tight_lower",
            "build_manifest": {"sha256": "2" * 64},
        },
    }

    result = rehearsal._retain_orchestration_failure(
        run_dir=tmp_path,
        bundle=bundle,
        evidence_index_path=tmp_path.parent / "index.json",
        error=RuntimeError("synthetic cross-surface failure"),
    )

    report = json.loads(
        (tmp_path / rehearsal.ORCHESTRATION_FAILURE_PATH).read_text(
            encoding="utf-8"
        )
    )
    assert result["content_sha256"] == "f" * 64
    assert report["failure_class"] == "platform_defect_caught_in_rehearsal"
    assert report["error"] == "synthetic cross-surface failure"
    assert registered["attempt_classification"] == "failed_rehearsal"
    assert registered["package_path"] == tmp_path
