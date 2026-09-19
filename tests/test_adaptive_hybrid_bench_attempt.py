from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from host.otis_tools.adaptive_hybrid_contract import (
    ABSOLUTE_WALL_LIMIT_S,
    ARM_SUBMISSION_LIMIT,
    AUTOMATIC_APPLICATION_ADMISSION_DEADLINE_APERTURES,
    CAUSAL_STATE_CONTRACT_ID,
    CAUSAL_STATE_SCHEMA_VERSION,
    CONTRACT_ID,
    CORRECTION_RESPONSE_RESERVE_APERTURES,
    UNATTENDED_7_DAY_HYBRID_CONTROL,
    EXPECTED_BASE_FQBN,
    EXPECTED_BOARD_SERIAL,
    EXPECTED_COMPILE_FQBN,
    EXPECTED_HARDWARE_ID,
    EXPECTED_USB_PID,
    EXPECTED_USB_PRODUCT,
    EXPECTED_USB_VID,
    ENDPOINT_CONTRACT,
    FIRST_DEPENDENT_DECISION_RESERVE_APERTURES,
    INHIBITED_ZERO_WRITE,
    PROGRESS_DOMAIN,
    QUALIFIED_APERTURE_MILESTONES,
    canonical_bench_attempt_sha256,
    envelope_for_purpose,
    validate_bench_attempt_envelope,
)


def _mutated(value):
    if value is None:
        return 0
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return f"{value}_changed"
    if isinstance(value, list):
        return [0]
    raise AssertionError(f"unhandled leaf type {type(value)!r}")


def _leaf_paths(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaf_paths(item, (*prefix, key))
        return
    if isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaf_paths(item, (*prefix, index))
        return
    yield prefix


def _replace_path(value, path, replacement):
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement


@pytest.mark.parametrize(
    ("purpose", "expected_limits"),
    [
        (
            INHIBITED_ZERO_WRITE,
            {
                "setup_application_limit": 0,
                "automatic_application_limit": 0,
                "required_completed_automatic_applications": 0,
                "arm_submission_limit": 0,
                "total_dac_value_write_limit": 0,
                "maximum_outstanding_requests": 0,
                "setup_code": None,
            },
        ),
        (
            UNATTENDED_7_DAY_HYBRID_CONTROL,
            {
                "setup_application_limit": 1,
                "automatic_application_limit": 336,
                "required_completed_automatic_applications": 0,
                "arm_submission_limit": ARM_SUBMISSION_LIMIT,
                "total_dac_value_write_limit": 337,
                "maximum_outstanding_requests": 1,
                "setup_code": 0xA84D,
            },
        ),
    ],
)
def test_exact_closed_purpose_envelopes(purpose, expected_limits):
    envelope = envelope_for_purpose(purpose)
    document = envelope.as_dict()

    assert document["schema_version"] == 2
    assert document["contract"] == CONTRACT_ID
    assert document["purpose"] == purpose
    for key, expected in expected_limits.items():
        assert document["authority"][key] == expected
    assert document["authority"]["automatic_retry_permitted"] is False
    assert document["authority"]["arm_retry_permitted"] is False
    assert document["authority"]["arm_submission_scope"] == (
        "distinct_natural_correction_opportunities"
    )
    assert document["authority"]["restore_write_permitted"] is False
    assert document["authority"]["attempt_extension_permitted"] is False
    assert document["authority"]["forced_correction_permitted"] is False
    assert document["terminal_semantics"]["natural_correction_only"] is True
    assert document["terminal_semantics"]["no_retry"] is True
    assert document["terminal_semantics"]["no_restore"] is True
    assert document["terminal_semantics"]["no_extension"] is True
    assert validate_bench_attempt_envelope(document) == envelope


def test_device_identity_is_exactly_frozen():
    identity = envelope_for_purpose(
        UNATTENDED_7_DAY_HYBRID_CONTROL
    ).as_dict()[
        "device_identity"
    ]

    assert identity == {
        "expected_board_serial": EXPECTED_BOARD_SERIAL,
        "expected_hardware_id": EXPECTED_HARDWARE_ID,
        "expected_usb_vid": EXPECTED_USB_VID,
        "expected_usb_pid": EXPECTED_USB_PID,
        "expected_usb_product": EXPECTED_USB_PRODUCT,
        "expected_board_name": "Arduino Nano RP2040 Connect",
        "expected_base_fqbn": EXPECTED_BASE_FQBN,
        "expected_compile_fqbn": EXPECTED_COMPILE_FQBN,
    }


@pytest.mark.parametrize(
    "purpose", [INHIBITED_ZERO_WRITE, UNATTENDED_7_DAY_HYBRID_CONTROL]
)
def test_timing_is_in_exact_d14_d8_apertures_with_separate_wall_bound(purpose):
    timing = envelope_for_purpose(purpose).as_dict()["timing"]

    assert timing["progress_domain"] == PROGRESS_DOMAIN
    assert timing["endpoint_contract"] == ENDPOINT_CONTRACT
    assert timing["correction_response_reserve_delta"] == (
        CORRECTION_RESPONSE_RESERVE_APERTURES
    )
    assert timing["first_dependent_decision_reserve_delta"] == (
        FIRST_DEPENDENT_DECISION_RESERVE_APERTURES
    )
    expected_wall_s = (
        300 if purpose == INHIBITED_ZERO_WRITE else ABSOLUTE_WALL_LIMIT_S
    )
    assert timing["absolute_wall_limit_s"] == expected_wall_s
    if purpose == INHIBITED_ZERO_WRITE:
        assert timing["wall_limit_origin"] == "supervisor_monotonic_start_after_capture_ready"
    else:
        assert timing["wall_limit_origin"] == "supervisor_monotonic_start_after_capture_ready"
    assert timing["wall_limit_role"] == (
        "fixed_host_observation_endpoint"
    )
    assert all("16" not in key for key in timing)


def test_long_run_application_admission_deadline_is_exact():
    timing = envelope_for_purpose(
        UNATTENDED_7_DAY_HYBRID_CONTROL
    ).as_dict()["timing"]
    assert timing["automatic_application_admission_deadline_delta"] == (
        AUTOMATIC_APPLICATION_ADMISSION_DEADLINE_APERTURES
    )


@pytest.mark.parametrize(
    "purpose", [INHIBITED_ZERO_WRITE, UNATTENDED_7_DAY_HYBRID_CONTROL]
)
def test_causal_state_closes_authority_and_disagreement_holds_for_review(purpose):
    document = envelope_for_purpose(purpose).as_dict()
    state = document["causal_state"]
    discrepancy = document["host_discrepancy_semantics"]

    assert state["schema_version"] == CAUSAL_STATE_SCHEMA_VERSION
    assert state["contract"] == CAUSAL_STATE_CONTRACT_ID
    assert state["durable_ACT_application_count"]["source"] == (
        "durable_validated_ACT_application_records"
    )
    assert state["firmware_correction_count"]["source"] == (
        "causally_complete_firmware_snapshot_for_same_request_sequence"
    )
    assert state["count_comparison_precondition"] == (
        "ACT_and_firmware_snapshot_causally_complete_for_same_request_sequence"
    )
    assert state["count_mismatch_transition"] == "operator_review_hold"
    assert state["authority_closed"]["reopening_permitted"] is False
    assert state["authority_closed"]["new_ARM_permitted_when_closed"] is False
    assert discrepancy == {
        "transition": "operator_review_hold",
        "new_setup_authority": False,
        "new_ARM_authority": False,
        "automatic_abort_authority": False,
        "automatic_teardown_authority": False,
        "failed_campaign_authority": False,
        "retain_capture_and_serial_owner": True,
        "preserve_last_confirmed_code": True,
        "preserve_exact_pending_phase_identity": True,
    }


def test_long_run_closes_only_at_the_application_limit():
    document = envelope_for_purpose(
        UNATTENDED_7_DAY_HYBRID_CONTROL
    ).as_dict()
    state = document["causal_state"]

    assert state["authority_closed"] == {
        "initial": False,
        "closure_trigger": "automatic_application_limit_reached",
        "source": "durable_bench_attempt_causal_state",
        "persistence_required": True,
        "persistence_order": "durable_before_phase_3_evidence_acknowledgement",
        "reopening_permitted": False,
        "new_ARM_permitted_when_closed": False,
    }
    assert state["durable_ACT_application_count"]["maximum"] == 336
    assert state["firmware_correction_count"]["maximum"] == 336
    assert document["terminal_semantics"][
        "zero_natural_correction_outcome"
    ] == "zero_natural_corrections_valid_at_qualified_endpoint"
    assert {key: document["monitoring_semantics"][key] for key in ("authoritative_source", "accepted_D14_D8_aperture_milestones", "first_application_milestone_nonterminal", "host_monitor_may_decide_terminal")} == {
        "authoritative_source": "retained_supervisor_state_and_capture_evidence",
        "accepted_D14_D8_aperture_milestones": list(
            QUALIFIED_APERTURE_MILESTONES
        ),
        "first_application_milestone_nonterminal": True,
        "host_monitor_may_decide_terminal": False,
    }


def test_zero_write_authority_is_closed_from_initial_state():
    state = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()["causal_state"]

    assert state["authority_closed"]["initial"] is True
    assert state["authority_closed"]["closure_trigger"] == (
        "initial_contract_state"
    )
    assert state["durable_ACT_application_count"]["maximum"] == 0
    assert state["firmware_correction_count"]["maximum"] == 0


def test_envelope_value_is_frozen():
    envelope = envelope_for_purpose(INHIBITED_ZERO_WRITE)

    with pytest.raises(FrozenInstanceError):
        envelope.purpose = UNATTENDED_7_DAY_HYBRID_CONTROL


def test_only_two_purposes_are_accepted():
    with pytest.raises(ValueError, match="unsupported bench-attempt purpose"):
        envelope_for_purpose("legacy_campaign")


@pytest.mark.parametrize(
    "purpose", [INHIBITED_ZERO_WRITE, UNATTENDED_7_DAY_HYBRID_CONTROL]
)
def test_every_leaf_mutation_is_rejected_even_with_recomputed_hash(purpose):
    original = envelope_for_purpose(purpose).as_dict()
    unsigned = {
        key: value for key, value in original.items() if key != "envelope_sha256"
    }

    for path in _leaf_paths(unsigned):
        changed = deepcopy(unsigned)
        cursor = changed
        for key in path:
            cursor = cursor[key]
        _replace_path(changed, path, _mutated(cursor))
        candidate = {
            **changed,
            "envelope_sha256": canonical_bench_attempt_sha256(changed),
        }
        with pytest.raises(ValueError):
            validate_bench_attempt_envelope(candidate)


def test_unknown_missing_and_stale_identity_are_rejected():
    original = envelope_for_purpose(
        UNATTENDED_7_DAY_HYBRID_CONTROL
    ).as_dict()

    unknown = deepcopy(original)
    unknown["authority"]["legacy_retry_limit"] = 1
    unsigned_unknown = {
        key: value for key, value in unknown.items() if key != "envelope_sha256"
    }
    unknown["envelope_sha256"] = canonical_bench_attempt_sha256(unsigned_unknown)

    missing = deepcopy(original)
    del missing["causal_state"]["authority_closed"]
    unsigned_missing = {
        key: value for key, value in missing.items() if key != "envelope_sha256"
    }
    missing["envelope_sha256"] = canonical_bench_attempt_sha256(unsigned_missing)

    stale = deepcopy(original)
    stale["purpose"] = INHIBITED_ZERO_WRITE

    for candidate in (unknown, missing, stale):
        with pytest.raises(ValueError):
            validate_bench_attempt_envelope(candidate)


def test_json_number_cannot_substitute_for_boolean():
    candidate = envelope_for_purpose(
        UNATTENDED_7_DAY_HYBRID_CONTROL
    ).as_dict()
    candidate["authority"]["automatic_retry_permitted"] = 0
    unsigned = {
        key: value for key, value in candidate.items() if key != "envelope_sha256"
    }
    candidate["envelope_sha256"] = canonical_bench_attempt_sha256(unsigned)

    with pytest.raises(ValueError):
        validate_bench_attempt_envelope(candidate)
