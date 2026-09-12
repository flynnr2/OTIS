"""Normal terminal handoff through the real two-process simulated runtime."""

from __future__ import annotations

import json
import os
import pty
import threading
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_analyze as analyze_module
from host.otis_tools import run_spec as run_spec_module
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    INHIBITED_ZERO_WRITE,
)
from host.otis_tools.adaptive_hybrid_supervisor import AdaptiveHybridSupervisor
from host.otis_tools.evidence_package import (
    PASSING_ANALYSIS_CHECKS,
    validate_package,
)
from host.otis_tools.live_run import run_experiment
from host.otis_tools.offline import finish_run
from host.otis_tools.run_spec import create_run_record
from tests.run_spec_fixtures import build_synthetic_spec
from tools.otis_rehearsal_device import DeterministicPtyInstrument
from tools.rehearse_host import _capture_command, _utc_now


def test_inhibited_wall_endpoint_closes_capture_and_analyzes_without_abort(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Accelerate only the wall deadline after the real raw origin is admitted."""

    run_dir = tmp_path / "healthy-inhibited"
    run_dir.mkdir()
    spec = build_synthetic_spec(monkeypatch, run_dir, purpose=INHIBITED_ZERO_WRITE)
    master, slave = pty.openpty()
    slave_open = True
    device = os.ttyname(slave)
    record = create_run_record(
        spec,
        execution_kind="simulated",
        run_id=run_dir.name,
        started_at_utc=_utc_now(),
        serial_device=device,
        output_path=run_dir / "run_manifest.json",
    )
    instrument = DeterministicPtyInstrument(
        master, spec.runtime_manifest(record), ADAPTIVE_HYBRID_PROGRAMME
    )
    worker: threading.Thread | None = None

    establish_origin = (
        AdaptiveHybridSupervisor._maybe_establish_zero_write_aperture_origin
    )

    def establish_origin_then_expire_wall(
        owner: AdaptiveHybridSupervisor,
        health: dict[tuple[str, str], str],
    ) -> None:
        establish_origin(owner, health)
        if (
            owner.state.get("qualified_acceptance_ordinal_origin") is not None
            and owner._wall_deadline_monotonic_ns > time.monotonic_ns()
        ):
            # This is the sole acceleration seam. The production owner has
            # already admitted its solicited census and raw D14/D8 origin.
            owner._wall_deadline_monotonic_ns = time.monotonic_ns()

    monkeypatch.setattr(
        AdaptiveHybridSupervisor,
        "_maybe_establish_zero_write_aperture_origin",
        establish_origin_then_expire_wall,
    )

    os.close(slave)
    slave_open = False

    def on_ready(_experiment):
        nonlocal worker
        worker = instrument.start()

        def cleanup() -> None:
            instrument.stop()
            assert worker is not None
            worker.join(timeout=2)
            assert not worker.is_alive()

        return cleanup

    try:
        live = run_experiment(
            manifest_path=run_dir / "run_manifest.json",
            device=device,
            physical=False,
            capture_command=_capture_command(device, run_dir),
            on_ready=on_ready,
        )
    finally:
        if slave_open:
            os.close(slave)
        os.close(master)

    assert instrument.error is None
    assert live["status"] == "terminal"
    assert live["supervisor_exit"] == 0
    assert live["capture_exit"] == 0
    assert live["terminal"]["result"] == "healthy_stop"
    assert live["terminal"]["reason"] == "inhibited_zero_write_complete"
    assert not any(
        command.startswith(("ACTIVE SETUP ", "ACTIVE ARM "))
        or command == "ACTIVE ABORT"
        for command in instrument.commands
    )

    closure = json.loads(
        (run_dir / "reports/capture_segment_closure_v1.json").read_text()
    )
    assert closure["logical_segment_closed"] is True
    assert closure["physical_serial_open"] is False
    assert not (run_dir / "capture_in_progress.flag").exists()
    assert '"event": "emergency_abort_sent"' not in (
        run_dir / "raw/serial.log"
    ).read_text(encoding="utf-8")

    packaged = finish_run(run_dir)
    assert packaged["capture"]["integrity"] == "complete"
    assert packaged["analysis"]["status"] == "passed"
    assert packaged["analysis"]["outcome"] == "diagnostic_complete"
    analysis = json.loads((run_dir / "reports/offline_analysis_v2.json").read_text())
    assert analysis["schema_version"] == 2
    assert analysis["contract"] == "otis_offline_analysis_v2"
    assert analysis["tool"] == "adaptive_hybrid_analyze_v2"
    assert analysis["host_toolset_sha256"] == spec.host_toolset_sha256
    assert set(analysis["checks"]) == PASSING_ANALYSIS_CHECKS
    assert analysis["checks"]["D14_D8_measurement_replay_exact"] is True
    assert analysis["measurement_replay"]["estimate_replay"] == {
        "applicability": "not_applicable_no_emitted_estimates",
        "emitted_count": 0,
        "selected_sources_exact": True,
        "exact": True,
    }

    source_before = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    changed_toolset = deepcopy(run_spec_module._host_toolset())
    changed_entry = next(
        item
        for item in changed_toolset["entries"]
        if item["path"] == "host/otis_tools/adaptive_hybrid_replay.py"
    )
    changed_entry["sha256"] = "f" * 64
    changed_unsigned = {
        key: value for key, value in changed_toolset.items() if key != "toolset_sha256"
    }
    changed_toolset["toolset_sha256"] = sha256(
        json.dumps(
            changed_unsigned,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    repaired_toolset_sha256 = changed_toolset["toolset_sha256"]
    monkeypatch.setattr(run_spec_module, "_host_toolset", lambda: changed_toolset)
    external_path = tmp_path / "corrected-offline-analysis-v2.json"
    _, corrected = analyze_module.analyze(run_dir, output_path=external_path)
    assert (
        corrected["source_package_content_sha256"] == packaged["package_content_sha256"]
    )
    assert corrected["host_toolset_sha256"] == repaired_toolset_sha256
    assert source_before == {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    # A report remains invalid if an omitted mandatory check is hidden by
    # recomputing its own semantic digest and all retained source hashes still
    # match. The check-name contract is part of the passing boundary.
    analysis["checks"].pop("supervisor_terminal_exact")
    unsigned = {
        key: value for key, value in analysis.items() if key != "analysis_sha256"
    }
    analysis["analysis_sha256"] = sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (run_dir / "reports/offline_analysis_v2.json").write_text(
        json.dumps(analysis), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="passing analysis report"):
        validate_package(run_dir)
