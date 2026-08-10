from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import cx318_stage5_promote as promote


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    rehearsal = (tmp_path / "rehearsal").resolve()
    transition = (tmp_path / "transition").resolve()
    live = (tmp_path / "live").resolve()
    control = (tmp_path / "control").resolve()
    rehearsal.mkdir()
    (rehearsal / "run_manifest.json").write_text("{}\n", encoding="utf-8")
    (rehearsal / promote.CAPTURE_IN_PROGRESS_FLAG).touch()
    _write_json(
        rehearsal / promote.SUPERVISOR_STATE,
        {
            "stage5_mode": "rehearsal",
            "stage5_leg": "A",
            "terminal": {
                "result": "healthy_stop",
                "reason": "2700s_exact_profile_no_write_rehearsal_complete",
            },
        },
    )
    _write_json(
        rehearsal / promote.CAPTURE_STATE,
        {
            "pid": 123,
            "capture_active": True,
            "serial_open": True,
            "transport_generation": 1,
        },
    )
    _write_json(
        control / promote.SEGMENT_CARRIER_STATE,
        {
            "pid": 123,
            "status": "running",
            "serial_open": True,
            "current_run": str(rehearsal),
            "transport_generation": 1,
            "reconnect_count": 0,
        },
    )
    manifest = {
        "stage": promote.REHEARSAL_STAGE,
        "stage5": {"leg": "A"},
        "firmware": {
            "path": str(tmp_path / "build.json"),
            "uf2": {"path": str(tmp_path / "firmware.uf2")},
        },
        "stage4_seal": {"path": str(tmp_path / "stage4.json")},
        "host": {"serial_device": "/dev/cu.test", "baud": 115200},
    }
    return rehearsal, transition, live, control, manifest


def test_promotion_orders_rotation_seal_manifest_and_live_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rehearsal, transition, live, control, manifest = _fixture(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(promote, "validate_manifest", lambda _: manifest)

    def prepare(source: Path, target: Path) -> Path:
        events.append("prepare_transition")
        target.mkdir()
        path = target / "run_manifest.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(promote, "prepare_transition", prepare)

    def rotate(**kwargs):
        target = Path(kwargs["to_run"]).resolve()
        if target == transition:
            events.append("rotate_rehearsal_to_transition")
            (rehearsal / promote.CAPTURE_IN_PROGRESS_FLAG).unlink()
            return {
                "from_run": str(rehearsal),
                "to_run": str(transition),
                "pid": 123,
                "transport_generation": 2,
                "serial_reopened": False,
                "reconnect_count": 0,
            }
        events.append("rotate_transition_to_live")
        _write_json(
            control / promote.SEGMENT_CARRIER_STATE,
            {
                "pid": 123,
                "status": "running",
                "serial_open": True,
                "current_run": str(live),
                "transport_generation": 3,
                "reconnect_count": 0,
            },
        )
        _write_json(
            live / promote.CAPTURE_STATE,
            {
                "pid": 123,
                "capture_active": True,
                "serial_open": True,
                "transport_generation": 3,
            },
        )
        return {
            "from_run": str(transition),
            "to_run": str(live),
            "pid": 123,
            "transport_generation": 3,
            "serial_reopened": False,
            "reconnect_count": 0,
        }

    monkeypatch.setattr(promote, "request_rotation", rotate)

    def evidence(run: Path) -> Path:
        events.append("seal_evidence")
        assert (run / promote.COMPLETE_MARKER).is_file()
        path = run / "evidence_manifest.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(promote, "create_evidence_snapshot", evidence)

    def analyze(run: Path):
        events.append("analyze_rehearsal")
        path = run / promote.REHEARSAL_SEAL
        path.parent.mkdir(exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path, {"status": "passed"}

    monkeypatch.setattr(promote, "analyze", analyze)

    def create(**kwargs):
        events.append("create_live_manifest")
        assert Path(kwargs["rehearsal_seal_path"]).is_file()
        live.mkdir()
        path = live / "run_manifest.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(promote, "create_manifest", create)

    result = promote.promote(
        rehearsal_run=rehearsal,
        transition_run=transition,
        live_run=live,
        control_dir=control,
        capability="capability",
    )

    assert events == [
        "prepare_transition",
        "rotate_rehearsal_to_transition",
        "seal_evidence",
        "analyze_rehearsal",
        "create_live_manifest",
        "rotate_transition_to_live",
    ]
    assert result["serial_reopened"] is False
    assert result["reconnect_count"] == 0
    assert (transition / promote.REPORT).is_file()


def test_failed_rehearsal_seal_stays_in_no_authority_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rehearsal, transition, live, control, manifest = _fixture(tmp_path)
    monkeypatch.setattr(promote, "validate_manifest", lambda _: manifest)

    def prepare(source: Path, target: Path) -> Path:
        target.mkdir()
        path = target / "run_manifest.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(promote, "prepare_transition", prepare)

    def rotate(**kwargs):
        assert Path(kwargs["to_run"]).resolve() == transition
        (rehearsal / promote.CAPTURE_IN_PROGRESS_FLAG).unlink()
        return {
            "from_run": str(rehearsal),
            "to_run": str(transition),
            "pid": 123,
            "serial_reopened": False,
            "reconnect_count": 0,
        }

    monkeypatch.setattr(promote, "request_rotation", rotate)

    def evidence(run: Path) -> Path:
        path = run / "evidence_manifest.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(promote, "create_evidence_snapshot", evidence)
    monkeypatch.setattr(
        promote,
        "analyze",
        lambda run: (run / promote.REHEARSAL_SEAL, {"status": "failed"}),
    )
    monkeypatch.setattr(
        promote,
        "create_manifest",
        lambda **kwargs: pytest.fail("live manifest must not be created"),
    )

    with pytest.raises(ValueError, match="did not produce a passed"):
        promote.promote(
            rehearsal_run=rehearsal,
            transition_run=transition,
            live_run=live,
            control_dir=control,
            capability="capability",
        )
    assert not live.exists()
    assert transition.is_dir()
