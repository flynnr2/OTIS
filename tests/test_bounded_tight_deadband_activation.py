from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import bounded_tight_deadband_bundle
from host.otis_tools import bounded_tight_deadband_activation
from host.otis_tools import bounded_tight_deadband_live_analyze
from host.otis_tools import bounded_tight_deadband_run
from host.otis_tools.bounded_tight_deadband_bundle import BUNDLE_ID, TOOL_ID as PROPOSAL_TOOL
from host.otis_tools.bounded_tight_deadband_outcome_contract import canonical_sha256
from host.otis_tools.bounded_tight_deadband_leg import UPPER
from host.otis_tools.bounded_tight_deadband_activation import (
    ACTIVATION_ID,
    OPERATIONAL_REHEARSAL_SEAL,
    TOOL_ID,
    create_activation,
    main,
    validate_frozen_activation,
    validate_operational_rehearsal,
)
from host.otis_tools.bounded_tight_deadband_prewrite_contract import RUNTIME_CONTRACT_ID
from host.otis_tools.programme_status import ProgrammeExecutionBlocked


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _proposal(path: Path) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "tool": PROPOSAL_TOOL,
        "bundle_id": BUNDLE_ID,
        "status": "proposed_not_authorized",
        "authority": {"effective": False},
    }
    value = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _write(path, value)
    return value


def test_frozen_activation_can_be_revalidated_from_retained_proposal(
    tmp_path: Path,
) -> None:
    proposal_path = tmp_path / "proposal.json"
    proposal = _proposal(proposal_path)
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "activation_id": ACTIVATION_ID,
        "programme_id": "cx319_stabilized_tight_deadband",
        "operation": "g2_live_leg",
        "gate": "G2",
        "leg": "A",
        "status": "effective_exact_leg_authority",
        "proposal": {
            "path": str(proposal_path),
            "sha256": sha256(proposal_path.read_bytes()).hexdigest(),
            "bundle_sha256": proposal["bundle_sha256"],
        },
        "operational_rehearsal": {"path": "/retained/rehearsal.json"},
        "authority": {
            "effective": True,
            "firmware_flash": False,
            "fresh_host_attach_maximum_uptime_s": 120,
            "gnss_pps_qualification_deadline_s": 660,
            "ordinary_telemetry_attach_baseline_stable_observations": 2,
            "post_attach_ordinary_telemetry_increment_allowed": False,
            "evidence_capture_preview_partition_and_control_gates_absolute": True,
            "setup_code": 0xA808,
            "setup_write_limit": 1,
            "automatic_correction_limit": 4,
            "maximum_automatic_step_codes": 21,
            "maximum_cumulative_codes": 84,
            "minimum_code": 0xA800,
            "maximum_code": 0xAB00,
            "phase_or_hybrid_actionable": False,
            "automatic_retry": False,
            "automatic_restore": False,
        },
    }
    activation = {
        **unsigned,
        "activation_sha256": canonical_sha256(unsigned),
    }
    activation_path = tmp_path / "activation.json"
    _write(activation_path, activation)

    observed, observed_proposal = validate_frozen_activation(activation_path)

    assert observed == activation
    assert observed_proposal == proposal


def test_activation_is_blocked_before_any_input_or_hardware_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise ProgrammeExecutionBlocked("operation 'g2_live_leg' is blocked")

    monkeypatch.setattr(
        bounded_tight_deadband_activation, "require_programme_operation_allowed", blocked
    )
    with pytest.raises(ProgrammeExecutionBlocked, match="g2_live_leg"):
        create_activation(
            proposal_path=tmp_path / "missing-proposal.json",
            operational_rehearsal_path=tmp_path / "missing-rehearsal.json",
            serial_device="/dev/not-opened",
            operator_instruction_ref="not-authorized",
            output_path=tmp_path / "must-not-exist.json",
        )

    assert not (tmp_path / "must-not-exist.json").exists()


def test_activation_cli_reports_the_block_without_a_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise ProgrammeExecutionBlocked("operation 'g2_live_leg' is blocked")

    monkeypatch.setattr(
        bounded_tight_deadband_activation, "require_programme_operation_allowed", blocked
    )
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "activate",
                "--proposal",
                str(tmp_path / "missing-proposal.json"),
                "--operational-rehearsal",
                str(tmp_path / "missing-rehearsal.json"),
                "--serial-device",
                "/dev/not-opened",
                "--operator-instruction-ref",
                "not-authorized",
                "--output",
                str(tmp_path / "must-not-exist.json"),
            ]
        )

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "g2_live_leg" in error
    assert "Traceback" not in error


def test_activation_consumer_accepts_the_exact_accelerated_rehearsal_seal(
    tmp_path: Path,
) -> None:
    proposal = {"gate": "G2", "leg": "A", "bundle_sha256": "a" * 64}
    analysis_path = tmp_path / "analysis.json"
    _write(analysis_path, {"status": "passed"})
    unsigned_seal: dict[str, object] = {
        "seal_type": OPERATIONAL_REHEARSAL_SEAL,
        "status": "passed",
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "analysis_file_sha256": sha256(analysis_path.read_bytes()).hexdigest(),
    }
    seal = {
        **unsigned_seal,
        "seal_sha256": canonical_sha256(unsigned_seal),
    }
    seal_path = tmp_path / "seal.json"
    _write(seal_path, seal)
    result_path = tmp_path / "result.json"
    _write(
        result_path,
        {
            "schema_version": 1,
            "tool": "cx319_g2_accelerated_operational_rehearsal_v1",
            "status": "passed",
            "proposal_bundle_sha256": proposal["bundle_sha256"],
            "hardware_operations": {
                "serial_opens": 0,
                "firmware_flashes": 0,
                "dac_writes": 0,
                "control_arms": 0,
            },
            "seal": str(seal_path),
            "analysis": str(analysis_path),
            "artifact_content_sha256": "b" * 64,
        },
    )

    observed = validate_operational_rehearsal(result_path, proposal)

    assert observed["seal_sha256"] == seal["seal_sha256"]


def test_authorized_activation_creates_an_exact_live_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_sha = sha256(bounded_tight_deadband_bundle.POLICY_PATH.read_bytes()).hexdigest()
    firmware = {
        "source_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "profile_id": "cx319_tight_lower",
        "fqbn": "rp2040:test",
        "build_manifest": {"sha256": "c" * 64},
        "uf2": {"sha256": "d" * 64},
    }
    policy = {
        "policy_id": "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
        "sha256": policy_sha,
    }
    fake_g1 = {
        "qualification_sequence_gate": "Q3",
        "run_id": "g1-pass",
        "run_dir": "/retained/g1-pass",
        "run_manifest_sha256": "1" * 64,
        "analysis_sha256": "2" * 64,
        "analysis_file_sha256": "3" * 64,
        "seal_sha256": "4" * 64,
        "seal_file_sha256": "5" * 64,
        "evidence_content_sha256": "6" * 64,
        "bundle_sha256": "7" * 64,
        "sequence_prerequisites": {"q1": {}, "q2": {}},
        "firmware": firmware,
        "policy": policy,
    }
    monkeypatch.setattr(
        bounded_tight_deadband_bundle, "_git_identity", lambda: ("8" * 40, "clean")
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle, "validate_no_write_qualification_pass", lambda path: fake_g1
    )
    monkeypatch.setattr(
        bounded_tight_deadband_bundle,
        "_firmware_build_provenance",
        lambda observed: {
            "configuration": {"sha256": observed["configuration_sha256"]},
            "target": {"fqbn": observed["fqbn"]},
            "invocation": {"arduino_cli_version": "test"},
            "toolchain": {
                "compiler_identity": "test",
                "installed_sha256": "0" * 64,
            },
        },
    )
    proposal_path = tmp_path / "proposal.json"
    proposal = bounded_tight_deadband_bundle.create_proposal(
        no_write_run_dir=tmp_path / "g1", output_path=proposal_path
    )
    rehearsal = {
        "path": str(tmp_path / "operational.json"),
        "sha256": "9" * 64,
        "artifact_content_sha256": "a" * 64,
        "seal_path": str(tmp_path / "seal.json"),
        "seal_sha256": "b" * 64,
        "seal_file_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        bounded_tight_deadband_activation, "require_programme_operation_allowed", lambda *args: {}
    )
    monkeypatch.setattr(bounded_tight_deadband_activation, "_git_clean", lambda: True)
    monkeypatch.setattr(
        bounded_tight_deadband_activation,
        "validate_operational_rehearsal",
        lambda path, observed: rehearsal,
    )
    activation_path = tmp_path / "activation.json"
    activation = bounded_tight_deadband_activation.create_activation(
        proposal_path=proposal_path,
        operational_rehearsal_path=tmp_path / "operational.json",
        serial_device="/dev/cu.test",
        operator_instruction_ref="test-authority",
        output_path=activation_path,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_proposal = run_dir / bounded_tight_deadband_activation.RUN_PROPOSAL_PATH
    run_activation = run_dir / bounded_tight_deadband_activation.RUN_ACTIVATION_PATH
    run_proposal.write_bytes(proposal_path.read_bytes())
    run_activation.write_bytes(activation_path.read_bytes())

    manifest = bounded_tight_deadband_activation.create_run_manifest(
        activation_path=run_activation,
        proposal_path=run_proposal,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
    )

    assert manifest["stage"] == bounded_tight_deadband_activation.LIVE_STAGE
    assert manifest["firmware"] == proposal["firmware"]
    assert manifest["g1_pass"]["evidence_content_sha256"] == "6" * 64
    assert manifest["cx319"]["planned_live_stimulus"]["code"] == 0xA808
    assert manifest["cx319"]["automatic_frequency_control"] == {
        "authorized": True,
        "required_direction": "positive",
        "maximum_corrections": 4,
        "maximum_step_codes": 21,
        "maximum_cumulative_movement_codes": 84,
        "minimum_applied_correction_cadence_s": 1800,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "settling_exclusion_s": 900,
        "fresh_support_after_settling_s": 600,
        "one_request_outstanding": True,
        "automatic_retry": False,
        "automatic_restore": False,
    }
    assert bounded_tight_deadband_activation.validate_frozen_run_manifest(
        run_dir / "run_manifest.json"
    ) == manifest


def test_physical_runner_flashes_only_profiles_whose_exact_leg_requires_it() -> None:
    source = Path("host/otis_tools/bounded_tight_deadband_run.py").read_text(encoding="utf-8")

    assert 'f"exact_cx319_{selected.gate.lower()}_firmware_flash"' in source
    assert "if not selected.firmware_flash" in source
    assert '"firmware_flashes": int(selected.firmware_flash)' in source
    assert source.index(
        "_wait_for_terminal_abort_delivery(run_dir, terminal)"
    ) < source.index("capture_exit = _graceful_capture_stop(capture)")


def test_upper_flash_is_exactly_one_upload_and_binds_reenumerated_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    board = {"serial_number": "503533748A919118", "address": "/dev/cu.before"}
    board_after = {**board, "address": "/dev/cu.after"}
    monkeypatch.setattr(bounded_tight_deadband_run.subprocess, "run", run)
    monkeypatch.setattr(
        bounded_tight_deadband_run,
        "_locate_board_by_serial",
        lambda *args, **kwargs: ("/dev/cu.after", board_after),
    )
    (tmp_path / "reports").mkdir()
    proposal = {
        "bundle_sha256": "a" * 64,
        "firmware": {
            "fqbn": "rp2040:test",
            "profile_id": UPPER.profile_id,
            "build_manifest": {"sha256": "b" * 64},
            "uf2": {"path": "/tmp/upper.uf2", "sha256": "c" * 64},
        },
    }
    activation = {"device": {"expected_board_serial": "503533748A919118"}}

    device, observed, record = bounded_tight_deadband_run._flash_exact_upper(
        run_dir=tmp_path,
        selected=UPPER,
        proposal=proposal,
        activation=activation,
        device="/dev/cu.before",
        board_before=board,
        arduino_cli="arduino-cli",
    )

    assert len(calls) == 1
    assert calls[0][1] == "upload"
    assert device == "/dev/cu.after"
    assert observed == board_after
    assert record["firmware_flash_count"] == 1
    assert record["status"] == "passed"
    assert record["record_sha256"] == canonical_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def test_post_snapshot_finalization_failure_registers_without_mutating_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    snapshot = run_dir / bounded_tight_deadband_run.EVIDENCE_MANIFEST
    snapshot.write_text("sealed-before-analyzer\n", encoding="utf-8")
    registered: dict[str, object] = {}

    def register(**kwargs: object) -> dict[str, str]:
        registered.update(kwargs)
        return {"content_sha256": "f" * 64}

    monkeypatch.setattr(bounded_tight_deadband_run, "register_package", register)
    result = bounded_tight_deadband_run._retain_finalization_failure(
        run_dir=run_dir,
        activation={
            "gate": "G2",
            "leg": "A",
            "activation_sha256": "a" * 64,
            "proposal": {"bundle_sha256": "b" * 64},
        },
        proposal={
            "source_revision": "b" * 40,
            "firmware": {"build_manifest": {"sha256": "c" * 64}},
            "leg_spec": {"profile_id": "cx319_tight_lower"},
        },
        evidence_index_path=tmp_path / "index.jsonl",
        error=RuntimeError("analyzer mismatch"),
    )

    assert result["content_sha256"] == "f" * 64
    assert snapshot.read_text(encoding="utf-8") == "sealed-before-analyzer\n"
    assert not (run_dir / bounded_tight_deadband_run.ORCHESTRATION_FAILURE).exists()
    assert registered["attempt_classification"] == "interrupted_campaign"
    assert "finalization failed" in str(registered["result_or_failure_reason"])


def test_prewrite_failure_uses_the_existing_interrupted_campaign_index_class(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "reports").mkdir(parents=True)

    record = bounded_tight_deadband_run._retain_failure(
        run_dir=run_dir,
        activation={
            "gate": "G2",
            "leg": "A",
            "activation_sha256": "a" * 64,
            "proposal": {"bundle_sha256": "b" * 64},
        },
        evidence_index_path=tmp_path / "external" / "index.json",
        error=RuntimeError("prewrite partition fault"),
    )

    assert record["attempt_classification"] == "interrupted_campaign"
    failure = json.loads(
        (run_dir / bounded_tight_deadband_run.ORCHESTRATION_FAILURE).read_text(
            encoding="utf-8"
        )
    )
    assert failure["attempt_classification"] == "interrupted_campaign"


def test_missing_abort_reader_does_not_mask_primary_orchestration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emergency_fifo = tmp_path / "emergency_abort.fifo"
    emergency_fifo.touch()
    capture = SimpleNamespace(poll=lambda: None)

    def no_reader(*args: object, **kwargs: object) -> None:
        raise SystemExit("no capture_device command reader is active")

    monkeypatch.setattr(
        bounded_tight_deadband_run,
        "send_timestamped_command_to_fifo",
        no_reader,
    )

    bounded_tight_deadband_run._best_effort_emergency_abort(
        emergency_fifo, capture
    )


def test_runner_waits_for_terminal_abort_delivery_before_capture_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "reports" / "capture_device_state.json"
    state.parent.mkdir()
    _write(
        state,
        {
            "capture_active": True,
            "emergency_abort_latched": True,
            "emergency_aborts_sent": 1,
        },
    )
    observed: dict[str, object] = {}

    def wait_until(predicate, timeout_s, description):  # type: ignore[no-untyped-def]
        observed.update(
            predicate=predicate(), timeout_s=timeout_s, description=description
        )

    monkeypatch.setattr(bounded_tight_deadband_run, "_wait_until", wait_until)

    bounded_tight_deadband_run._wait_for_terminal_abort_delivery(
        tmp_path,
        {"result": "aborted", "reason": "finite_endpoint"},
    )

    assert observed == {
        "predicate": True,
        "timeout_s": bounded_tight_deadband_run.TERMINAL_ABORT_DELIVERY_TIMEOUT_S,
        "description": "terminal independent abort delivery before capture close",
    }


def test_live_outcome_classifies_terminal_abort_race_separately() -> None:
    assert bounded_tight_deadband_live_analyze._classify_outcome(
        common_pass=False,
        pass_checks_exact=False,
        terminal_bounded_nonpass=True,
        terminal_abort_delivery_escape=True,
    ) == (
        "failed",
        "terminal_abort_delivery_race_after_scientific_bounded_nonpass",
    )


def test_live_outcome_preserves_clean_bounded_nonpass_and_pass() -> None:
    assert bounded_tight_deadband_live_analyze._classify_outcome(
        common_pass=True,
        pass_checks_exact=False,
        terminal_bounded_nonpass=True,
        terminal_abort_delivery_escape=False,
    ) == (
        "bounded_nonpass",
        "finite_endpoint_without_required_direction_transaction",
    )
    assert bounded_tight_deadband_live_analyze._classify_outcome(
        common_pass=True,
        pass_checks_exact=True,
        terminal_bounded_nonpass=False,
        terminal_abort_delivery_escape=False,
    ) == ("passed", "none")


def test_live_analyzer_wires_a_complete_physical_evidence_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "reports").mkdir()
    (run_dir / "csv").mkdir()
    for relative, value in {
        "run_manifest.json": {},
        "reports/capture_device_state.json": {},
        "reports/capture_segment_closure_v1.json": {},
            "reports/cx317_active_supervisor_state.json": {
            "terminal": {
                "result": "healthy_stop",
                "reason": "required_direction_and_two_estimate_tight_entry",
            },
                "arm_pending": False,
                    "telemetry_drop_baseline": 3,
                    "telemetry_drop_baseline_status_seq": 2,
                    "host_attach_uptime_s": 30,
                    "host_attach_uptime_status_seq": 1,
                    "host_attach_query_nonce": 99,
                    "host_attach_snapshot_generation": 7,
                "prewrite_contract_ready_utc": "2026-08-11T17:00:00Z",
                "setup_confirmed_utc": "2026-08-11T17:00:01Z",
                "latest_prewrite_readiness": {
                    "contract_id": RUNTIME_CONTRACT_ID,
                    "ready": True,
                    "missing": [],
                    "mismatches": [],
                },
            },
        "reports/cx317_active_supervisor_events.jsonl": {},
        "reports/setup_authority_input_v1.json": {},
        "evidence_manifest.json": {"run_state": "complete"},
    }.items():
        _write(run_dir / relative, value)
    (run_dir / "raw/serial.log").write_text("# retained\n", encoding="utf-8")
    (run_dir / "csv/association_loss_decisions_v1.csv").write_text(
        "decision_sequence\n0\n", encoding="utf-8"
    )
    (run_dir / "COMPLETE").write_text("complete\n", encoding="utf-8")

    manifest_value = {
        "stage": bounded_tight_deadband_activation.LIVE_STAGE,
        "cx319": {"gate": "G2", "leg": "A"},
        "contracts": {"association_loss_decisions_v1": 1},
        "policy": {
            "sha256": "a" * 64,
            "policy_id": "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
        },
        "firmware": {
            "source_sha256": "b" * 64,
            "configuration_sha256": "c" * 64,
            "build_manifest": {"sha256": "d" * 64},
            "uf2": {"sha256": "e" * 64},
        },
        "proposal": {"bundle_sha256": "f" * 64},
        "activation": {"activation_sha256": "1" * 64},
        "g1_pass": {"evidence_content_sha256": "2" * 64},
    }
    loaded = SimpleNamespace(
        known_channels=set(),
        known_domains=set(),
        files=[
            {
                "path": "csv/association_loss_decisions_v1.csv",
                "contract": "association_loss_decisions_v1",
            }
        ],
        root=run_dir,
    )
    manual = {"event": "manual_start", "dac_epoch": "1"}
    application = {
        "event": "application",
        "request_sequence": "1",
        "requested_delta_codes": "21",
        "requested_code": str(0xA81D),
        "applied_code": str(0xA81D),
        "application_timestamp_s": "4202",
        "dac_epoch": "2",
    }
    response = {
        "event": "response",
        "request_sequence": "1",
        "response_class": "healthy_detected",
        "dac_epoch": "2",
    }
    active = [manual, application, response]
    rows = {
        "active_transactions_v1.csv": active,
        "dac_steps.csv": [
            {
                "event": "manual_apply",
                "dac_code_requested": str(0xA808),
                "dac_code_applied": str(0xA808),
                "dac_code_clamped": "0",
                "flags": "0",
            },
            {
                "event": "active_apply",
                "dac_code_requested": str(0xA81D),
                "dac_code_applied": str(0xA81D),
                "dac_code_clamped": "0",
                "flags": "0",
            },
        ],
        "control_previews_v1.csv": [{"control_seq": "0"}],
        "relative_phase_observations_v1.csv": [
            {"observation_sequence": "0", "dac_epoch": "2"}
        ],
        "phase_estimator_outputs_v1.csv": [{"observation_sequence": "0"}],
        "hybrid_preview_decisions_v1.csv": [
            {"preview_sequence": "0", "dac_epoch": "2"}
        ],
        "tight_deadband_decisions_v1.csv": [
            {
                "decision_sequence": "0",
                "dac_epoch": "2",
                "state_after": "OUTSIDE",
                "transition": "false",
            },
            {
                "decision_sequence": "1",
                "dac_epoch": "2",
                "state_after": "TIGHT_INSIDE",
                "frequency_controller_eligible": "false",
                "transition": "true",
            },
        ],
        "environment.csv": [{"source": "sht4x"}, {"source": "bmp280"}],
    }
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "fail_static"): "false",
    }

    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "validate_frozen_run_manifest",
        lambda path: manifest_value,
    )
    monkeypatch.setattr(bounded_tight_deadband_live_analyze, "load_manifest", lambda path: loaded)
    validation_contexts = []

    def validate_csv_with_context(path, context):  # type: ignore[no-untyped-def]
        validation_contexts.append(context)
        return SimpleNamespace(ok=True, row_count=0, errors=[])

    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "validate_csv",
        validate_csv_with_context,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_read_csv",
        lambda path: rows.get(Path(path).name, []),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze, "validate_transaction_history", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_response_replay",
        lambda *args: (True, [{"exact": True}]),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_measurement_replay",
        lambda *args: (True, {"exact": True}, {}),
    )
    monkeypatch.setattr(bounded_tight_deadband_live_analyze, "_host_markers", lambda path: [])
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_capsules_exact",
        lambda *args: (True, {}),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "replay_tight_deadband",
        lambda *args, **kwargs: SimpleNamespace(
            exact=True, as_dict=lambda: {"exact": True}
        ),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "healthy_required_direction_applications",
        lambda *args: [application],
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_controller_replay",
        lambda *args, **kwargs: (True, {"exact": True}),
    )
    monkeypatch.setattr(bounded_tight_deadband_live_analyze, "_authority_false", lambda path: True)
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "latest_complete_health",
        lambda path, **kwargs: health,
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "evaluate_health_integrity",
        lambda value, **kwargs: SimpleNamespace(
            clean=True, missing=[], mismatches=[]
        ),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "evaluate_telemetry_drop_history",
        lambda *args, **kwargs: {"exact": True},
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_nonce_bound_attach_history",
        lambda *args, **kwargs: {"exact": True},
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "replay_setup_authority_input",
        lambda *args, **kwargs: SimpleNamespace(
            exact=True,
            errors=(),
            readiness=SimpleNamespace(contract_id=RUNTIME_CONTRACT_ID),
            request={
                "authorization_sequence": 1,
                "status_generation": 7,
                "query_nonce": 99,
            },
        ),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_setup_phase_history",
        lambda *args, **kwargs: {"exact": True},
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "validate_evidence_snapshot",
        lambda *args: ([], []),
    )
    monkeypatch.setattr(
        bounded_tight_deadband_live_analyze,
        "_capture_closure",
        lambda *args, **kwargs: {"ok": True, "mode": "physical_serial_close"},
    )
    monkeypatch.setattr(bounded_tight_deadband_live_analyze, "_commands_exact", lambda *args, **kwargs: True)

    output, result = bounded_tight_deadband_live_analyze.analyze(run_dir)

    assert output.is_file()
    assert result["status"] == "passed"
    assert all(result["checks"].values())
    assert result["hardware_operations"] == {
        "serial_opens": 1,
        "firmware_flashes": 0,
        "dac_writes": 2,
        "control_arms": 0,
    }
    assert validation_contexts
    assert all(
        context.tight_deadband_policy_sha256 == manifest_value["policy"]["sha256"]
        for context in validation_contexts
    )
