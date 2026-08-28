from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import gnss_baud_envelope_capture_adapter as capture_adapter
from host.otis_tools.gnss_baud_envelope_capture_adapter import (
    CHARACTERIZATION_COMPONENT,
    COMMAND_TABLE_ID,
    COMPLETED_PEAK_METRIC_KEYS,
    METRIC_KEYS,
    NONINTERFERENCE_COUNTER_KEYS,
    RECEIVER_COMPONENT,
    RECEIVER_COUNTER_KEYS,
    UART_COMPONENT,
    UART_COUNTER_KEYS,
    CaptureDeviceTransport,
    HealthSnapshotReducer,
    ProgrammeTerminalError,
    RetainedSnapshot,
    completed_peak_metrics,
    snapshot_counters,
    snapshot_metrics,
)
from host.otis_tools.gnss_baud_envelope_live import (
    _claim_run_directory,
    _exception_reason_and_detail,
    _validate_exact_registration,
    _validate_usb_serial_identity,
)
from host.otis_tools.evidence_index import register_package, validate_index
from host.otis_tools.gnss_baud_envelope_run import (
    PhaseOutcome,
    PhaseStart,
    _validate_peak_challenges,
    transition_command,
)
from host.otis_tools.gnss_baud_envelope_supervisor import (
    CampaignSupervisor,
    PhasePlan,
    SegmentPlan,
    load_contract,
)
from host.otis_tools.serial_commands import parse_serial_command


CONTRACT_PATH = Path(
    "profiles/qualification/otis_gnss_baud_envelope_characterization_v1.json"
)
CONTINUATION_CONTRACT_PATH = Path(
    "profiles/qualification/otis_gnss_baud_envelope_characterization_continuation_v1.json"
)
HEALTH_HEADER = [
    "record_type",
    "schema_version",
    "status_seq",
    "timestamp_ticks",
    "status_domain",
    "component",
    "status_key",
    "status_value",
    "severity",
    "flags",
]


def test_live_activation_claim_is_atomic_and_cannot_be_replayed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "live" / "live_20990101T000000Z"

    _claim_run_directory(run_dir)
    sentinel = run_dir / "first_attempt"
    sentinel.write_text("claimed\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already claimed"):
        _claim_run_directory(run_dir)

    assert sentinel.read_text(encoding="utf-8") == "claimed\n"


def test_live_exception_mapping_retains_programme_and_generic_detail() -> None:
    programme = ProgrammeTerminalError(
        "evidence_discontinuity", "challenge 7 response deadline expired"
    )
    assert _exception_reason_and_detail(programme) == (
        "evidence_discontinuity",
        "challenge 7 response deadline expired",
    )
    assert _exception_reason_and_detail(RuntimeError("capture fixture stopped")) == (
        "evidence_carrier_failure",
        "capture fixture stopped",
    )


def test_live_finalization_validates_only_its_exact_registered_package(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external" / "evidence_index_v1.json"
    package = tmp_path / "campaign"
    package.mkdir()
    (package / "evidence.txt").write_text("campaign\n", encoding="utf-8")
    registration = register_package(
        index_path=index_path,
        package_path=package,
        source_revision="revision",
        build_identity="build",
        profile_identity="profile",
        attempt_classification="completed_campaign",
        result_or_failure_reason="complete",
        analyzer_identity="analyzer",
    )
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    unrelated_evidence = unrelated / "evidence.txt"
    unrelated_evidence.write_text("original\n", encoding="utf-8")
    register_package(
        index_path=index_path,
        package_path=unrelated,
        source_revision="old-revision",
        build_identity="old-build",
        profile_identity="old-profile",
        attempt_classification="historical",
        result_or_failure_reason="historical",
        analyzer_identity="old-analyzer",
    )
    unrelated_evidence.write_text("mutated\n", encoding="utf-8")
    assert validate_index(index_path)["valid"] is False

    _validate_exact_registration(
        index_path=index_path,
        package_path=package,
        registration=registration,
    )


def _runtime_identity() -> dict[tuple[str, str], str]:
    return {
        (CHARACTERIZATION_COMPONENT, "programme_id"):
            "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1",
        (CHARACTERIZATION_COMPONENT, "contract_sha256"):
            "08308e05ecc4b169a46ace1eb339b93a778abe04070278fcc3c47519666b0550",
        (CHARACTERIZATION_COMPONENT, "command_table_id"): COMMAND_TABLE_ID,
        ("build", "profile_id"):
            "otis_gnss_baud_envelope_characterization_v1",
        ("build", "git_commit"): "fixture-git",
        ("build", "source_sha256"): "1" * 64,
        ("build", "config_sha256"): "2" * 64,
        ("firmware", "version"):
            "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1",
    }


def _snapshot(
    generation: int,
    ticks: int,
    *,
    reference_sequence: int | None = None,
    mirror_generation: int | None = None,
    frontier: int = 10,
    metric: int = 4,
) -> RetainedSnapshot:
    fields: dict[tuple[str, str], str] = {}
    for source in UART_COUNTER_KEYS:
        fields[(UART_COMPONENT, source)] = "0"
    for source in RECEIVER_COUNTER_KEYS:
        fields[(RECEIVER_COMPONENT, source)] = "0"
    for identity in NONINTERFERENCE_COUNTER_KEYS:
        fields[identity] = "0"
    fields[("dual_core", "partition_fault")] = "none"
    fields[("pps_gate", "characterization_mirror_available")] = "true"
    fields[("pps_gate", "characterization_mirror_generation")] = str(
        generation if mirror_generation is None else mirror_generation
    )
    fields[("pps_gate", "characterization_mirror_capture_session")] = "7"
    fields[("pps_gate", "characterization_mirror_reference_sequence")] = str(
        generation if reference_sequence is None else reference_sequence
    )
    fields[(RECEIVER_COMPONENT, "identity_stable")] = "true"
    fields[(RECEIVER_COMPONENT, "configuration_confirmed")] = "true"
    fields[(RECEIVER_COMPONENT, "checksum_requalified")] = "true"
    fields[(RECEIVER_COMPONENT, "gsa_checksum_requalified")] = "true"
    fields[(RECEIVER_COMPONENT, "receiver_identity")] = "AXN_5.1.6_3333_18041700"
    fields[(RECEIVER_COMPONENT, "output_configuration_signature")] = (
        "0101100000000000000000"
    )
    fields[(UART_COMPONENT, "isr_drain_policy")] = "drain_fifo_until_empty"
    fields[(UART_COMPONENT, "isr_timing_policy")] = "entry_exit_timer_reads_only"
    fields[(UART_COMPONENT, "phase_window_sequence")] = str(generation)
    for identity in METRIC_KEYS:
        fields[identity] = str(metric)
    fields[(UART_COMPONENT, "completed_peak_available")] = "false"
    fields[(UART_COMPONENT, "completed_peak_challenge_sequence")] = "0"
    fields[(UART_COMPONENT, "completed_peak_observation_phase")] = "unavailable"
    for identity in COMPLETED_PEAK_METRIC_KEYS:
        fields[identity] = "0"
    fields.update(_runtime_identity())
    fields[(CHARACTERIZATION_COMPONENT, "snapshot_generation")] = str(generation)
    fields[(CHARACTERIZATION_COMPONENT, "extended_counter_ticks")] = str(ticks)
    fields[(CHARACTERIZATION_COMPONENT, "snapshot_extended_ticks_available")] = "true"
    fields[(CHARACTERIZATION_COMPONENT, "snapshot_counter_domain")] = (
        "rp2040_timer0_extended"
    )
    fields[(CHARACTERIZATION_COMPONENT, "snapshot_tick_rate_hz")] = "16000000"
    fields[(CHARACTERIZATION_COMPONENT, "snapshot_capture_session")] = "7"
    fields[(CHARACTERIZATION_COMPONENT, "snapshot_reference_sequence")] = str(
        generation if reference_sequence is None else reference_sequence
    )
    fields[(CHARACTERIZATION_COMPONENT, "transition_evidence_frontier")] = str(
        frontier
    )
    fields[(CHARACTERIZATION_COMPONENT, "confirmed_baud")] = "19200"
    fields[(CHARACTERIZATION_COMPONENT, "baud_epoch")] = "3"
    fields[(CHARACTERIZATION_COMPONENT, "observation_phase")] = "ordinary_online"
    begin_status_sequence = generation * 100
    sequences = {identity: begin_status_sequence + 1 for identity in fields}
    timestamps = {identity: ticks for identity in fields}
    return RetainedSnapshot(
        generation=generation,
        begin_status_sequence=begin_status_sequence,
        end_status_sequence=generation * 100 + 99,
        end_timestamp_ticks=ticks,
        fields=fields,
        field_status_sequences=sequences,
        field_timestamp_ticks=timestamps,
    )


def _with_snapshot_fields(
    snapshot: RetainedSnapshot,
    updates: dict[tuple[str, str], str],
) -> RetainedSnapshot:
    fields = {**snapshot.fields, **updates}
    return RetainedSnapshot(
        generation=snapshot.generation,
        begin_status_sequence=snapshot.begin_status_sequence,
        end_status_sequence=snapshot.end_status_sequence,
        end_timestamp_ticks=snapshot.end_timestamp_ticks,
        fields=fields,
        field_status_sequences={
            key: snapshot.begin_status_sequence + 1 for key in fields
        },
        field_timestamp_ticks={key: snapshot.end_timestamp_ticks for key in fields},
    )


def _csv_bytes(
    snapshot: RetainedSnapshot,
    *,
    omit_identity: tuple[str, str] | None = None,
) -> bytes:
    rows: list[list[str]] = []
    sequence = 1

    def row(component: str, key: str, value: str) -> None:
        nonlocal sequence
        rows.append(
            [
                "STS",
                "1",
                str(sequence),
                str(snapshot.end_timestamp_ticks),
                "rp2040_timer0",
                component,
                key,
                value,
                "INFO",
                "0",
            ]
        )
        sequence += 1

    # Platform evidence intentionally precedes the GNSS sub-envelope, matching
    # the real periodic status ordering.
    platform = set(NONINTERFERENCE_COUNTER_KEYS) | {
        ("dual_core", "partition_fault"),
        ("pps_gate", "characterization_mirror_available"),
        ("pps_gate", "characterization_mirror_generation"),
        ("pps_gate", "characterization_mirror_capture_session"),
        ("pps_gate", "characterization_mirror_reference_sequence"),
    }
    for component, key in sorted(platform):
        row(component, key, snapshot.fields[(component, key)])
    row(CHARACTERIZATION_COMPONENT, "snapshot", "begin")
    for (component, key), value in sorted(snapshot.fields.items()):
        if (component, key) != omit_identity:
            row(component, key, value)
    row(CHARACTERIZATION_COMPONENT, "snapshot", "end")
    output: list[str] = []
    from io import StringIO

    stream = StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(HEALTH_HEADER)
    writer.writerows(rows)
    return stream.getvalue().encode()


def test_incremental_reducer_requires_in_envelope_platform_and_partial_row(tmp_path: Path) -> None:
    path = tmp_path / "health.csv"
    encoded = _csv_bytes(_snapshot(1, 160_000_000))
    split = len(encoded) - 13
    path.write_bytes(encoded[:split])
    reducer = HealthSnapshotReducer(path)
    assert reducer.poll() == []
    with path.open("ab") as handle:
        handle.write(encoded[split:])
    completed = reducer.poll()
    assert len(completed) == 1
    assert snapshot_counters(completed[0])["capture_dropped_count"] == 0
    assert reducer.bytes_read == len(encoded)
    assert all(
        completed[0].begin_status_sequence
        < completed[0].field_status_sequences[identity]
        < completed[0].end_status_sequence
        for identity in NONINTERFERENCE_COUNTER_KEYS
    )


def test_reducer_does_not_inherit_omitted_counter_from_prior_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "health.csv"
    first = _csv_bytes(_snapshot(1, 16_000_000))
    second = _csv_bytes(
        _snapshot(2, 32_000_000), omit_identity=("capture", "dropped_count")
    ).split(b"\n", 1)[1]
    path.write_bytes(first + second)
    reducer = HealthSnapshotReducer(path)
    completed = reducer.poll()
    assert len(completed) == 2
    assert ("capture", "dropped_count") not in completed[1].fields
    contract = load_contract(CONTRACT_PATH)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    with pytest.raises(Exception, match="decision fields missing"):
        transport._assert_snapshot_programme_health(completed[1])


def test_incremental_reducer_projected_twelve_hours_is_linear(tmp_path: Path) -> None:
    path = tmp_path / "health.csv"
    reducer = HealthSnapshotReducer(path, retention=4)
    payload = b""
    for generation in range(1, 121):
        block = _csv_bytes(_snapshot(generation, generation * 16_000_000))
        if generation > 1:
            block = block.split(b"\n", 1)[1]
        payload += block
        path.write_bytes(payload)
        reducer.poll()
    assert reducer.bytes_read == len(payload)
    projected_bytes = reducer.bytes_read * (43_200 // 120)
    assert projected_bytes == len(payload) * 360
    assert [item.generation for item in reducer.snapshots] == [117, 118, 119, 120]


def test_full_ordinary_phase_completes_with_stable_transition_frontier(
    tmp_path: Path,
) -> None:
    contract = load_contract(CONTRACT_PATH)
    snapshots = [
        _snapshot(1, 0, reference_sequence=100, frontier=10),
        _snapshot(2, 160_000_000, reference_sequence=101, frontier=10),
        _snapshot(3, 320_000_000, reference_sequence=102, frontier=10),
    ]
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    transport._last_transition_frontier = 10
    transport._phase_snapshot = lambda **_kwargs: snapshots.pop(0)  # type: ignore[method-assign]
    first = _snapshot(0, 0, reference_sequence=99, frontier=10)
    counters = snapshot_counters(first)
    counters["transport_metadata_hold_count"] = 0
    start = PhaseStart(
        start_ticks=1,
        online_counter_ticks=0,
        online_counter_domain="rp2040_timer0_extended",
        start_counters=counters,
        metrics=snapshot_metrics(first, ring_capacity=1024),
    )
    phase = PhasePlan("ordinary", "ordinary_online", 20)
    segment = SegmentPlan("S02", 19200, 20, (phase,))
    outcome = transport.complete_online_phase(
        segment=segment,
        phase=phase,
        baud_epoch=3,
        start=start,
        status_command=lambda _sequence: "unused",
    )
    assert outcome.online_counter_ticks == 320_000_000
    assert outcome.evidence_continuous is True


def test_phase_local_metrics_do_not_inherit_prior_baud_maximum() -> None:
    high = snapshot_metrics(_snapshot(2, 1, metric=900), ring_capacity=1024)
    low = snapshot_metrics(_snapshot(3, 2, metric=9), ring_capacity=1024)
    assert high["ring_high_water"] == 900
    assert low["ring_high_water"] == 9
    assert low["maximum_isr_entry_gap_ticks"] == 9


def test_unavailable_pps_gate_mirror_retries_before_platform_baseline(
    tmp_path: Path,
) -> None:
    contract = load_contract(CONTRACT_PATH)
    snapshot = _snapshot(1, 16_000_000)
    fields = dict(snapshot.fields)
    fields[("pps_gate", "characterization_mirror_available")] = "false"
    fields[("pps_gate", "characterization_mirror_generation")] = "0"
    fields[("pps_gate", "characterization_mirror_capture_session")] = "0"
    fields[("pps_gate", "characterization_mirror_reference_sequence")] = "0"
    unavailable = RetainedSnapshot(
        generation=snapshot.generation,
        begin_status_sequence=snapshot.begin_status_sequence,
        end_status_sequence=snapshot.end_status_sequence,
        end_timestamp_ticks=snapshot.end_timestamp_ticks,
        fields=fields,
        field_status_sequences=snapshot.field_status_sequences,
        field_timestamp_ticks=snapshot.field_timestamp_ticks,
    )
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    assert transport._assert_snapshot_programme_health(unavailable) == (
        False,
        False,
    )
    assert transport._assert_snapshot_programme_health(
        _snapshot(2, 32_000_000)
    ) == (True, True)


def test_running_firmware_identity_mismatch_is_terminal(tmp_path: Path) -> None:
    contract = load_contract(CONTRACT_PATH)
    snapshot = _snapshot(1, 16_000_000)
    fields = dict(snapshot.fields)
    fields[("build", "source_sha256")] = "f" * 64
    mismatch = RetainedSnapshot(
        generation=snapshot.generation,
        begin_status_sequence=snapshot.begin_status_sequence,
        end_status_sequence=snapshot.end_status_sequence,
        end_timestamp_ticks=snapshot.end_timestamp_ticks,
        fields=fields,
        field_status_sequences=snapshot.field_status_sequences,
        field_timestamp_ticks=snapshot.field_timestamp_ticks,
    )
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    with pytest.raises(Exception, match="running firmware identity differs"):
        transport._assert_snapshot_programme_health(mismatch)


def test_transition_milestones_accept_one_complete_causal_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = load_contract(CONTRACT_PATH)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )

    def transition_snapshot(
        generation: int,
        *,
        state: str,
        tx: bool,
        identity: bool,
        output: bool,
        complete: bool,
    ) -> RetainedSnapshot:
        snapshot = _snapshot(
            generation,
            generation * 1_000_000,
            reference_sequence=100 + generation,
            mirror_generation=7,
            frontier=1 if complete else 0,
        )
        fields = dict(snapshot.fields)
        fields.update(
            {
                (CHARACTERIZATION_COMPONENT, "request_sequence"): "1",
                (CHARACTERIZATION_COMPONENT, "segment_id"): "S02",
                (CHARACTERIZATION_COMPONENT, "source_baud"): "9600",
                (CHARACTERIZATION_COMPONENT, "source_baud_epoch"): "1",
                (CHARACTERIZATION_COMPONENT, "target_baud"): "19200",
                (CHARACTERIZATION_COMPONENT, "request_disposition"): "accepted",
                (CHARACTERIZATION_COMPONENT, "transition_state"): state,
                (
                    CHARACTERIZATION_COMPONENT,
                    "target_command_transmit_complete",
                ): "true" if tx else "false",
                (
                    CHARACTERIZATION_COMPONENT,
                    "target_command_transmit_elapsed_ms",
                ): "100" if tx else "0",
                (CHARACTERIZATION_COMPONENT, "target_identity_confirmed"):
                    "true" if identity else "false",
                (CHARACTERIZATION_COMPONENT, "target_identity_elapsed_ms"):
                    "500" if identity else "0",
                (CHARACTERIZATION_COMPONENT, "target_output_confirmed"):
                    "true" if output else "false",
                (CHARACTERIZATION_COMPONENT, "target_output_elapsed_ms"):
                    "600" if output else "0",
                (CHARACTERIZATION_COMPONENT, "transition_complete_elapsed_ms"):
                    "700" if complete else "0",
                (CHARACTERIZATION_COMPONENT, "recovery_started_elapsed_ms"): "0",
                (CHARACTERIZATION_COMPONENT, "recovery_terminal_elapsed_ms"): "0",
                (CHARACTERIZATION_COMPONENT, "first_dependent_snapshot"):
                    "true" if complete else "false",
                (CHARACTERIZATION_COMPONENT, "confirmed_baud"):
                    "19200" if complete else "9600",
                (CHARACTERIZATION_COMPONENT, "baud_epoch"):
                    "2" if complete else "1",
            }
        )
        return RetainedSnapshot(
            generation=snapshot.generation,
            begin_status_sequence=snapshot.begin_status_sequence,
            end_status_sequence=snapshot.end_status_sequence,
            end_timestamp_ticks=snapshot.end_timestamp_ticks,
            fields=fields,
            field_status_sequences={
                key: snapshot.begin_status_sequence + 1 for key in fields
            },
            field_timestamp_ticks={key: snapshot.end_timestamp_ticks for key in fields},
        )

    snapshots = iter(
        (
            transition_snapshot(
                1, state="accepted", tx=False, identity=False, output=False,
                complete=False,
            ),
            transition_snapshot(
                2, state="transmitting", tx=True, identity=False, output=False,
                complete=False,
            ),
            transition_snapshot(
                3, state="confirming", tx=True, identity=True, output=True,
                complete=False,
            ),
            transition_snapshot(
                4, state="complete", tx=True, identity=True, output=True,
                complete=True,
            ),
        )
    )
    freshness_requirements: list[bool] = []

    def wait_snapshot(predicate, *, require_fresh_mirror=True, **_kwargs):
        freshness_requirements.append(require_fresh_mirror)
        snapshot = next(snapshots)
        assert predicate(snapshot)
        return snapshot

    transport._wait_snapshot = wait_snapshot  # type: ignore[method-assign]
    monkeypatch.setattr(
        "host.otis_tools.gnss_baud_envelope_capture_adapter.send_timestamped_command_to_fifo",
        lambda *_args, **_kwargs: None,
    )
    outcome = transport.transition(
        {
            "request_sequence": 1,
            "segment_id": "S02",
            "source_baud": 9600,
            "source_baud_epoch": 1,
            "target_baud": 19200,
        },
        "fixture",
    )
    assert outcome["status"] == "confirmed"
    assert freshness_requirements == [False, False, False, False]


def test_stale_platform_mirror_hits_independent_deadline(tmp_path: Path) -> None:
    transport = CaptureDeviceTransport(
        contract=load_contract(CONTRACT_PATH),
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    transport._last_mirror_advance_ns = 1
    with pytest.raises(Exception, match="platform mirror did not advance"):
        transport._assert_capture()


def test_completed_peak_tail_is_sequence_bound_and_not_overwritten() -> None:
    challenge_n = _snapshot(20, 20, metric=900)
    fields_n = dict(challenge_n.fields)
    fields_n[(UART_COMPONENT, "completed_peak_available")] = "true"
    fields_n[(UART_COMPONENT, "completed_peak_challenge_sequence")] = "20"
    fields_n[(UART_COMPONENT, "completed_peak_observation_phase")] = "peak_load"
    for identity in COMPLETED_PEAK_METRIC_KEYS:
        fields_n[identity] = "20"
    tail_n = RetainedSnapshot(
        generation=challenge_n.generation,
        begin_status_sequence=challenge_n.begin_status_sequence,
        end_status_sequence=challenge_n.end_status_sequence,
        end_timestamp_ticks=challenge_n.end_timestamp_ticks,
        fields=fields_n,
        field_status_sequences=challenge_n.field_status_sequences,
        field_timestamp_ticks=challenge_n.field_timestamp_ticks,
    )
    metrics_n = completed_peak_metrics(
        tail_n, expected_challenge_sequence=20, ring_capacity=1024
    )
    assert metrics_n["ring_high_water"] == 20

    fields_n_plus_1 = dict(fields_n)
    fields_n_plus_1[(UART_COMPONENT, "completed_peak_challenge_sequence")] = "21"
    for identity in COMPLETED_PEAK_METRIC_KEYS:
        fields_n_plus_1[identity] = "21"
    tail_n_plus_1 = RetainedSnapshot(
        generation=21,
        begin_status_sequence=2100,
        end_status_sequence=2199,
        end_timestamp_ticks=21,
        fields=fields_n_plus_1,
        field_status_sequences={key: 2101 for key in fields_n_plus_1},
        field_timestamp_ticks={key: 21 for key in fields_n_plus_1},
    )
    with pytest.raises(ValueError, match="another challenge"):
        completed_peak_metrics(
            tail_n_plus_1, expected_challenge_sequence=20, ring_capacity=1024
        )
    assert metrics_n["ring_high_water"] == 20


def test_peak_challenge_accepts_response_longer_than_start_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = load_contract(CONTRACT_PATH)
    workload = contract["peak_status_workload"]
    assert workload["minimum_period_ms"] == 1000
    assert workload["response_completion_deadline_ms"] == 5000
    assert workload["maximum_request_rate_hz"] == 1
    assert workload["challenges_per_900_second_phase"] == 900

    raw_path = tmp_path / "raw" / "serial.log"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"prior evidence\n")
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    response = _with_snapshot_fields(
        _snapshot(11, 176_000_000),
        {
            (CHARACTERIZATION_COMPONENT, "segment_id"): "S06",
            (CHARACTERIZATION_COMPONENT, "baud_epoch"): "7",
            (CHARACTERIZATION_COMPONENT, "observation_phase"): "peak_load",
            (CHARACTERIZATION_COMPONENT, "status_request_sequence"): "1",
            (CHARACTERIZATION_COMPONENT, "status_request_segment_id"): "S06",
            (CHARACTERIZATION_COMPONENT, "status_request_baud_epoch"): "7",
            (CHARACTERIZATION_COMPONENT, "status_request_disposition"): "accepted",
            (CHARACTERIZATION_COMPONENT, "status_challenge_sequence"): "1",
            (CHARACTERIZATION_COMPONENT, "status_challenge_active"): "false",
        },
    )
    tail_updates = {
        (CHARACTERIZATION_COMPONENT, "segment_id"): "S06",
        (CHARACTERIZATION_COMPONENT, "baud_epoch"): "7",
        (CHARACTERIZATION_COMPONENT, "observation_phase"): "ordinary_online",
        (UART_COMPONENT, "completed_peak_available"): "true",
        (UART_COMPONENT, "completed_peak_challenge_sequence"): "1",
        (UART_COMPONENT, "completed_peak_observation_phase"): "peak_load",
    }
    tail_updates.update({identity: "4" for identity in COMPLETED_PEAK_METRIC_KEYS})
    tail = _with_snapshot_fields(_snapshot(12, 192_000_000), tail_updates)
    deadlines: list[float] = []

    def wait_snapshot(predicate, *, deadline_s, description, require_fresh_mirror=True):
        deadlines.append(deadline_s)
        snapshot = response if len(deadlines) == 1 else tail
        assert predicate(snapshot), description
        if snapshot is response:
            with raw_path.open("ab") as handle:
                handle.write(b"complete retained response\n")
        return snapshot

    transport._wait_snapshot = wait_snapshot  # type: ignore[method-assign]
    clock = iter((1_000_000_000, 2_500_000_000))
    monkeypatch.setattr(capture_adapter.time, "monotonic_ns", lambda: next(clock))
    monkeypatch.setattr(
        capture_adapter,
        "send_timestamped_command_to_fifo",
        lambda *_args, **_kwargs: None,
    )

    challenge, observed_tail, _metrics = transport._challenge(
        segment=SegmentPlan("S06", 57600, 2700, ()),
        baud_epoch=7,
        status_command=lambda sequence: f"fixture status {sequence}",
    )

    assert deadlines == [5.0, 15.0]
    assert challenge["response_duration_ns"] == 1_500_000_000
    assert challenge["response_duration_ns"] > 1_000_000_000
    assert challenge["response_duration_ns"] < 5_000_000_000
    assert challenge["completed_peak_challenge_sequence"] == 1
    assert observed_tail is tail


def test_peak_challenge_response_deadline_is_typed_evidence_discontinuity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = load_contract(CONTRACT_PATH)
    raw_path = tmp_path / "raw" / "serial.log"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"prior evidence\n")
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )

    def expire(_predicate, *, deadline_s, description, require_fresh_mirror=True):
        assert deadline_s == 5.0
        raise TimeoutError(f"timed out waiting for {description}")

    transport._wait_snapshot = expire  # type: ignore[method-assign]
    monkeypatch.setattr(capture_adapter.time, "monotonic_ns", lambda: 1_000_000_000)
    monkeypatch.setattr(
        capture_adapter,
        "send_timestamped_command_to_fifo",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ProgrammeTerminalError) as captured:
        transport._challenge(
            segment=SegmentPlan("S06", 57600, 2700, ()),
            baud_epoch=7,
            status_command=lambda sequence: f"fixture status {sequence}",
        )

    assert captured.value.reason == "evidence_discontinuity"
    assert captured.value.detail == (
        "status challenge 1 for S06 baud epoch 7 response did not complete within "
        "the frozen 5000 ms deadline: timed out waiting for completed or rejected "
        "status challenge"
    )


def _valid_peak_challenge(
    sequence: int, *, sent_ticks: int, response_duration_ns: int
) -> dict[str, int | str]:
    completed = sent_ticks + response_duration_ns
    return {
        "challenge_sequence": sequence,
        "sent_ticks": sent_ticks,
        "completed_ticks": completed,
        "host_drained_ticks": completed,
        "timestamp_domain": "host_monotonic_ns",
        "response_bytes": 10,
        "response_duration_ns": response_duration_ns,
        "response_start_raw_offset": (sequence - 1) * 10,
        "response_end_raw_offset": sequence * 10,
        "response_start_status_sequence": sequence * 100,
        "response_end_status_sequence": sequence * 100 + 10,
        "response_snapshot_generation": sequence * 2 - 1,
        "completed_peak_snapshot_generation": sequence * 2,
        "completed_peak_end_status_sequence": sequence * 100 + 20,
        "completed_peak_challenge_sequence": sequence,
    }


def test_peak_ledger_separates_response_deadline_from_start_cadence() -> None:
    contract = load_contract(CONTRACT_PATH)
    phase = PhasePlan("peak", "peak_status", 2)
    outcome = PhaseOutcome(
        end_ticks=3_000_000_000,
        online_counter_ticks=48_000_000,
        end_counters={"counter": 0},
        metrics={},
        status_challenges=(
            _valid_peak_challenge(
                1, sent_ticks=0, response_duration_ns=1_500_000_000
            ),
            _valid_peak_challenge(
                2,
                sent_ticks=1_500_000_000,
                response_duration_ns=1_500_000_000,
            ),
        ),
    )

    _validate_peak_challenges(contract, phase, outcome)

    expired = PhaseOutcome(
        end_ticks=5_000_000_001,
        online_counter_ticks=80_000_001,
        end_counters={"counter": 0},
        metrics={},
        status_challenges=(
            _valid_peak_challenge(
                1, sent_ticks=0, response_duration_ns=5_000_000_001
            ),
        ),
    )
    with pytest.raises(ValueError, match="response-completion deadline"):
        _validate_peak_challenges(
            contract, PhasePlan("peak", "peak_status", 1), expired
        )


def test_supervisor_terminal_retains_optional_exception_detail(
    tmp_path: Path,
) -> None:
    contract = load_contract(CONTRACT_PATH)
    supervisor = CampaignSupervisor(
        contract,
        run_id="fixture-run",
        initial_state={
            "programme_id": contract["programme_id"],
            "profile_id": contract["firmware_profile"]["profile_id"],
            "confirmed_baud": 9600,
            "baud_epoch": 1,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "snapshot_generation": 1,
        },
        event_path=tmp_path / "events.jsonl",
        state_path=tmp_path / "state.json",
    )

    terminal = supervisor.programme_fault(
        "evidence_discontinuity",
        timestamp_ticks=1,
        error_detail="status challenge 1 response deadline expired",
    )

    assert terminal["error_detail"] == "status challenge 1 response deadline expired"
    state = json.loads((tmp_path / "state.json").read_text())
    event = json.loads((tmp_path / "events.jsonl").read_text())
    assert state["terminal"]["error_detail"] == terminal["error_detail"]
    assert event["error_detail"] == terminal["error_detail"]


def _continuation_initial_state(baud: int) -> dict[str, object]:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    return {
        "programme_id": contract["programme_id"],
        "profile_id": contract["firmware_profile"]["profile_id"],
        "confirmed_baud": baud,
        "baud_epoch": 1,
        "identity_confirmed": True,
        "configuration_confirmed": True,
        "fresh_rmc": True,
        "fresh_gga": True,
        "fresh_two_gsa": True,
        "snapshot_generation": 4,
        "startup_discovery": {"initial_identity_baud": baud},
    }


def test_continuation_supervisor_maps_local_source_to_logical_tail(
    tmp_path: Path,
) -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    supervisor = CampaignSupervisor(
        contract,
        run_id="continuation-fixture",
        initial_state=_continuation_initial_state(57600),
        event_path=tmp_path / "events.jsonl",
        state_path=tmp_path / "state.json",
    )

    segment = supervisor.current_segment
    assert segment is not None
    assert segment.source_segment_id == "S01"
    assert segment.effective_logical_segment_id == "S06"
    assert [phase.kind for phase in segment.phases] == [
        "peak_status",
        "clean_requalification",
    ]
    assert (
        supervisor.segments[-1].source_segment_id,
        supervisor.segments[-1].effective_logical_segment_id,
        supervisor.segments[-1].baud,
    ) == ("S06", "S11", 9600)
    request = supervisor.next_transition_request(timestamp_ticks=1)
    assert request == {
        "request_sequence": 1,
        "segment_id": "S01",
        "source_segment_id": "S01",
        "logical_segment_id": "S06",
        "source_baud": 57600,
        "source_baud_epoch": 1,
        "target_baud": 57600,
        "expected_prior_request_sequence": 0,
        "transition_mode": "same_target_session_bind",
        "physical_transmit_required": False,
    }
    assert " 1 S01 57600 1 57600" in transition_command(request)
    supervisor.accept_transition(
        {
            **request,
            "status": "confirmed",
            "confirmed_baud": 57600,
            "baud_epoch": 1,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "fresh_rmc": True,
            "fresh_gga": True,
            "fresh_two_gsa": True,
            "first_dependent_snapshot_bound": True,
        },
        timestamp_ticks=2,
    )
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert {(event["source_segment_id"], event["logical_segment_id"]) for event in events} == {
        ("S01", "S06")
    }


def test_continuation_fallback_attachment_uses_normal_first_transition() -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    supervisor = CampaignSupervisor(
        contract,
        run_id="fallback-fixture",
        initial_state=_continuation_initial_state(38400),
    )

    request = supervisor.next_transition_request(timestamp_ticks=1)

    assert request["logical_segment_id"] == "S06"
    assert request["source_baud"] == 38400
    assert request["target_baud"] == 57600
    assert request["transition_mode"] == "baud_change"
    assert request["physical_transmit_required"] is True


def _continuation_attachment_snapshot(
    *, baud: int, hint_hit: bool, metadata_fresh: bool = True
) -> RetainedSnapshot:
    snapshot = _snapshot(4, 64_000_000, frontier=20)
    startup = {
        (RECEIVER_COMPONENT, "startup_hint_attempted"): "true",
        (RECEIVER_COMPONENT, "startup_hint_baud"): "57600",
        (RECEIVER_COMPONENT, "startup_hint_identity_outcome"): (
            "confirmed" if hint_hit else "timed_out"
        ),
        (RECEIVER_COMPONENT, "startup_fallback_entered"): (
            "false" if hint_hit else "true"
        ),
        (RECEIVER_COMPONENT, "initial_discovery_identity_baud"): str(baud),
        (RECEIVER_COMPONENT, "initial_discovery_outcome"): (
            "hint_confirmed" if hint_hit else "fallback_confirmed"
        ),
        (RECEIVER_COMPONENT, "pmtk605_peripheral_complete_count"): (
            "1" if hint_hit else "2"
        ),
        (RECEIVER_COMPONENT, "pmtk605_last_peripheral_complete_ticks"): "32000000",
        (
            RECEIVER_COMPONENT,
            "pmtk605_last_peripheral_complete_ticks_available",
        ): "true",
        (RECEIVER_COMPONENT, "pmtk605_last_peripheral_complete_ticks_domain"): (
            "rp2040_timer0_extended"
        ),
        (RECEIVER_COMPONENT, "metadata_fresh"): (
            "true" if metadata_fresh else "false"
        ),
        (RECEIVER_COMPONENT, "checksum_requalified"): "true",
        (RECEIVER_COMPONENT, "gsa_checksum_requalified"): "true",
        (RECEIVER_COMPONENT, "rmc_count"): "1",
        (RECEIVER_COMPONENT, "gga_count"): "1",
        (RECEIVER_COMPONENT, "gsa_count"): "2",
        (CHARACTERIZATION_COMPONENT, "confirmed_baud"): str(baud),
        (CHARACTERIZATION_COMPONENT, "baud_epoch"): "1",
        ("build", "profile_id"): (
            "otis_gnss_baud_envelope_characterization_continuation_v1"
        ),
    }
    return _with_snapshot_fields(snapshot, startup)


@pytest.mark.parametrize("baud,hint_hit", [(57600, True), (38400, False)])
def test_continuation_attachment_accepts_fresh_dynamic_allowed_baud(
    tmp_path: Path, baud: int, hint_hit: bool
) -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    snapshot = _continuation_attachment_snapshot(baud=baud, hint_hit=hint_hit)

    def wait_snapshot(predicate, **_kwargs):
        assert predicate(snapshot)
        return snapshot

    transport._wait_snapshot = wait_snapshot  # type: ignore[method-assign]
    evidence = transport.initial_state_evidence(
        expected_device={
            "gnss_identity": "AXN_5.1.6_3333_18041700",
            "gnss_configuration": "0101100000000000000000",
        }
    )

    assert evidence["confirmed_baud"] == baud
    assert evidence["baud_epoch"] == 1
    assert evidence["fresh_two_gsa"] is True


def test_continuation_attachment_accepts_observed_nmea_identity(
    tmp_path: Path,
) -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    snapshot = _with_snapshot_fields(
        _continuation_attachment_snapshot(baud=57600, hint_hit=True),
        {(RECEIVER_COMPONENT, "receiver_identity"): "NMEA_CADENCE_OBSERVED"},
    )

    def wait_snapshot(predicate, **_kwargs):
        assert predicate(snapshot)
        return snapshot

    transport._wait_snapshot = wait_snapshot  # type: ignore[method-assign]
    evidence = transport.initial_state_evidence(
        expected_device={
            "gnss_identity": "AXN_5.1.6_3333_18041700",
            "gnss_configuration": "0101100000000000000000",
        }
    )

    assert evidence["confirmed_baud"] == 57600


def test_continuation_attachment_rejects_stale_metadata(tmp_path: Path) -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    snapshot = _continuation_attachment_snapshot(
        baud=57600, hint_hit=True, metadata_fresh=False
    )

    def wait_snapshot(predicate, **_kwargs):
        assert predicate(snapshot) is False
        raise TimeoutError("fixture attachment remained stale")

    transport._wait_snapshot = wait_snapshot  # type: ignore[method-assign]
    with pytest.raises(TimeoutError, match="remained stale"):
        transport.initial_state_evidence(
            expected_device={
                "gnss_identity": "AXN_5.1.6_3333_18041700",
                "gnss_configuration": "0101100000000000000000",
            }
        )


def test_continuation_same_target_binding_requires_no_transmit_and_fresh_frontier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    supervisor = CampaignSupervisor(
        contract,
        run_id="binding-fixture",
        initial_state=_continuation_initial_state(57600),
    )
    request = supervisor.next_transition_request(timestamp_ticks=1)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    common_fields = {
        (CHARACTERIZATION_COMPONENT, "request_sequence"): "1",
        (CHARACTERIZATION_COMPONENT, "segment_id"): "S01",
        (CHARACTERIZATION_COMPONENT, "source_baud"): "57600",
        (CHARACTERIZATION_COMPONENT, "source_baud_epoch"): "1",
        (CHARACTERIZATION_COMPONENT, "target_baud"): "57600",
        (CHARACTERIZATION_COMPONENT, "request_disposition"): "accepted",
        (CHARACTERIZATION_COMPONENT, "target_command_transmit_complete"): "false",
        (CHARACTERIZATION_COMPONENT, "target_command_transmit_elapsed_ms"): "0",
        (CHARACTERIZATION_COMPONENT, "target_identity_confirmed"): "true",
        (CHARACTERIZATION_COMPONENT, "target_output_confirmed"): "true",
        (CHARACTERIZATION_COMPONENT, "target_identity_elapsed_ms"): "0",
        (CHARACTERIZATION_COMPONENT, "target_output_elapsed_ms"): "0",
        (CHARACTERIZATION_COMPONENT, "transition_complete_elapsed_ms"): "0",
        (CHARACTERIZATION_COMPONENT, "recovery_started_elapsed_ms"): "0",
        (CHARACTERIZATION_COMPONENT, "recovery_terminal_elapsed_ms"): "0",
        (CHARACTERIZATION_COMPONENT, "confirmed_baud"): "57600",
        (CHARACTERIZATION_COMPONENT, "baud_epoch"): "1",
    }
    awaiting = _with_snapshot_fields(
        _continuation_attachment_snapshot(baud=57600, hint_hit=True),
        {
            **common_fields,
            (CHARACTERIZATION_COMPONENT, "transition_state"): (
                "await_fresh_metadata"
            ),
            (CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"): "0",
            (CHARACTERIZATION_COMPONENT, "first_dependent_snapshot"): "false",
        },
    )
    complete = _with_snapshot_fields(
        _continuation_attachment_snapshot(baud=57600, hint_hit=True),
        {
            **common_fields,
            (CHARACTERIZATION_COMPONENT, "transition_state"): "complete",
            (CHARACTERIZATION_COMPONENT, "transition_complete_elapsed_ms"): "1000",
            (CHARACTERIZATION_COMPONENT, "transition_evidence_frontier"): "25",
            (CHARACTERIZATION_COMPONENT, "first_dependent_snapshot"): "true",
        },
    )
    snapshots = iter((awaiting, complete))

    def wait_snapshot(predicate, **_kwargs):
        snapshot = next(snapshots)
        assert predicate(snapshot)
        return snapshot

    transport._wait_snapshot = wait_snapshot  # type: ignore[method-assign]
    monkeypatch.setattr(
        capture_adapter,
        "send_timestamped_command_to_fifo",
        lambda *_args, **_kwargs: None,
    )

    result = transport.transition(request, transition_command(request))

    assert result["status"] == "confirmed"
    assert result["baud_epoch"] == 1
    assert result["source_segment_id"] == "S01"
    assert result["logical_segment_id"] == "S06"
    assert result["transition_milestones"]["physical_transmit"] == {
        "required": False,
        "complete": False,
        "firmware_elapsed_ms": 0,
        "deadline_ms": 500,
    }


def test_continuation_transport_rejects_prefix_logical_segment(
    tmp_path: Path,
) -> None:
    contract = load_contract(CONTINUATION_CONTRACT_PATH)
    transport = CaptureDeviceTransport(
        contract=contract,
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )

    with pytest.raises(ValueError, match="cannot run logical S01..S05"):
        transport.transition(
            {
                "request_sequence": 1,
                "segment_id": "S01",
                "source_segment_id": "S01",
                "logical_segment_id": "S01",
                "source_baud": 57600,
                "source_baud_epoch": 1,
                "target_baud": 57600,
                "transition_mode": "same_target_session_bind",
                "physical_transmit_required": False,
            },
            "fixture",
        )


def test_peak_challenge_requires_retained_end_marker_evidence() -> None:
    contract = load_contract(CONTRACT_PATH)
    phase = PhasePlan("peak", "peak_status", 1)
    outcome = PhaseOutcome(
        end_ticks=2_000_000_000,
        online_counter_ticks=16_000_000,
        end_counters={"counter": 0},
        metrics={},
        status_challenges=(
            {
                "challenge_sequence": 1,
                "sent_ticks": 1,
                "completed_ticks": 2,
                "host_drained_ticks": 2,
                "timestamp_domain": "host_monotonic_ns",
                "response_bytes": 10,
                "response_duration_ns": 1,
            },
        ),
    )
    with pytest.raises(ValueError, match="end-marker"):
        _validate_peak_challenges(contract, phase, outcome)


def _peak_outcome_with_response_duration(response_duration_ns: int) -> PhaseOutcome:
    sent_ticks = 10
    completed_ticks = sent_ticks + response_duration_ns
    return PhaseOutcome(
        end_ticks=completed_ticks,
        online_counter_ticks=16_000_000,
        end_counters={"counter": 0},
        metrics={},
        status_challenges=(
            {
                "challenge_sequence": 1,
                "sent_ticks": sent_ticks,
                "completed_ticks": completed_ticks,
                "host_drained_ticks": completed_ticks,
                "timestamp_domain": "host_monotonic_ns",
                "response_bytes": 10,
                "response_duration_ns": response_duration_ns,
                "response_start_raw_offset": 100,
                "response_end_raw_offset": 110,
                "response_start_status_sequence": 1,
                "response_end_status_sequence": 2,
                "response_snapshot_generation": 1,
                "completed_peak_snapshot_generation": 2,
                "completed_peak_end_status_sequence": 3,
                "completed_peak_challenge_sequence": 1,
            },
        ),
    )


def test_peak_challenge_response_may_exceed_minimum_start_period() -> None:
    contract = load_contract(CONTRACT_PATH)
    phase = PhasePlan("peak", "peak_status", 1)

    _validate_peak_challenges(
        contract,
        phase,
        _peak_outcome_with_response_duration(1_700_000_000),
    )


def test_peak_challenge_response_cannot_exceed_liveness_deadline() -> None:
    contract = load_contract(CONTRACT_PATH)
    phase = PhasePlan("peak", "peak_status", 1)

    with pytest.raises(ValueError, match="response-completion deadline"):
        _validate_peak_challenges(
            contract,
            phase,
            _peak_outcome_with_response_duration(5_000_000_001),
        )


def test_peak_challenge_timeout_is_specific_evidence_discontinuity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/serial.log").write_bytes(b"")
    transport = CaptureDeviceTransport(
        contract=load_contract(CONTRACT_PATH),
        run_dir=tmp_path,
        normal_fifo=tmp_path / "normal.fifo",
        device="fixture",
        capture_pid=1,
        capture_status_interval_s=1.0,
        expected_runtime_identity=_runtime_identity(),
    )
    observed_deadlines: list[float] = []

    def timeout_wait(_predicate, *, deadline_s: float, **_kwargs):
        observed_deadlines.append(deadline_s)
        raise TimeoutError("fixture retained no response end marker")

    transport._wait_snapshot = timeout_wait  # type: ignore[method-assign]
    monkeypatch.setattr(
        capture_adapter,
        "send_timestamped_command_to_fifo",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ProgrammeTerminalError, match="frozen 5000 ms") as exc_info:
        transport._challenge(
            segment=SegmentPlan("S06", 57600, 2700, ()),
            baud_epoch=7,
            status_command=lambda sequence: f"fixture {sequence}",
        )

    assert observed_deadlines == [5.0]
    assert exc_info.value.reason == "evidence_discontinuity"


def test_initial_epoch_zero_is_rejected_by_host_command_parser() -> None:
    with pytest.raises(ValueError):
        parse_serial_command(
            "GNSS BAUD OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1 "
            "1 S01 9600 0 9600"
        )


def test_usb_serial_mismatch_fails_before_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    from serial.tools import list_ports

    monkeypatch.setattr(
        list_ports,
        "comports",
        lambda: [SimpleNamespace(device="/dev/cu.fixture", serial_number="WRONG")],
    )
    with pytest.raises(ValueError, match="USB serial identity differs"):
        _validate_usb_serial_identity("/dev/cu.fixture", "EXPECTED")
    monkeypatch.setattr(
        list_ports,
        "comports",
        lambda: [SimpleNamespace(device="/dev/cu.fixture", serial_number=None)],
    )
    with pytest.raises(ValueError, match="USB serial identity differs"):
        _validate_usb_serial_identity("/dev/cu.fixture", "EXPECTED")
    monkeypatch.setattr(
        list_ports,
        "comports",
        lambda: [
            SimpleNamespace(device="/dev/cu.fixture", serial_number="EXPECTED")
        ],
    )
    _validate_usb_serial_identity("/dev/cu.fixture", "EXPECTED")
