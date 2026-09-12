from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import threading

import pytest

from host.otis_tools import adaptive_hybrid_bundle as bundle_module
from host.otis_tools import adaptive_hybrid_operational_rehearsal as rehearsal_module
from host.otis_tools import adaptive_hybrid_supervisor as supervisor_module
from host.otis_tools import authoritative_inputs
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


def test_rehearsal_startup_snapshot_does_not_invent_capture_lease(monkeypatch, tmp_path):
    bundle_path, _ = _frozen_inputs(monkeypatch, tmp_path)
    instrument = rehearsal_module.DeterministicPtyInstrument(
        -1, json.loads(bundle_path.read_text())
    )
    assert instrument._active_health()[("adaptive_hybrid", "capture_lease_live")] == "false"
    instrument._handle_command("ACTIVE LEASE 1")
    assert instrument._active_health()[("adaptive_hybrid", "capture_lease_live")] == "true"


def test_cold_supervisor_worker_reaches_actual_factory_with_one_schema_check_per_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle_path, proposal_path = _frozen_inputs(monkeypatch, tmp_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    run_dir = tmp_path / "cold-worker-run"
    run_dir.mkdir()
    manifest_path = rehearsal_module.create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/ttys999",
    )
    authoritative_inputs._check_schema_bytes.cache_clear()
    checked: list[str] = []
    original = authoritative_inputs.Draft202012Validator.check_schema

    def check(schema: object) -> None:
        checked.append(json.dumps(schema, sort_keys=True))
        original(schema)

    monkeypatch.setattr(
        authoritative_inputs.Draft202012Validator, "check_schema", check
    )

    def stop_at_run(supervisor: supervisor_module.AdaptiveHybridSupervisor) -> int:
        startup = json.loads(
            (run_dir / rehearsal_module.SUPERVISOR_STARTUP_PATH).read_text()
        )
        assert startup["current_phase"] == "ready_to_run"
        assert supervisor.state_path.is_file()
        return 23

    monkeypatch.setattr(supervisor_module.AdaptiveHybridSupervisor, "run", stop_at_run)

    assert rehearsal_module._supervisor_worker(manifest_path, run_dir) == 23
    assert len(checked) == len(set(checked)) == len(
        authoritative_inputs.CURRENT_SCHEMA_PATHS
    )


@pytest.mark.parametrize("command_effect_delay_s", [0.0, 4.0], ids=["normal", "delayed-command-effects"])
def test_full_process_operational_rehearsal_reaches_registered_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command_effect_delay_s: float,
) -> None:
    bundle_path, proposal_path = _frozen_inputs(monkeypatch, tmp_path)
    run_dir = tmp_path / "rehearsal-run"
    original_start = rehearsal_module.DeterministicPtyInstrument.start
    original_handle = rehearsal_module.DeterministicPtyInstrument._handle_command

    def delayed_effect(instrument, command):
        # Delay device-side effect after the real capture owner wrote the
        # command. Each causal exchange remains bounded; total runtime grows.
        if command.startswith("ACTIVE EVIDENCE "):
            if instrument.stop_event.wait(command_effect_delay_s):
                return
        original_handle(instrument, command)

    monkeypatch.setattr(rehearsal_module.DeterministicPtyInstrument, "_handle_command", delayed_effect)

    def start_after_capture_owns_slave(instrument):
        session = json.loads((run_dir / "reports/adaptive_hybrid_session_v1.json").read_text())
        assert session["phase"] == "capture_ready"
        return original_start(instrument)

    monkeypatch.setattr(rehearsal_module.DeterministicPtyInstrument, "start", start_after_capture_owns_slave)
    index_path = tmp_path / "evidence_index_v1.json"
    original_publish = rehearsal_module._atomic_json
    report_path = run_dir.parent / f"{run_dir.name}-{rehearsal_module.REPORT_NAME}"

    def fail_report_publication(path, *args, **kwargs):
        if path == report_path:
            raise OSError("injected report publication interruption")
        return original_publish(path, *args, **kwargs)

    if command_effect_delay_s == 0.0:
        monkeypatch.setattr(rehearsal_module, "_atomic_json", fail_report_publication)
        with pytest.raises(OSError, match="report publication interruption"):
            run_operational_rehearsal(
                bundle_path=bundle_path, proposal_path=proposal_path,
                run_dir=run_dir, evidence_index_path=index_path,
            )
        assert not report_path.exists()
        monkeypatch.setattr(rehearsal_module, "_atomic_json", original_publish)
        report_path = rehearsal_module.recover_operational_rehearsal(
            run_dir=run_dir, evidence_index_path=index_path,
        )
    else:
        report_path = run_operational_rehearsal(
            bundle_path=bundle_path, proposal_path=proposal_path,
            run_dir=run_dir, evidence_index_path=index_path,
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

    from host.otis_tools.evidence_index import package_identity
    before_recovery = package_identity(run_dir)
    report_before_recovery = report_path.read_bytes()
    for _ in range(2):
        recovered = rehearsal_module.recover_operational_rehearsal(
            run_dir=run_dir, evidence_index_path=index_path,
        )
        assert recovered == report_path
        assert report_path.read_bytes() == report_before_recovery
        assert package_identity(run_dir) == before_recovery

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
    from host.otis_tools.authoritative_inputs import validate_authoritative_inputs
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
    from host.otis_tools.contracts import CsvValidationContext, validate_csv
    validation_rows = {contracts[tag]: values for tag, values in rows.items()}
    validation_rows.update({
        "active_transactions_v3": instrument.fixture.transactions,
        "active_hybrid_decisions_v3": instrument.fixture.decisions,
        "active_hybrid_maintenance_v2": instrument.fixture.maintenance,
    })
    for contract, records in validation_rows.items():
        path = tmp_path / f"{contract}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[contract])
            writer.writeheader()
            writer.writerows(records)
        validation = validate_csv(path, CsvValidationContext(
            contract=contract, known_channels=frozenset({0, 1, 2}),
            known_domains=frozenset({"rp2040_monotonic_us32", "rp2040_monotonic_us64", "h1_oscillator_10mhz"}),
            expected_policy_sha256=instrument.reference_acceptance_binding["policy_sha256"],
        ))
        assert validation.ok, (contract, validation.errors)
    inputs = validate_authoritative_inputs(bundle["authoritative_inputs"])
    policy = inputs.document("data_contracts/reference_acceptance_policy_v1.json")
    exact, report, accepted = replay_accepted_spans(
        rows["SNP"], rows["REF"], rows["CNT"], rows["APS"],
        acceptance_policy=policy,
        acceptance_policy_sha256=rehearsal_module._reference_acceptance_binding(inputs)["policy_sha256"],
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
    assert [int(row["observation_sequence"]) for row in rows["RPH"]] == [1501, 3002, 3602, 4202, 5102, 6603]
    assert [int(row["estimate_age_s"]) for row in rows["PHE"]] == [301, 300, 300, 300, 0, 300]
    assert [float(row["estimated_frequency_error_hz"]) for row in rows["PHE"]] == pytest.approx([0, 0, 0, 3 / 600, 1 / 600, 0], abs=1e-12)
    from host.otis_tools.adaptive_hybrid_supervisor import _authoritative_capture_health_faults
    from host.otis_tools.firmware_host_contract import active_status_value_error
    for metadata_state in ("normal", "hold", "requalified"):
        instrument.metadata_state = metadata_state
        health = {**instrument._active_health(), **instrument._pps_health()}
        assert not _authoritative_capture_health_faults(health)
        assert not [active_status_value_error(key, health[("adaptive_hybrid", key)])
                    for key in rehearsal_module.ACTIVE_STATUS_KEYS
                    if active_status_value_error(key, health[("adaptive_hybrid", key)])]

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
    baseline = float(instrument.fixture.first_transaction.phases[0]["pre_error_hz"])
    for number, transaction in enumerate((instrument.fixture.first_transaction, instrument.fixture.second_transaction), 1):
        response = transaction.phases[3]
        assert int(response["consecutive_indeterminate"]) == number
        assert float(response["cumulative_response_hz"]) == pytest.approx(-baseline, abs=1e-12)
        assert response["post_error_hz"] == transaction.response_decision["frequency_error_hz"]
        assert float(response["observed_response_hz"]) == pytest.approx(-float(response["pre_error_hz"]), abs=1e-12)


def test_concurrent_snapshot_construction_preserves_generation_and_row_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import csv
    import io

    instrument = object.__new__(rehearsal_module.DeterministicPtyInstrument)
    instrument.master_fd = 17
    instrument._lock = threading.RLock()
    instrument.generation = instrument.status_sequence = 0
    instrument.latest_event_timestamp_ticks = 1200000000
    instrument.accepted_boundary_ordinal = 1200
    entered = threading.Event()
    release = threading.Event()
    second_constructed = threading.Event()
    wire = bytearray()
    calls = 0

    def active_health():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(2)
        else:
            second_constructed.set()
        return {("adaptive_hybrid", key): "0" for key in rehearsal_module.ACTIVE_STATUS_KEYS}

    monkeypatch.setattr(instrument, "_pps_health", lambda: {})
    monkeypatch.setattr(instrument, "_active_health", active_health)
    monkeypatch.setattr(rehearsal_module, "_write_all_fd", lambda _fd, payload: wire.extend(payload))
    first = threading.Thread(target=instrument._emit_snapshot)
    second = threading.Thread(target=instrument._emit_snapshot)
    first.start()
    assert entered.wait(1)
    second.start()
    try:
        assert not second_constructed.wait(0.05)
    finally:
        release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    rows = list(csv.reader(io.StringIO(wire.decode())))
    assert [int(row[2]) for row in rows] == list(range(1, len(rows) + 1))
    assert [int(row[7]) for row in rows if row[6] == rehearsal_module.SNAPSHOT_BEGIN_KEY] == [1, 2]
