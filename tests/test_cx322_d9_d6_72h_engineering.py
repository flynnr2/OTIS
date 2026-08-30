from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import cx322_d9_d6_72h_engineering as programme
from host.otis_tools.active_control_supervisor import (
    RP2040_TIMER0_TICKS_PER_SECOND,
)
from host.otis_tools.active_hybrid_live_supervisor import (
    FORWARDED_MONITOR_OBSERVABILITY_KEYS,
    FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH,
)
from host.otis_tools.contracts import CONTRACT_FIELDS, CONTRACT_RECORD_TYPES
from host.otis_tools.time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS


ROOT = Path(__file__).resolve().parents[1]


def _build_manifest(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    matrix = json.loads(
        (ROOT / "firmware/arduino/firmware_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    base = next(
        item
        for item in matrix["profiles"]
        if item["id"] == "cx322_d9_d6_integration_engineering"
    )
    defines = {
        **base["defines"],
        "OTIS_CX317_ACTIVE_CAMPAIGN": (
            "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID"
        ),
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "144u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "3024u",
        "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS": "144u",
        "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES": "3024u",
    }
    path = tmp_path / "build_manifest.json"
    path.write_text(
        json.dumps(
            {
                "provenance": {
                    "configuration": {
                        "profile_id": "cx322_d9_d6_72h_sustained_engineering",
                        "defines": defines,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _frequency_only_predecessor_product(
    tmp_path: Path, *, status: str = "passed"
) -> Path:
    reports = tmp_path / "frequency-only-predecessor" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    source_content_sha256 = "1" * 64
    analysis_path = reports / Path(
        programme.FREQUENCY_ONLY_PREDECESSOR_ANALYSIS
    ).name
    analysis_path.write_text(
        json.dumps({"terminal": programme.FREQUENCY_ONLY_PREDECESSOR_TERMINAL}),
        encoding="utf-8",
    )
    analysis_file_sha256 = sha256(analysis_path.read_bytes()).hexdigest()

    supersession_unsigned = {
        "schema_version": 1,
        "result_type": "d9_d6_frequency_only_analysis_supersession_v1",
        "status": status,
        "source_package": {
            "run_id": programme.FREQUENCY_ONLY_PREDECESSOR_RUN_ID,
            "content_sha256": source_content_sha256,
        },
        "replacement_product": {
            "analysis_file_sha256": analysis_file_sha256,
            "analysis_terminal": programme.FREQUENCY_ONLY_PREDECESSOR_TERMINAL,
        },
        "criterion_changed": False,
        "raw_evidence_unchanged": True,
        "physical_rerun": False,
        "hardware_interaction": False,
        "actionable": False,
        "actuation_authorized": False,
        "claims_boundary": dict(programme.FREQUENCY_ONLY_PREDECESSOR_CLAIMS),
    }
    supersession = {
        **supersession_unsigned,
        "supersession_sha256": programme.canonical_sha256(
            supersession_unsigned
        ),
    }
    supersession_path = reports / Path(
        programme.FREQUENCY_ONLY_PREDECESSOR_SUPERSESSION
    ).name
    supersession_path.write_text(json.dumps(supersession), encoding="utf-8")
    supersession_file_sha256 = sha256(supersession_path.read_bytes()).hexdigest()

    seal_unsigned = {
        "schema_version": 1,
        "seal_type": "d9_d6_frequency_only_superseding_seal_v1",
        "status": status,
        "source_content_sha256": source_content_sha256,
        "analysis_file_sha256": analysis_file_sha256,
        "supersession_file_sha256": supersession_file_sha256,
        "supersession_sha256": supersession["supersession_sha256"],
        "review_authority": "operator_test_authority",
        "claims_boundary": dict(programme.FREQUENCY_ONLY_PREDECESSOR_CLAIMS),
        "hardware_interaction": False,
        "actionable": False,
        "actuation_authorized": False,
    }
    seal = {
        **seal_unsigned,
        "seal_sha256": programme.canonical_sha256(seal_unsigned),
    }
    seal_path = reports / Path(programme.FREQUENCY_ONLY_PREDECESSOR_SEAL).name
    seal_path.write_text(json.dumps(seal), encoding="utf-8")

    product_root = reports.parent
    files = []
    for path in sorted(reports.iterdir()):
        files.append(
            {
                "path": path.relative_to(product_root).as_posix(),
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest_unsigned = {
        "schema_version": 1,
        "product_type": programme.FREQUENCY_ONLY_PREDECESSOR_PRODUCT_TYPE,
        "source_content_sha256": source_content_sha256,
        "files": files,
    }
    manifest = {
        **manifest_unsigned,
        "product_manifest_sha256": programme.canonical_sha256(
            manifest_unsigned
        ),
    }
    manifest_path = product_root / "product_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _bundle(tmp_path: Path) -> dict[str, object]:
    return programme.freeze_bundle(
        build_manifest_path=_build_manifest(tmp_path),
        frequency_only_predecessor_product_manifest_path=(
            _frequency_only_predecessor_product(tmp_path)
        ),
        source_revision="a" * 40,
    )


def _write_rows(
    path: Path, contract_id: str, rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[contract_id])
        writer.writeheader()
        writer.writerows(rows)


def _row(
    contract_id: str,
    sequence: int,
    **values: str,
) -> dict[str, str]:
    row = {field: "" for field in CONTRACT_FIELDS[contract_id]}
    sequence_fields = {
        "active_transactions_v1": "transaction_record_sequence",
        "active_hybrid_decisions_v1": "hybrid_record_sequence",
        "raw_events_v1": "event_seq",
        "count_observations_v1": "count_seq",
        "pps_snapshots_v1": "snapshot_sequence",
        "forwarded_monitor_snapshots_v1": "snapshot_sequence",
        "health_v1": "status_seq",
        "reference_observations_v1": "reference_observation_seq",
        "relative_phase_observations_v1": "observation_sequence",
        "phase_estimator_outputs_v1": "observation_sequence",
    }
    row.update(
        {
            "record_type": sorted(CONTRACT_RECORD_TYPES[contract_id])[0],
            "schema_version": "1",
            sequence_fields[contract_id]: str(sequence),
            **values,
        }
    )
    return row


def _transaction_row(
    sequence: int, request: int, event: str
) -> dict[str, str]:
    application = event in {"application", "response"}
    return _row(
        "active_transactions_v1",
        sequence,
        event=event,
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
        build_identity=f"{'a' * 64}:{'b' * 64}",
        profile_identity="cx322_d9_d6_72h_sustained_engineering",
        session_id="7",
        authorization_sequence="9",
        nonce=str(900 + request),
        request_sequence=str(request),
        decision_sequence=str(100 + request),
        source_first_sequence=str(request * 600),
        source_last_sequence=str(request * 600 + 599),
        decision_timestamp_s=str(request * 1800),
        current_applied_code=str(0xA83C + (request - 1) * 21),
        requested_delta_codes="21",
        requested_code=str(0xA83C + request * 21),
        correction_ordinal=str(request),
        cumulative_after_codes=str(request * 21),
        pre_error_hz="0.01",
        accepted_code=str(0xA83C + request * 21),
        accepted_timestamp_s=str(request * 1800),
        applied_code=str(0xA83C + request * 21) if application else "0",
        application_sequence=str(request) if application else "0",
        application_timestamp_s=str(request * 1800 + 1) if application else "0",
        i2c_ok="true" if application else "false",
        clamped="false",
        ambiguous="false",
        dac_epoch=str(request + 1) if application else "0",
        estimator_history_reset="true" if application else "false",
        correction_count=str(request) if application else str(request - 1),
        cumulative_movement_codes=(
            str(request * 21) if application else str((request - 1) * 21)
        ),
        post_error_hz="0.001" if event == "response" else "0",
        observed_response_hz="-0.009" if event == "response" else "0",
        cumulative_response_hz="-0.009" if event == "response" else "0",
        consecutive_indeterminate="0",
        active_state="DISARMED" if event == "response" else "AWAITING_RESPONSE",
        response_class="healthy_detected" if event == "response" else "unavailable",
        reason=f"lifecycle_{request}",
        estimator_sha256="c" * 64,
        model_sha256="d" * 64,
        active_policy_sha256="e" * 64,
        response_policy_sha256="f" * 64,
        numerical_policy_sha256="1" * 64,
        actionable="false",
        evidence_state=(
            "request_pending"
            if event in {"request_created", "request_accepted"}
            else "application_pending" if event == "application" else "response_pending"
        ),
    )


def _decision_consumer_row(sequence: int, request: int) -> dict[str, str]:
    return _row(
        "active_hybrid_decisions_v1",
        sequence,
        decision_sequence=str(100 + request),
        decision_timestamp_s=str(request * 1800 + 600),
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
        build_identity=f"{'a' * 64}:{'b' * 64}",
        profile_identity="cx322_d9_d6_72h_sustained_engineering",
        capture_session="7",
        source_first_sequence=str(request * 600),
        source_last_sequence=str(request * 600 + 599),
        current_applied_code=str(0xA83C + request * 21),
        dac_epoch=str(request + 1),
        phase_applied_code=str(0xA83C + request * 21),
        phase_dac_epoch=str(request + 1),
        request_sequence=str(request),
        acceptance_sequence=str(request),
        application_sequence=str(request),
        response_class="healthy_detected",
        actual_applied_code=str(0xA83C + request * 21),
        actual_dac_epoch=str(request + 1),
        downstream_epoch_exact="true",
        reason=f"lifecycle_{request}",
        actionable="false",
    )


def _health_rows() -> list[dict[str, str]]:
    sequence = 0
    rows: list[dict[str, str]] = []

    def add(component: str, key: str, value: str) -> None:
        nonlocal sequence
        sequence += 1
        rows.append(
            _row(
                "health_v1",
                sequence,
                timestamp_ticks=str(sequence * 100),
                status_domain="rp2040_timer0_extended",
                component=component,
                status_key=key,
                status_value=value,
                severity="INFO",
                flags="0",
            )
        )

    expected = dict(FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH)
    expected[("forwarded_clock_output", "first_valid_ticks")] = "100"
    for component, key in FORWARDED_MONITOR_OBSERVABILITY_KEYS:
        expected[(component, key)] = "0"
    for (component, key), value in sorted(expected.items()):
        add(component, key, value)

    common = {
        "confirmed_applied_code": "0xA866",
        "dac_epoch": "3",
        "session_id": "7",
        "gnss_metadata_hold_transaction_pending": "false",
        "evidence_pending": "false",
        "evidence_phase": "evidence_clear",
        "evidence_request_sequence": "0",
    }
    for generation, active, entry, requalification, frontier, observation, state in (
        (1, "true", "10", "0", "0", "200", "GNSS_METADATA_HOLD"),
        (2, "false", "10", "11", "200", "201", "DISARMED"),
    ):
        add("cx317_active", "snapshot_generation_begin", str(generation))
        add("cx317_active", "snapshot_contract", "cx317_active_status_snapshot_v1")
        for key, value in common.items():
            add("cx317_active", key, value)
        add("cx317_active", "state", state)
        add("cx317_active", "gnss_metadata_hold_active", active)
        add("cx317_active", "gnss_metadata_hold_entry_sequence", entry)
        add(
            "cx317_active",
            "gnss_metadata_requalification_sequence",
            requalification,
        )
        add("cx317_active", "gnss_metadata_qualification_frontier", frontier)
        add("cx317_active", "d14_d8_observation_sequence", observation)
        add("cx317_active", "snapshot_generation_complete", str(generation))
    return rows


def _retained_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "retained_run"
    files = dict(programme._INSPECTION_SOURCES)
    files.update(
        {
            str(item["contract"]): str(item["path"])
            for item in programme._LIVE_SOURCE_DECLARATIONS
        }
    )
    manual_start = _transaction_row(1, 0, "manual_start")
    manual_start.update(
        {
            "requested_delta_codes": "0",
            "requested_code": str(0xA83C),
            "accepted_code": str(0xA83C),
            "applied_code": str(0xA83C),
            "application_sequence": "0",
            "dac_epoch": "1",
            "reason": "manual_start",
        }
    )
    transactions = [manual_start, *[
        _transaction_row(sequence, request, event)
        for sequence, (request, event) in enumerate(
            (
                (1, "request_created"),
                (1, "request_accepted"),
                (1, "application"),
                (1, "response"),
                (2, "request_created"),
                (2, "request_accepted"),
                (2, "application"),
                (2, "response"),
            ),
            start=2,
        )
    ]]
    raw = [
        _row(
            "raw_events_v1",
            number,
            record_type="REF",
            channel_id="1",
            edge="R",
            timestamp_ticks=str(number * 16_000_000),
            capture_domain="rp2040_timer0",
            flags="0",
        )
        for number in range(1, 4)
    ]
    counts = [
        _row(
            "count_observations_v1",
            number,
            channel_id="2",
            gate_open_ticks=str((number - 1) * 16_000_000),
            gate_close_ticks=str(number * 16_000_000),
            gate_domain="rp2040_timer0",
            counted_edges="10000000",
            source_edge="R",
            source_domain="h1_cx317_ocxo_10mhz",
            flags="0",
        )
        for number in range(1, 4)
    ]
    snapshots = [
        _row(
            "pps_snapshots_v1",
            number,
            session="7",
            cumulative_down_counter=str(0xFFFFFFFF - number * 10_000_000),
            reference_sequence=str(number),
            reference_timestamp_ticks=str(number * 16_000_000),
            status="0",
            backend="pio_wait_cumulative_snapshot_dma_v1",
        )
        for number in range(1, 4)
    ]
    monitors = [
        _row(
            "forwarded_monitor_snapshots_v1",
            number,
            session="7",
            reference_session="7",
            cumulative_down_counter=str(0xFFFFFFFF - number * 10_000_000),
            reference_sequence=str(number),
            reference_timestamp_ticks=str(number * 16_000_000),
            status="8" if number == 2 else "0",
            backend="pio_wait_cumulative_snapshot_cpu_v1",
            channel_id="3",
        )
        for number in range(1, 4)
    ]
    reference_rows = [
        _row(
            "reference_observations_v1",
            number,
            reference_observation_id=f"reference-{number}",
            observation_timestamp_ticks=str(number * 16_000_000),
            time_domain="rp2040_timer0_extended",
            source_identity_epoch="1",
            metadata_freshness="stale" if number == 1 else "current",
        )
        for number in range(1, 3)
    ]
    decisions = [
        _decision_consumer_row(1, 1),
        _decision_consumer_row(2, 2),
    ]
    for decision in decisions:
        decision.update(
            {
                "frequency_term_hz": "0.001",
                "phase_term_hz": "0",
                "combined_demand_hz": "0.001",
                "requested_delta_codes": "21",
                "counterfactual_frequency_only_delta_codes": "21",
                "phase_materially_influenced": "false",
                "phase_recorder_published": "true",
                "range_clamped": "false",
                "cadence_limited": "false",
                "count_limited": "false",
                "cumulative_budget_limited": "false",
            }
        )
    transaction_timings: list[dict[str, str]] = []
    transaction_join = programme._LIVE_SOURCE_DECLARATIONS[0]["join_fields"]
    for timing_sequence, row in enumerate(transactions, start=1):
        timing = {
            field: "" for field in programme.ACTIVE_TRANSACTION_V2_FIELDS
        }
        timing.update({field: row[field] for field in transaction_join})
        timing.update(
            {
                "record_type": "AT2",
                "schema_version": "2",
                "timing_record_sequence": str(timing_sequence),
                "event_timestamp_ticks": str(timing_sequence * 16_000_000),
                "time_domain": programme.EXACT_LIFECYCLE_TIME_DOMAIN,
            }
        )
        transaction_timings.append(timing)
    decision_timings: list[dict[str, str]] = []
    decision_join = programme._LIVE_SOURCE_DECLARATIONS[1]["join_fields"]
    for timing_sequence, row in enumerate(decisions, start=1):
        timing = {
            field: "" for field in programme.ACTIVE_HYBRID_DECISION_V2_FIELDS
        }
        timing.update({field: row[field] for field in decision_join})
        timing.update(
            {
                "record_type": "AH2",
                "schema_version": "2",
                "timing_record_sequence": str(timing_sequence),
                "decision_timestamp_ticks": str(timing_sequence * 64_000_000),
                "time_domain": programme.EXACT_LIFECYCLE_TIME_DOMAIN,
            }
        )
        decision_timings.append(timing)
    content = {
        "active_transactions_v1": transactions,
        "active_hybrid_decisions_v1": decisions,
        "active_transactions_v2": transaction_timings,
        "active_hybrid_decisions_v2": decision_timings,
        "raw_events_v1": raw,
        "count_observations_v1": counts,
        "pps_snapshots_v1": snapshots,
        "forwarded_monitor_snapshots_v1": monitors,
        "health_v1": _health_rows(),
        "reference_observations_v1": reference_rows,
        "relative_phase_observations_v1": [],
        "phase_estimator_outputs_v1": [],
    }
    for contract_id, relative in files.items():
        _write_rows(run_dir / relative, contract_id, content[contract_id])
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {"path": relative, "contract": contract_id}
                    for contract_id, relative in files.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "reports").mkdir(exist_ok=True)
    (run_dir / "reports/cx317_active_supervisor_state.json").write_text(
        json.dumps(
            {
                "qualified_origin_extended_timestamp_ticks": 1_000,
                "qualified_frontier_extended_ticks": (
                    1_000 + 259_200 * RP2040_TIMER0_TICKS_PER_SECOND
                ),
                "qualified_endpoint_extended_timestamp_ticks": (
                    1_000 + 259_200 * RP2040_TIMER0_TICKS_PER_SECOND
                ),
                "arm_pending": False,
                "host_verification_hold": None,
                "terminal": {
                    "result": "healthy_stop",
                    "reason": (
                        "cx322_d9_d6_72h_72h_qualified_endpoint_complete"
                    ),
                    "preliminary_decision": (
                        "pending_offline_scientific_analysis"
                    ),
                    "last_confirmed_code": 0xA866,
                },
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _established_supervisor(
    *, run_start_ticks: int = 0
) -> programme.Engineering72hSupervisor:
    contract = programme.load_contract()
    supervisor = programme.Engineering72hSupervisor(contract, run_start_ticks)
    supervisor.record_setup_establishment(
        applied_code=0xA83C,
        applied_epoch=1,
        application_ticks=run_start_ticks + 100,
        pre_setup_physical_code_readable=False,
        dac_query_claimed_physical_readback=False,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
    )
    supervisor.arm(
        frontier_ticks=run_start_ticks + 200,
        fresh_auto_detect=True,
        candidate_count=1,
        baud=115200,
        sole_serial_owner=True,
        independent_abort_ready=True,
        d9_state="configured_10mhz_forwarded_unqualified",
        d9_identity_exact=True,
        d9_readback_exact=True,
        d14_d8_healthy=True,
        gnss_metadata_fresh_same_receiver=True,
        d6_status="present",
        no_outstanding_transaction=True,
    )
    return supervisor


def test_contract_is_exact_72h_engineering_and_non_promotional() -> None:
    contract = programme.load_contract()

    assert contract["firmware"]["profile_id"] == (
        "cx322_d9_d6_72h_sustained_engineering"
    )
    assert contract["firmware"]["generic_sustained_regulation_mode"] is False
    assert contract["firmware"]["deliberate_reversal_challenge_enabled"] is False
    assert contract["serial"]["baud"] == 115200
    assert "--auto-detect" in contract["serial"]["selection"]
    assert contract["gnss_uart_policy"]["maximum_total_attempts"] == 2
    assert contract["gnss_uart_policy"]["settle_after_peripheral_drain_ms"] == 1200
    assert contract["gnss_uart_policy"]["autodiscovery_permitted"] is False
    assert contract["gnss_uart_policy"]["post_bootstrap_baud_change_permitted"] is False
    assert contract["time"]["qualified_duration_s"] == 259_200
    assert contract["time"]["source_counter_domain"] == "rp2040_timer0"
    assert contract["time"]["counter_domain"] == "rp2040_timer0_extended"
    assert contract["time"]["nominal_counter_hz"] == (
        RP2040_TIMER0_TICKS_PER_SECOND
    )
    assert contract["time"]["qualification_deadline_s"] == 5_400
    assert contract["time"]["absolute_wall_limit_s"] == 280_800
    assert contract["time"]["milestones_qualified_s"] == [
        21_600 * number for number in range(1, 13)
    ]
    assert contract["controller_envelope"]["automatic_application_limit"] == 144
    assert contract["controller_envelope"][
        "automatic_cumulative_movement_limit_codes"
    ] == 3024
    assert contract["controller_envelope"][
        "total_dac_write_limit_including_setup"
    ] == 145
    assert contract["controller_envelope"][
        "authority_ceilings_are_nonbinding_not_targets"
    ] is True
    assert contract["timing_truth"]["reference_input"] == "D14"
    assert contract["timing_truth"]["oscillator_and_control_input"] == "D8"
    assert contract["d9"]["readback_exact_required"] is True
    assert contract["d6"]["measurement_authority"] is False
    assert contract["d6"]["control_authority"] is False
    assert contract["claim_boundary"]["waveform_evidence_status"] == (
        "unresolved_oscilloscope_deferred"
    )
    assert contract["claim_boundary"]["prompt02_promotion_permitted"] is False


def test_bundle_binds_exact_build_contract_and_no_io_preflight(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    checked = programme.validate_bundle(bundle)
    result = programme.no_io_preflight(checked)

    assert checked["effective"] is False
    assert checked["physical_authority"] is False
    assert checked["controller_envelope"]["automatic_application_limit"] == 144
    assert checked["controller_envelope"][
        "automatic_cumulative_movement_limit_codes"
    ] == 3024
    assert checked["controller_envelope"]["automatic_step_limit_codes"] == 21
    assert checked["starting_dac"]["setup_write_limit"] == 1
    assert result["hardware_operations"] is False
    assert result["qualified_duration_s"] == 259_200
    assert result["promotion_permitted"] is False
    assert result["firmware_profile_matrix_integrated"] is True
    assert result["physical_activation_ready"] is False
    assert result["programme"]["generic_sustained_regulation_mode"] is False
    assert result["programme"]["sustained_authority_programme"] is True
    assert result["programme"]["maximum_physical_writes"] == 145
    assert result["remaining_live_components"] == [
        "separate_exact_physical_activation"
    ]
    predecessor = checked["frequency_only_predecessor"]
    assert predecessor["analysis_terminal"] == (
        programme.FREQUENCY_ONLY_PREDECESSOR_TERMINAL
    )
    assert predecessor["seal_sha256"]
    assert result["frequency_only_predecessor"] == predecessor


def test_bundle_rejects_self_consistent_nonpassing_frequency_predecessor(
    tmp_path: Path,
) -> None:
    predecessor = _frequency_only_predecessor_product(
        tmp_path, status="incomplete"
    )

    with pytest.raises(
        ValueError, match="frequency-only predecessor supersession is not exact"
    ):
        programme.freeze_bundle(
            build_manifest_path=_build_manifest(tmp_path),
            frequency_only_predecessor_product_manifest_path=predecessor,
            source_revision="a" * 40,
        )


def test_live_preflight_rejects_frequency_predecessor_product_drift(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    activation = programme.draft_live_activation(
        bundle=bundle,
        run_directory=tmp_path / "future-run",
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )
    manifest_path = Path(
        bundle["bindings"]["frequency_only_predecessor_product_manifest"][
            "path"
        ]
    )
    seal_path = manifest_path.parent / programme.FREQUENCY_ONLY_PREDECESSOR_SEAL
    seal_path.write_text(
        seal_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="frequency-only predecessor product file differs"
    ):
        programme.validate_live_activation(
            bundle=bundle,
            activation=activation,
        )


def test_preflight_cli_can_retain_exact_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    output_path = tmp_path / "retained" / "adapter_preflight.json"

    assert (
        programme.main(
            [
                "preflight",
                "--bundle",
                str(bundle_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    retained = json.loads(output_path.read_text(encoding="utf-8"))
    printed = json.loads(capsys.readouterr().out)
    assert retained == printed
    assert retained["status"] == "passed"
    assert retained["frequency_only_predecessor"] == bundle[
        "frequency_only_predecessor"
    ]


def test_bundle_rejects_profile_selector_and_bound_file_drift(
    tmp_path: Path,
) -> None:
    build_path = _build_manifest(tmp_path)
    changed = json.loads(build_path.read_text(encoding="utf-8"))
    changed["provenance"]["configuration"]["defines"][
        "OTIS_ENABLE_FORWARDED_D6_MONITOR"
    ] = "0"
    build_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="exact CX322 D9/D6"):
        programme.freeze_bundle(
            build_manifest_path=build_path,
            frequency_only_predecessor_product_manifest_path=(
                _frequency_only_predecessor_product(tmp_path)
            ),
            source_revision="a" * 40,
        )

    bundle = _bundle(tmp_path / "second")
    manifest = Path(bundle["bindings"]["firmware_build_manifest"]["path"])
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bound-file identity differs"):
        programme.validate_bundle(bundle)


def test_freeze_rejects_stale_pending_profile_status_even_with_valid_hash(
    tmp_path: Path,
) -> None:
    contract = json.loads(programme.CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["firmware"]["profile_matrix_status"] = (
        "pending_new_profile_and_firmware_guards_required_before_physical_"
        "activation"
    )
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_semantic_sha256"
    }
    contract["contract_semantic_sha256"] = programme.canonical_sha256(unsigned)
    path = tmp_path / "stale-profile-contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="integrated profile status differs"):
        programme.freeze_bundle(
            build_manifest_path=_build_manifest(tmp_path),
            frequency_only_predecessor_product_manifest_path=(
                _frequency_only_predecessor_product(tmp_path)
            ),
            source_revision="a" * 40,
            contract_path=path,
        )


def test_live_activation_is_no_io_and_requires_separate_physical_binding(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    run_dir = tmp_path / "future_run"
    activation = programme.draft_live_activation(
        bundle=bundle,
        run_directory=run_dir,
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )

    result = programme.validate_live_activation(
        bundle=bundle, activation=activation
    )

    assert result["status"] == "ready"
    assert result["hardware_operations"] is False
    assert result["physical_activation_ready"] is False
    assert result["adapter_authority"] == {
        "retained_evidence_reader": True,
        "scientific_report_writer": True,
        "canonical_reducer_writer": False,
        "serial_owner": False,
        "command_writer": False,
        "acknowledgement_sender": False,
        "controller": False,
        "actuator_authority": False,
    }
    assert result["hard_blockers"] == []
    asserted = dict(activation)
    asserted["effective"] = True
    asserted["physical_authority"] = True
    asserted_unsigned = {
        key: value
        for key, value in asserted.items()
        if key != "activation_sha256"
    }
    asserted["activation_sha256"] = programme.canonical_sha256(asserted_unsigned)
    with pytest.raises(ValueError, match="lacks active-hybrid activation"):
        programme.validate_live_activation(bundle=bundle, activation=asserted)


def test_adapter_activation_binds_one_exact_campaign18_physical_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    draft = programme.draft_live_activation(
        bundle=bundle,
        run_directory=tmp_path / "future-run",
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )
    physical_path = tmp_path / "campaign18-active.json"
    physical_path.write_text("{}\n", encoding="utf-8")
    active_activation = {
        "profile_identity": bundle["profile_id"],
        "activation_sha256": "a" * 64,
        "firmware": {"build_identity": f"{'a' * 64}:{'b' * 64}"},
        "device": {
            "selection": bundle["serial"]["selection"],
            "baud": 115200,
        },
    }
    active_bundle = {"bundle_sha256": "b" * 64}
    monkeypatch.setattr(
        programme,
        "_validate_campaign18_active_activation",
        lambda **kwargs: (active_activation, active_bundle),
    )

    effective = programme.bind_effective_live_activation(
        bundle=bundle,
        draft=draft,
        active_hybrid_activation_path=physical_path,
    )
    result = programme.validate_campaign18_entrypoint(
        bundle=bundle,
        adapter_activation=effective,
        active_hybrid_activation_path=physical_path,
    )

    assert effective["effective"] is True
    assert effective["physical_authority"] is True
    assert effective["active_hybrid_activation"] == programme.file_binding(
        physical_path
    )
    assert result["status"] == "ready"
    assert result["serial_selection"] == bundle["serial"]["selection"]
    assert result["baud"] == 115200
    assert result["frequency_only_predecessor"] == bundle[
        "frequency_only_predecessor"
    ]

    bundle_path = tmp_path / "adapter-bundle.json"
    adapter_path = tmp_path / "effective-adapter-activation.json"
    output_path = tmp_path / "retained-campaign18-entry-preflight.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    adapter_path.write_text(json.dumps(effective), encoding="utf-8")
    assert (
        programme.main(
            [
                "campaign18-entry-preflight",
                "--bundle",
                str(bundle_path),
                "--adapter-activation",
                str(adapter_path),
                "--active-hybrid-activation",
                str(physical_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    retained = json.loads(output_path.read_text(encoding="utf-8"))
    assert retained == json.loads(capsys.readouterr().out)
    assert retained["frequency_only_predecessor"] == bundle[
        "frequency_only_predecessor"
    ]


def test_campaign18_physical_binding_accepts_shared_auto_detect_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from host.otis_tools import active_hybrid_activation
    from host.otis_tools.active_hybrid_bundle import FRESH_SERIAL_AUTO_DETECT

    bundle = _bundle(tmp_path / "bundle")
    checked = programme.validate_bundle(bundle)
    envelope = checked["controller_envelope"]
    active_bundle = {
        "firmware": {
            "profile_id": checked["profile_id"],
            "source_revision": checked["source_revision"],
            "build_manifest": {
                "sha256": checked["bindings"]["firmware_build_manifest"][
                    "sha256"
                ]
            },
            "defines": programme._intended_profile_defines(
                programme.load_contract()
            ),
        },
        "finite_limits": {
            "qualified_duration_s": checked["time"]["qualified_duration_s"],
            "absolute_wall_clock_limit_s": checked["time"][
                "absolute_wall_limit_s"
            ],
            "maximum_total_automatic_applications": envelope[
                "automatic_application_limit"
            ],
            "maximum_total_physical_control_applications": envelope[
                "automatic_application_limit"
            ],
            "maximum_cumulative_absolute_movement_codes": envelope[
                "automatic_cumulative_movement_limit_codes"
            ],
            "maximum_combined_step_codes": envelope[
                "automatic_step_limit_codes"
            ],
            "minimum_applied_cadence_s": envelope[
                "minimum_application_cadence_s"
            ],
        },
    }
    active_activation = {
        "programme_id": programme.CAMPAIGN18_PROGRAMME_ID,
        "run_identity": programme.CAMPAIGN18_RUN_IDENTITY,
        "profile_identity": checked["profile_id"],
        "device": {
            "path": None,
            "selection": FRESH_SERIAL_AUTO_DETECT,
            "baud": 115200,
            "expected_board_serial": None,
        },
        "authority": {
            "effective": True,
            "physical_execution": True,
            "firmware_flash_limit": 1,
            "setup_write_limit": 1,
            "maximum_total_automatic_applications": 144,
            "maximum_total_physical_control_applications": 144,
            "maximum_cumulative_absolute_movement_codes": 3024,
            "maximum_deliberate_challenges": 0,
            "automatic_retry": False,
            "automatic_restoration": False,
            "live_extension": False,
        },
    }
    monkeypatch.setattr(
        active_hybrid_activation,
        "validate_frozen_activation",
        lambda *_args, **_kwargs: (active_activation, active_bundle, {}),
    )

    observed, _active_bundle = programme._validate_campaign18_active_activation(
        bundle=bundle,
        active_hybrid_activation_path=tmp_path / "activation.json",
    )

    assert observed["device"]["selection"] == FRESH_SERIAL_AUTO_DETECT


def test_campaign18_runner_delegates_then_reads_without_mutating_sealed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from host.otis_tools import active_hybrid_run

    bundle = _bundle(tmp_path / "bundle")
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    run_dir = _retained_run(tmp_path)
    adapter = programme.draft_live_activation(
        bundle=bundle,
        run_directory=run_dir,
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )
    adapter_path = tmp_path / "adapter.json"
    adapter_path.write_text(json.dumps(adapter), encoding="utf-8")
    physical_path = tmp_path / "physical.json"
    physical_activation_sha = "d" * 64
    build_identity = f"{'a' * 64}:{'b' * 64}"
    physical_path.write_text(
        json.dumps(
            {
                "activation_sha256": physical_activation_sha,
                "bundle": {"path": str(bundle_path)},
                "firmware": {"build_identity": build_identity},
            }
        ),
        encoding="utf-8",
    )
    from host.otis_tools import active_hybrid_run

    reservation_path = active_hybrid_run._activation_attempt_reservation_path(
        json.loads(physical_path.read_text(encoding="utf-8"))
    )
    reservation_path.write_text("reserved\n", encoding="utf-8")
    monkeypatch.setattr(
        programme,
        "validate_campaign18_entrypoint",
        lambda **kwargs: {
            "status": "ready",
            "active_hybrid_activation_sha256": physical_activation_sha,
            "active_hybrid_bundle_sha256": "f" * 64,
            "build_identity": build_identity,
        },
    )
    before = programme.package_identity(run_dir)["content_sha256"]
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "status": "passed",
            "primary_decision": "cx322_d9_d6_72h_qualified_engineering_complete",
            "run_dir": str(run_dir),
            "evidence_content_sha256": before,
            "firmware_flashes": 1,
            "activation_sha256": physical_activation_sha,
            "bundle_sha256": "f" * 64,
            "build_identity": build_identity,
            "activation_attempt_reservation": {
                "path": str(reservation_path),
                "sha256": sha256(reservation_path.read_bytes()).hexdigest(),
            },
        }

    monkeypatch.setattr(
        active_hybrid_run, "run_active_hybrid_qualification", fake_run
    )
    adapter_output = tmp_path / "adapter-output"
    result = programme.run_campaign18_qualification(
        bundle_path=bundle_path,
        adapter_activation_path=adapter_path,
        active_hybrid_activation_path=physical_path,
        run_dir=run_dir,
        adapter_output_dir=adapter_output,
        evidence_index_path=tmp_path / "index.jsonl",
    )

    assert len(calls) == 1
    assert calls[0]["activation_path"] == physical_path.resolve()
    assert result["retained_adapter"]["status"] == "complete_read_only"
    assert result["retained_adapter"]["sealed_evidence_unchanged"] is True
    assert programme.package_identity(run_dir)["content_sha256"] == before


def test_retained_adapter_inspects_two_lifecycles_hold_and_d14_d8_without_io(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    run_dir = _retained_run(tmp_path)
    activation = programme.draft_live_activation(
        bundle=bundle,
        run_directory=run_dir,
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )

    first = programme.RetainedEvidence72hAdapter(
        bundle=bundle, activation=activation
    ).poll()
    second = programme.RetainedEvidence72hAdapter(
        bundle=bundle, activation=activation
    ).poll()

    assert first["status"] == "complete_read_only"
    assert first["structural_lifecycles"]["complete_count"] == 2
    assert first["structural_lifecycles"]["incomplete_count"] == 0
    assert first["structural_lifecycles"]["exact_ticks_available"] is False
    assert first["canonical_record_count"] == 0
    assert first["canonical_records_appended"] == 0
    assert first["coarse_seconds_projected_to_ticks"] is False
    timing = first["timing_and_forwarded_evidence"]
    assert timing["D14"]["read"] is True
    assert timing["D8"]["read"] is True
    assert timing["D14_D8"]["healthy_and_aligned"] is True
    assert timing["D9"]["configuration_and_readback_exact"] is True
    assert timing["D6"]["local_degraded"] is True
    assert timing["D6"]["terminal_authority"] is False
    assert timing["terminal_classification"] is None
    assert first["gnss_metadata"]["hold_entry_count"] == 1
    assert first["gnss_metadata"]["requalification_count"] == 1
    assert first["gnss_metadata"]["contradictions"] == []
    assert first["gnss_metadata"]["metadata_freshness_counts"] == {
        "current": 1,
        "stale": 1,
    }
    assert first["gnss_metadata"]["control_only"] is True
    assert first["gnss_metadata"]["D14_D8_measurement_continues"] is True
    assert second["poll_number"] == 2
    assert all(count == 0 for count in second["new_rows"].values())
    assert second["canonical_record_count"] == 0
    assert not (run_dir / "adapter_state_v1.json").exists()
    assert not (run_dir / "adapter_report_v1.json").exists()
    assert first["qualified_endpoint"]["exact"] is True


@pytest.mark.parametrize(
    ("frontier_delta", "arm_pending", "expected_blocker"),
    (
        (-1, False, "campaign18_qualified_endpoint_short_or_right_censored"),
        (0, True, "campaign18_terminal_arm_or_request_pending"),
    ),
)
def test_retained_adapter_blocks_short_or_pending_campaign18_endpoint(
    tmp_path: Path,
    frontier_delta: int,
    arm_pending: bool,
    expected_blocker: str,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    run_dir = _retained_run(tmp_path)
    state_path = run_dir / "reports/cx317_active_supervisor_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["qualified_frontier_extended_ticks"] += frontier_delta
    state["arm_pending"] = arm_pending
    state_path.write_text(json.dumps(state), encoding="utf-8")
    activation = programme.draft_live_activation(
        bundle=bundle,
        run_directory=run_dir,
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )

    result = programme.RetainedEvidence72hAdapter(
        bundle=bundle,
        activation=activation,
        state_path=tmp_path / "adapter-state.json",
        report_path=tmp_path / "adapter-report.json",
    ).poll()

    assert result["status"] == "blocked_inspection_only"
    assert expected_blocker in result["hard_blockers"]


def test_retained_adapter_restart_rejects_consumed_prefix_mutation(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    run_dir = _retained_run(tmp_path)
    activation = programme.draft_live_activation(
        bundle=bundle,
        run_directory=run_dir,
        run_identity=programme.CAMPAIGN18_RUN_IDENTITY,
    )
    programme.RetainedEvidence72hAdapter(
        bundle=bundle, activation=activation
    ).poll()
    path = run_dir / "csv/health.csv"
    changed = path.read_bytes().replace(b",slow,", b",fast,", 1)
    assert changed != path.read_bytes()
    path.write_bytes(changed)

    with pytest.raises(ValueError, match="prefix changed after consumption"):
        programme.RetainedEvidence72hAdapter(
            bundle=bundle, activation=activation
        ).poll()


def test_scientific_metrics_are_derived_from_exact_joined_retained_records() -> None:
    hz = RP2040_TIMER0_TICKS_PER_SECOND
    application_ticks = 2 * hz
    manual = _transaction_row(1, 0, "manual_start")
    manual.update(
        {
            "session_id": "7",
            "nonce": "900",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "current_applied_code": str(0xA83C),
            "requested_delta_codes": "0",
            "requested_code": str(0xA83C),
            "accepted_code": str(0xA83C),
            "applied_code": str(0xA83C),
            "application_sequence": "0",
            "dac_epoch": "1",
            "reason": "manual_start",
        }
    )
    transactions = [manual]
    for sequence, event in enumerate(
        ("request_created", "request_accepted", "application", "response"),
        start=2,
    ):
        transactions.append(_transaction_row(sequence, 1, event))

    decisions = [_decision_consumer_row(1, 1), _decision_consumer_row(2, 2)]
    decisions[0].update(
        {
            "frequency_term_hz": "-0.010",
            "phase_term_hz": "-0.002",
            "combined_demand_hz": "-0.012",
            "requested_delta_codes": "21",
            "counterfactual_frequency_only_delta_codes": "18",
            "phase_materially_influenced": "true",
            "range_clamped": "false",
            "cadence_limited": "false",
            "count_limited": "false",
            "cumulative_budget_limited": "false",
            "reason": "application_requested",
        }
    )
    decisions[1].update(
        {
            "frequency_term_hz": "0",
            "phase_term_hz": "0",
            "combined_demand_hz": "0",
            "requested_delta_codes": "0",
            "counterfactual_frequency_only_delta_codes": "0",
            "phase_materially_influenced": "false",
            "range_clamped": "false",
            "cadence_limited": "false",
            "count_limited": "false",
            "cumulative_budget_limited": "false",
            "reason": "gnss_metadata_hold_no_new_request",
        }
    )

    transaction_ticks = [
        0,
        application_ticks - 3,
        application_ticks - 2,
        application_ticks,
        application_ticks + 600 * hz,
    ]
    transaction_timings: list[dict[str, str]] = []
    transaction_join = programme._LIVE_SOURCE_DECLARATIONS[0]["join_fields"]
    for timing_sequence, (row, ticks) in enumerate(
        zip(transactions, transaction_ticks, strict=True), start=1
    ):
        timing = {
            field: "" for field in programme.ACTIVE_TRANSACTION_V2_FIELDS
        }
        timing.update(
            {
                field: row[field]
                for field in transaction_join
            }
        )
        timing.update(
            {
                "record_type": "AT2",
                "schema_version": "2",
                "timing_record_sequence": str(timing_sequence),
                "event_timestamp_ticks": str(ticks),
                "time_domain": "rp2040_timer0_extended",
            }
        )
        transaction_timings.append(timing)

    decision_timings: list[dict[str, str]] = []
    decision_join = programme._LIVE_SOURCE_DECLARATIONS[1]["join_fields"]
    for timing_sequence, (row, ticks) in enumerate(
        zip(
            decisions,
            (application_ticks - 4, application_ticks + 21_600 * hz),
            strict=True,
        ),
        start=1,
    ):
        timing = {
            field: "" for field in programme.ACTIVE_HYBRID_DECISION_V2_FIELDS
        }
        timing.update({field: row[field] for field in decision_join})
        timing.update(
            {
                "record_type": "AH2",
                "schema_version": "2",
                "timing_record_sequence": str(timing_sequence),
                "decision_timestamp_ticks": str(ticks),
                "time_domain": "rp2040_timer0_extended",
            }
        )
        decision_timings.append(timing)

    boundaries = [
        0,
        application_ticks,
        application_ticks + 600 * hz,
        application_ticks + 1500 * hz,
        application_ticks + 3600 * hz,
        application_ticks + 7200 * hz,
        application_ticks + 21_600 * hz,
    ]
    raw = [
        _row(
            "raw_events_v1",
            sequence,
            record_type="REF",
            channel_id="1",
            edge="R",
            timestamp_ticks=str(ticks),
            capture_domain="rp2040_timer0_extended",
            flags="0",
        )
        for sequence, ticks in enumerate(boundaries, start=1)
    ]
    counts: list[dict[str, str]] = []
    for sequence, (opening, closing) in enumerate(
        zip(boundaries, boundaries[1:]), start=1
    ):
        duration = closing - opening
        expected_edges = 10_000_000 * duration // hz
        counts.append(
            _row(
                "count_observations_v1",
                sequence,
                channel_id="2",
                gate_open_ticks=str(opening),
                gate_close_ticks=str(closing),
                gate_domain="rp2040_timer0_extended",
                counted_edges=str(expected_edges + sequence),
                source_edge="R",
                source_domain="h1_cx317_ocxo_10mhz",
                flags="0",
            )
        )
    metrics = programme.derive_retained_scientific_metrics(
        rows={
            "active_transactions_v1": transactions,
            "active_hybrid_decisions_v1": decisions,
            "raw_events_v1": raw,
            "count_observations_v1": counts,
        },
        transaction_timings=transaction_timings,
        decision_timings=decision_timings,
    )

    assert metrics["status"] == "exact"
    assert metrics["hard_producer_field_blockers"] == []
    assert metrics["caller_supplied_metric_summaries_used"] is False
    assert metrics["D14_relative_frequency_distribution_nanohz"][
        "sample_count"
    ] == 6
    assert metrics["stationary_DAC_epoch_drift"]["epoch_count"] == 2
    assert metrics["response_horizons"]["horizons_s"] == [
        600,
        1500,
        3600,
        7200,
        21_600,
    ]
    assert metrics["response_horizons"]["status_counts"] == {
        "observed_exact": 5
    }
    attribution = metrics["FLL_PLL_phase_and_counterfactual_attribution"]
    assert attribution["decision_count"] == 2
    assert attribution["phase_material_decision_count"] == 1
    assert attribution["frequency_only_counterfactual_difference_count"] == 1
    assert metrics["lost_opportunities"] == {
        "count": 1,
        "dispositions": {
            "APPLICATION_REQUESTED_APPLIED": 1,
            "GNSS_METADATA_HOLD": 1,
        },
        "derived_per_decision": True,
    }
    assert metrics["gain_and_overshoot"]["gain_nanohz_per_code"][
        "sample_count"
    ] == 5
    assert metrics["chatter"]["application_count"] == 1
    assert metrics["measurement_window_fitness"][
        "valid_D14_D8_interval_count"
    ] == 6
    comparison = metrics["measurement_window_fitness"][
        "candidate_window_comparison"
    ]
    assert comparison["candidate_windows_s"] == [60, 300, 600, 900, 1800]
    assert comparison["deployed_frequency_window_s"] == 600
    assert comparison["live_tuning_or_authority_changed"] is False
    assert [item["window_s"] for item in comparison["candidates"]] == [
        60,
        300,
        600,
        900,
        1800,
    ]
    assert any(
        "counterfactual PLL estimator windows are not identifiable" in item
        for item in comparison["limitations"]
    )


def test_gnss_withdrawn_request_is_not_attributed_as_application() -> None:
    decision = _decision_consumer_row(1, 1)
    decision.update(
        {
            "requested_delta_codes": "21",
            "counterfactual_frequency_only_delta_codes": "21",
            "phase_materially_influenced": "false",
            "frequency_term_hz": "0.01",
            "phase_term_hz": "0",
            "combined_demand_hz": "0.01",
            "range_clamped": "false",
            "cadence_limited": "false",
            "count_limited": "false",
            "cumulative_budget_limited": "false",
            "reason": "gnss_metadata_hold_request_withdrawn",
        }
    )
    transactions = [
        _transaction_row(1, 1, "request_created"),
        _transaction_row(2, 1, "request_withdrawn"),
    ]
    transaction_timings = []
    for sequence, row in enumerate(transactions, start=1):
        timing = {
            field: "" for field in programme.ACTIVE_TRANSACTION_V2_FIELDS
        }
        timing.update(
            {
                field: row[field]
                for field in programme._LIVE_SOURCE_DECLARATIONS[0][
                    "join_fields"
                ]
            }
        )
        timing.update(
            {
                "record_type": "AT2",
                "schema_version": "2",
                "timing_record_sequence": str(sequence),
                "event_timestamp_ticks": str(sequence),
                "time_domain": programme.EXACT_LIFECYCLE_TIME_DOMAIN,
            }
        )
        transaction_timings.append(timing)
    decision_timing = {
        field: "" for field in programme.ACTIVE_HYBRID_DECISION_V2_FIELDS
    }
    decision_timing.update(
        {
            field: decision[field]
            for field in programme._LIVE_SOURCE_DECLARATIONS[1]["join_fields"]
        }
    )
    decision_timing.update(
        {
            "record_type": "AH2",
            "schema_version": "2",
            "timing_record_sequence": "1",
            "decision_timestamp_ticks": "1",
            "time_domain": programme.EXACT_LIFECYCLE_TIME_DOMAIN,
        }
    )

    result = programme._controller_attribution(
        [decision], [decision_timing], transactions, transaction_timings
    )

    assert result["opportunity_dispositions"] == {"GNSS_METADATA_HOLD": 1}
    assert result["lost_opportunity_count"] == 1
    assert result["samples"][0]["exact_ACT_application_join"] is False


def test_PLL_pull_in_candidates_assess_realized_phase_without_counterfactual_claim() -> None:
    phases = (24, 18, 6, -2, -1)
    phase_observations = [
        _row(
            "relative_phase_observations_v1",
            sequence,
            phase_epoch="1",
            capture_session="7",
            opening_snapshot_sequence=str(sequence),
            closing_snapshot_sequence=str(sequence + 1),
            opening_reference_sequence=str(99 + sequence),
            closing_reference_sequence=str(100 + sequence),
            dac_epoch="2",
            source_backend="fixture",
            source_file_sha256="a" * 64,
            method_id="fixture",
            configuration_sha256="b" * 64,
            interval_edges="10000000",
            edge_error_cycles="0",
            relative_phase_cycles=str(value),
            relative_phase_time_ns=str(value * 100),
            qualification_state="qualified",
            observation_age_s="0",
            discontinuity_reason="none",
            calibrated_uncertainty_status="available",
        )
        for sequence, value in enumerate(phases, start=1)
    ]
    phase_estimates = [
        _row(
            "phase_estimator_outputs_v1",
            sequence,
            phase_epoch="1",
            source_relative_phase_observation=f"RPH:1:{sequence}",
            raw_relative_phase_cycles=str(value),
            raw_relative_phase_time_ns=str(value * 100),
            filtered_relative_phase_cycles=str(value),
            estimated_frequency_error_hz="0",
            estimator_id="fixture",
            configuration_sha256="c" * 64,
            estimate_age_s="0",
            qualification_state="qualified",
            uncertainty_status="available",
            reason_codes="none",
        )
        for sequence, value in enumerate(phases, start=1)
    ]
    decision = _decision_consumer_row(1, 1)
    decision.update(
        {
            "phase_epoch": "1",
            "phase_observation_sequence": "1",
            "phase_materially_influenced": "true",
        }
    )
    application = _transaction_row(1, 1, "application")
    application["decision_sequence"] = decision["decision_sequence"]
    timing = {
        field: "" for field in programme.ACTIVE_TRANSACTION_V2_FIELDS
    }
    timing.update(
        {
            field: application[field]
            for field in programme._LIVE_SOURCE_DECLARATIONS[0]["join_fields"]
        }
    )
    timing.update(
        {
            "record_type": "AT2",
            "schema_version": "2",
            "timing_record_sequence": "1",
            "event_timestamp_ticks": "100",
            "time_domain": programme.EXACT_LIFECYCLE_TIME_DOMAIN,
        }
    )

    result = programme._phase_pull_in_candidate_fitness(
        phase_observations=phase_observations,
        phase_estimates=phase_estimates,
        decisions=[decision],
        transactions=[application],
        transaction_timings=[timing],
    )

    assert result["status"] == "observational_exact_join"
    assert result["candidate_pull_in_times_s"] == [3600, 10800, 21600, 43200]
    assert all(
        candidate["closed_loop_outcome_replayed"] is False
        for candidate in result["candidate_comparison"]
    )
    deployed = result["deployed_21600_behavior"]
    assert deployed["phase_epochs"][0]["net_abs_phase_reduction_cycles"] == {
        "numerator": 23,
        "denominator": 1,
    }
    assert deployed["zero_crossing_overshoot_count"] == 1
    assert deployed["phase_direction_reversal_count"] == 1
    assert deployed["application_time_to_effect"][0][
        "time_to_first_abs_phase_reduction_D14_intervals"
    ] == 1
    assert result["live_tuning_or_authority_changed"] is False
    assert any(
        "alternative actuation and resulting closed-loop trajectories are not identifiable"
        in limitation
        for limitation in result["limitations"]
    )


def test_D14_D8_frequency_derivation_extends_declared_raw_timer_wrap() -> None:
    opening = RP2040_TIMER0_MICROS_WRAP_TICKS - 8_000_000
    closing = 8_000_000
    raw = [
        _row(
            "raw_events_v1",
            sequence,
            record_type="REF",
            channel_id="1",
            edge="R",
            timestamp_ticks=str(ticks),
            capture_domain="rp2040_timer0",
            flags="0",
        )
        for sequence, ticks in enumerate((opening, closing), start=1)
    ]
    count = _row(
        "count_observations_v1",
        1,
        channel_id="2",
        gate_open_ticks=str(opening),
        gate_close_ticks=str(closing),
        gate_domain="rp2040_timer0",
        counted_edges="10000000",
        source_edge="R",
        source_domain="h1_cx317_ocxo_10mhz",
        flags="0",
    )

    samples, invalid = programme._d14_relative_frequency_samples(raw, [count])

    assert invalid == []
    assert samples[0]["duration_ticks"] == 16_000_000
    assert samples[0]["opening_ticks"] == opening
    assert samples[0]["closing_ticks"] == (
        RP2040_TIMER0_MICROS_WRAP_TICKS + closing
    )
    assert samples[0]["frequency_error_nanohz"] == 0


def test_response_horizons_prove_next_application_and_endpoint_censoring() -> None:
    hz = RP2040_TIMER0_TICKS_PER_SECOND
    origin = 10 * hz
    decision = _decision_consumer_row(1, 1)
    decision.update(
        {
            "source_first_sequence": "1",
            "source_last_sequence": "600",
            "phase_recorder_published": "true",
        }
    )
    timing = {
        field: "" for field in programme.ACTIVE_HYBRID_DECISION_V2_FIELDS
    }
    timing.update(
        {
            field: decision[field]
            for field in programme._LIVE_SOURCE_DECLARATIONS[1]["join_fields"]
        }
    )
    timing.update(
        {
            "record_type": "AH2",
            "schema_version": "2",
            "timing_record_sequence": "1",
            "decision_timestamp_ticks": str(origin),
            "time_domain": "rp2040_timer0_extended",
        }
    )
    qualification_sample = {
        "opening_ticks": origin,
        "closing_ticks": origin + 259_200 * hz,
        "frequency_error_nanohz": programme.Fraction(1),
    }
    derived_origin, endpoint = programme._qualification_boundary_ticks(
        decisions=[decision],
        decision_timings=[timing],
        samples=[qualification_sample],
    )
    assert derived_origin == origin
    assert endpoint == origin + 259_200 * hz

    first_application = {
        "ticks": origin + 1000 * hz,
        "application_sequence": 1,
        "requested_delta_codes": 21,
    }
    second_application = {
        "ticks": origin + 2000 * hz,
        "application_sequence": 2,
        "requested_delta_codes": -21,
    }
    late_application = {
        "ticks": endpoint - 1000 * hz,
        "application_sequence": 3,
        "requested_delta_codes": 21,
    }
    samples = [
        {
            "closing_ticks": first_application["ticks"],
            "frequency_error_nanohz": programme.Fraction(10),
        },
        {
            "closing_ticks": late_application["ticks"],
            "frequency_error_nanohz": programme.Fraction(5),
        },
        {
            "closing_ticks": endpoint,
            "frequency_error_nanohz": programme.Fraction(1),
        },
    ]
    response, _, _ = programme._response_and_chatter_metrics(
        samples,
        [first_application, second_application, late_application],
        qualification_endpoint_ticks=endpoint,
    )

    first_1500 = next(
        row
        for row in response["records"]
        if row["application_sequence"] == 1 and row["horizon_s"] == 1500
    )
    late_1500 = next(
        row
        for row in response["records"]
        if row["application_sequence"] == 3 and row["horizon_s"] == 1500
    )
    assert first_1500["status"] == "right_censored_by_next_application"
    assert first_1500["next_application_ticks"] == second_application["ticks"]
    assert late_1500["status"] == "right_censored_by_qualified_endpoint"
    assert late_1500["qualified_endpoint_ticks"] == endpoint


def test_setup_is_separate_from_nonbinding_144_application_ceiling() -> None:
    supervisor = _established_supervisor()
    hz = supervisor.timer_hz
    code = 0xA83C
    for number in range(1, 145):
        delta = 21 if number % 2 else -21
        next_code = code + delta
        supervisor.record_automatic_application(
            requested_from_code=code,
            applied_code=next_code,
            applied_epoch=number + 1,
            application_ticks=200 + number * 1800 * hz,
            outstanding_transactions_before_request=0,
            acknowledgement_exact=True,
            first_dependent_consumer_exact=True,
            response_complete=True,
        )
        code = next_code

    assert supervisor.terminal is None
    assert supervisor.setup_establishments == 1
    assert supervisor.automatic_applications == 144
    assert supervisor.cumulative_movement_codes == 3024
    assert supervisor.summary()["total_dac_writes"] == 145
    assert supervisor.summary()["authority_ceiling_reached"] is True
    assert supervisor.terminal is None

    supervisor.record_control_opportunity(
        opportunity_id="application-145",
        frontier_ticks=200 + 145 * 1800 * hz,
        disposition="APPLICATION_REQUESTED",
    )
    assert supervisor.terminal == supervisor.contract["terminals"][
        "controller_or_transaction_fault"
    ]


def test_exact_counter_milestones_and_d6_local_degradation() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    supervisor.record_control_opportunity(
        opportunity_id="first-no-correction",
        frontier_ticks=frontier + 1,
        disposition="NO_CORRECTION_REQUESTED",
    )
    opening = frontier
    for number in range(1, 13):
        closing = frontier + number * 21_600 * supervisor.timer_hz
        supervisor.observe_interval(
            opening_ticks=opening,
            closing_ticks=closing,
            measurement_qualified=True,
            d14_d8_healthy=True,
            d9_configuration_and_readback_exact=True,
            d6_status="local_degraded" if number in {3, 7} else "present",
        )
        opening = closing

    assert supervisor.qualified_ticks == 259_200 * supervisor.timer_hz
    assert supervisor.milestones == [21_600 * number for number in range(1, 13)]
    assert supervisor.summary()["d6_local_degradation"]["interval_count"] == 2
    assert supervisor.terminal == supervisor.contract["terminals"][
        "qualified_complete"
    ]


def test_qualified_completion_rejects_zero_opportunity_evidence() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    supervisor.observe_interval(
        opening_ticks=frontier,
        closing_ticks=frontier + supervisor.target_ticks,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
    )

    assert supervisor.terminal == supervisor.contract["terminals"][
        "controller_or_transaction_fault"
    ]


def test_interval_residence_is_split_at_exact_application_tick() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    application_ticks = frontier + 1800 * supervisor.timer_hz
    supervisor.record_automatic_application(
        requested_from_code=0xA83C,
        applied_code=0xA851,
        applied_epoch=2,
        application_ticks=application_ticks,
        outstanding_transactions_before_request=0,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
        response_complete=True,
    )
    supervisor.observe_interval(
        opening_ticks=frontier,
        closing_ticks=frontier + 2000 * supervisor.timer_hz,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
    )

    residence = supervisor.summary()["qualified_range_residence"]["by_code_ticks"]
    assert residence == {
        "0xA83C": 1800 * supervisor.timer_hz,
        "0xA851": 200 * supervisor.timer_hz,
    }


@pytest.mark.parametrize(
    ("d14_d8_healthy", "d9_exact", "terminal_key"),
    [
        (False, True, "authoritative_capture_fault"),
        (True, False, "d9_digital_fault"),
    ],
)
def test_d14_d8_and_d9_faults_have_contract_derived_terminals(
    d14_d8_healthy: bool,
    d9_exact: bool,
    terminal_key: str,
) -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    supervisor.observe_interval(
        opening_ticks=frontier,
        closing_ticks=frontier + supervisor.timer_hz,
        measurement_qualified=True,
        d14_d8_healthy=d14_d8_healthy,
        d9_configuration_and_readback_exact=d9_exact,
        d6_status="present",
    )
    assert supervisor.terminal == supervisor.contract["terminals"][terminal_key]


def test_deadline_wall_limit_and_pre_setup_abort_are_explicit() -> None:
    contract = programme.load_contract()
    late = programme.Engineering72hSupervisor(contract, 0)
    late.record_setup_establishment(
        applied_code=0xA83C,
        applied_epoch=1,
        application_ticks=100,
        pre_setup_physical_code_readable=False,
        dac_query_claimed_physical_readback=False,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
    )
    with pytest.raises(ValueError, match="deadline"):
        late.arm(
            frontier_ticks=5_400 * late.timer_hz + 1,
            fresh_auto_detect=True,
            candidate_count=1,
            baud=115200,
            sole_serial_owner=True,
            independent_abort_ready=True,
            d9_state="configured_10mhz_forwarded_unqualified",
            d9_identity_exact=True,
            d9_readback_exact=True,
            d14_d8_healthy=True,
            gnss_metadata_fresh_same_receiver=True,
            d6_status="present",
            no_outstanding_transaction=True,
        )
    assert late.terminal == contract["terminals"]["right_censored_incomplete"]

    wall = _established_supervisor()
    frontier = wall.armed_ticks
    assert frontier is not None
    wall.observe_interval(
        opening_ticks=frontier,
        closing_ticks=280_800 * wall.timer_hz + 1,
        measurement_qualified=False,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
    )
    assert wall.terminal == contract["terminals"]["right_censored_incomplete"]

    pre_setup = programme.Engineering72hSupervisor(contract, 0)
    pre_setup.operator_abort()
    summary = pre_setup.summary()
    assert summary["terminal"] == contract["terminals"][
        "pre_setup_no_write_abort"
    ]
    assert summary["setup_establishments"] == 0
    assert summary["automatic_applications"] == 0
    assert summary["total_dac_writes"] == 0
    assert summary["cumulative_automatic_movement_codes"] == 0
    assert summary["qualified_ticks"] == 0
    assert summary["last_confirmed_code"] is None


def test_canonical_record_log_replays_identically_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    supervisor.observe_interval(
        opening_ticks=frontier,
        closing_ticks=frontier + supervisor.timer_hz,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
        performance={
            "frequency_error_nanohz": 123,
            "phase_error_ns": -7,
            "drift_nanohz_per_hour": 2,
            "window_support_ticks": supervisor.timer_hz,
        },
    )
    record_path = tmp_path / "records.jsonl"
    binding = supervisor.persist_record_log(record_path)

    replayed = programme.replay_record_log(
        contract=supervisor.contract,
        record_log_path=record_path,
    )
    assert replayed.summary() == supervisor.summary()
    assert binding["last_record_sha256"] == supervisor.summary()[
        "last_record_sha256"
    ]
    monitor = programme.monitor_record_log(
        contract=supervisor.contract,
        record_log_path=record_path,
    )
    analyzer = programme.analyze_record_log(
        contract=supervisor.contract,
        record_log_path=record_path,
    )
    assert monitor["qualified_ticks"] == supervisor.timer_hz
    assert analyzer["summary"]["performance_metrics"][
        "frequency_error_nanohz"
    ]["mean_exact"] == {"numerator": 123, "denominator": 1}
    assert analyzer["waveform_promotion_permitted"] is False

    records = programme.load_record_log(record_path)
    records[-1]["performance"]["phase_error_ns"] = 8
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identity or ordering"):
        programme.replay_record_log(
            contract=supervisor.contract,
            record_log_path=tampered,
        )


def test_gnss_metadata_hold_qualifies_measurement_and_d6_fault_stays_local() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    supervisor.record_control_opportunity(
        opportunity_id="metadata-hold",
        frontier_ticks=frontier + 1,
        disposition="GNSS_METADATA_HOLD",
    )
    supervisor.observe_interval(
        opening_ticks=frontier,
        closing_ticks=frontier + 600 * supervisor.timer_hz,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="local_degraded",
        gnss_metadata_state="GNSS_METADATA_HOLD",
    )

    summary = supervisor.summary()
    assert summary["terminal"] is None
    assert summary["qualified_seconds"] == 600
    assert summary["opportunity_dispositions"] == {"GNSS_METADATA_HOLD": 1}
    assert summary["lost_opportunity_count"] == 1
    assert summary["gnss_metadata_hold"]["seconds"] == 600
    assert summary["gnss_metadata_hold"]["run_or_measurement_failure"] is False
    assert summary["d6_local_degradation"]["seconds"] == 600
    assert summary["d6_local_degradation"][
        "affected_D14_D8_or_control"
    ] is False


def test_transaction_identity_one_outstanding_and_endpoint_quiescence() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    supervisor.record_control_opportunity(
        opportunity_id="opportunity-1",
        frontier_ticks=frontier + 1800 * supervisor.timer_hz,
        disposition="APPLICATION_REQUESTED",
    )
    supervisor.record_automatic_request(
        transaction_id="transaction-1",
        opportunity_id="opportunity-1",
        session_id="session-1",
        request_sequence=1,
        evidence_sequence=10,
        request_ticks=frontier + 1800 * supervisor.timer_hz,
        requested_from_code=0xA83C,
        requested_code=0xA851,
        outstanding_transactions_before_request=0,
    )
    assert supervisor.outstanding_transactions == 1

    supervisor.record_control_opportunity(
        opportunity_id="illegal-overlap",
        frontier_ticks=frontier + 1800 * supervisor.timer_hz + 1,
        disposition="APPLICATION_REQUESTED",
    )
    assert supervisor.terminal == supervisor.contract["terminals"][
        "controller_or_transaction_fault"
    ]

    endpoint = _established_supervisor()
    endpoint_frontier = endpoint.armed_ticks
    assert endpoint_frontier is not None
    endpoint.record_control_opportunity(
        opportunity_id="unclosed-opportunity",
        frontier_ticks=endpoint_frontier + 1,
        disposition="APPLICATION_REQUESTED",
    )
    endpoint.observe_interval(
        opening_ticks=endpoint_frontier,
        closing_ticks=endpoint_frontier + endpoint.target_ticks,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
    )
    assert endpoint.qualified_ticks == endpoint.target_ticks
    assert endpoint.terminal == endpoint.contract["terminals"][
        "controller_or_transaction_fault"
    ]
    assert endpoint.summary()["endpoint_quiescent"] is False


def test_exact_response_reserve_closes_new_application_admission() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
    reserve_ticks = 1500 * supervisor.timer_hz
    supervisor.observe_interval(
        opening_ticks=frontier,
        closing_ticks=frontier + supervisor.target_ticks - reserve_ticks,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
    )
    closing = supervisor.last_observation_ticks
    assert closing is not None
    supervisor.record_control_opportunity(
        opportunity_id="endpoint-closed",
        frontier_ticks=closing,
        disposition="ENDPOINT_ADMISSION_CLOSED",
    )
    assert supervisor.terminal is None

    supervisor.record_control_opportunity(
        opportunity_id="too-late-request",
        frontier_ticks=closing + 1,
        disposition="APPLICATION_REQUESTED",
    )
    assert supervisor.terminal == supervisor.contract["terminals"][
        "controller_or_transaction_fault"
    ]


@pytest.mark.parametrize("applied_code", [0xA83C + 22, 0xAB00 + 1])
def test_step_and_range_envelopes_fail_static(applied_code: int) -> None:
    supervisor = _established_supervisor()
    supervisor.record_automatic_application(
        requested_from_code=0xA83C,
        applied_code=applied_code,
        applied_epoch=2,
        application_ticks=200 + 1800 * supervisor.timer_hz,
        outstanding_transactions_before_request=0,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
        response_complete=True,
    )
    assert supervisor.terminal == supervisor.contract["terminals"][
        "controller_or_transaction_fault"
    ]


def test_pty_rehearsal_exercises_capture_commands_abort_rotation_and_72h_counter(
    tmp_path: Path,
) -> None:
    report = programme.pty_operational_rehearsal(
        bundle=_bundle(tmp_path),
        output_dir=tmp_path / "rehearsal",
    )
    contract = programme.load_contract()

    assert report["status"] == "passed"
    assert report["hardware_operations"] is False
    assert report["baud"] == 115200
    assert report["priority_abort_delivered"] is True
    assert report["rotation_owner_check"]["performed"] is False
    assert report["rotation_owner_check"]["reason"] == (
        "bounded_explicit_nonphysical_PTY_fixture_owner_seam"
    )
    assert report["rotation_owner_check"][
        "production_lsof_check_unchanged"
    ] is True
    assert report["commands_observed_in_order"][:4] == [
        "CONFIG?",
        "DUALCORE?",
        "DAC?",
        "ACTIVE?",
    ]
    assert report["commands_observed_in_order"][4].startswith(
        "ACTIVE SETUP 1 1 1 1000 1 0xA83C 1 "
    )
    assert report["accelerated_counter_result"]["terminal"] == contract[
        "terminals"
    ]["qualified_complete"]
    assert report["accelerated_counter_result"]["qualified_seconds"] == 259_200
    assert report["accelerated_counter_result"]["automatic_applications"] == 144
    assert report["accelerated_counter_result"][
        "cumulative_automatic_movement_codes"
    ] == 3024
    assert report["accelerated_counter_result"]["total_dac_writes"] == 145
    assert report["accelerated_counter_result"][
        "requested_automatic_movement_codes"
    ] == 3024
    assert report["accelerated_counter_result"][
        "net_automatic_movement_codes"
    ] == 0
    assert report["accelerated_counter_result"]["automatic_reversal_count"] == 143
    assert report["accelerated_counter_result"][
        "qualified_range_residence"
    ]["interior_code_ticks"] == report["accelerated_counter_result"][
        "qualified_ticks"
    ]
    assert report["accelerated_counter_result"]["endpoint_quiescent"] is True
    assert report["accelerated_counter_result"]["gnss_metadata_hold"][
        "run_or_measurement_failure"
    ] is False
    assert report["accelerated_counter_result"]["d6_local_degradation"][
        "affected_D14_D8_or_control"
    ] is False
    assert report["canonical_record_log"]["record_count"] > 1000
    assert report["monitor_replay"]["last_record_sha256"] == report[
        "accelerated_counter_result"
    ]["last_record_sha256"]
    assert report["analyzer_replay"]["summary"] == report[
        "accelerated_counter_result"
    ]
    assert report["finalization_rehearsal"]["status"] == "passed"
    assert report["finalization_rehearsal"]["registered"] is True
    assert report["waveform_evidence_status"] == (
        "unresolved_oscilloscope_deferred"
    )
    assert report["promotion_permitted"] is False
    assert report["activation_bindable"] is False
    assert report["rehearsal_class"] == "local_component_non_authorizing"
    assert "fresh_USB_auto_detect" in report["not_proved"]
    assert "production_lsof_sole_serial_owner_check" in report["not_proved"]
    assert "mandatory_exact_AT2_AH2_production_sidecars" in report["not_proved"]
