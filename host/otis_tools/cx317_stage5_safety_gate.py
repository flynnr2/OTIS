"""Machine-verifiable, fail-closed Stage 5 physical safety gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import json
import math
from typing import Any


GATE_ID = "CX317_STAGE5_PHYSICAL_SAFETY_GATE_V1"
INTENDED_CODES = (0xA800, 0xA950, 0xAB00)
AD5693R_NOMINAL_REFERENCE_V = 2.5
AD5693R_INTERNAL_REFERENCE_GAIN1_TUE_FRACTION = 0.0016


@dataclass(frozen=True)
class GateCheck:
    check: str
    status: str
    threshold: str
    source: str
    result: str
    consequence: str = "no DAC-enabled flash or DAC command"


def _finite(value: Any) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    return float(value)


def _bounded_measurement(
    check: str,
    item: Any,
    *,
    value_key: str,
    uncertainty_key: str,
    minimum: float,
    maximum: float,
    units: str,
    source: str,
) -> GateCheck:
    if not isinstance(item, dict):
        return GateCheck(check, "unavailable", f"{minimum}..{maximum} {units}", source, "measurement object unavailable")
    value = _finite(item.get(value_key))
    uncertainty = _finite(item.get(uncertainty_key))
    instrument = item.get("instrument")
    conditional_bound = _finite(item.get("conditional_accuracy_bound_v"))
    direct_bench_screen = (
        item.get("direct_bench_screen_confirmed") is True
        and conditional_bound is not None
        and conditional_bound >= 0
    )
    if value is None or not instrument or (
        (uncertainty is None or uncertainty < 0) and not direct_bench_screen
    ):
        return GateCheck(
            check,
            "unavailable",
            f"value ± uncertainty wholly within {minimum}..{maximum} {units}",
            source,
            "value, nonnegative uncertainty, or instrument unavailable",
        )
    interval_allowance = (
        float(uncertainty)
        if uncertainty is not None and uncertainty >= 0
        else float(conditional_bound)
    )
    low = value - interval_allowance
    high = value + interval_allowance
    status = "pass" if low >= minimum and high <= maximum else "fail"
    basis = (
        f"accepted uncertainty {interval_allowance} {units}"
        if uncertainty is not None
        else f"conditional expired-calibration scale check {interval_allowance} {units}; accepted uncertainty unavailable; direct bench/operator screen explicitly confirmed"
    )
    return GateCheck(
        check,
        status,
        f"direct measured value and available interval screen wholly within {minimum}..{maximum} {units}",
        source,
        f"{value} {units}; {basis}; screened interval {low}..{high} {units}",
    )


def _screened_interval(item: Any) -> tuple[float, float, str] | None:
    if not isinstance(item, dict) or not item.get("instrument"):
        return None
    value = _finite(item.get("value_v"))
    uncertainty = _finite(item.get("uncertainty_v"))
    if value is None:
        return None
    if uncertainty is not None and uncertainty >= 0:
        return value - uncertainty, value + uncertainty, "accepted uncertainty"
    conditional = _finite(item.get("conditional_accuracy_bound_v"))
    if (
        item.get("direct_bench_screen_confirmed") is True
        and conditional is not None
        and conditional >= 0
    ):
        return (
            value - conditional,
            value + conditional,
            "conditional expired-calibration scale check; accepted uncertainty unavailable; direct bench/operator screen explicitly confirmed",
        )
    return None


def _confirmation(check: str, value: Any, source: str) -> GateCheck:
    return GateCheck(
        check,
        "pass" if value is True else "unavailable",
        "explicit true confirmation",
        source,
        f"confirmation={value!r}",
    )


def evaluate_gate(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != 1 or value.get("gate_id") != GATE_ID:
        raise ValueError("unsupported Stage 5 safety gate schema/id")
    topology = value.get("topology")
    measurements = value.get("measurements")
    live = value.get("live_checks")
    if not isinstance(topology, dict) or not isinstance(measurements, dict) or not isinstance(live, dict):
        raise ValueError("Stage 5 safety gate sections are malformed")

    checks: list[GateCheck] = []
    exact_topology = (
        topology.get("oscillator_part") == "CX317 VCOCXO"
        and topology.get("dac_part") == "AD5693R"
        and topology.get("dac_i2c_address") == "0x4C"
        and topology.get("dac_reference_mode") == "internal_2p5v_power_up_default"
        and topology.get("dac_gain_mode") == "1x_power_up_default"
        and topology.get("dac_to_vc_network_unchanged_confirmed") is True
        and topology.get("conditioner_and_pps_topology_unchanged_confirmed") is True
        and topology.get("common_ground_confirmed") is True
    )
    checks.append(
        GateCheck(
            "topology_and_dac_identity",
            "pass" if exact_topology else "unavailable",
            "exact CX317/AD5693R 0x4C/internal-2.5-V/1x/common-ground topology",
            "Stage 5 mandatory checkpoint; operator confirmation and exact source inspection",
            f"exact_match={exact_topology}",
        )
    )
    checks.extend(
        [
            _bounded_measurement(
                "cx317_vdd",
                measurements.get("cx317_vdd"),
                value_key="value_v",
                uncertainty_key="uncertainty_v",
                minimum=3.13,
                maximum=3.47,
                units="V",
                source="CX317 datasheet p. 2 recommended operating Vdd",
            ),
            _bounded_measurement(
                "conditioner_vcc",
                measurements.get("conditioner_vcc"),
                value_key="value_v",
                uncertainty_key="uncertainty_v",
                minimum=1.65,
                maximum=5.5,
                units="V",
                source="TI SN74LVC1G17 datasheet p. 5, section 5.3 recommended Vcc",
            ),
            _bounded_measurement(
                "ad5693r_vdd",
                measurements.get("ad5693r_vdd"),
                value_key="value_v",
                uncertainty_key="uncertainty_v",
                minimum=2.7,
                maximum=5.5,
                units="V",
                source="Analog Devices AD5693R Rev. E p. 5 Table 2 POWER REQUIREMENTS (gain 1); Adafruit breakout guide p. 5 Power Pins",
            ),
        ]
    )

    intended = measurements.get("intended_vc")
    intended_by_code = (
        {item.get("code"): item for item in intended if isinstance(item, dict)}
        if isinstance(intended, list)
        else {}
    )
    if set(intended_by_code) != set(INTENDED_CODES) or len(intended or []) != 3:
        checks.append(
            GateCheck(
                "intended_code_set",
                "fail",
                "exactly 0xA800, 0xA950 and 0xAB00",
                "Stage 5 mandatory low/centre/high connected-Vc checkpoint",
                f"observed_codes={sorted(item for item in intended_by_code if isinstance(item, int))}",
            )
        )
    else:
        checks.append(
            GateCheck(
                "intended_code_set",
                "pass",
                "exactly 0xA800, 0xA950 and 0xAB00",
                "Stage 5 mandatory low/centre/high connected-Vc checkpoint",
                "exact code set present",
            )
        )
    for code in INTENDED_CODES:
        item = intended_by_code.get(code)
        measured = _bounded_measurement(
            f"connected_vc_0x{code:04X}",
            item,
            value_key="value_v",
            uncertainty_key="uncertainty_v",
            minimum=0.0,
            maximum=3.3,
            units="V",
            source="CX317 datasheet p. 2 recommended Vc; direct connected-node measurement",
        )
        calculated_bound_confirmed = (
            isinstance(item, dict)
            and item.get("manufacturer_topology_bound_confirmed") is True
            and exact_topology
        )
        if measured.status != "unavailable" or not calculated_bound_confirmed:
            checks.append(measured)
            continue
        ideal_v = AD5693R_NOMINAL_REFERENCE_V * code / 65536
        tue_v = (
            AD5693R_INTERNAL_REFERENCE_GAIN1_TUE_FRACTION
            * AD5693R_NOMINAL_REFERENCE_V
        )
        dac_upper_v = ideal_v + tue_v
        checks.append(
            GateCheck(
                f"connected_vc_0x{code:04X}",
                "pass" if 0.0 <= dac_upper_v <= 3.3 else "fail",
                "calculated connected Vc range 0 V through the guaranteed DAC upper bound must be wholly within the CX317 0.0..3.3 V recommended range",
                "Analog Devices AD5693R Rev. E p. 4 Table 2 (internal-reference/gain-1 TUE maximum 0.16% FSR and 2 kOhm test load), p. 19 transfer function; CX317 p. 2 Vc range/input impedance; explicit unchanged passive-series-network/common-ground confirmation",
                f"code=0x{code:04X}; ideal={ideal_v} V; TUE allowance={tue_v} V; AD5693R upper={dac_upper_v} V; passive series network into CX317 >=100 kOhm input cannot increase voltage; connected safety bound=0..{dac_upper_v} V; fresh direct Vc remains required for plant characterization, not first-write electrical safety",
            )
        )

    power = measurements.get("power_path")
    if isinstance(power, dict):
        peak = _finite(power.get("measured_peak_current_a"))
        peak_upper = _finite(power.get("measured_peak_current_upper_bound_a"))
        peak_u = _finite(power.get("current_uncertainty_a"))
        limit = _finite(power.get("buck_limit_a"))
        upstream = _finite(power.get("upstream_available_current_a"))
        upstream_u = _finite(power.get("upstream_uncertainty_a"))
        instrument = power.get("instrument")
    else:
        peak = peak_upper = peak_u = limit = upstream = upstream_u = None
        instrument = None
    direct_cold_start_observation = (
        peak_upper is not None
        and peak_upper >= 0.0
        and isinstance(power, dict)
        and power.get("upper_bound_exclusive") is True
        and power.get("measurement_location") == "3.3_v_output"
        and _finite(power.get("cold_start_room_temperature_c")) is not None
        and limit is not None
        and math.isclose(float(limit), 2.0, rel_tol=0.0, abs_tol=0.0)
    )
    if direct_cold_start_observation:
        passed = peak_upper < float(limit)
        checks.append(
            GateCheck(
                "power_path_current_margin",
                "pass" if passed else "fail",
                "observed cold-start 3.3 V output current indication < installed-board conservative 2.0 A limit (continuous); the reported indication is a measured result, not a new acceptance threshold",
                "direct assembled-rig operator measurement; Adafruit TPS62827 breakout page p. 2; TI TPS62827 datasheet pp. 3-4; Fluke 117 manual pp. 19 and 22",
                f"reported_peak<{peak_upper} A at approximately {power.get('cold_start_room_temperature_c')} C; nominal_margin>{float(limit) - peak_upper} A; method={power.get('peak_capture_method')!r}; display_update_rate_hz={power.get('display_update_rate_hz')!r}; sub_250ms_peak_excluded={power.get('sub_250ms_peak_excluded')!r}; accepted uncertainty unavailable",
            )
        )
    elif None in {peak, peak_u, limit, upstream, upstream_u} or not instrument:
        checks.append(
            GateCheck(
                "power_path_current_margin",
                "unavailable",
                "peak+uncertainty <= 2.0 A and upstream-uncertainty >= peak+uncertainty",
                "Adafruit TPS62827 breakout page p. 2 (2 A continuous board recommendation); TI TPS62827 datasheet pp. 3-4; USB breakout p. 1; direct whole-rail measurement",
                "current, uncertainty, upstream capability, or instrument unavailable",
            )
        )
    else:
        load_high = float(peak) + float(peak_u)
        upstream_low = float(upstream) - float(upstream_u)
        passed = (
            math.isclose(float(limit), 2.0, rel_tol=0.0, abs_tol=0.0)
            and load_high <= float(limit)
            and upstream_low >= load_high
        )
        checks.append(
            GateCheck(
                "power_path_current_margin",
                "pass" if passed else "fail",
                "installed-board limit exactly 2.0 A; peak+uncertainty <= 2.0 A; upstream-uncertainty >= peak+uncertainty",
                "Adafruit TPS62827 breakout page p. 2 (2 A continuous board recommendation); TI TPS62827 datasheet pp. 3-4; USB breakout p. 1; direct whole-rail measurement",
                f"load_high={load_high} A; buck_limit={limit} A; upstream_low={upstream_low} A",
            )
        )

    thermal = measurements.get("thermal")
    checks.append(
        _confirmation(
            "cx317_safe_thermal_state",
            thermal.get("cx317_safe_thermal_state_operator_confirmed")
            if isinstance(thermal, dict)
            else None,
            "Stage 5 permits direct measurement or explicit operator confirmation; SHT41 near-air is proxy only",
        )
    )

    d8_dc = measurements.get("d8_dc_logic")
    conditioner = measurements.get("conditioner_vcc")
    iovdd = d8_dc.get("nano_iovdd") if isinstance(d8_dc, dict) else None
    iovdd_value = _finite(iovdd.get("value_v")) if isinstance(iovdd, dict) else None
    iovdd_instrument = iovdd.get("instrument") if isinstance(iovdd, dict) else None
    iovdd_interval = _screened_interval(iovdd)
    iovdd_nominal_sufficiency = (
        isinstance(iovdd, dict)
        and iovdd.get("direct_bench_reading_sufficiency_confirmed") is True
    )
    if iovdd_value is None or not iovdd_instrument:
        nano_operating_status = "unavailable"
        nano_operating_result = "Nano 3V3 value or instrument unavailable"
        nano_operating_pass = False
    elif iovdd_interval is not None and iovdd_interval[0] >= 3.25 and iovdd_interval[1] <= 3.35:
        nano_operating_status = "pass"
        nano_operating_pass = True
        nano_operating_result = (
            f"screened interval={iovdd_interval[0]}..{iovdd_interval[1]} V; "
            f"basis={iovdd_interval[2]}"
        )
    elif iovdd_nominal_sufficiency:
        nano_operating_pass = 3.25 <= iovdd_value <= 3.35
        nano_operating_status = "pass" if nano_operating_pass else "fail"
        nano_operating_result = (
            f"direct indicated value={iovdd_value} V; nominal lower margin="
            f"{iovdd_value - 3.25} V; nominal upper margin={3.35 - iovdd_value} V; "
            "operator explicitly judged the DMM reading adequate for this direct "
            "bench screen; accepted calibrated uncertainty remains unavailable"
        )
    else:
        nano_operating_status = "fail" if not 3.25 <= iovdd_value <= 3.35 else "unavailable"
        nano_operating_pass = False
        nano_operating_result = (
            f"direct indicated value={iovdd_value} V; available interval does not "
            "remain wholly within 3.25..3.35 V and no explicit bench-reading "
            "sufficiency confirmation is recorded"
        )
    checks.append(
        GateCheck(
            "nano_v3v3_operating_screen",
            nano_operating_status,
            "direct indicated Nano V3V3 within 3.25..3.35 V, with either an applicable interval or explicit operator confirmation that the DMM reading is adequate for this bench screen",
            "Arduino Nano RP2040 Connect datasheet p. 7 section 2.1, V3V3 recommended operating row; direct assembled-rig Fluke 117 reading; explicit operator measurement-sufficiency confirmation",
            nano_operating_result,
        )
    )
    if not isinstance(conditioner, dict) or not isinstance(iovdd, dict):
        status = "unavailable"
        result = "conditioner VCC or Nano IOVDD measurement object unavailable"
    else:
        conditioner_interval = _screened_interval(conditioner)
        if conditioner_interval is None or iovdd_interval is None:
            status = "unavailable"
            result = "conditioner VCC/Nano IOVDD direct interval screen or instrument unavailable"
        else:
            conditioner_low, conditioner_high, conditioner_basis = conditioner_interval
            iovdd_low, iovdd_high, iovdd_basis = iovdd_interval
            # G17 guarantees VOH >= VCC-0.1 V and VOL <= 0.1 V at
            # |IO|=100 uA. RP2040 input leakage is <=1 uA, so the G17 test
            # load is conservative for this one input. Use the stricter
            # Nano/RP2040 input thresholds and the Nano's 3.3 V input maximum.
            guaranteed_high_low = conditioner_low - 0.1
            guaranteed_low_high = 0.1
            vih_limit = 2.31
            vil_limit = 0.8
            gpio_input_operating_maximum = iovdd_low + 0.3
            gpio_input_absolute_maximum = iovdd_low + 0.5
            passed = (
                nano_operating_pass
                and iovdd_low >= -0.5
                and iovdd_high <= 3.63
                and guaranteed_high_low >= vih_limit
                and guaranteed_low_high <= vil_limit
                and conditioner_high <= gpio_input_operating_maximum
                and conditioner_high <= gpio_input_absolute_maximum
            )
            status = "pass" if passed else "fail"
            result = (
                f"Nano IOVDD conservative scale interval={iovdd_low}..{iovdd_high} V "
                f"vs RP2040 absolute IOVDD range -0.5..3.63 V; "
                f"G17 VCC interval={conditioner_low}..{conditioner_high} V; "
                f"guaranteed VOH>={guaranteed_high_low} V vs VIH>={vih_limit} V; "
                f"guaranteed VOL<={guaranteed_low_high} V vs VIL<={vil_limit} V; "
                f"normal output maximum<={conditioner_high} V vs RP2040 operating input maximum {gpio_input_operating_maximum} V and absolute maximum {gpio_input_absolute_maximum} V; "
                f"conditioner basis={conditioner_basis}; Nano basis={iovdd_basis}"
            )
    checks.append(
        GateCheck(
            "d8_dc_logic_compatibility",
            status,
            "separate Nano V3V3 operating screen must pass; conservative Nano IOVDD interval within RP2040 -0.5..3.63 V absolute range; calculated G17 VOH >= 2.31 V and VOL <= 0.8 V; G17 output upper bound <= IOVDD_low+0.3 V operating and IOVDD_low+0.5 V absolute maxima",
            "TI SN74LVC1G17 pp. 5-6 §5.3/Table 5-1; RP2040 datasheet pp. 617-618 Tables 621/624; Nano RP2040 Connect datasheet p. 7 §2.1; Nano full pinout p. 1",
            result,
        )
    )

    for key in (
        "dac_enabled_profile_address_and_init_confirmed",
        "dac_enabled_boot_applied_code_unavailable_confirmed",
        "manual_dac_ack_record_contract_confirmed",
        "capture_fifo_live_confirmed",
        "independent_abort_path_live_confirmed",
        "abort_is_fail_static_without_restore_confirmed",
        "final_safe_code_and_vc_operator_confirmed",
    ):
        checks.append(_confirmation(key, live.get(key), "Stage 5 mandatory live checkpoint"))
    final_code_ok = live.get("final_safe_code") == 0xA950
    checks.append(
        GateCheck(
            "final_safe_code_identity",
            "pass" if final_code_ok else "fail",
            "exact reviewed final-safe code 0xA950",
            "campaign plan and explicit operator confirmation; historical value alone is not authority",
            f"code={live.get('final_safe_code')!r}",
        )
    )
    authorization_ok = (
        value.get("authorization_status") == "operator_confirmed_ready"
        and bool(value.get("authorized_by"))
        and bool(value.get("authorized_at_utc"))
    )
    checks.append(
        GateCheck(
            "explicit_operator_authorization",
            "pass" if authorization_ok else "unavailable",
            "operator_confirmed_ready with identity and UTC timestamp",
            "Stage 5 mandatory checkpoint",
            f"authorization_status={value.get('authorization_status')!r}",
        )
    )
    passed = all(item.status == "pass" for item in checks)
    return {
        "schema_version": 1,
        "gate_id": GATE_ID,
        "decision": "pass" if passed else "not_ready",
        "hardware_execution_authorized": passed,
        "checks": [asdict(item) for item in checks],
        "status_counts": {
            status: sum(item.status == status for item in checks)
            for status in ("pass", "fail", "unavailable")
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Stage 5 physical safety gate.")
    parser.add_argument("gate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.gate.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("gate must be a JSON object")
        result = evaluate_gate(value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text, end="")
    return 0 if result["decision"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
