from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from host.otis_tools.cx318_stage1_handoff import reconstruct_phase


PROFILE_PATH = Path("profiles/discipline/cx318_stage1_contracts_v1.json")
SCHEMA_PATH = Path("schemas/cx318_stage1_contracts_v1.schema.json")
FIRMWARE_ROOT = Path("firmware/arduino/otis_nano_rp2040_connect")


def _snapshot(sequence: int, counter: int) -> dict[str, str]:
    return {
        "record_type": "SNP",
        "schema_version": "1",
        "session": "1",
        "snapshot_sequence": str(sequence),
        "cumulative_down_counter": str(counter),
        "reference_sequence": str(sequence),
        "reference_timestamp_ticks": str(sequence * 100),
        "status": "0",
        "backend": "pio_wait_cumulative_snapshot_dma_v1",
    }


def _count(sequence: int, edges: int) -> dict[str, str]:
    return {"count_seq": str(sequence), "counted_edges": str(edges)}


def test_relative_phase_sign_and_determinism() -> None:
    snapshots = [_snapshot(1, 100), _snapshot(2, 89), _snapshot(3, 80)]
    counts = [_count(2, 11), _count(3, 9)]

    first, prefix = reconstruct_phase(
        snapshots,
        counts,
        nominal_edges=10,
        counter_width_bits=32,
        expected_backend="pio_wait_cumulative_snapshot_dma_v1",
        period_ns_per_cycle=100,
    )
    second, _ = reconstruct_phase(
        snapshots,
        counts,
        nominal_edges=10,
        counter_width_bits=32,
        expected_backend="pio_wait_cumulative_snapshot_dma_v1",
        period_ns_per_cycle=100,
    )

    assert prefix[2] == 1
    assert prefix[3] == 0
    assert first["full_run_movement_cycles"] == 0
    assert first["edge_error_distribution_counts"] == {"-1": 1, "1": 1}
    assert first["relative_phase_stream_sha256"] == second["relative_phase_stream_sha256"]


def test_down_counter_wrap_reconstructs_exactly() -> None:
    snapshots = [
        _snapshot(1, 2),
        _snapshot(2, 0xFFFFFFFE),
        _snapshot(3, 0xFFFFFFF9),
    ]
    counts = [_count(2, 4), _count(3, 5)]

    summary, prefix = reconstruct_phase(
        snapshots,
        counts,
        nominal_edges=5,
        counter_width_bits=32,
        expected_backend="pio_wait_cumulative_snapshot_dma_v1",
        period_ns_per_cycle=100,
    )

    assert prefix[2] == -1
    assert prefix[3] == -1
    assert summary["full_run_movement_cycles"] == -1


def test_stage1_contract_is_schema_valid_source_bound_and_non_actionable() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)

    for binding in profile["bindings"].values():
        if not isinstance(binding, dict) or "path" not in binding:
            continue
        source = Path(binding["path"])
        assert source.is_file()
        assert sha256(source.read_bytes()).hexdigest() == binding["sha256"]

    # CX317 is the oscillator model identity. CX318 labels this programme only.
    assert profile["oscillator_contract"]["oscillator_identity"] == "CX317"
    authority = profile["authority_separation"]
    assert authority["phase_preview_actionable"] is False
    assert authority["phase_preview_actuation_authorized"] is False
    assert authority["phase_preview_authorization_consumed"] is False
    assert authority["phase_preview_may_import_or_call_actuator_serial_or_i2c"] is False
    assert authority["phase_preview_may_mutate_frequency_controller_response_or_budget"] is False
    assert authority["phase_or_hybrid_value_may_influence_live_delta_or_eligibility"] is False


def test_hybrid_preview_requires_a_separate_telemetry_only_source_boundary() -> None:
    existing_preview = (FIRMWARE_ROOT / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    active_actuator = (FIRMWARE_ROOT / "otis_cx317_active_actuator.cpp").read_text(
        encoding="utf-8"
    )
    offline_handoff = Path("host/otis_tools/cx318_stage1_handoff.py").read_text(
        encoding="utf-8"
    )

    # The accepted frequency preview can feed bounded-active control, so future
    # relative-phase/hybrid code must not be inserted into this authority path.
    assert '#include "otis_cx317_active_live.h"' in existing_preview
    assert "otis_cx317_active_live_on_decision(" in existing_preview
    assert "otis_dac_ad5693r_set_raw(" in active_actuator

    # The Stage 1 reconstruction is intentionally offline and cannot reach any
    # serial, active-controller, actuator, DAC or I2C surface.
    forbidden = (
        "import serial",
        "otis_cx317_active_live",
        "otis_cx317_active_actuator",
        "otis_dac_ad5693r",
        "Wire.",
    )
    assert all(token not in offline_handoff for token in forbidden)
