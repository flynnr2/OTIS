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


def test_explicit_count_query_reports_live_pps_queue_state() -> None:
    sketch = SKETCH.read_text(encoding="utf-8")
    query_handler = sketch.split(
        "command.kind == OtisSerialCommandKind::Fc0Query", 1
    )[1].split("#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE", 1)[0]

    assert "otis_count_observation_emit_runtime_status(" in query_handler
    assert "otis_count_observation_emit_status(" in query_handler
