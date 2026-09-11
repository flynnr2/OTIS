from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_COMPONENT,
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
    complete_active_status_snapshots,
)
from host.otis_tools.active_status_live_state import ActiveStatusLiveReducer
from host.otis_tools.adaptive_hybrid_replay import ResponseClassifier
from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    CONTRACT_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.firmware_host_contract import (
    COMMAND_FORMS,
    CONTRACT,
    CONTRACT_ID,
    CONTRACT_SHA256,
    FRONTIERS,
    ACTIVE_STATUS_VALUE_WIRE_TYPES,
    RAW_ONLY_DIAGNOSTIC_FORMS,
    RAW_ONLY_DIAGNOSTIC_RECORD_TYPES,
    RECORD_FIELDS,
    RECORD_FIELD_WIRE_TYPES,
    RECORD_SCHEMA_VERSIONS,
    RECORD_TYPES,
    RELATIONS,
    SIMPLE_COMMANDS,
    WIRE_TYPES,
    active_status_value_error,
    validate_raw_only_diagnostic,
    validate_record_wire_values,
    verify_generated_cpp_header,
    wire_value_error,
)
from host.otis_tools.prewrite_readiness_contract import (
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness,
)
from host.otis_tools.serial_commands import parse_serial_command


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _base_type(type_name: str) -> tuple[str, dict[str, object], bool]:
    wire_type = WIRE_TYPES[type_name]
    if wire_type["kind"] != "optional":
        return type_name, wire_type, False
    base_name = str(wire_type["base"])
    return base_name, WIRE_TYPES[base_name], True


def _legal_wire_values(contract: str, field: str) -> tuple[str, ...]:
    type_name = RECORD_FIELD_WIRE_TYPES[contract][field]
    _, wire_type, optional = _base_type(type_name)
    kind = str(wire_type["kind"])
    values: list[str] = [""] if optional else []
    if kind == "record_type":
        values.extend(sorted(RECORD_TYPES[contract]))
    elif kind == "schema_version":
        values.append(str(RECORD_SCHEMA_VERSIONS[contract]))
    elif kind == "integer":
        values.extend(
            {
                str(wire_type["minimum"]),
                "0",
                str(wire_type["maximum"]),
            }
        )
    elif kind == "finite_decimal":
        values.extend(("0", "-0.000000000", "1.25", "-1.25"))
    elif kind == "enum":
        values.extend(str(value) for value in wire_type["values"])
    elif kind == "escaped_atom":
        if wire_type.get("optional") is True:
            values.append("")
        values.extend(("value", "value%25%2C%22%0D%0A"))
    elif kind == "lower_hex":
        length = int(wire_type["length"])
        values.extend(("0" * length, "f" * length))
    elif kind == "lower_hex_or_literal":
        length = int(wire_type["length"])
        values.extend((str(wire_type["literal"]), "0" * length, "f" * length))
    else:  # pragma: no cover - contract loader rejects unknown kinds
        raise AssertionError(kind)
    return tuple(dict.fromkeys(values))


def _illegal_wire_values(contract: str, field: str) -> tuple[str, ...]:
    type_name = RECORD_FIELD_WIRE_TYPES[contract][field]
    _, wire_type, optional = _base_type(type_name)
    kind = str(wire_type["kind"])
    if kind == "record_type":
        return ("UNKNOWN", "", "STS ")
    if kind == "schema_version":
        return ("0", "01", "-1")
    if kind == "integer":
        minimum = int(wire_type["minimum"])
        maximum = int(wire_type["maximum"])
        candidates = (str(minimum - 1), str(maximum + 1), "+1", "01", "-0")
        return tuple(value for value in candidates if not (optional and value == ""))
    if kind == "finite_decimal":
        candidates = ("nan", "inf", "1e3", "+1.0", "01.0", "9" * 400)
        if not optional and wire_type.get("optional") is not True:
            candidates = ("", *candidates)
        return candidates
    if kind == "enum":
        candidates = ("", "TRUE", "2")
        return tuple(value for value in candidates if not (optional and value == ""))
    if kind == "escaped_atom":
        candidates = ('raw"quote', "raw%", "raw%2c", "nonascii-\N{POUND SIGN}")
        if not optional and wire_type.get("optional") is not True:
            candidates = ("", *candidates)
        return candidates
    if kind == "lower_hex":
        length = int(wire_type["length"])
        return ("", "a" * (length - 1), "A" * length, "g" * length)
    if kind == "lower_hex_or_literal":
        length = int(wire_type["length"])
        return ("", "a" * (length - 1), "A" * length, "other_literal")
    raise AssertionError(kind)  # pragma: no cover


def _canonical_wire_row(
    contract: str, *, record_type: str | None = None
) -> list[str]:
    row = [
        _legal_wire_values(contract, field)[0]
        for field in RECORD_FIELDS[contract]
    ]
    row[0] = record_type or sorted(RECORD_TYPES[contract])[0]
    if contract == "raw_events_v1":
        channel_index = RECORD_FIELDS[contract].index("channel_id")
        row[channel_index] = "0" if row[0] == "EVT" else "1"
    return row


def _health_row(key: str, value: str, *, version: str = "1") -> dict[str, str]:
    return {
        "record_type": "STS",
        "schema_version": version,
        "status_seq": "1",
        "timestamp_ticks": "1",
        "status_domain": "rp2040_monotonic_us32",
        "component": ACTIVE_STATUS_COMPONENT,
        "status_key": key,
        "status_value": value,
        "severity": "INFO",
        "flags": "0",
    }


def _snapshot_rows(*, version: str = "1") -> list[dict[str, str]]:
    rows = [
        _health_row(SNAPSHOT_BEGIN_KEY, "1", version=version),
        _health_row(
            SNAPSHOT_CONTRACT_KEY,
            ACTIVE_STATUS_SNAPSHOT_CONTRACT,
            version=version,
        ),
    ]
    rows.extend(
        _health_row(key, _active_status_value(key), version=version)
        for key in ACTIVE_STATUS_KEYS
    )
    rows.append(_health_row(SNAPSHOT_COMPLETE_KEY, "1", version=version))
    return rows


def _active_status_value(key: str) -> str:
    type_name = ACTIVE_STATUS_VALUE_WIRE_TYPES[key]
    wire_type = WIRE_TYPES[type_name]
    if wire_type["kind"] == "integer":
        return "0"
    if wire_type["kind"] == "enum":
        return str(wire_type["values"][0])
    if wire_type["kind"] == "escaped_atom":
        return "value"
    if wire_type["kind"] == "lower_hex":
        return "a" * int(wire_type["length"])
    if wire_type["kind"] == "hex_integer":
        return "0x0000"
    if wire_type["kind"] == "literal_or":
        return str(wire_type["literal"])
    raise AssertionError(f"unhandled ACTIVE status type {type_name}")


def test_contract_authority_is_current_complete_and_deterministically_generated() -> None:
    verify_generated_cpp_header()
    assert CONTRACT["compatibility"] == "exact_current_only"
    assert CONTRACT_ID == "OTIS_FIRMWARE_HOST_CONTRACT_V1"
    assert len(CONTRACT_SHA256) == 64
    assert {name: tuple(fields) for name, fields in CONTRACT_FIELDS.items()} == (
        RECORD_FIELDS
    )
    assert len(RECORD_FIELDS) == 17
    assert sum(len(fields) for fields in RECORD_FIELDS.values()) == 451
    assert RAW_ONLY_DIAGNOSTIC_RECORD_TYPES == {
        "BOOT",
        "BOOTDIAG",
        "BOOT_FATAL",
        "BOOT_WARN",
    }
    assert {
        name: set(field_types)
        for name, field_types in RECORD_FIELD_WIRE_TYPES.items()
    } == {name: set(fields) for name, fields in RECORD_FIELDS.items()}
    assert set(RELATIONS) == {
        "accepted_span_sources_are_exact",
        "phase_consumes_accepted_span",
        "active_decision_whole_seconds_from_exact_ticks",
        "estimate_capture_precedes_operational_decision",
        "active_status_generation_is_atomic",
        "metadata_absence_is_deferred_not_contradictory",
        "lifetime_counters_are_not_current_health",
        "authority_release_is_latched",
        "decision_replay_uses_post_decision_frontier",
        "response_classification_is_stateful",
    }


def test_every_record_field_has_contract_derived_legal_and_illegal_boundaries() -> None:
    exercised = 0
    for contract, fields in RECORD_FIELDS.items():
        for field in fields:
            legal = _legal_wire_values(contract, field)
            illegal = _illegal_wire_values(contract, field)
            assert legal, f"{contract}.{field} lacks legal boundary values"
            assert illegal, f"{contract}.{field} lacks illegal boundary values"
            assert all(
                wire_value_error(contract, field, value) is None
                for value in legal
            ), f"{contract}.{field} legal matrix disagrees with the contract"
            assert all(
                wire_value_error(contract, field, value) is not None
                for value in illegal
            ), f"{contract}.{field} illegal matrix disagrees with the contract"
            exercised += 1
    assert exercised == 451


def test_every_active_status_value_has_a_contract_derived_wire_type() -> None:
    expected_keys = {
        SNAPSHOT_BEGIN_KEY,
        SNAPSHOT_CONTRACT_KEY,
        *ACTIVE_STATUS_KEYS,
        SNAPSHOT_COMPLETE_KEY,
    }
    assert set(ACTIVE_STATUS_VALUE_WIRE_TYPES) == expected_keys
    for key in ACTIVE_STATUS_KEYS:
        value = _active_status_value(key)
        assert active_status_value_error(key, value) is None
    assert active_status_value_error(SNAPSHOT_BEGIN_KEY, "1") is None
    assert active_status_value_error(SNAPSHOT_BEGIN_KEY, "01") is not None
    assert active_status_value_error(SNAPSHOT_COMPLETE_KEY, str(2**32)) is not None
    assert (
        active_status_value_error(
            SNAPSHOT_CONTRACT_KEY, ACTIVE_STATUS_SNAPSHOT_CONTRACT
        )
        is None
    )


def test_raw_only_boot_diagnostics_are_typed_but_never_canonical_records(
    tmp_path: Path,
) -> None:
    boot = (
        "BOOT,v=1,boot_count=1,phase=run_mode,prev_valid=1,"
        "prev_phase=run_mode,prev_fatal=none,reset_reason=0x00000000,"
        "watchdog=0,watchdog_enable=0,failure_count=0,safe_mode=0,"
        "prev_reset_reason=0x00000000"
    )
    warnings = (
        "BOOT_WARN,v=1,key=serial_absent,wait_ms=250",
        "BOOT_WARN,v=1,key=safe_mode,reason=repeated_boot_failure,"
        "failure_count=3,threshold=3,prev_phase=fatal,prev_fatal=boot_fatal",
    )
    fatal = "BOOT_FATAL,v=1,fatal=boot_fatal,phase=fatal,boot_count=2,failure_count=1"
    diag_fields = RAW_ONLY_DIAGNOSTIC_FORMS["BOOTDIAG"][0][0]
    diag = "BOOTDIAG," + ",".join(
        f"{field}={'1' if field == 'v' else '0x00000000'}"
        for field in diag_fields
    )
    lines = (boot, *warnings, fatal, diag)
    for line in lines:
        assert validate_raw_only_diagnostic(next(csv.reader([line]))) == ()
        assert len(line.encode("ascii")) <= 1024
        for offset in range(len(line)):
            offset_errors: list[str] = []
            with CsvRecordSplitter(
                {}, on_parser_error=offset_errors.append
            ) as splitter:
                assert splitter.process_line(line[offset:]) is None
                assert splitter.last_disposition == (
                    "raw_only_diagnostic"
                    if offset == 0
                    else "late_attach_boot_fragment"
                )
                assert offset_errors == []

    oversized_errors: list[str] = []
    with CsvRecordSplitter({}, on_parser_error=oversized_errors.append) as splitter:
        assert splitter.process_line("x" * 1025) is None
        assert splitter.last_disposition == "error"
        assert "unknown record type" in oversized_errors[-1]

    complete_boot_errors: list[str] = []
    with CsvRecordSplitter(
        {"health_v1": tmp_path / "complete_boot_health.csv"},
        on_parser_error=complete_boot_errors.append,
    ) as splitter:
        assert splitter.process_line(boot) is None
        assert splitter.last_disposition == "raw_only_diagnostic"
        assert splitter.process_line(
            boot.replace("BOOT,v=1", "BOOT,v=2")
        ) is None
        assert splitter.last_disposition == "error"
        assert "BOOT.v must be one of ['1']" in complete_boot_errors[-1]

    errors: list[str] = []
    target = tmp_path / "health.csv"
    observed_late_attach_fragment = (
        "=0x00000000,wd_s1=0x00000000,wd_s2=0x0000000a,"
        "wd_s3=0x00010100,wd_s4=0x00000000,wd_s5=0x4ff824a4,"
        "wd_s6=0x20042000,wd_s7=0x00001b89,"
        "resets_reset=0x00000000,resets_done=0x01ffffff,"
        "clk_ref_ctrl=0x00000002,clk_ref_div=0x00000100,"
        "clk_sys_ctrl=0x00000001,clk_sys_div=0x00000100,"
        "clk_peri_ctrl=0x00000840,clk_peri_div=0x00000000,"
        "xosc_status=0x81001001,rosc_status=0x81011000,"
        "rosc_ctrl=0x00fab000,pll_sys_cs=0x80000001,"
        "pll_usb_cs=0x80000001,vreg=0x000010b1,bod=0x00000091,"
        "chip_id=0x20002927,platform=0x00000002,"
        "gitref_rp2040=0xe0c912e8"
    )
    assert len(observed_late_attach_fragment.encode("ascii")) == 526
    with CsvRecordSplitter(
        {"health_v1": target}, on_parser_error=errors.append
    ) as splitter:
        assert splitter.process_line(observed_late_attach_fragment) is None
        assert splitter.last_disposition == "late_attach_boot_fragment"
        for line in lines:
            assert splitter.process_line(line) is None
            assert splitter.last_disposition == "raw_only_diagnostic"
        assert errors == []
        assert splitter.process_line("BOOT_WARN,v=2,key=serial_absent,wait_ms=250") is None
        assert "BOOT_WARN.v must be one of ['1']" in errors[-1]
        assert splitter.process_line("arbitrary second unknown line") is None
        assert "unknown record type" in errors[-1]

    assert target.read_text(encoding="utf-8").splitlines() == [
        ",".join(RECORD_FIELDS["health_v1"])
    ]


def test_every_legal_record_shape_crosses_the_live_splitter(tmp_path: Path) -> None:
    targets = {
        contract: tmp_path / f"{contract}.csv" for contract in RECORD_FIELDS
    }
    with CsvRecordSplitter(targets) as splitter:
        for contract in RECORD_FIELDS:
            for record_type in sorted(RECORD_TYPES[contract]):
                row = _canonical_wire_row(contract, record_type=record_type)
                assert validate_record_wire_values(contract, row) == ()
                assert splitter.process_line(",".join(row)) == contract


def test_out_of_range_wire_value_enters_live_parser_hold_without_storage(
    tmp_path: Path,
) -> None:
    errors: list[str] = []
    target = tmp_path / "count_observations.csv"
    row = _canonical_wire_row("count_observations_v1")
    field_index = RECORD_FIELDS["count_observations_v1"].index("count_seq")
    row[field_index] = str(2**32)
    with CsvRecordSplitter(
        {"count_observations_v1": target}, on_parser_error=errors.append
    ) as splitter:
        assert splitter.process_line(",".join(row)) is None
    assert len(errors) == 1
    assert "count_observations_v1.count_seq must be in 0..4294967295" in errors[0]
    assert target.read_text(encoding="utf-8").splitlines() == [
        ",".join(RECORD_FIELDS["count_observations_v1"])
    ]


def test_out_of_range_wire_value_is_rejected_by_offline_validation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "count_observations.csv"
    row = _canonical_wire_row("count_observations_v1")
    row[RECORD_FIELDS["count_observations_v1"].index("count_seq")] = str(
        2**32
    )
    path.write_text(
        ",".join(RECORD_FIELDS["count_observations_v1"])
        + "\n"
        + ",".join(row)
        + "\n",
        encoding="utf-8",
    )

    result = validate_csv(
        path,
        CsvValidationContext(
            contract="count_observations_v1",
            known_channels=frozenset({0}),
            known_domains=frozenset({"value"}),
        ),
    )

    assert any(
        "count_observations_v1.count_seq must be in 0..4294967295"
        in error
        for error in result.errors
    )


def test_firmware_uses_generated_headers_and_capacity_frontiers() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FIRMWARE.iterdir()
        if path.suffix in {".cpp", ".h", ".ino"}
        and path.name != "otis_firmware_host_contract.generated.h"
    )
    assert '"record_type,schema_version' not in source
    for contract in (
        "raw_events_v1",
        "count_observations_v1",
        "accepted_pps_spans_v1",
        "health_v1",
        "dac_steps_v1",
        "environment_v1",
        "pps_snapshots_v1",
        "forwarded_monitor_snapshots_v1",
        "estimates_v3",
        "control_previews_v1",
        "active_transactions_v3",
        "active_hybrid_decisions_v3",
        "active_hybrid_maintenance_v2",
        "relative_phase_observations_v2",
        "phase_estimator_outputs_v2",
        "tight_deadband_decisions_v1",
    ):
        macro = "OTIS_CONTRACT_" + contract.upper()
        assert macro + "_HEADER" in source
    partition = (FIRMWARE / "otis_dual_core_partition.h").read_text(
        encoding="utf-8"
    )
    assert "OTIS_ACTIVE_STATUS_FIELD_COUNT" in partition
    assert "OTIS_EVIDENCE_RESPONSE_FRONTIER" in partition
    assert "OTIS_TELEMETRY_MAXIMUM_CONCURRENT_COUNT" in partition
    assert FRONTIERS["adaptive_hybrid_status"]["field_count"] == len(
        ACTIVE_STATUS_KEYS
    )


def test_live_csv_admission_rejects_unknown_version_and_header_drift(
    tmp_path: Path,
) -> None:
    errors: list[str] = []
    target = tmp_path / "health.csv"
    with CsvRecordSplitter(
        {"health_v1": target}, on_parser_error=errors.append
    ) as splitter:
        header = ",".join(CONTRACT_FIELDS["health_v1"])
        assert splitter.process_line(header) is None
        assert errors == []
        assert splitter.process_line("UNKNOWN,1,anything") is None
        stale = ["STS", "99", *("" for _ in range(8))]
        assert splitter.process_line(",".join(stale)) is None
        wrong_header = list(CONTRACT_FIELDS["health_v1"])
        wrong_header[-1] = "unexpected"
        assert splitter.process_line(",".join(wrong_header)) is None
    assert len(errors) == 3
    assert "unknown record type" in errors[0]
    assert "schema_version" in errors[1]
    assert "mismatched contract header" in errors[2]
    assert target.read_text(encoding="utf-8").splitlines() == [
        ",".join(CONTRACT_FIELDS["health_v1"])
    ]


def test_active_status_reducer_rejects_stale_versions_and_extra_keys() -> None:
    reducer = ActiveStatusLiveReducer()
    assert reducer.observe(_snapshot_rows(version="99")[0])["state"] == "invalid"

    reducer = ActiveStatusLiveReducer()
    rows = _snapshot_rows()
    assert reducer.observe(rows[0])["state"] == "in_progress"
    assert reducer.observe(rows[1]) is None
    update = reducer.observe(_health_row("unexpected_key", "0"))
    assert update is not None
    assert update["state"] == "invalid"
    assert update["reason"] == "unknown active snapshot key 'unexpected_key'"


def test_active_status_wire_value_failure_reaches_live_and_offline_consumers() -> None:
    rows = _snapshot_rows()
    query_nonce = next(
        row for row in rows if row["status_key"] == "query_nonce"
    )
    query_nonce["status_value"] = "01"

    reducer = ActiveStatusLiveReducer()
    updates = [
        update for row in rows if (update := reducer.observe(row)) is not None
    ]
    assert updates[-1]["state"] == "invalid"
    assert "query_nonce" in updates[-1]["reason"]

    snapshots, newest_started_generation = complete_active_status_snapshots(rows)
    assert snapshots == []
    assert newest_started_generation == 1


def test_active_event_status_outside_generation_does_not_replace_snapshot() -> None:
    reducer = ActiveStatusLiveReducer()
    assert reducer.observe(_health_row("fail_static", "false")) is None
    assert reducer.observe(_health_row("capture_lease", "accepted")) is None
    assert reducer.invalid_reason is None


def test_runtime_contract_digest_is_a_prewrite_authority_gate() -> None:
    identity = {
        "run_identity": "run",
        "build_identity": "build",
        "image_identity": "adaptive_hybrid_regulation",
        "estimator_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "active_policy_sha256": "c" * 64,
        "response_policy_sha256": "d" * 64,
        "numerical_policy_sha256": "e" * 64,
    }
    health = canonical_prewrite_fixture(
        expected_identity=identity, planned_live_stimulus_code=0xA808
    )
    ready = evaluate_prewrite_readiness(
        health,
        expected_identity=identity,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
    )
    assert ready.ready
    assert health[("protocol", "contract_id")] == CONTRACT_ID
    assert health[("protocol", "contract_sha256")] == CONTRACT_SHA256

    health[("protocol", "contract_sha256")] = "0" * 64
    held = evaluate_prewrite_readiness(
        health,
        expected_identity=identity,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
    )
    assert not held.ready
    assert any("protocol.contract_sha256" in item for item in held.mismatches)


@pytest.fixture(scope="module")
def firmware_command_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    output = tmp_path_factory.mktemp("firmware_host_contract") / "commands"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{FIRMWARE}",
            str(ROOT / "tests/cpp/firmware_host_command_contract_harness.cpp"),
            str(FIRMWARE / "otis_serial_command.cpp"),
            str(FIRMWARE / "otis_setup_authority.cpp"),
            "-o",
            str(output),
        ],
        check=True,
    )
    return output


def _firmware_verdicts(harness: Path, commands: list[str]) -> list[str]:
    completed = subprocess.run(
        [str(harness)],
        input="\n".join(commands) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.splitlines()


@pytest.fixture(scope="module")
def firmware_response_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    output = tmp_path_factory.mktemp("firmware_host_contract") / "responses"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{FIRMWARE}",
            str(ROOT / "tests/cpp/response_classifier_contract_harness.cpp"),
            str(FIRMWARE / "otis_regulation_transaction.cpp"),
            "-o",
            str(output),
        ],
        check=True,
    )
    return output


def _firmware_response_verdicts(
    harness: Path, vectors: list[tuple[float, float, int]]
) -> list[str]:
    completed = subprocess.run(
        [str(harness)],
        input="".join(
            f"{pre:.12g} {post:.12g} {delta}\n"
            for pre, post, delta in vectors
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.splitlines()


def _host_response_verdicts(
    vectors: list[tuple[float, float, int]],
) -> list[str]:
    policy_path = ROOT / str(
        RELATIONS["response_classification_is_stateful"]["policy"]
    )
    classifier = ResponseClassifier(
        observational=True,
        policy_document=json.loads(policy_path.read_text(encoding="utf-8")),
    )
    return [
        f"{result.classification.value},{result.reason}"
        for pre, post, delta in vectors
        for result in [
            classifier.classify(
                pre_error_hz=pre,
                post_error_hz=post,
                applied_delta_codes=delta,
                current_code=0xA950,
                minimum_code=0xA800,
                maximum_code=0xAB00,
            )
        ]
    ]


def test_host_legal_commands_cross_the_production_firmware_parser(
    firmware_command_harness: Path,
) -> None:
    commands = sorted(SIMPLE_COMMANDS) + [
        "ACTIVE LEASE 1",
        "ACTIVE SNAPSHOT 4294967295",
        "ACTIVE SETUP 1 7 99 650 4 0xA808 1 " + "a" * 64,
        "ACTIVE ARM 8 1234 2500",
        *(f"ACTIVE EVIDENCE 2 {phase}" for phase in (1, 2, 3, 4)),
    ]
    normalized = [parse_serial_command(command).normalized for command in commands]
    assert _firmware_verdicts(firmware_command_harness, normalized) == [
        "ACCEPT"
    ] * len(commands)


def test_stateful_response_classifier_matches_production_firmware(
    firmware_response_harness: Path,
) -> None:
    # Requests 2 and 4 reproduce the cumulative-response cases that escaped
    # the 2026-09-09 physical run's original offline replay.
    campaign_vectors = [
        (0.001666667, -0.001666667, -9),
        (0.0, -0.001666667, -4),
        (0.0, 0.0, -1),
        (-0.001666667, -0.001666667, 5),
    ]
    expected = [
        "healthy_detected,response_detected_with_commanded_sign",
        "healthy_detected,response_detected_with_commanded_sign",
        (
            "healthy_indeterminate_near_resolution,"
            "healthy_evidence_below_empirical_detection_floor"
        ),
        "healthy_detected,response_detected_with_commanded_sign",
    ]
    assert _host_response_verdicts(campaign_vectors) == expected
    assert _firmware_response_verdicts(
        firmware_response_harness, campaign_vectors
    ) == expected

    cumulative_wrong_sign = [(0.0, 0.004, 1), (-0.001, -0.0035, 1)]
    assert _host_response_verdicts(cumulative_wrong_sign) == (
        _firmware_response_verdicts(
            firmware_response_harness, cumulative_wrong_sign
        )
    )
    assert _host_response_verdicts(cumulative_wrong_sign)[-1] == (
        "wrong_sign,observed_response_opposes_positive_plant_gain"
    )

    branch_scenarios = [
        ([(0.01, 0.006, 1)], "wrong_sign"),
        ([(0.001, 0.008, 1)], "growing_error"),
        ([(-0.02, -0.012, 1)], "excess_response"),
        ([(0.0, 0.004, 1)], "healthy_detected"),
        ([(0.0, 0.001, 1)], "healthy_indeterminate_near_resolution"),
    ]
    for vectors, classification in branch_scenarios:
        host = _host_response_verdicts(vectors)
        assert host == _firmware_response_verdicts(
            firmware_response_harness, vectors
        )
        assert host[0].split(",", 1)[0] == classification


def test_illegal_command_boundaries_are_rejected_by_host_and_firmware(
    firmware_command_harness: Path,
) -> None:
    commands = [
        "ACTIVE LEASE 0",
        "ACTIVE LEASE 01",
        "ACTIVE SNAPSHOT 0x1",
        "ACTIVE ARM 1 2 0",
        "ACTIVE EVIDENCE 1 5",
        "ACTIVE EVIDENCE 1 4 5 -3 1 2 9000 " + "a" * 64,
        "ACTIVE SETUP 1 7 0x63 650 4 0xA808 1 " + "a" * 64,
    ]
    for command in commands:
        with pytest.raises(ValueError):
            parse_serial_command(command)
    assert _firmware_verdicts(firmware_command_harness, commands) == [
        "REJECT"
    ] * len(commands)


def test_every_command_form_has_arguments_and_a_first_consumer() -> None:
    assert set(COMMAND_FORMS) == {
        "active_lease",
        "active_snapshot",
        "active_setup",
        "active_arm",
        "active_evidence",
    }
    for form in COMMAND_FORMS.values():
        assert form["arguments"]
        assert form["acknowledgement"]
        assert form["first_consumer"]
    assert RECORD_SCHEMA_VERSIONS["active_hybrid_decisions_v3"] == 3
