from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools.adaptive_hybrid_replay import replay_phase_accepted_sources
from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.firmware_host_contract import validate_record_wire_values

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_phase_preview_binds_only_after_confirmed_application(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "phase_preview_binding"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/phase_preview_binding_harness.cpp"),
            str(FIRMWARE / "otis_phase_preview_live.cpp"),
            str(FIRMWARE / "otis_selected_phase_frequency_preview_engine.cpp"),
            str(FIRMWARE / "otis_phase_preview_format.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    completed = subprocess.run(
        [str(executable)], cwd=ROOT, check=True, capture_output=True, text=True
    )
    rows = list(csv.reader(completed.stdout.splitlines()))
    assert rows and len(rows) % 2 == 0
    qualification_pairs = set()
    emitted_rph = []
    emitted_phe = []
    accepted_spans = []
    allowed_qualification = {
        "epoch_open": {"initializing"},
        "qualified": {"initializing", "qualified"},
        "invalid": {"invalid"},
    }
    for rph_values, phe_values in zip(rows[::2], rows[1::2], strict=True):
        assert (
            validate_record_wire_values("relative_phase_observations_v2", rph_values)
            == ()
        )
        assert (
            validate_record_wire_values("phase_estimator_outputs_v2", phe_values) == ()
        )
        rph = dict(
            zip(
                CONTRACT_FIELDS["relative_phase_observations_v2"],
                rph_values,
                strict=True,
            )
        )
        phe = dict(
            zip(CONTRACT_FIELDS["phase_estimator_outputs_v2"], phe_values, strict=True)
        )
        for field in (
            "phase_epoch",
            "observation_sequence",
            "capture_session",
            "acceptance_epoch",
            "accepted_boundary_ordinal",
        ):
            assert rph[field] == phe[field]
        qualification_pair = (
            rph["qualification_state"],
            phe["qualification_state"],
        )
        qualification_pairs.add(qualification_pair)
        emitted_rph.append(rph)
        emitted_phe.append(phe)
        assert qualification_pair[1] in allowed_qualification[qualification_pair[0]]
        if rph["qualification_state"] == "qualified":
            accepted_spans.append(
                {
                    "capture_session": rph["capture_session"],
                    "acceptance_epoch": rph["acceptance_epoch"],
                    "accepted_boundary_ordinal": rph["accepted_boundary_ordinal"],
                    "opening_snapshot_sequence": rph["opening_snapshot_sequence"],
                    "closing_snapshot_sequence": rph["closing_snapshot_sequence"],
                    "opening_reference_sequence": rph["opening_reference_sequence"],
                    "closing_reference_sequence": rph["closing_reference_sequence"],
                    "counted_edges": rph["interval_edges"],
                }
            )
            assert rph["source_accepted_span_ref"] == (
                f"live:APS:{rph['capture_session']}:{rph['acceptance_epoch']}:{rph['accepted_boundary_ordinal']}"
            )
        else:
            assert rph["source_accepted_span_ref"] == ""
    assert qualification_pairs == {
        ("epoch_open", "initializing"),
        ("qualified", "initializing"),
        ("qualified", "qualified"),
        ("invalid", "invalid"),
    }

    replay_rows = {
        "spans.csv": accepted_spans,
        "rph.csv": emitted_rph,
        "phe.csv": emitted_phe,
    }
    files = [
        {"contract": "accepted_pps_spans_v1", "path": "spans.csv"},
        {"contract": "relative_phase_observations_v2", "path": "rph.csv"},
        {"contract": "phase_estimator_outputs_v2", "path": "phe.csv"},
    ]
    monkeypatch.setattr(
        "host.otis_tools.adaptive_hybrid_replay._read_csv",
        lambda path: replay_rows[path.name],
    )
    replay = replay_phase_accepted_sources(
        SimpleNamespace(root=Path("/unused"), files=files)
    )
    assert replay["exact"], replay
    assert replay["paired_identity_count"] == len(emitted_rph)
    assert replay["unpaired_rph_count"] == 0


def _phase_replay(
    monkeypatch,
    *,
    rph_qualification: str,
    phe_qualification: str,
    phe_updates: dict[str, str] | None = None,
    rph_count: int = 1,
    phe_count: int = 1,
):
    span = {
        "capture_session": "3",
        "acceptance_epoch": "5",
        "accepted_boundary_ordinal": "9",
        "opening_snapshot_sequence": "20",
        "closing_snapshot_sequence": "21",
        "opening_reference_sequence": "30",
        "closing_reference_sequence": "31",
        "counted_edges": "10000001",
    }
    rph = {
        "phase_epoch": "2",
        "observation_sequence": "7",
        "capture_session": "3",
        "acceptance_epoch": "5",
        "accepted_boundary_ordinal": "9",
        "source_accepted_span_ref": (
            "live:APS:3:5:9" if rph_qualification == "qualified" else ""
        ),
        "opening_snapshot_sequence": "20",
        "closing_snapshot_sequence": "21",
        "opening_reference_sequence": "30",
        "closing_reference_sequence": "31",
        "interval_edges": "10000001",
        "relative_phase_cycles": "4",
        "relative_phase_time_ns": "400",
        "qualification_state": rph_qualification,
    }
    phe = {
        "phase_epoch": "2",
        "observation_sequence": "7",
        "capture_session": "3",
        "acceptance_epoch": "5",
        "accepted_boundary_ordinal": "9",
        "source_relative_phase_observation": "RPH:2:7",
        "raw_relative_phase_cycles": "4",
        "raw_relative_phase_time_ns": "400",
        "qualification_state": phe_qualification,
    }
    phe.update(phe_updates or {})
    rows = {
        "spans.csv": [span],
        "rph.csv": [dict(rph) for _ in range(rph_count)],
        "phe.csv": [dict(phe) for _ in range(phe_count)],
    }
    files = [
        {"contract": "accepted_pps_spans_v1", "path": "spans.csv"},
        {"contract": "relative_phase_observations_v2", "path": "rph.csv"},
        {"contract": "phase_estimator_outputs_v2", "path": "phe.csv"},
    ]
    monkeypatch.setattr(
        "host.otis_tools.adaptive_hybrid_replay._read_csv",
        lambda path: rows[path.name],
    )
    return replay_phase_accepted_sources(
        SimpleNamespace(root=Path("/unused"), files=files)
    )


@pytest.mark.parametrize(
    ("rph_qualification", "phe_qualification"),
    [
        ("epoch_open", "initializing"),
        ("qualified", "initializing"),
        ("qualified", "qualified"),
        ("invalid", "invalid"),
    ],
)
def test_phase_replay_accepts_exact_producer_qualification_relations(
    monkeypatch,
    rph_qualification: str,
    phe_qualification: str,
) -> None:
    report = _phase_replay(
        monkeypatch,
        rph_qualification=rph_qualification,
        phe_qualification=phe_qualification,
    )
    assert report["exact"], report


@pytest.mark.parametrize(
    ("rph_qualification", "phe_qualification"),
    [
        ("epoch_open", "qualified"),
        ("qualified", "invalid"),
        ("invalid", "initializing"),
    ],
)
def test_phase_replay_rejects_contradictory_qualification_relations(
    monkeypatch,
    rph_qualification: str,
    phe_qualification: str,
) -> None:
    report = _phase_replay(
        monkeypatch,
        rph_qualification=rph_qualification,
        phe_qualification=phe_qualification,
    )
    assert not report["exact"]
    assert report["error_count"] == 1


def test_phase_replay_reports_unpaired_rph_without_inventing_capture_failure(
    monkeypatch,
) -> None:
    report = _phase_replay(
        monkeypatch,
        rph_qualification="qualified",
        phe_qualification="initializing",
        phe_count=0,
    )
    assert report["exact"], report
    assert report["paired_identity_count"] == 0
    assert report["unpaired_rph_count"] == 1


@pytest.mark.parametrize(
    ("rph_count", "phe_count"),
    [(2, 1), (1, 2)],
)
def test_phase_replay_rejects_duplicate_pair_identities(
    monkeypatch,
    rph_count: int,
    phe_count: int,
) -> None:
    report = _phase_replay(
        monkeypatch,
        rph_qualification="qualified",
        phe_qualification="initializing",
        rph_count=rph_count,
        phe_count=phe_count,
    )
    assert not report["exact"]
    assert any("identity is duplicated" in error for error in report["errors"])


def test_phase_replay_warmup_still_requires_exact_rph_source_values(
    monkeypatch,
) -> None:
    report = _phase_replay(
        monkeypatch,
        rph_qualification="qualified",
        phe_qualification="initializing",
        phe_updates={"raw_relative_phase_cycles": "5"},
    )
    assert not report["exact"]
    assert report["error_count"] == 1


def test_sketch_does_not_fabricate_a_pre_setup_code() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(encoding="utf-8")
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    frequency_live = (FIRMWARE / "otis_frequency_regulation_live.cpp").read_text(
        encoding="utf-8"
    )
    start = sketch.index("OtisRegulationStaticCodeState regulation_static_code_state")
    end = sketch.index("\nvoid ", start)
    static_state = sketch[start:end]

    assert "return dual_core_static_code;" in static_state
    assert "if (!dual_core_static_code.available)" not in static_state
    assert "TIGHT_DEADBAND_INITIAL" not in config
    assert "otis_phase_preview_live_begin();" in sketch
    assert "otis_phase_preview_live_update_applied_code(applied_code,dac_epoch)" in sketch
    assert '"static_code"' not in sketch
    assert 'char current_code[16] = "";' in frequency_live
    assert '"%u", code->applied_code' in frequency_live
