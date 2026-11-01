from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKETCH = (
    ROOT
    / "firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino"
)
COUNT_SOURCE = (
    ROOT
    / "firmware/arduino/otis_nano_rp2040_connect/otis_count_observation.cpp"
)


def test_count_path_runtime_status_is_owned_by_count_observation_module() -> None:
    sketch = SKETCH.read_text(encoding="utf-8")
    count_source = COUNT_SOURCE.read_text(encoding="utf-8")

    assert "void emit_count_path_status" not in sketch
    assert "otis_count_observation_emit_runtime_status(" in sketch
    assert "void otis_count_observation_emit_runtime_status(" in count_source
    for key in (
        '"observation_valid"',
        '"measurement_mode"',
        '"control_eligible"',
        '"fault_latched"',
        '"last_counted_edges"',
    ):
        assert key in count_source


def test_configuration_query_reports_snapshot_queue_capacity() -> None:
    count_source = COUNT_SOURCE.read_text(encoding="utf-8")
    configuration_status = count_source.split(
        "void otis_count_observation_emit_configuration_status(", 1
    )[1].split("const char *otis_count_observation_measurement_mode", 1)[0]

    assert "otis_pps_snapshot_backend_get_stats(&snapshot_stats);" in configuration_status
    assert '"snapshot_ring_capacity"' in configuration_status


def test_explicit_count_query_requests_the_core1_runtime_snapshot() -> None:
    sketch = SKETCH.read_text(encoding="utf-8")
    query_handler = sketch.split(
        "command.kind == OtisSerialCommandKind::CountQuery", 1
    )[1].split("command.kind == OtisSerialCommandKind::ActiveQuery", 1)[0]

    assert "OtisRunControlKind::DiagnosticRuntimeQuery" in query_handler
    assert '"timing_runtime_snapshot"' in query_handler
    assert "queued_to_core1" in query_handler


def test_count_status_uses_supplied_sink_and_timing_callers_supply_core1_context():
    count = COUNT_SOURCE.read_text()
    emitters = count.split("void emit_status(", 1)[1].split(
        "const char *bool_text(", 1
    )[0]
    assert "otis_dual_core_publish_telemetry" not in emitters
    assert "otis_status_emit(context," in emitters
    assert "otis_status_emit_u32(context," in emitters
    sketch = SKETCH.read_text()
    for name in (
        "otis_count_observation_begin",
        "otis_count_observation_service",
        "otis_count_observation_on_pps_boundary",
        "otis_count_observation_note_capture_loss",
        "otis_count_observation_emit_status",
        "otis_count_observation_emit_runtime_status",
        "otis_count_observation_emit_configuration_status",
    ):
        calls = sketch.split(name + "(")[1:]
        assert calls
        for call in calls:
            arguments = call.split(");", 1)[0]
            assert "&dual_core_timing_status_context" in arguments
            assert "&status_emit_context" not in arguments
