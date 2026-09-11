from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import threading

import pytest

from host.otis_tools import adaptive_hybrid_bundle as bundle_module
from host.otis_tools import adaptive_hybrid_operational_rehearsal as rehearsal_module
from host.otis_tools.adaptive_hybrid_bundle import create_bundle
from host.otis_tools.adaptive_hybrid_operational_rehearsal import (
    REQUIRED_BOUNDARIES,
    run_operational_rehearsal,
    validate_operational_rehearsal_package,
)
from host.otis_tools.adaptive_hybrid_proposal import create_proposal


def test_idle_wakeup_serializes_with_complete_pty_record_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = object.__new__(rehearsal_module.DeterministicPtyInstrument)
    instrument.master_fd = 17
    instrument._lock = threading.Lock()
    write_started = threading.Event()
    writes: list[tuple[int, bytes]] = []

    def record_write(descriptor: int, payload: bytes) -> None:
        writes.append((descriptor, payload))
        write_started.set()

    monkeypatch.setattr(rehearsal_module, "_write_all_fd", record_write)
    instrument._lock.acquire()
    worker = threading.Thread(target=instrument._emit_idle_wakeup)
    worker.start()
    try:
        assert not write_started.wait(0.05)
    finally:
        instrument._lock.release()
    assert write_started.wait(1.0)
    worker.join(timeout=1.0)
    assert not worker.is_alive()
    assert writes == [(17, b"\n")]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _binding(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _frozen_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    build_manifest = tmp_path / "build.json"
    uf2 = tmp_path / "adaptive_hybrid.uf2"
    generated_header = tmp_path / "otis_build_manifest.generated.h"
    uf2.write_bytes(b"deterministic nonphysical rehearsal image fixture")
    generated_header.write_text("// deterministic rehearsal fixture\n", encoding="utf-8")
    _write_json(build_manifest, {"fixture": "nonphysical_rehearsal"})
    firmware = {
        "image_id": bundle_module.ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_manifest": _binding(build_manifest),
        "source_revision": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
        "build_identity": "b" * 64 + ":" + "c" * 64,
        "build_provenance_required": False,
        "uf2": _binding(uf2),
        "generated_header": _binding(generated_header),
        "fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133",
        "toolchain": {"fixture": True},
        "binary_contract": {"fixture": True},
        "independent_binary_verification": {"fixture": True},
        "deterministic_reproduction": {"fixture": True},
    }
    monkeypatch.setattr(bundle_module, "_validate_build", lambda *_args, **_kwargs: firmware)

    bundle_path = tmp_path / "bundle.json"
    _write_json(bundle_path, create_bundle(build_manifest_path=build_manifest))
    proposal_path = tmp_path / "proposal.json"
    create_proposal(bundle_path=bundle_path, output_path=proposal_path)
    return bundle_path, proposal_path


def test_full_process_operational_rehearsal_reaches_registered_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, proposal_path = _frozen_inputs(monkeypatch, tmp_path)
    run_dir = tmp_path / "rehearsal-run"
    report_path = run_operational_rehearsal(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        run_dir=run_dir,
        evidence_index_path=tmp_path / "evidence_index_v1.json",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["required_boundaries"] == list(REQUIRED_BOUNDARIES)
    assert report["boundary_results"] == {
        boundary: True for boundary in REQUIRED_BOUNDARIES
    }
    assert report["required_evidence"] == {
        "immutable_complete_acquisition_snapshot": True,
        "shared_current_analyzer_consumers_exact": True,
        "successful_rehearsal_registration": True,
        "exact_tool_bindings": {
            name: bundle["host_tools"][name]
            for name in sorted(
                {
                    "capture_device",
                    "acquisition_frontier",
                    "raw_measurement_replay",
                    "adaptive_hybrid_operational_rehearsal",
                    "adaptive_hybrid_supervisor",
                    "adaptive_hybrid_run",
                    "adaptive_hybrid_analyze",
                    "evidence",
                    "evidence_finalization",
                    "evidence_index",
                }
            )
        },
        "raw_evidence_and_frozen_criteria_unchanged_during_analysis": True,
    }
    assert report["claim_boundary"]["is_not_physical_plant_qualification"] is True
    assert report["claim_boundary"]["physical_actions_performed"] == 0

    producer_sha256 = bundle["host_tools"][
        "adaptive_hybrid_operational_rehearsal"
    ]["sha256"]
    validation = validate_operational_rehearsal_package(
        run_dir,
        source_revision=bundle["firmware"]["source_revision"],
        build_identity=bundle["firmware"]["build_identity"],
        image_identity=bundle["image_identity"],
        result_or_failure_reason="adaptive-hybrid operational rehearsal passed",
        analyzer_identity=producer_sha256,
    )
    assert validation["primary_decision"] == (
        "adaptive_hybrid_operational_rehearsal_passed"
    )

    process_path = run_dir / (
        "reports/adaptive_hybrid_operational_process_evidence_v1.json"
    )
    process_value = json.loads(process_path.read_text(encoding="utf-8"))
    process_value["physical_actions_performed"] = 1
    process_path.chmod(0o644)
    _write_json(process_path, process_value)
    with pytest.raises(ValueError, match="snapshot|source|process"):
        validate_operational_rehearsal_package(
            run_dir,
            source_revision=bundle["firmware"]["source_revision"],
            build_identity=bundle["firmware"]["build_identity"],
            image_identity=bundle["image_identity"],
            result_or_failure_reason=(
                "adaptive-hybrid operational rehearsal passed"
            ),
            analyzer_identity=producer_sha256,
        )


def test_rehearsal_raw_accepted_sources_and_phase_are_coherent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import csv
    import io
    from host.otis_tools.accepted_span_replay import replay_accepted_spans
    from host.otis_tools.authoritative_inputs import authoritative_document
    from host.otis_tools.contracts import CONTRACT_FIELDS

    bundle_path, _ = _frozen_inputs(monkeypatch, tmp_path)
    bundle = json.loads(bundle_path.read_text())
    wire = bytearray()
    monkeypatch.setattr(rehearsal_module, "_write_all_fd", lambda _fd, payload: wire.extend(payload))
    instrument = rehearsal_module.DeterministicPtyInstrument(17, bundle)
    instrument._emit_initial_observations()
    instrument._emit_source_through(7803)
    for decision in instrument.fixture.decisions:
        instrument._emit_selected_estimate(decision)
    contracts = {"REF": "raw_events_v1", "SNP": "pps_snapshots_v1",
                 "CNT": "count_observations_v1", "APS": "accepted_pps_spans_v1",
                 "EST": "estimates_v3", "RPH": "relative_phase_observations_v2",
                 "PHE": "phase_estimator_outputs_v2"}
    rows: dict[str, list[dict[str, str]]] = {name: [] for name in contracts}
    for values in csv.reader(io.StringIO(wire.decode())):
        if values[0] in contracts:
            rows[values[0]].append(dict(zip(CONTRACT_FIELDS[contracts[values[0]]], values, strict=True)))
    policy = authoritative_document(bundle["authoritative_inputs"], "data_contracts/reference_acceptance_policy_v1.json")
    exact, report, accepted = replay_accepted_spans(
        rows["SNP"], rows["REF"], rows["CNT"], rows["APS"],
        acceptance_policy=policy,
        acceptance_policy_sha256=rehearsal_module._reference_acceptance_binding(bundle)["policy_sha256"],
    )
    assert exact, report
    assert len(accepted) == 7803
    assert len(rows["CNT"]) == 7804
    split = rows["APS"][1499]
    assert (split["opening_snapshot_sequence"], split["closing_snapshot_sequence"],
            split["excluded_candidate_count"], split["counted_edges"]) == ("1499", "1501", "1", "10000000")
    assert [(row["counted_edges"], row["flags"]) for row in rows["CNT"][1499:1503]] == [
        ("2462937", "4120"), ("7537063", "4120"), ("10000000", "4120"), ("10000000", "16")]
    assert [int(row["relative_phase_cycles"]) for row in rows["RPH"]] == [-6, -6, -3, 0, 6, 6]
    applications = [int(item.phases[2]["event_timestamp_ticks"]) for item in (
        instrument.fixture.first_transaction, instrument.fixture.second_transaction)]
    for index, (decision, estimate) in enumerate(zip(instrument.fixture.decisions, rows["EST"], strict=True)):
        opening = int(estimate["source_opening_accepted_boundary_ordinal"])
        closing = int(estimate["source_closing_accepted_boundary_ordinal"])
        assert closing - opening == 600
        assert closing == int(decision["decision_timestamp_s"])
        assert sum(int(row["counted_edges"]) - 10000000 for row in rows["APS"][opening:closing]) == int(decision["accumulated_edge_error_counts"])
        if index in (0, 1, 5):
            application = 1200071551 if index == 0 else applications[0 if index == 1 else 1]
            assert opening * 1000000 >= application + 900000000
    for transaction in (instrument.fixture.first_transaction, instrument.fixture.second_transaction):
        response = transaction.phases[3]
        assert response["post_error_hz"] == transaction.response_decision["frequency_error_hz"]
        assert float(response["observed_response_hz"]) == pytest.approx(-float(response["pre_error_hz"]), abs=1e-12)
