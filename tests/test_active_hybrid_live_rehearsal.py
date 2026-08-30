from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_activation as activation
from host.otis_tools import active_hybrid_live_analyze as live_analyze
from host.otis_tools import active_hybrid_live_rehearsal as rehearsal
from host.otis_tools.active_hybrid_programme_contract import (
    CX322_D9_D6_72H_PROGRAMME,
    CX322_D9_D6_INTEGRATION_PROGRAMME,
    CX322_PROGRAMME,
)
from host.otis_tools.active_hybrid_live_analyze import (
    _response_dependent_consumer_propagation,
)
from host.otis_tools.active_status_contract import (
    complete_active_status_snapshots,
)
from host.otis_tools.active_status_live_state import ActiveStatusLiveReducer
from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    ACTIVE_HYBRID_DECISION_V2_FIELDS,
    ACTIVE_TRANSACTION_V2_FIELDS,
    CONTRACT_FIELDS,
)


def _binding(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _fixture(tmp_path: Path) -> tuple[Path, dict, Path, dict]:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text("{}\n", encoding="utf-8")
    tool_path = tmp_path / "tool.py"
    tool_path.write_text("# tool\n", encoding="utf-8")
    bundle_path = tmp_path / "bundle.json"
    proposal_path = tmp_path / "proposal.json"
    firmware = {
        "build_identity": "a" * 64 + ":" + "b" * 64,
        "source_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "uf2": {"sha256": "c" * 64},
    }
    bundle = {
        "bundle_sha256": "d" * 64,
        "firmware": firmware,
        "policy": {
            **_binding(policy_path),
            "policy_sha256": "e" * 64,
        },
        "host_tools": {"fixture": _binding(tool_path)},
    }
    proposal = {
        "proposal_sha256": "f" * 64,
        "exact_bundle": {"bundle_sha256": bundle["bundle_sha256"]},
    }
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    return bundle_path, bundle, proposal_path, proposal


def test_cx322_post_abort_snapshot_preserves_confirmed_static_state() -> None:
    payload = rehearsal._post_abort_active_status_wire_fixture(
        generation=12,
        bundle={"programme_id": CX322_PROGRAMME.programme_id},
        applied_code=0xA837,
        dac_epoch=2,
        correction_count=1,
        cumulative_movement_codes=5,
    ).decode("ascii")

    assert ",cx317_active,state,ABORTED," in payload
    assert ",cx317_active,fail_static,true," in payload
    assert ",cx317_active,confirmed_applied_code_known,true," in payload
    assert f",cx317_active,confirmed_applied_code,{0xA837}," in payload
    assert ",cx317_active,correction_count,1," in payload
    assert ",cx317_active,cumulative_movement_codes,5," in payload
    assert ",cx317_active,dac_epoch,2," in payload


def test_campaign18_status_fixture_publishes_exact_producer_frontier() -> None:
    policy_path = CX322_D9_D6_72H_PROGRAMME.policy_path
    frontier = (2400 * 16_000_000) % (1 << 32)
    payload = rehearsal._cx322_active_status_wire_fixture(
        generation=3,
        query_nonce="77",
        evidence_phase="evidence_clear",
        bundle={
            "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
            "firmware": {"build_identity": "a" * 64 + ":" + "b" * 64},
            "policy": {
                "path": str(policy_path),
                "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
            },
        },
        applied=False,
        checkpoint_passed=False,
        frontier_timestamp_ticks=frontier,
    )
    rows = [
        dict(zip(CONTRACT_FIELDS["health_v1"], row, strict=True))
        for row in csv.reader(payload.decode("ascii").splitlines())
    ]

    reducer = ActiveStatusLiveReducer()
    updates = [item for row in rows if (item := reducer.observe(row)) is not None]

    assert updates[-1]["state"] == "complete"
    assert updates[-1]["frontier_timestamp_ticks"] == frontier
    assert updates[-1]["frontier_status_domain"] == "rp2040_timer0"


def test_campaign18_multi_transaction_reporting_uses_observed_cardinality() -> None:
    labels = rehearsal._observational_transaction_result_labels(
        applications={1: {}, 2: {}},
        summary={},
        first_response_consumer_reason=(
            "first_phase_observation_recorded_and_tight_reacquired"
        ),
    )

    assert labels == {
        "response_class": "multiple_observational",
        "later_authority_release_reason": (
            "first_phase_observation_recorded_and_tight_reacquired"
        ),
    }


def test_campaign18_fixture_defers_a_zero_authority_consumer_after_requalification() -> None:
    policy_path = CX322_D9_D6_72H_PROGRAMME.policy_path
    bundle = {
        "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
        "firmware": {
            "build_identity": "a" * 64 + ":" + "b" * 64,
            "profile_id": CX322_D9_D6_72H_PROGRAMME.profile_id,
        },
        "policy": {
            "path": str(policy_path),
            "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        },
    }

    decisions, transactions, summary = (
        rehearsal._sustained_multi_transaction_fixture(bundle)
    )
    sequence = summary["first_post_recovery_consumer_decision_sequence"]
    consumer = next(
        row for row in decisions if int(row["decision_sequence"]) == sequence
    )

    assert sequence == int(decisions[-1]["decision_sequence"])
    assert consumer["requested_delta_codes"] == "0"
    assert consumer["request_sequence"] == "0"
    assert _response_dependent_consumer_propagation(
        transactions, decisions
    )["exact"] is True

    stale = dict(decisions[9])
    stale.update(
        {
            "decision_sequence": "9",
            "request_sequence": "0",
            "application_sequence": "0",
            "response_class": "unavailable",
            "actual_applied_code": "0",
            "actual_dac_epoch": "0",
            "downstream_epoch_exact": "false",
        }
    )
    mutated = [*decisions[:8], stale, *decisions[8:]]
    assert _response_dependent_consumer_propagation(
        transactions, mutated
    )["exact"] is False


def test_campaign18_exact_sidecars_round_trip_through_capture_splitter(
    tmp_path: Path,
) -> None:
    policy_path = CX322_D9_D6_72H_PROGRAMME.policy_path
    bundle = {
        "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
        "firmware": {
            "build_identity": "a" * 64 + ":" + "b" * 64,
            "profile_id": CX322_D9_D6_72H_PROGRAMME.profile_id,
        },
        "policy": {
            "path": str(policy_path),
            "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        },
    }
    decisions, transactions, _summary = (
        rehearsal._sustained_multi_transaction_fixture(bundle)
    )
    response_times = {
        int(row["request_sequence"]): int(row["decision_timestamp_s"])
        for row in decisions
        if row["authority_state"] == "AWAITING_RESPONSE"
    }
    at2 = [
        rehearsal._campaign18_exact_timing_sidecar_row(
            row,
            decision=False,
            timing_record_sequence=index,
            response_timestamp_s=response_times,
        )
        for index, row in enumerate(transactions, start=1)
    ]
    ah2 = [
        rehearsal._campaign18_exact_timing_sidecar_row(
            row,
            decision=True,
            timing_record_sequence=len(at2) + index,
            response_timestamp_s=response_times,
        )
        for index, row in enumerate(decisions, start=1)
    ]
    targets = {
        "active_transactions_v2": tmp_path / "active_transactions_v2.csv",
        "active_hybrid_decisions_v2": tmp_path
        / "active_hybrid_decisions_v2.csv",
    }
    with CsvRecordSplitter(targets) as splitter:
        for row, fields in (
            *((row, ACTIVE_TRANSACTION_V2_FIELDS) for row in at2),
            *((row, ACTIVE_HYBRID_DECISION_V2_FIELDS) for row in ah2),
        ):
            line = rehearsal._wire_rows([row], fields).decode().strip()
            assert splitter.process_line(line) in targets

    captured_at2 = list(
        csv.DictReader(targets["active_transactions_v2"].open(encoding="utf-8"))
    )
    captured_ah2 = list(
        csv.DictReader(
            targets["active_hybrid_decisions_v2"].open(encoding="utf-8")
        )
    )
    join = live_analyze.campaign18_exact_timing_sidecar_join(
        transactions=transactions,
        decisions=decisions,
        transaction_timings=captured_at2,
        decision_timings=captured_ah2,
    )
    assert join == {
        "exact": True,
        "AT2_rows": len(transactions),
        "AH2_rows": len(decisions),
        "mismatches": [],
        "coarse_seconds_used_as_ticks": False,
    }


def test_integrated_snapshot_overlap_latches_live_reducer_but_allows_later_abort_snapshot() -> None:
    first_generation = 41
    overlap = rehearsal._overlapping_active_status_generation_fixture(
        first_generation=first_generation
    )
    post_abort = rehearsal._post_abort_active_status_wire_fixture(
        generation=first_generation + 2,
        bundle={"programme_id": CX322_D9_D6_INTEGRATION_PROGRAMME.programme_id},
        applied_code=0xA837,
        dac_epoch=2,
        correction_count=1,
        cumulative_movement_codes=5,
    )
    rows = [
        dict(zip(CONTRACT_FIELDS["health_v1"], row, strict=True))
        for row in csv.reader((overlap + post_abort).decode("ascii").splitlines())
    ]

    reducer = ActiveStatusLiveReducer()
    updates = [item for row in rows if (item := reducer.observe(row)) is not None]
    assert updates[-1]["state"] == "invalid"
    assert "before the prior generation" in str(updates[-1]["reason"])

    snapshots, newest_started = complete_active_status_snapshots(rows)
    assert newest_started == first_generation + 2
    assert snapshots[-1]["snapshot_generation_complete"] == str(
        first_generation + 2
    )
    assert snapshots[-1]["state"] == "ABORTED"
    assert snapshots[-1]["fail_static"] == "true"


def test_rehearsal_manifest_is_strictly_non_authorizing_and_pty_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/pts/99",
    )

    observed = rehearsal.validate_rehearsal_run_manifest(path)

    assert observed["qualification_evidence"] is False
    assert observed["physical_actions_performed"] == 0
    assert observed["actionable"] is False
    assert observed["actuation_authorized"] is False
    assert "active_transactions_v2" not in observed["contracts"]
    assert "active_hybrid_decisions_v2" not in observed["contracts"]


def test_campaign18_rehearsal_manifest_requires_exact_timing_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    bundle["programme_id"] = CX322_D9_D6_72H_PROGRAMME.programme_id
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setattr(
        rehearsal, "validate_bundle", lambda path, programme: bundle
    )
    monkeypatch.setattr(
        rehearsal, "validate_proposal", lambda path, programme: proposal
    )
    run_dir = tmp_path / "campaign18-run"
    run_dir.mkdir()

    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/pts/99",
    )
    observed = rehearsal.validate_rehearsal_run_manifest(path)
    files = {entry["contract"]: entry for entry in observed["files"]}

    assert observed["contracts"]["active_transactions_v2"] == 2
    assert observed["contracts"]["active_hybrid_decisions_v2"] == 2
    assert files["active_transactions_v2"].get("optional") is None
    assert files["active_hybrid_decisions_v2"].get("optional") is None
    assert {
        "name": "rp2040_timer0_extended",
        "nominal_hz": 16_000_000,
    } in observed["domains"]


def test_rehearsal_manifest_rejects_non_pty_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/cu.usbmodem-real",
    )

    with pytest.raises(ValueError, match="no-I/O boundary"):
        rehearsal.validate_rehearsal_run_manifest(path)


def test_rehearsal_manifest_accepts_macos_pty_slave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/ttys001",
    )

    observed = rehearsal.validate_rehearsal_run_manifest(path)

    assert observed["host"]["serial_device"] == "/dev/ttys001"


def test_integrated_rehearsal_manifest_can_select_first_response_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    bundle["programme_id"] = CX322_D9_D6_INTEGRATION_PROGRAMME.programme_id
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setattr(
        rehearsal, "validate_bundle", lambda path, programme: bundle
    )
    monkeypatch.setattr(
        rehearsal, "validate_proposal", lambda path, programme: proposal
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/pts/99",
        endpoint_mode="first_response",
    )

    observed = rehearsal.validate_rehearsal_run_manifest(path)
    assert observed["qualification_evidence"] is False
    assert observed["rehearsal_endpoint_mode"] == "first_response"


def test_cx321_rehearsal_manifest_declares_extended_plant_sign_time_domain(
    tmp_path: Path,
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    bundle.update(
        {
            "programme_id": "CX321_BOUNDED_ACTIVE_HYBRID_SUCCESSOR_V2",
            "run_identity": "cx321_active_hybrid:3210001",
            "programme_policy": {"sha256": "1" * 64},
            "identification": {"bindings": {}},
        }
    )
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    run_dir = tmp_path / "cx321_run"
    run_dir.mkdir()

    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/ttys001",
    )
    observed = json.loads(path.read_text(encoding="utf-8"))

    assert {
        "name": "rp2040_timer0_extended",
        "nominal_hz": 16_000_000,
    } in observed["domains"]
    assert observed["contracts"]["plant_sign_qualification_v1"] == 1


def test_activation_and_rehearsal_require_the_same_complete_coverage() -> None:
    assert set(rehearsal.REHEARSAL_COVERAGE) == set(
        activation.REHEARSAL_COVERAGE
    )


def test_obstruction_requires_the_exact_final_status_generation(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    path = reports / "cx317_active_status_live_state_v1.json"
    path.write_text(
        json.dumps(
            {
                "state": "in_progress",
                "generation": 7,
                "newest_started_generation": 7,
                "newest_complete_generation": 6,
            }
        ),
        encoding="utf-8",
    )
    assert not rehearsal._active_status_generation_complete(tmp_path, 7)

    path.write_text(
        json.dumps(
            {
                "state": "complete",
                "generation": 7,
                "newest_started_generation": 7,
                "newest_complete_generation": 7,
            }
        ),
        encoding="utf-8",
    )
    assert rehearsal._active_status_generation_complete(tmp_path, 7)
    assert not rehearsal._active_status_generation_complete(tmp_path, 6)


def test_wire_fixture_uses_frozen_supervisor_identities() -> None:
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    bundle = {
        "firmware": {"build_identity": "a" * 64 + ":" + "b" * 64},
        "policy": {
            "path": str(policy_path),
            "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        },
    }

    values = rehearsal._active_hybrid_wire_fixture(bundle).decode().strip().split(",")
    row = dict(zip(ACTIVE_HYBRID_DECISION_V1_FIELDS, values, strict=True))

    assert len(values) == 56
    assert row["frequency_estimator_sha256"] == policy["bindings"][
        "frequency_estimator"
    ]["sha256"]
    assert row["phase_estimator_sha256"] == policy["bindings"]["phase_estimator"][
        "sha256"
    ]
    assert row["active_policy_sha256"] == bundle["policy"]["policy_sha256"]
    assert row["response_policy_sha256"] == policy["bindings"]["response_policy"][
        "sha256"
    ]
    assert row["actionable"] == "false"


def test_cx321_first_natural_fixture_consumes_identification_handoff() -> None:
    root = Path(__file__).resolve().parents[1]
    natural_policy = (
        root
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    programme_policy = (
        root
        / "profiles/discipline/cx321_bounded_active_hybrid_plant_sign_v2.json"
    )
    bundle = {
        "programme_id": "CX321_BOUNDED_ACTIVE_HYBRID_SUCCESSOR_V2",
        "firmware": {"build_identity": "a" * 64 + ":" + "b" * 64},
        "policy": {"path": str(natural_policy)},
        "programme_policy": {
            "path": str(programme_policy),
            "sha256": sha256(programme_policy.read_bytes()).hexdigest(),
        },
    }

    ahy_rows, transactions, summary = (
        rehearsal._cx321_first_natural_transaction_fixture(bundle)
    )
    ahy = ahy_rows[0]

    assert ahy["current_applied_code"] == str(0xA827)
    assert ahy["dac_epoch"] == "2"
    assert ahy["correction_count_before"] == "1"
    assert ahy["cumulative_movement_before_codes"] == "21"
    assert ahy["request_sequence"] == "2"
    assert summary["plant_sign_handoff_first_consumer"] is True
    assert summary["phase_materially_influenced"] is True
    assert [row["event"] for row in transactions] == [
        "request_created",
        "core0_accepted",
        "application",
        "response",
    ]
    assert {row["request_sequence"] for row in transactions} == {"2"}
    assert transactions[-1]["correction_count"] == "2"
    assert ahy_rows[1]["authority_state"] == "AWAITING_RESPONSE"
    assert ahy_rows[1]["request_sequence"] == "2"


def test_obstruction_queues_abort_before_resuming_the_supervisor() -> None:
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")
    supervisor_stop = source.index(
        "os.kill(supervisor.pid, signal.SIGSTOP)"
    )
    capture_stop = source.index(
        "os.kill(capture.pid, signal.SIGSTOP)", supervisor_stop
    )
    saturate = source.index("for _ in range(100_000):", capture_stop)
    abort = source.index("send_abort(host_abort)", saturate)
    supervisor_continue = source.index(
        "os.kill(supervisor.pid, signal.SIGCONT)", abort
    )
    capture_continue = source.index(
        "os.kill(capture.pid, signal.SIGCONT)", supervisor_continue
    )

    assert (
        supervisor_stop
        < capture_stop
        < saturate
        < abort
        < supervisor_continue
        < capture_continue
    )


def test_integrated_overlap_precedes_obstruction_and_requires_retained_fallback() -> None:
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")
    overlap = source.index("_overlapping_active_status_generation_fixture(")
    invalid = source.index(
        '"integrated overlapping active-status generations latch invalid"', overlap
    )
    capture_stop = source.index("os.kill(capture.pid, signal.SIGSTOP)", invalid)
    abort = source.index("send_abort(host_abort)", capture_stop)
    delivery = source.index(
        "_wait_for_terminal_abort_delivery(run_dir, terminal_state[\"terminal\"])",
        abort,
    )
    retained = source.index("_retained_abort_consumption_health(run_dir)", delivery)
    rotation = source.index("prepare_transition(", retained)

    assert overlap < invalid < capture_stop < abort < delivery < retained < rotation


def test_integrated_wire_fixture_captures_d14_d8_d9_d6_and_localizes_d6_fault(
    tmp_path: Path,
) -> None:
    csv_dir = tmp_path / "csv"
    targets = {
        "health_v1": csv_dir / "health.csv",
        "pps_snapshots_v1": csv_dir / "pps_snapshots.csv",
        "count_observations_v1": csv_dir / "count_observations.csv",
        "forwarded_monitor_snapshots_v1": (
            csv_dir / "forwarded_monitor_snapshots.csv"
        ),
    }
    with CsvRecordSplitter(targets) as splitter:
        for line in rehearsal._forwarded_integration_wire_fixture().decode(
            "ascii"
        ).splitlines():
            assert splitter.process_line(line) is not None

    summary = rehearsal._forwarded_integration_capture_summary(tmp_path)

    assert summary == {
        "d9_configuration_and_readback_exact": True,
        "d9_evidence_missing": [],
        "d9_evidence_mismatches": [],
        "d14_snapshot_rows_captured": 3,
        "d8_count_rows_captured": 3,
        "d6_monitor_snapshot_rows_captured": 3,
        "d6_local_fault_observed": True,
        "d6_fault_has_control_authority": False,
        "gnss_bootstrap_in_progress_then_complete_exact": True,
        "d9_waveform_or_load_claim": False,
    }


def test_integrated_first_response_consumer_binds_application_and_epoch() -> None:
    policy_path = CX322_D9_D6_INTEGRATION_PROGRAMME.policy_path
    bundle = {
        "programme_id": CX322_D9_D6_INTEGRATION_PROGRAMME.programme_id,
        "firmware": {"build_identity": "a" * 64 + ":" + "b" * 64},
        "policy": {
            "path": str(policy_path),
            "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        },
    }

    ahy, transactions, summary = (
        rehearsal._cx322_first_observational_transaction_fixture(bundle)
    )
    response = transactions[-1]
    consumer = ahy[-1]

    assert response["event"] == "response"
    assert consumer["reason"] == summary["first_response_consumer_reason"]
    assert consumer["request_sequence"] == response["request_sequence"]
    assert consumer["application_sequence"] == response["application_sequence"]
    assert consumer["actual_applied_code"] == response["applied_code"]
    assert consumer["actual_dac_epoch"] == response["dac_epoch"]
    assert consumer["response_class"] == response["response_class"]
    assert consumer["downstream_epoch_exact"] == "true"


def test_accelerated_prewrite_boundary_uses_physical_evidence_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    policy_sha256 = sha256(policy_path.read_bytes()).hexdigest()
    bundle["policy"] = {
        **_binding(policy_path),
        "policy_sha256": policy_sha256,
    }
    bundle["firmware"] = {
        **bundle["firmware"],
        "source_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
    }
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)

    result = rehearsal._exercise_prewrite_qualification_boundary(
        output_dir=tmp_path / "boundary",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )

    assert result == {
        "startup_inhibit_s": 600,
        "observed_historical_qualification_s": 612,
        "qualification_deadline_s": 660,
        "waits_while_unqualified_at_30s": True,
        "ready_at_observed_612s": True,
        "unarmed_observation_required_s": 0,
        "unarmed_setup_held_before_boundary": True,
        "unarmed_observation_complete_at_boundary": True,
        "atomic_handoff_hybrid_state": "SETUP_PENDING",
        "pre_setup_dac_provenance_exact": True,
        "pre_setup_physical_applied_code": "unknown",
        "pre_setup_firmware_dac_epoch": 0,
        "first_post_setup_consumer_passed": True,
        "missing_authority_at_660s_is_terminal": True,
        "setup_commands_issued": 0,
        "physical_actions_performed": 0,
    }


def test_accelerated_qualified_boundaries_use_device_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    bundle["policy"] = {
        **_binding(policy_path),
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)

    result = rehearsal._exercise_qualified_device_time_boundaries(
        output_dir=tmp_path / "qualified_time",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )

    assert result == {
        "time_domain": "rp2040_timer0",
        "capture_session": 1,
        "qualified_origin_subsecond_ticks": 13_602_864,
        "fractional_origin_deferred_until_lower_bound": True,
        "exact_fractional_origin_established": True,
        "correction_admission_close_elapsed_s": 41_400,
        "qualified_endpoint_elapsed_s": 43_200,
        "admission_open_at_floor_before_exact_boundary": True,
        "admission_closed_at_first_conservative_uptime": True,
        "forward_host_utc_step_did_not_close_early": True,
        "backward_host_utc_step_did_not_delay_endpoint": True,
        "physical_actions_performed": 0,
    }
