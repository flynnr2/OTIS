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
)
from host.otis_tools.active_status_live_state import ActiveStatusLiveReducer
from host.otis_tools.adaptive_hybrid_replay import ResponseClassifier
from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.firmware_host_contract import (
    COMMAND_FORMS,
    CONTRACT,
    CONTRACT_ID,
    CONTRACT_SHA256,
    FRONTIERS,
    RECORD_FIELDS,
    RECORD_SCHEMA_VERSIONS,
    RELATIONS,
    SIMPLE_COMMANDS,
    verify_generated_cpp_header,
)
from host.otis_tools.prewrite_readiness_contract import (
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness,
)
from host.otis_tools.serial_commands import parse_serial_command


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


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
    rows.extend(_health_row(key, "0", version=version) for key in ACTIVE_STATUS_KEYS)
    rows.append(_health_row(SNAPSHOT_COMPLETE_KEY, "1", version=version))
    return rows


def test_contract_authority_is_current_complete_and_deterministically_generated() -> None:
    verify_generated_cpp_header()
    assert CONTRACT["compatibility"] == "exact_current_only"
    assert CONTRACT_ID == "OTIS_FIRMWARE_HOST_CONTRACT_V1"
    assert len(CONTRACT_SHA256) == 64
    assert {name: tuple(fields) for name, fields in CONTRACT_FIELDS.items()} == (
        RECORD_FIELDS
    )
    assert len(RECORD_FIELDS) == 16
    assert set(RELATIONS) == {
        "active_decision_whole_seconds_from_exact_ticks",
        "estimate_tick_is_wrapped_suffix_of_decision_tick",
        "active_status_generation_is_atomic",
        "metadata_absence_is_deferred_not_contradictory",
        "lifetime_counters_are_not_current_health",
        "authority_release_is_latched",
        "decision_replay_uses_post_decision_frontier",
        "response_classification_is_stateful",
    }


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
        "health_v1",
        "dac_steps_v1",
        "environment_v1",
        "pps_snapshots_v1",
        "forwarded_monitor_snapshots_v1",
        "estimates_v2",
        "control_previews_v1",
        "active_transactions_v2",
        "active_hybrid_decisions_v2",
        "active_hybrid_maintenance_v1",
        "relative_phase_observations_v1",
        "phase_estimator_outputs_v1",
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
    assert RECORD_SCHEMA_VERSIONS["active_hybrid_decisions_v2"] == 2
