from __future__ import annotations

from copy import deepcopy
import csv

import pytest

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.active_hybrid_live_analyze import (
    _cx321_plant_sign_replay,
)
from host.otis_tools.contracts import (
    PPS_SNAPSHOT_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.cx321_plant_sign_evidence_guard import (
    PLANT_SIGN_QUALIFICATION_V1_FIELDS,
    PlantSignEvidenceError,
    PlantSignReplayContext,
    complete_plant_sign_evidence_chain,
    parse_psq_line,
    replay_plant_sign_evidence,
    replay_plant_sign_leading_prefix,
    replay_plant_sign_terminal_prefix,
    replay_plant_sign_windows_against_snapshots,
)
from host.otis_tools.run_loader import RunManifest
from host.otis_tools.time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS


DIGESTS = [f"{value:064x}" for value in range(1, 6)]
CONTEXT = PlantSignReplayContext(
    run_identity="cx321:test",
    build_identity=f"{DIGESTS[0]}:{DIGESTS[1]}",
    profile_identity="cx321_bounded_active_hybrid_plant_sign_v2",
    policy_sha256=DIGESTS[0],
    plant_sign_gate_sha256=DIGESTS[1],
    identification_estimator_sha256=DIGESTS[2],
    identification_estimator_config_sha256=DIGESTS[3],
    natural_frequency_estimator_sha256=DIGESTS[4],
    capture_session=41,
)


def _base(sequence: int, event: str) -> dict[str, str]:
    row = {field: "" for field in PLANT_SIGN_QUALIFICATION_V1_FIELDS}
    row.update({
        "record_type": "PSQ", "schema_version": "1",
        "qualification_record_sequence": str(sequence), "event": event,
        "event_timestamp_ticks": "0", "run_identity": CONTEXT.run_identity,
        "build_identity": CONTEXT.build_identity, "profile_identity": CONTEXT.profile_identity,
        "capture_session": str(CONTEXT.capture_session), "policy_sha256": CONTEXT.policy_sha256,
        "plant_sign_gate_sha256": CONTEXT.plant_sign_gate_sha256,
        "identification_estimator_sha256": CONTEXT.identification_estimator_sha256,
        "identification_estimator_config_sha256": CONTEXT.identification_estimator_config_sha256,
        "natural_frequency_estimator_sha256": CONTEXT.natural_frequency_estimator_sha256,
        "setup_application_sequence": "1", "setup_application_timestamp_ticks": "16000000",
        "setup_applied_code": str(0xA83C), "setup_dac_epoch": "1",
        "state_before": "PLANT_SIGN_QUALIFY", "state_after": "PLANT_SIGN_QUALIFY",
        "reason": event, "actionable": "false",
    })
    return row


def _window(row: dict[str, str], *, first: int, opened_s: int, total: int, epoch: int) -> None:
    close_s = opened_s + 1500
    row.update({
        "event_timestamp_ticks": str(close_s * 16_000_000), "total_count": str(total),
        "signed_error_counts": str(total - 15_000_000_000),
        "open_ticks": str(opened_s * 16_000_000), "close_ticks": str(close_s * 16_000_000),
        "source_first_sequence": str(first), "source_last_sequence": str(first + 1500),
        "accepted_intervals": "1500", "dac_epoch": str(epoch), "tight_state": "TIGHT_INSIDE",
    })


def _records() -> list[dict[str, str]]:
    pre1 = _base(1, "pre1")
    _window(pre1, first=901, opened_s=901, total=15_000_000_002, epoch=1)
    pre1.update({
        "state_before": "FREQUENCY_ACQUIRE",
        "state_after": "FREQUENCY_ACQUIRE",
        "reason": "first_pre_identification_window_accepted",
    })
    pre2 = _base(2, "pre2")
    _window(pre2, first=2401, opened_s=2401, total=15_000_000_002, epoch=1)
    pre2.update({
        "state_before": "FREQUENCY_ACQUIRE",
        "state_after": "PLANT_SIGN_QUALIFY",
        "reason": "identification_request_ready",
    })
    request = _base(3, "request")
    request.update({
        "event_timestamp_ticks": pre2["close_ticks"], "pre_error_counts": "2",
        "current_code": str(0xA83C), "request_sequence": "7",
        "requested_delta_codes": "-21", "requested_code": str(0xA827),
        "reason": "identification_request_created",
    })
    application = _base(4, "application")
    application.update({
        "event_timestamp_ticks": str(3902 * 16_000_000), "request_sequence": "7",
        "acceptance_sequence": "8", "application_sequence": "9",
        "requested_delta_codes": "-21", "requested_code": str(0xA827),
        "accepted_code": str(0xA827), "applied_code": str(0xA827),
        "application_timestamp_ticks": str(3902 * 16_000_000), "dac_epoch": "2",
        "reason": "identification_applied_response_pending",
    })
    response = _base(5, "response")
    _window(response, first=4802, opened_s=4802, total=14_999_999_997, epoch=2)
    response.update({key: application[key] for key in (
        "request_sequence", "acceptance_sequence", "application_sequence",
        "requested_delta_codes", "requested_code", "accepted_code", "applied_code",
        "application_timestamp_ticks",
    )})
    response.update({
        "pre_total_count": "15000000002", "post_total_count": "14999999997",
        "response_counts": "-5", "response_source_last_sequence": response["source_last_sequence"],
        "sign_pass": "true", "magnitude_pass": "true", "exact_evidence_pass": "true",
        "tight_reentry_pass": "true", "passed": "true",
        "state_after": "PLANT_SIGN_RESPONSE_ACK_PENDING",
        "reason": "identification_response_exact_ack_pending",
    })
    response["event_timestamp_ticks"] = response["close_ticks"]
    prefix = [pre1, pre2, request, application, response]
    attestation = replay_plant_sign_evidence(prefix, CONTEXT)
    common_echo = {key: application[key] for key in (
        "request_sequence", "acceptance_sequence", "application_sequence",
        "requested_delta_codes", "requested_code", "accepted_code", "applied_code",
        "application_timestamp_ticks", "dac_epoch",
    )}
    ack = _base(6, "response_ack")
    ack.update(common_echo)
    ack.update({
        "event_timestamp_ticks": str(6303 * 16_000_000), "response_counts": "-5",
        "response_source_last_sequence": response["response_source_last_sequence"],
        "acknowledged_response_record_sequence": "5", "host_replay_exact": "true",
        "replay_attestation_sha256": attestation["attestation_sha256"],
        "state_before": "PLANT_SIGN_RESPONSE_ACK_PENDING",
        "state_after": "PHASE_QUALIFY",
        "reason": "identification_response_acknowledged",
    })
    handoff = _base(7, "handoff")
    handoff.update(common_echo)
    handoff.update({
        "event_timestamp_ticks": str(6304 * 16_000_000), "state_after": "PHASE_QUALIFY",
        "response_counts": "-5", "response_source_last_sequence": response["response_source_last_sequence"],
        "acknowledged_response_record_sequence": "5", "host_replay_exact": "true",
        "replay_attestation_sha256": attestation["attestation_sha256"],
        "global_correction_count": "1", "global_cumulative_movement_codes": "21",
        "global_last_application_timestamp_ticks": application["application_timestamp_ticks"],
        "natural_chatter_origin_code": str(0xA827), "natural_cumulative_movement_codes": "0",
        "natural_direction_count": "0", "attested": "true",
        "state_before": "PHASE_QUALIFY",
        "reason": "plant_sign_first_natural_consumer_handoff_exact",
    })
    return prefix + [ack, handoff]


def _snapshots_for_records(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_sequence: dict[int, dict[str, str]] = {}
    next_origin = 3_000_000_000
    for window in (
        row
        for row in rows
        if row["event"] in {"pre1", "pre2", "response"}
    ):
        first = int(window["source_first_sequence"])
        last = int(window["source_last_sequence"])
        open_ticks = int(window["open_ticks"])
        target_total = int(window["total_count"])
        if first in by_sequence:
            counter = int(by_sequence[first]["cumulative_down_counter"])
        else:
            counter = next_origin
            next_origin = (next_origin - 700_000_000) & 0xFFFFFFFF
            by_sequence[first] = {
                "record_type": "SNP",
                "schema_version": "1",
                "session": str(CONTEXT.capture_session),
                "snapshot_sequence": str(first),
                "cumulative_down_counter": str(counter),
                "reference_sequence": str(first),
                "reference_timestamp_ticks": str(
                    open_ticks % RP2040_TIMER0_MICROS_WRAP_TICKS
                ),
                "status": "0",
                "backend": "pio_wait_cumulative_snapshot_dma_v1",
            }
        first_interval = target_total - 1_499 * 10_000_000
        for offset, sequence in enumerate(range(first + 1, last + 1), 1):
            count = first_interval if offset == 1 else 10_000_000
            counter = (counter - count) & 0xFFFFFFFF
            row = {
                "record_type": "SNP",
                "schema_version": "1",
                "session": str(CONTEXT.capture_session),
                "snapshot_sequence": str(sequence),
                "cumulative_down_counter": str(counter),
                "reference_sequence": str(sequence),
                "reference_timestamp_ticks": str(
                    (open_ticks + offset * CONTEXT.timer_hz)
                    % RP2040_TIMER0_MICROS_WRAP_TICKS
                ),
                "status": "0",
                "backend": "pio_wait_cumulative_snapshot_dma_v1",
            }
            if sequence in by_sequence:
                assert by_sequence[sequence] == row
            else:
                by_sequence[sequence] = row
    return [by_sequence[key] for key in sorted(by_sequence)]


def _analyzer_fixture(tmp_path, rows: list[dict[str, str]]):
    path = tmp_path / "csv/plant_sign_qualification_v1.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=PLANT_SIGN_QUALIFICATION_V1_FIELDS
        )
        writer.writeheader()
        writer.writerows(rows)
    snapshot_path = tmp_path / "csv/pps_snapshots.csv"
    with snapshot_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PPS_SNAPSHOT_FIELDS)
        writer.writeheader()
        writer.writerows(_snapshots_for_records(rows))
    manifest_value = {
        "run_identity": CONTEXT.run_identity,
        "profile_identity": CONTEXT.profile_identity,
        "firmware": {"build_identity": CONTEXT.build_identity},
        "programme_policy": {"sha256": CONTEXT.policy_sha256},
        "identification": {
            "bindings": {
                "plant_sign_gate": {
                    "sha256": CONTEXT.plant_sign_gate_sha256
                },
                "identification_estimator": {
                    "sha256": CONTEXT.identification_estimator_sha256
                },
                "natural_frequency_estimator": {
                    "sha256": CONTEXT.natural_frequency_estimator_sha256
                },
            },
            "estimator_runtime_config": {
                "sha256": CONTEXT.identification_estimator_config_sha256
            },
        },
    }
    manifest = RunManifest(
        root=tmp_path,
        path=tmp_path / "run_manifest.json",
        data={
            "files": [
                {
                    "contract": "plant_sign_qualification_v1",
                    "path": "csv/plant_sign_qualification_v1.csv",
                },
                {
                    "contract": "pps_snapshots_v1",
                    "path": "csv/pps_snapshots.csv",
                },
            ]
        },
    )
    return manifest, manifest_value


def test_exact_integer_replay_ack_and_handoff() -> None:
    result = replay_plant_sign_evidence(_records(), CONTEXT, require_ack_handoff=True)
    assert result["response_counts"] == -5
    assert result["passed"] is True
    assert result["ack_exact"] and result["handoff_exact"]


@pytest.mark.parametrize("length", range(1, 7))
def test_every_progressing_leading_prefix_replays_exactly(length: int) -> None:
    result = replay_plant_sign_leading_prefix(_records()[:length], CONTEXT)

    assert result["exact_replay"] is True
    assert result["record_count"] == length
    assert result["events"] == list(
        ("pre1", "pre2", "request", "application", "response", "response_ack")[
            :length
        ]
    )


@pytest.mark.parametrize("length", range(1, 7))
def test_every_leading_prefix_rejects_changed_identity(length: int) -> None:
    rows = deepcopy(_records()[:length])
    rows[-1]["policy_sha256"] = "0" * 64

    with pytest.raises(PlantSignEvidenceError, match="identity tuple differs"):
        replay_plant_sign_leading_prefix(rows, CONTEXT)


def test_partial_application_and_ack_mismatches_are_not_right_censored_exact() -> None:
    application = deepcopy(_records()[:4])
    application[-1]["applied_code"] = str(0xA828)
    with pytest.raises(PlantSignEvidenceError, match="application code tuple"):
        replay_plant_sign_leading_prefix(application, CONTEXT)

    acknowledgement = deepcopy(_records()[:6])
    acknowledgement[-1]["replay_attestation_sha256"] = "0" * 64
    with pytest.raises(PlantSignEvidenceError, match="attestation hash differs"):
        replay_plant_sign_leading_prefix(acknowledgement, CONTEXT)


def test_analyzer_strictly_replays_right_censored_prefix(tmp_path) -> None:
    manifest, value = _analyzer_fixture(tmp_path, _records()[:4])

    result = _cx321_plant_sign_replay(
        tmp_path,
        manifest,
        value,
        {"primary_decision": "operator_abort"},
    )

    assert result["exact_replay"] is True
    assert result["record_count"] == 4
    assert result["scientific_terminal_exact"] is False


def test_analyzer_corrects_exact_legacy_pre2_scientific_terminal(tmp_path) -> None:
    rows = deepcopy(_records()[:2])
    rows[1]["total_count"] = "15000000003"
    rows[1]["signed_error_counts"] = "3"
    rows[1].update(
        {
            "state_after": "PLANT_SIGN_NOT_EXERCISED",
            "reason": "second_pre_window_not_equal_and_tight",
        }
    )
    manifest, value = _analyzer_fixture(tmp_path, rows)

    result = _cx321_plant_sign_replay(
        tmp_path,
        manifest,
        value,
        {
            "result": "aborted",
            "primary_decision": "measurement_authority_or_platform_fault",
            "reason": (
                "cx321_live_supervisor_fault:live active_fail_static asserted"
            ),
        },
    )

    assert result["scientific_terminal_exact"] is True
    assert result["terminal_decision"] == (
        "plant_sign_qualification_not_exercised"
    )
    assert result[
        "legacy_supervisor_terminal_misclassification_corrected"
    ] is True


def test_analyzer_malformed_right_censored_prefix_is_platform_failure(
    tmp_path,
) -> None:
    rows = deepcopy(_records()[:2])
    rows[1]["source_first_sequence"] = "2402"
    rows[1]["source_last_sequence"] = "3902"
    manifest, value = _analyzer_fixture(tmp_path, rows)

    with pytest.raises(PlantSignEvidenceError, match="not contiguous"):
        _cx321_plant_sign_replay(
            tmp_path,
            manifest,
            value,
            {"primary_decision": "operator_abort"},
        )


def test_analyzer_accepts_empty_psq_only_before_nonplant_terminal(
    tmp_path,
) -> None:
    manifest, value = _analyzer_fixture(tmp_path, [])

    result = _cx321_plant_sign_replay(
        tmp_path,
        manifest,
        value,
        {"primary_decision": "operator_abort"},
    )
    assert result["terminal_preceded_pre1"] is True

    with pytest.raises(ValueError, match="scientific terminal lacks PSQ"):
        _cx321_plant_sign_replay(
            tmp_path,
            manifest,
            value,
            {"primary_decision": "plant_sign_qualification_not_exercised"},
        )


def test_psq_windows_reconstruct_exactly_from_raw_snapshots() -> None:
    rows = _records()[:5]

    result = replay_plant_sign_windows_against_snapshots(
        rows,
        _snapshots_for_records(rows),
        CONTEXT,
    )

    assert result["exact"] is True
    assert [item["event"] for item in result["window_proofs"]] == [
        "pre1",
        "pre2",
        "response",
    ]
    # The response window is already in extended epoch 1, but its retained
    # 1,500-second raw support does not itself cross the next raw wrap.
    assert result["window_proofs"][-1]["raw_timer_wrap_count"] == 0


def test_raw_snapshots_reject_an_injected_whole_extended_timer_wrap() -> None:
    rows = deepcopy(_records()[:5])
    rows[-1]["close_ticks"] = str(
        int(rows[-1]["close_ticks"])
        + RP2040_TIMER0_MICROS_WRAP_TICKS
    )
    rows[-1]["event_timestamp_ticks"] = rows[-1]["close_ticks"]

    with pytest.raises(PlantSignEvidenceError, match="extended span differs"):
        replay_plant_sign_windows_against_snapshots(
            rows,
            _snapshots_for_records(_records()[:5]),
            CONTEXT,
        )


def test_raw_snapshots_reject_a_whole_wrap_added_to_both_window_endpoints() -> None:
    original = _records()[:5]
    rows = deepcopy(original)
    rows[-1]["open_ticks"] = str(
        int(rows[-1]["open_ticks"]) + RP2040_TIMER0_MICROS_WRAP_TICKS
    )
    rows[-1]["close_ticks"] = str(
        int(rows[-1]["close_ticks"]) + RP2040_TIMER0_MICROS_WRAP_TICKS
    )
    rows[-1]["event_timestamp_ticks"] = rows[-1]["close_ticks"]

    with pytest.raises(PlantSignEvidenceError, match="first raw TIMER0 projection"):
        replay_plant_sign_windows_against_snapshots(
            rows,
            _snapshots_for_records(original),
            CONTEXT,
        )


def test_raw_snapshots_reject_changed_downcounter_total() -> None:
    rows = _records()[:5]
    snapshots = _snapshots_for_records(rows)
    target = next(
        row
        for row in snapshots
        if row["snapshot_sequence"] == rows[0]["source_last_sequence"]
    )
    target["cumulative_down_counter"] = str(
        (int(target["cumulative_down_counter"]) - 1) & 0xFFFFFFFF
    )

    with pytest.raises(PlantSignEvidenceError, match="total differs"):
        replay_plant_sign_windows_against_snapshots(rows, snapshots, CONTEXT)


def test_phase4_attestation_binds_psq_raw_snapshots_and_act_join() -> None:
    rows = _records()
    psq_replay = replay_plant_sign_evidence(rows[:5], CONTEXT)
    snapshot_proof = replay_plant_sign_windows_against_snapshots(
        rows[:5], _snapshots_for_records(rows[:5]), CONTEXT
    )
    response = rows[4]
    act_join = {
        "exact": True,
        "act_transaction_record_sequence": 5,
        "request_sequence": int(response["request_sequence"]),
        "application_sequence": int(response["application_sequence"]),
        "application_timestamp_s": 3902,
        "application_timestamp_ticks": int(
            response["application_timestamp_ticks"]
        ),
        "acknowledgement_lag_lower_bound_ticks": 0,
        "cross_core_actuator_ack_maximum_age_s": 30,
        "timer_hz": CONTEXT.timer_hz,
    }
    chain = complete_plant_sign_evidence_chain(
        psq_replay=psq_replay,
        snapshot_window_proof=snapshot_proof,
        act_response_join=act_join,
    )
    for row in rows[5:]:
        row["replay_attestation_sha256"] = chain["attestation_sha256"]

    result = replay_plant_sign_evidence(
        rows,
        CONTEXT,
        require_ack_handoff=True,
        expected_ack_attestation_sha256=chain["attestation_sha256"],
    )

    assert result["ack_attestation_sha256"] == chain["attestation_sha256"]
    assert chain["attestation_sha256"] != psq_replay["attestation_sha256"]
    changed_join = dict(act_join)
    changed_join["acknowledgement_lag_lower_bound_ticks"] = 1
    changed_chain = complete_plant_sign_evidence_chain(
        psq_replay=psq_replay,
        snapshot_window_proof=snapshot_proof,
        act_response_join=changed_join,
    )
    assert changed_chain["attestation_sha256"] != chain["attestation_sha256"]


def test_complete_attestation_rejects_tampered_raw_snapshot_proof() -> None:
    rows = _records()[:5]
    proof = replay_plant_sign_windows_against_snapshots(
        rows, _snapshots_for_records(rows), CONTEXT
    )
    proof["window_proofs"][0]["total_count"] += 1

    with pytest.raises(PlantSignEvidenceError, match="content differs"):
        complete_plant_sign_evidence_chain(
            psq_replay=replay_plant_sign_evidence(rows, CONTEXT),
            snapshot_window_proof=proof,
            act_response_join={"exact": True},
        )


def test_exact_partial_not_exercised_is_scientific() -> None:
    rows = deepcopy(_records()[:2])
    rows[0].update(
        {
            "state_before": "FREQUENCY_ACQUIRE",
            "state_after": "FREQUENCY_ACQUIRE",
            "reason": "first_pre_identification_window_accepted",
        }
    )
    rows[1]["total_count"] = "15000000003"
    rows[1]["signed_error_counts"] = "3"
    rows[1].update(
        {
            "state_before": "FREQUENCY_ACQUIRE",
            "state_after": "PLANT_SIGN_NOT_EXERCISED",
            "reason": "second_pre_window_not_equal_and_tight",
        }
    )

    result = replay_plant_sign_terminal_prefix(
        rows,
        CONTEXT,
        terminal_decision="plant_sign_qualification_not_exercised",
    )

    assert result["scientific_terminal_exact"] is True
    assert result["exact_replay"] is True
    assert result["scientific_rejection_predicates"] == [
        "pre_totals_not_equal"
    ]


def test_exact_one_row_entry_rejection_is_scientific() -> None:
    rows = deepcopy(_records()[:1])
    rows[0]["total_count"] = "15000000000"
    rows[0]["signed_error_counts"] = "0"
    rows[0].update(
        {
            "state_before": "FREQUENCY_ACQUIRE",
            "state_after": "PLANT_SIGN_NOT_EXERCISED",
            "reason": (
                "pre_identification_scientific_entry_band_not_satisfied"
            ),
        }
    )

    result = replay_plant_sign_terminal_prefix(
        rows,
        CONTEXT,
        terminal_decision="plant_sign_qualification_not_exercised",
    )

    assert result["scientific_terminal_exact"] is True
    assert result["scientific_rejection_predicates"] == [
        "pre1_entry_band_not_satisfied"
    ]


def test_exact_two_row_second_entry_band_rejection_is_scientific() -> None:
    rows = deepcopy(_records()[:2])
    rows[1]["total_count"] = "15000000000"
    rows[1]["signed_error_counts"] = "0"
    rows[1].update(
        {
            "state_after": "PLANT_SIGN_NOT_EXERCISED",
            "reason": (
                "pre_identification_scientific_entry_band_not_satisfied"
            ),
        }
    )

    result = replay_plant_sign_terminal_prefix(
        rows,
        CONTEXT,
        terminal_decision="plant_sign_qualification_not_exercised",
    )

    assert result["scientific_rejection_predicates"] == [
        "pre_totals_not_equal",
        "pre2_entry_band_not_satisfied",
    ]


def test_partial_not_exercised_support_discontinuity_is_platform_fault() -> None:
    rows = deepcopy(_records()[:2])
    rows[0].update(
        {
            "state_after": "FREQUENCY_ACQUIRE",
            "reason": "first_pre_identification_window_accepted",
        }
    )
    rows[1]["source_first_sequence"] = "2402"
    rows[1]["source_last_sequence"] = "3902"
    rows[1].update(
        {
            "state_after": "PLANT_SIGN_NOT_EXERCISED",
            "reason": "second_pre_window_not_equal_and_tight",
        }
    )
    with pytest.raises(PlantSignEvidenceError, match="not contiguous"):
        replay_plant_sign_terminal_prefix(
            rows,
            CONTEXT,
            terminal_decision="plant_sign_qualification_not_exercised",
        )


def test_exact_failed_response_is_scientific_without_ack() -> None:
    rows = deepcopy(_records()[:5])
    response = rows[-1]
    post_total = int(response["pre_total_count"]) + 3
    response.update(
        {
            "total_count": str(post_total),
            "signed_error_counts": str(post_total - 15_000_000_000),
            "post_total_count": str(post_total),
            "response_counts": "3",
            "sign_pass": "false",
            "magnitude_pass": "true",
            "passed": "false",
            "state_after": "FAIL_STATIC",
            "reason": "identification_response_failed",
        }
    )

    result = replay_plant_sign_terminal_prefix(
        rows,
        CONTEXT,
        terminal_decision="plant_sign_qualification_failed",
    )

    assert result["scientific_terminal_exact"] is True
    assert result["failed_predicates"] == ["sign_pass"]


def test_parser_requires_exact_psq_shape() -> None:
    row = _records()[0]
    line = ",".join(row[field] for field in PLANT_SIGN_QUALIFICATION_V1_FIELDS)
    assert parse_psq_line(line) == row
    with pytest.raises(PlantSignEvidenceError, match="field count"):
        parse_psq_line(line + ",extra")


def test_capture_splitter_and_contract_share_exact_psq_schema(tmp_path) -> None:
    target = tmp_path / "plant_sign_qualification_v1.csv"
    row = _records()[0]
    line = ",".join(row[field] for field in PLANT_SIGN_QUALIFICATION_V1_FIELDS)
    with CsvRecordSplitter(
        {"plant_sign_qualification_v1": target}
    ) as splitter:
        assert splitter.process_line(line) == "plant_sign_qualification_v1"

    result = validate_csv(
        target,
        CsvValidationContext(
            "plant_sign_qualification_v1",
            frozenset(),
            frozenset({"rp2040_timer0_extended"}),
        ),
    )
    assert result.ok, result.errors


@pytest.mark.parametrize(
    ("event", "field", "value", "message"),
    [
        ("response", "response_counts", "-4", "subtraction differs"),
        ("response", "sign_pass", "false", "sign_pass differs"),
        ("response_ack", "response_source_last_sequence", "999", "response source differs"),
        ("handoff", "natural_direction_count", "1", "natural direction history"),
    ],
)
def test_rejects_inexact_response_ack_or_handoff(event: str, field: str, value: str, message: str) -> None:
    rows = deepcopy(_records())
    target = next(row for row in rows if row["event"] == event)
    target[field] = value
    with pytest.raises(PlantSignEvidenceError, match=message):
        replay_plant_sign_evidence(rows, CONTEXT, require_ack_handoff=True)


def test_rejects_late_ack() -> None:
    rows = deepcopy(_records())
    ack = rows[5]
    ack["event_timestamp_ticks"] = str(int(rows[4]["event_timestamp_ticks"]) + 31 * 16_000_000)
    rows[6]["event_timestamp_ticks"] = ack["event_timestamp_ticks"]
    with pytest.raises(PlantSignEvidenceError, match="30-second deadline"):
        replay_plant_sign_evidence(rows, CONTEXT, require_ack_handoff=True)


@pytest.mark.parametrize(
    ("response_counts", "expected_sign", "expected_magnitude", "expected_pass"),
    [
        (-2, True, False, False),
        (-3, True, True, True),
        (-14, True, True, True),
        (-15, True, False, False),
        (3, False, True, False),
    ],
)
def test_exact_response_boundaries(
    response_counts: int,
    expected_sign: bool,
    expected_magnitude: bool,
    expected_pass: bool,
) -> None:
    rows = deepcopy(_records()[:5])
    response = rows[4]
    pre_total = int(response["pre_total_count"])
    post_total = pre_total + response_counts
    response.update(
        {
            "total_count": str(post_total),
            "signed_error_counts": str(post_total - 15_000_000_000),
            "post_total_count": str(post_total),
            "response_counts": str(response_counts),
            "sign_pass": str(expected_sign).lower(),
                "magnitude_pass": str(expected_magnitude).lower(),
                "passed": str(expected_pass).lower(),
                "state_after": (
                    "PLANT_SIGN_RESPONSE_ACK_PENDING"
                    if expected_pass
                    else "FAIL_STATIC"
                ),
                "reason": (
                    "identification_response_exact_ack_pending"
                    if expected_pass
                    else "identification_response_failed"
                ),
            }
        )

    result = replay_plant_sign_evidence(rows, CONTEXT)
    assert result["response_counts"] == response_counts
    assert result["passed"] is expected_pass
