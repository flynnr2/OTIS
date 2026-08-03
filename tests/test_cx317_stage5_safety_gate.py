from __future__ import annotations

from copy import deepcopy

import pytest

from host.otis_tools.cx317_stage5_safety_gate import evaluate_gate


def _measurement(value: float, uncertainty: float, instrument: str = "meter") -> dict:
    return {
        "value_v": value,
        "uncertainty_v": uncertainty,
        "instrument": instrument,
    }


def _passing_gate() -> dict:
    return {
        "schema_version": 1,
        "gate_id": "CX317_STAGE5_PHYSICAL_SAFETY_GATE_V1",
        "authorization_status": "operator_confirmed_ready",
        "authorized_by": "operator",
        "authorized_at_utc": "2026-08-02T00:00:00Z",
        "topology": {
            "oscillator_part": "CX317 VCOCXO",
            "dac_part": "AD5693R",
            "dac_i2c_address": "0x4C",
            "dac_reference_mode": "internal_2p5v_power_up_default",
            "dac_gain_mode": "1x_power_up_default",
            "dac_to_vc_network_unchanged_confirmed": True,
            "conditioner_and_pps_topology_unchanged_confirmed": True,
            "common_ground_confirmed": True,
        },
        "measurements": {
            "cx317_vdd": _measurement(3.292, 0.005),
            "conditioner_vcc": _measurement(3.292, 0.005),
            "ad5693r_vdd": _measurement(3.292, 0.005),
            "intended_vc": [
                {"code": 0xA800, **_measurement(1.635, 0.005)},
                {"code": 0xA950, **_measurement(1.648, 0.005)},
                {"code": 0xAB00, **_measurement(1.664, 0.005)},
            ],
            "power_path": {
                "measured_peak_current_a": 0.8,
                "current_uncertainty_a": 0.02,
                "buck_limit_a": 2.0,
                "upstream_available_current_a": 1.5,
                "upstream_uncertainty_a": 0.05,
                "instrument": "ammeter",
            },
            "thermal": {"cx317_safe_thermal_state_operator_confirmed": True},
            "d8_dc_logic": {
                "nano_iovdd": _measurement(3.292, 0.005),
                "waveform_scope_status": "not_tested_retained_limitation",
            },
        },
        "live_checks": {
            "dac_enabled_profile_address_and_init_confirmed": True,
            "dac_enabled_boot_applied_code_unavailable_confirmed": True,
            "manual_dac_ack_record_contract_confirmed": True,
            "capture_fifo_live_confirmed": True,
            "independent_abort_path_live_confirmed": True,
            "abort_is_fail_static_without_restore_confirmed": True,
            "final_safe_code": 0xA950,
            "final_safe_code_and_vc_operator_confirmed": True,
        },
    }


def test_complete_gate_passes_only_with_every_required_check() -> None:
    result = evaluate_gate(_passing_gate())
    assert result["decision"] == "pass"
    assert result["hardware_execution_authorized"] is True
    assert result["status_counts"] == {
        "pass": len(result["checks"]),
        "fail": 0,
        "unavailable": 0,
    }


def test_unknown_measurement_uncertainty_fails_closed() -> None:
    value = _passing_gate()
    value["measurements"]["cx317_vdd"]["uncertainty_v"] = None
    result = evaluate_gate(value)
    check = next(item for item in result["checks"] if item["check"] == "cx317_vdd")
    assert check["status"] == "unavailable"
    assert result["hardware_execution_authorized"] is False


def test_explicit_direct_bench_screen_can_use_conditional_scale_without_calibration_claim() -> None:
    value = _passing_gate()
    item = value["measurements"]["cx317_vdd"]
    item.update(
        uncertainty_v=None,
        conditional_accuracy_bound_v=0.01846,
        direct_bench_screen_confirmed=True,
    )
    result = evaluate_gate(value)
    check = next(item for item in result["checks"] if item["check"] == "cx317_vdd")
    assert check["status"] == "pass"
    assert "accepted uncertainty unavailable" in check["result"]
    assert result["hardware_execution_authorized"] is True


def test_operator_can_accept_nominal_nano_reading_while_logic_uses_conservative_interval() -> None:
    value = _passing_gate()
    item = value["measurements"]["d8_dc_logic"]["nano_iovdd"]
    item.update(
        value_v=3.265,
        uncertainty_v=None,
        conditional_accuracy_bound_v=0.018325,
        direct_bench_screen_confirmed=True,
        direct_bench_reading_sufficiency_confirmed=True,
    )
    result = evaluate_gate(value)
    operating = next(
        check
        for check in result["checks"]
        if check["check"] == "nano_v3v3_operating_screen"
    )
    logic = next(
        check
        for check in result["checks"]
        if check["check"] == "d8_dc_logic_compatibility"
    )
    assert operating["status"] == "pass"
    assert "accepted calibrated uncertainty remains unavailable" in operating["result"]
    assert logic["status"] == "pass"
    assert "3.246675" in logic["result"]
    assert result["hardware_execution_authorized"] is True


def test_nano_reading_with_interval_crossing_board_range_needs_explicit_sufficiency() -> None:
    value = _passing_gate()
    item = value["measurements"]["d8_dc_logic"]["nano_iovdd"]
    item.update(
        value_v=3.265,
        uncertainty_v=None,
        conditional_accuracy_bound_v=0.018325,
        direct_bench_screen_confirmed=True,
    )
    result = evaluate_gate(value)
    operating = next(
        check
        for check in result["checks"]
        if check["check"] == "nano_v3v3_operating_screen"
    )
    assert operating["status"] == "unavailable"
    assert result["hardware_execution_authorized"] is False


def test_prior_direct_cold_start_upper_bound_passes_power_screen_without_invented_uncertainty() -> None:
    value = _passing_gate()
    value["measurements"]["power_path"] = {
        "measured_peak_current_a": None,
        "measured_peak_current_upper_bound_a": 1.0,
        "upper_bound_exclusive": True,
        "measurement_location": "3.3_v_output",
        "cold_start_room_temperature_c": 25.0,
        "current_uncertainty_a": None,
        "buck_limit_a": 2.0,
        "upstream_available_current_a": None,
        "upstream_uncertainty_a": None,
        "instrument": None,
    }
    result = evaluate_gate(value)
    check = next(
        item
        for item in result["checks"]
        if item["check"] == "power_path_current_margin"
    )
    assert check["status"] == "pass"
    assert "uncertainty unavailable" in check["result"]
    assert "2.0 A limit" in check["threshold"]
    assert "not a new acceptance threshold" in check["threshold"]


def test_direct_cold_start_observation_is_rejected_at_board_limit() -> None:
    value = _passing_gate()
    value["measurements"]["power_path"] = {
        "measured_peak_current_a": None,
        "measured_peak_current_upper_bound_a": 2.0,
        "upper_bound_exclusive": True,
        "measurement_location": "3.3_v_output",
        "cold_start_room_temperature_c": 25.0,
        "current_uncertainty_a": None,
        "buck_limit_a": 2.0,
        "upstream_available_current_a": None,
        "upstream_uncertainty_a": None,
        "instrument": "display observation",
    }
    result = evaluate_gate(value)
    check = next(
        item
        for item in result["checks"]
        if item["check"] == "power_path_current_margin"
    )
    assert check["status"] == "fail"
    assert result["hardware_execution_authorized"] is False


def test_out_of_bounds_measurement_is_a_failure() -> None:
    value = _passing_gate()
    value["measurements"]["intended_vc"][2]["value_v"] = 3.3
    value["measurements"]["intended_vc"][2]["uncertainty_v"] = 0.01
    result = evaluate_gate(value)
    check = next(
        item for item in result["checks"] if item["check"] == "connected_vc_0xAB00"
    )
    assert check["status"] == "fail"
    assert result["hardware_execution_authorized"] is False


def test_manufacturer_and_unchanged_passive_topology_bound_first_code_safety() -> None:
    value = _passing_gate()
    for item in value["measurements"]["intended_vc"]:
        item["value_v"] = None
        item["uncertainty_v"] = None
        item["instrument"] = None
        item["manufacturer_topology_bound_confirmed"] = True
    result = evaluate_gate(value)
    checks = [
        item for item in result["checks"] if item["check"].startswith("connected_vc_")
    ]
    assert [item["status"] for item in checks] == ["pass", "pass", "pass"]
    assert "0..1.673921875 V" in checks[-1]["result"]
    assert result["hardware_execution_authorized"] is True


def test_calculated_code_bound_requires_explicit_unchanged_topology_confirmation() -> None:
    value = _passing_gate()
    item = value["measurements"]["intended_vc"][0]
    item.update(
        value_v=None,
        uncertainty_v=None,
        instrument=None,
        manufacturer_topology_bound_confirmed=True,
    )
    value["topology"]["dac_to_vc_network_unchanged_confirmed"] = False
    result = evaluate_gate(value)
    check = next(
        item for item in result["checks"] if item["check"] == "connected_vc_0xA800"
    )
    assert check["status"] == "unavailable"
    assert result["hardware_execution_authorized"] is False


def test_missing_abort_confirmation_fails_closed() -> None:
    value = deepcopy(_passing_gate())
    value["live_checks"]["independent_abort_path_live_confirmed"] = False
    result = evaluate_gate(value)
    assert result["decision"] == "not_ready"
    assert result["hardware_execution_authorized"] is False


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("iovdd", 3.20),
        ("conditioner_low", 2.40),
        ("conditioner_high", 3.90),
    ],
)
def test_d8_dc_calculation_uses_intersected_guaranteed_board_limits(
    target: str, value: float
) -> None:
    gate = _passing_gate()
    if target == "iovdd":
        gate["measurements"]["d8_dc_logic"]["nano_iovdd"]["value_v"] = value
    else:
        gate["measurements"]["conditioner_vcc"]["value_v"] = value
    result = evaluate_gate(gate)
    check = next(
        item
        for item in result["checks"]
        if item["check"] == "d8_dc_logic_compatibility"
    )
    assert check["status"] == "fail"
    assert result["hardware_execution_authorized"] is False


def test_d8_dc_gate_does_not_claim_scope_waveform_qualification() -> None:
    result = evaluate_gate(_passing_gate())
    check = next(
        item
        for item in result["checks"]
        if item["check"] == "d8_dc_logic_compatibility"
    )
    assert check["status"] == "pass"
    assert "scope" not in check["threshold"].lower()
