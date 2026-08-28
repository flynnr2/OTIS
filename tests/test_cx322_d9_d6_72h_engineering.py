from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import cx322_d9_d6_72h_engineering as programme
from host.otis_tools.active_control_supervisor import (
    RP2040_TIMER0_TICKS_PER_SECOND,
)


ROOT = Path(__file__).resolve().parents[1]


def _build_manifest(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    matrix = json.loads(
        (ROOT / "firmware/arduino/firmware_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    profile = next(
        item
        for item in matrix["profiles"]
        if item["id"] == "cx322_d9_d6_integration_engineering"
    )
    path = tmp_path / "build_manifest.json"
    path.write_text(
        json.dumps(
            {
                "provenance": {
                    "configuration": {
                        "profile_id": profile["id"],
                        "defines": profile["defines"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _bundle(tmp_path: Path) -> dict[str, object]:
    return programme.freeze_bundle(
        build_manifest_path=_build_manifest(tmp_path),
        source_revision="a" * 40,
    )


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
        "cx322_d9_d6_integration_engineering"
    )
    assert contract["serial"]["baud"] == 115200
    assert "--auto-detect" in contract["serial"]["selection"]
    assert contract["time"]["qualified_duration_s"] == 259_200
    assert contract["time"]["nominal_counter_hz"] == (
        RP2040_TIMER0_TICKS_PER_SECOND
    )
    assert contract["time"]["qualification_deadline_s"] == 5_400
    assert contract["time"]["absolute_wall_limit_s"] == 280_800
    assert contract["time"]["milestones_qualified_s"] == [
        21_600 * number for number in range(1, 13)
    ]
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
    assert checked["controller_envelope"]["automatic_application_limit"] == 4
    assert checked["controller_envelope"][
        "automatic_cumulative_movement_limit_codes"
    ] == 84
    assert checked["controller_envelope"]["automatic_step_limit_codes"] == 21
    assert checked["starting_dac"]["setup_write_limit"] == 1
    assert result["hardware_operations"] is False
    assert result["qualified_duration_s"] == 259_200
    assert result["promotion_permitted"] is False
    assert result["remaining_live_components"] == [
        "authorized_live_runner",
        "unattended_transition_monitor",
        "72h_scientific_analyzer",
        "immutable_finalizer_sealer_and_evidence_registration",
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
            source_revision="a" * 40,
        )

    bundle = _bundle(tmp_path / "second")
    manifest = Path(bundle["bindings"]["firmware_build_manifest"]["path"])
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bound-file identity differs"):
        programme.validate_bundle(bundle)


def test_setup_is_separate_from_four_applications_and_84_codes() -> None:
    supervisor = _established_supervisor()
    hz = supervisor.timer_hz
    code = 0xA83C
    for number, delta in enumerate((21, -21, 21, -21), start=1):
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
    assert supervisor.automatic_applications == 4
    assert supervisor.cumulative_movement_codes == 84
    assert supervisor.summary()["total_dac_writes"] == 5

    supervisor.record_automatic_application(
        requested_from_code=code,
        applied_code=code + 1,
        applied_epoch=6,
        application_ticks=200 + 5 * 1800 * hz,
        outstanding_transactions_before_request=0,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
        response_complete=True,
    )
    assert supervisor.terminal == supervisor.contract["terminals"][
        "controller_or_transaction_fault"
    ]


def test_exact_counter_milestones_and_d6_local_degradation() -> None:
    supervisor = _established_supervisor()
    frontier = supervisor.armed_ticks
    assert frontier is not None
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
    assert supervisor.d6_local_degraded_intervals == 2
    assert supervisor.terminal == supervisor.contract["terminals"][
        "qualified_complete"
    ]


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
    assert pre_setup.summary() == {
        "terminal": contract["terminals"]["pre_setup_no_write_abort"],
        "setup_establishments": 0,
        "automatic_applications": 0,
        "total_dac_writes": 0,
        "cumulative_automatic_movement_codes": 0,
        "qualified_ticks": 0,
        "qualified_seconds": 0,
        "milestones_qualified_s": [],
        "d6_local_degraded_intervals": 0,
        "last_confirmed_code": None,
        "last_confirmed_epoch": 0,
    }


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
    assert report["accelerated_counter_result"]["automatic_applications"] == 4
    assert report["accelerated_counter_result"][
        "cumulative_automatic_movement_codes"
    ] == 84
    assert report["waveform_evidence_status"] == (
        "unresolved_oscilloscope_deferred"
    )
    assert report["promotion_permitted"] is False
    assert "fresh_USB_auto_detect" in report["not_proved"]
    assert "production_lsof_sole_serial_owner_check" in report["not_proved"]
