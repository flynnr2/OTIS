from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from host.otis_tools.range_spanning_bundle import (
    canonical_sha256,
    create_bundle,
    validate_bundle,
    validate_bundle_for_offline_reanalysis,
)
from host.otis_tools.range_spanning_rehearsal import run as run_rehearsal
from host.otis_tools.range_spanning_run import (
    _create_validated_evidence_snapshot,
    _find_epoch_propagation,
    _prewrite_ready,
    _runtime_fault,
    _wait,
)


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_build(tmp_path: Path) -> Path:
    artifacts = tmp_path / "firmware/artifacts"
    artifacts.mkdir(parents=True)
    uf2 = artifacts / "candidate.uf2"
    uf2.write_bytes(b"CX319 deterministic rehearsal UF2 identity\n")
    manifest = {
        "schema_version": 1,
        "provenance": {
            "configuration": {
                "profile_id": "cx319_range_map_part_a",
                "sha256": "1" * 64,
                "defines": {
                    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
                    "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW": "1",
                },
            },
            "target": {
                "fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133"
            },
            "source": {
                "sha256": "2" * 64,
                "state": "synthetic_rehearsal_fixture",
                "git_commit": "3" * 40,
            },
            "invocation": {"id": "4" * 64},
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
                "size_bytes": uf2.stat().st_size,
            }
        ],
        "resource_budget": {"status": "within_budget"},
    }
    manifest_path = artifacts / "firmware_build_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def test_bundle_is_immutable_and_rejects_a_rehashed_binding_tamper(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path),
        output_path=bundle_path,
        maximum_points=10,
    )
    bundle = validate_bundle(bundle_path)

    assert bundle["part_a_segment"]["survey_prefix"] == [
        0xA800,
        0xA820,
        0xA824,
        0xA828,
        0xA82C,
        0xA830,
        0xA834,
        0xA844,
        0xA848,
        0xA84C,
    ]
    assert bundle["part_a_segment"]["phase_hybrid_authority"] is False
    assert bundle["part_a_segment"]["maximum_expected_point_duration_s"] == 2700
    assert bundle["part_a_segment"]["point_wait_timeout_s"] == 2820
    assert (
        bundle["part_a_segment"]["minimum_remaining_wall_before_new_point_s"]
        == 3000
    )
    assert bundle["firmware"]["defines"]["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "0"

    tampered = json.loads(bundle_path.read_text(encoding="utf-8"))
    tampered["host_tools"]["runner"]["sha256"] = "0" * 64
    unsigned = {key: value for key, value in tampered.items() if key != "bundle_sha256"}
    tampered["bundle_sha256"] = canonical_sha256(unsigned)
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="bundle binding differs"):
        validate_bundle(tampered_path)


def test_offline_reanalysis_keeps_acquisition_bindings_but_not_old_host_tools(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path),
        output_path=bundle_path,
        maximum_points=10,
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["host_tools"]["contracts"] = {
        "path": str(tmp_path / "retired-contracts.py"),
        "sha256": "f" * 64,
        "size_bytes": 1,
    }
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = canonical_sha256(unsigned)
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="bundle binding differs"):
        validate_bundle(bundle_path)
    assert validate_bundle_for_offline_reanalysis(bundle_path)["bundle_sha256"] == (
        bundle["bundle_sha256"]
    )


def test_complete_operational_rehearsal_exercises_abort_rotation_and_analysis(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle.json"
    create_bundle(
        build_manifest_path=_synthetic_build(tmp_path),
        output_path=bundle_path,
        maximum_points=10,
    )

    result = run_rehearsal(
        bundle_path=bundle_path,
        output_dir=tmp_path / "rehearsal",
    )

    assert result["status"] == "passed"
    assert all(result["real_boundaries"].values())
    assert result["hardware_operations"] == {
        "serial_opens": 0,
        "firmware_flashes": 0,
        "dac_writes": 0,
    }
    assert result["unexercised_physical_boundaries"] == [
        "RP2040 USB CDC and cross-core runtime",
        "AD5693R I2C write and physical plant",
        "D14 PPS and D8 oscillator capture",
    ]


def test_live_runner_preserves_exact_application_and_zero_authority_guards() -> None:
    source = (ROOT / "host/otis_tools/range_spanning_run.py").read_text(
        encoding="utf-8"
    )

    assert 'command = f"DAC SET 0x{code:04X}"' in source
    assert "exact DAC acknowledgement" in source
    assert "cross-core preview propagation" in source
    assert "priority_abort_delivery" in source
    assert 'send_command_to_fifo(emergency_fifo, "ACTIVE ABORT")' in source
    assert "actuation_authorized" in source
    assert "range_spanning_finalization_failure_v1.json" in source
    assert 'result["evidence_finalization"]["status"] == "passed"' in source

    recovery = (ROOT / "host/otis_tools/range_spanning_reanalyze.py").read_text(
        encoding="utf-8"
    )
    assert "source package content identity differs" in recovery
    assert '"criterion_changed": False' in recovery
    assert '"raw_evidence_unchanged": True' in recovery
    assert '"hardware_interaction": False' in recovery
    assert '"actuation_authorized": False' in recovery


def test_live_runner_reads_the_snapshot_digest_from_the_created_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_path = tmp_path / "evidence_manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_digest": "a" * 64}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "host.otis_tools.range_spanning_run.create_evidence_snapshot",
        lambda run_dir: snapshot_path,
    )
    monkeypatch.setattr(
        "host.otis_tools.range_spanning_run.load_manifest",
        lambda run_dir: object(),
    )
    monkeypatch.setattr(
        "host.otis_tools.range_spanning_run.validate_evidence_snapshot",
        lambda run_dir, manifest: ([], []),
    )

    assert _create_validated_evidence_snapshot(tmp_path) == {
        "path": str(snapshot_path),
        "snapshot_digest": "a" * 64,
    }


def test_live_runtime_monitor_fails_on_stale_state_or_post_gate_health_fault(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    raw = tmp_path / "raw"
    csv_dir = tmp_path / "csv"
    reports.mkdir()
    raw.mkdir()
    csv_dir.mkdir()
    (raw / "serial.log").write_text("retained evidence\n", encoding="utf-8")
    capture_state = {
        "capture_active": True,
        "serial_open": True,
        "command_fifo_configured": True,
        "emergency_command_fifo_configured": True,
        "state_heartbeat_interval_s": 5.0,
        "normal_command_batch_limit": 1,
        "normal_command_max_age_s": 2.0,
        "write_timeout_s": 1.0,
        "malformed_utf8": 0,
        "parser_errors": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    state_path = reports / "capture_device_state.json"
    state_path.write_text(json.dumps(capture_state), encoding="utf-8")
    health_header = (
        "record_type,schema_version,status_seq,timestamp_ticks,status_domain,"
        "component,status_key,status_value,severity,flags\n"
    )
    values = [
        ("gnss_receiver", "identity_stable", "true"),
        ("gnss_receiver", "metadata_control_eligible", "true"),
        ("gnss_receiver", "raw_pps_control_eligible", "true"),
        ("dual_core", "partition_fault", "none"),
        ("dual_core", "fail_static", "false"),
        ("dual_core", "service_publish_failures", "0"),
        ("dual_core", "telemetry_dropped", "0"),
        ("capture", "dropped_count", "0"),
        ("capture", "pps_count_boundary_dropped_count", "0"),
    ]

    def write_health(rows: list[tuple[str, str, str]]) -> None:
        body = "".join(
            f"STS,1,{sequence},{sequence},rp2040_timer0,{component},{key},{value},INFO,0\n"
            for sequence, (component, key, value) in enumerate(rows, start=1)
        )
        (csv_dir / "health.csv").write_text(health_header + body, encoding="utf-8")

    write_health(values)
    assert _runtime_fault(tmp_path, require_qualified_health=True) is None

    prewrite_values = [
        (component, key, "false" if component == "gnss_receiver" else value)
        for component, key, value in values
    ]
    write_health(prewrite_values)
    assert _runtime_fault(tmp_path, require_qualified_health=False) is None
    assert _runtime_fault(tmp_path, require_qualified_health=True) == (
        "health_gnss_receiver_identity_stable_'false'"
    )

    write_health([*values, ("dual_core", "telemetry_dropped", "1")])
    assert _runtime_fault(tmp_path, require_qualified_health=True) == (
        "health_dual_core_telemetry_dropped_'1'"
    )

    capture_state["updated_utc"] = (
        datetime.now(timezone.utc) - timedelta(seconds=30)
    ).isoformat()
    state_path.write_text(json.dumps(capture_state), encoding="utf-8")
    assert (_runtime_fault(tmp_path, require_qualified_health=True) or "").startswith(
        "capture_state_stale_age_"
    )


def test_capture_start_wait_does_not_apply_post_open_runtime_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def premature_runtime_guard(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("post-open guard ran before capture-open predicate")

    monkeypatch.setattr(
        "host.otis_tools.range_spanning_run._runtime_fault",
        premature_runtime_guard,
    )
    assert _wait(
        lambda: {"serial_open": True},
        timeout_s=1,
        description="capture startup regression",
        run_dir=tmp_path,
        wall_deadline=datetime.now(timezone.utc) + timedelta(seconds=5),
        runtime_monitoring_active=False,
    ) == {"serial_open": True}


def test_same_code_consumer_handoff_requires_a_strictly_new_dac_epoch(
    tmp_path: Path,
) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    path = csv_dir / "hybrid_preview_decisions_v1.csv"
    header = (
        "preview_sequence,dac_epoch,actual_applied_code,actionable,"
        "actuation_authorized,authorization_consumed\n"
    )
    path.write_text(
        header
        + "101,7,43008,false,false,false\n"
        + "102,7,43008,false,false,false\n",
        encoding="utf-8",
    )
    assert _find_epoch_propagation(
        tmp_path, after_preview_sequence=100, after_epoch=7, code=43008
    ) is None

    with path.open("a", encoding="utf-8") as handle:
        handle.write("103,8,43008,false,false,false\n")
    propagated = _find_epoch_propagation(
        tmp_path, after_preview_sequence=100, after_epoch=7, code=43008
    )
    assert propagated is not None
    assert propagated["preview_sequence"] == "103"
    assert propagated["dac_epoch"] == "8"


def test_continuation_prewrite_requires_both_preserved_state_consumers(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    csv_dir = tmp_path / "csv"
    reports.mkdir()
    csv_dir.mkdir()
    (reports / "capture_device_state.json").write_text(
        json.dumps(
            {"parser_errors": 0, "reconnect_count": 0, "commands_rejected": 0}
        ),
        encoding="utf-8",
    )
    bundle = {
        "firmware": {
            "git_commit": "a" * 40,
            "source_sha256": "b" * 64,
            "configuration_sha256": "c" * 64,
            "build_invocation_id": "d" * 64,
        },
        "entry": {
            "mode": "state_preserving_running_attach",
            "expected_live_state": {
                "applied_code": 0xA844,
                "applied_code_hex": "0xA844",
                "dac_epoch": 8,
                "band_state": "TIGHT_INSIDE",
                "hybrid_band_state": "INSIDE",
            },
        },
    }
    health_values = [
        ("build", "profile_id", "cx319_range_map_part_a"),
        ("firmware", "git_commit", "a" * 40),
        ("firmware", "source_hash", "b" * 64),
        ("firmware", "config_hash", "c" * 64),
        ("build", "invocation_id", "d" * 64),
        ("gnss_receiver", "identity_stable", "true"),
        ("gnss_receiver", "metadata_control_eligible", "true"),
        ("gnss_receiver", "raw_pps_control_eligible", "true"),
        ("dual_core", "partition_fault", "none"),
        ("dual_core", "fail_static", "false"),
        ("dual_core", "service_publish_failures", "0"),
        ("dual_core", "telemetry_dropped", "0"),
        ("dac", "initialized", "true"),
        ("dac", "applied_code_known", "true"),
        ("dac", "last_write_ok", "true"),
        ("dac", "last_requested_code", "0xA844"),
        ("dac", "last_applied_code", "0xA844"),
        ("cx318_preview", "applied_code", "0xA844"),
        ("cx318_preview", "dac_epoch", "8"),
    ]
    health_header = (
        "record_type,schema_version,status_seq,timestamp_ticks,status_domain,"
        "component,status_key,status_value,severity,flags\n"
    )
    (csv_dir / "health.csv").write_text(
        health_header
        + "".join(
            f"STS,1,{index},{index},rp2040_timer0,{component},{key},{value},INFO,0\n"
            for index, (component, key, value) in enumerate(health_values, start=1)
        ),
        encoding="utf-8",
    )
    (csv_dir / "count_observations.csv").write_text(
        "count_seq\n1\n2\n3\n4\n5\n", encoding="utf-8"
    )
    hybrid_path = csv_dir / "hybrid_preview_decisions_v1.csv"
    hybrid_path.write_text(
        "actual_applied_code,dac_epoch,band_state_after,actionable,"
        "actuation_authorized,authorization_consumed\n"
        "43076,8,INSIDE,false,false,false\n",
        encoding="utf-8",
    )
    (csv_dir / "tight_deadband_decisions_v1.csv").write_text(
        "dac_epoch,state_after,actionable,actuation_authorized,authorization_consumed\n"
        "8,TIGHT_INSIDE,false,false,false\n",
        encoding="utf-8",
    )

    assert _prewrite_ready(tmp_path, bundle) == (True, [])

    hybrid_path.write_text(
        "actual_applied_code,dac_epoch,band_state_after,actionable,"
        "actuation_authorized,authorization_consumed\n"
        "43080,9,INSIDE,false,false,false\n",
        encoding="utf-8",
    )
    ready, reasons = _prewrite_ready(tmp_path, bundle)
    assert ready is False
    assert "hybrid_preview_predecessor_state_not_observed" in reasons
