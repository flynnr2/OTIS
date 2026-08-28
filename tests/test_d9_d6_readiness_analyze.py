from __future__ import annotations

import csv
import json
from pathlib import Path

from host.otis_tools.d9_d6_readiness_analyze import (
    ANALYSIS_PATH,
    REPORT_PATH,
    SEAL_PATH,
    analyze,
    seal,
)
from host.otis_tools.time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (
        ROOT
        / "docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
        / "d9_d6_readiness_contract_v1.json"
    ).read_text(encoding="utf-8")
)


def _csv(path: Path, fields: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)


def _status(profile: str, *, enabled: bool) -> list[list[object]]:
    values = {
        "contract_id": CONTRACT["contract_id"],
        "contract_sha256": CONTRACT["contract_semantic_sha256"],
        "state": "configured_10mhz_forwarded_unqualified" if enabled else "disabled",
        "source": "D8_GPIO20_GPIN0",
        "destination": "D9_GPIO21_GPOUT0",
        "integer_divider": "1",
        "fractional_divider": "0",
        "applied_auxsrc": "1",
        "applied_integer_divider": "1",
        "applied_fractional_divider": "0",
        "source_gpio_function": "8",
        "destination_gpio_function": "8",
        "inversion": "0",
        "drive_strength_ma": "2",
        "slew_rate": "slow",
        "nominal_frequency_hz": "10000000",
        "readback_valid": "true",
        "first_valid_ticks": "1",
    }
    rows = [
        ["STS", 1, 1, 0, "rp2040_timer0", "build", "profile_id", profile, "INFO", 0],
        [
            "STS",
            1,
            2,
            0,
            "rp2040_timer0",
            "boot_capabilities",
            "selected_profile",
            "H1_OCXO_OBSERVE_OPEN_LOOP",
            "INFO",
            0,
        ],
    ]
    for sequence, (key, value) in enumerate(values.items(), start=2):
        rows.append(["STS", 1, sequence, sequence, "rp2040_timer0", "forwarded_clock_output", key, value, "INFO", 0])
    return rows


def _stratum(
    root: Path,
    name: str,
    *,
    d6_offset: int = 0,
    bad_identity: bool = False,
    reference_sessions: tuple[int, int, int] = (7, 7, 7),
) -> Path:
    profile = {
        "baseline": "d9_disabled_no_control_baseline",
        "output": "d9_forwarded_output_no_control",
        "monitor": "d9_d6_forwarded_output_no_control",
    }[name]
    run_dir = root / "strata" / name
    binding = {
        "contract_id": CONTRACT["contract_id"],
        "contract_semantic_sha256": CONTRACT["contract_semantic_sha256"],
        "profile": profile,
        "physical_authority": False,
    }
    if bad_identity:
        binding["contract_semantic_sha256"] = "bad"
    manifest = {
        "run_id": name,
        "d9_d6_readiness": binding,
        "files": [
            {"path": "csv/health.csv", "contract": "health_v1"},
            {"path": "csv/pps_snapshots.csv", "contract": "pps_snapshots_v1"},
            {"path": "csv/forwarded_monitor_snapshots.csv", "contract": "forwarded_monitor_snapshots_v1", "optional": True},
        ],
    }
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _csv(
        run_dir / "csv/health.csv",
        ["record_type", "schema_version", "status_seq", "timestamp_ticks", "status_domain", "component", "status_key", "status_value", "severity", "flags"],
        _status(profile, enabled=name != "baseline"),
    )
    _csv(
        run_dir / "csv/pps_snapshots.csv",
        ["record_type", "schema_version", "session", "snapshot_sequence", "cumulative_down_counter", "reference_sequence", "reference_timestamp_ticks", "status", "backend"],
        [
            ["SNP", 1, 7, 0, 3_000_000_000, 10, 0, 0, "pio_wait_cumulative_snapshot_dma_v1"],
            ["SNP", 1, 7, 1, 2_990_000_000, 11, 16_000_000, 0, "pio_wait_cumulative_snapshot_dma_v1"],
            ["SNP", 1, 7, 2, 2_980_000_000, 12, 32_000_000, 0, "pio_wait_cumulative_snapshot_dma_v1"],
        ],
    )
    if name == "monitor":
        _csv(
            run_dir / "csv/forwarded_monitor_snapshots.csv",
            ["record_type", "schema_version", "session", "reference_session", "snapshot_sequence", "cumulative_down_counter", "reference_sequence", "reference_timestamp_ticks", "status", "backend", "channel_id"],
            [
                ["MNS", 1, 3, reference_sessions[0], 0, 3_000_000_000, 10, 0, 0, "pio_wait_cumulative_snapshot_cpu_v1", 3],
                ["MNS", 1, 3, reference_sessions[1], 1, 2_990_000_000 - d6_offset, 11, 16_000_000, 0, "pio_wait_cumulative_snapshot_cpu_v1", 3],
                ["MNS", 1, 3, reference_sessions[2], 2, 2_980_000_000 - 2 * d6_offset, 12, 32_000_000, 0, "pio_wait_cumulative_snapshot_cpu_v1", 3],
            ],
        )
    return run_dir


def _candidate(tmp_path: Path, **monitor_kwargs: object) -> Path:
    _stratum(tmp_path, "baseline")
    _stratum(tmp_path, "output")
    _stratum(tmp_path, "monitor", **monitor_kwargs)
    return tmp_path


def test_readiness_analyzer_separates_three_strata_and_never_promotes_d6_to_waveform(tmp_path: Path) -> None:
    result = analyze(_candidate(tmp_path))

    assert result["terminals"] == {
        "programme": "d9_d6_candidate_bundle_ready_for_physical_authority",
        "d9_waveform_claim": "output_function_correct_but_waveform_evidence_incomplete",
        "d9_waveform_reason": "no external scope or independently referenced frequency evidence is accepted by this analyzer",
    }
    assert result["strata"]["baseline"]["terminals"]["d9_output"] == "d9_output_disabled_profile_verified"
    assert result["strata"]["output"]["terminals"]["d9_output"] == "output_function_correct_but_waveform_evidence_incomplete"
    monitor = result["strata"]["monitor"]
    assert monitor["terminals"]["d6_monitor"] == "d6_forwarded_clock_monitor_qualified_as_diagnostic_only"
    # The first interval straddles the declared first-valid boundary and is
    # retained as transition evidence rather than used as steady-state proof.
    assert [item["absolute_difference_cycles"] for item in monitor["d6"]["comparisons"]] == [0]
    assert len(monitor["d6"]["activation_excluded_intervals"]) == 1
    assert all(item["terminals"]["d14_d8_acquisition"] == "d14_d8_acquisition_healthy" for item in result["strata"].values())


def test_d6_count_fault_is_local_and_does_not_turn_into_a_d9_waveform_claim(tmp_path: Path) -> None:
    result = analyze(_candidate(tmp_path, d6_offset=3))

    monitor = result["strata"]["monitor"]
    assert monitor["terminals"]["d6_monitor"] == "d6_monitor_platform_defect"
    assert monitor["terminals"]["d14_d8_acquisition"] == "d14_d8_acquisition_healthy"
    assert monitor["terminals"]["d9_output"] == "output_function_correct_but_waveform_evidence_incomplete"
    assert result["terminals"]["programme"] == "d9_d6_candidate_bundle_ready_for_physical_authority"


def test_identity_mismatch_is_a_programme_terminal_not_a_d6_local_fault(tmp_path: Path) -> None:
    _stratum(tmp_path, "baseline")
    _stratum(tmp_path, "output", bad_identity=True)
    _stratum(tmp_path, "monitor")

    result = analyze(tmp_path)

    assert result["terminals"]["programme"] == "readiness_invalid_due_to_identity_or_verification_failure"
    assert "semantic SHA-256 mismatch" in " ".join(result["strata"]["output"]["identity_errors"])


def test_monitor_never_compares_across_authoritative_reference_sessions(tmp_path: Path) -> None:
    _stratum(tmp_path, "baseline")
    _stratum(tmp_path, "output")
    _stratum(tmp_path, "monitor", reference_sessions=(7, 8, 8))

    result = analyze(tmp_path)

    monitor = result["strata"]["monitor"]
    assert monitor["terminals"]["d6_monitor"] == "d6_monitor_platform_defect"
    assert "crosses authoritative reference session" in " ".join(monitor["d6_errors"])
    assert monitor["terminals"]["d14_d8_acquisition"] == "d14_d8_acquisition_healthy"


def test_snapshot_and_timer_rollover_are_derived_from_declared_domains(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    for name in ("baseline", "output", "monitor"):
        snapshots = candidate / "strata" / name / "csv/pps_snapshots.csv"
        rows = list(csv.DictReader(snapshots.open(newline="", encoding="utf-8")))
        rows[0]["snapshot_sequence"] = str((1 << 32) - 1)
        rows[1]["snapshot_sequence"] = "0"
        rows[2]["snapshot_sequence"] = "1"
        rows[0]["reference_sequence"] = str((1 << 32) - 1)
        rows[1]["reference_sequence"] = "0"
        rows[2]["reference_sequence"] = "1"
        rows[0]["reference_timestamp_ticks"] = str(
            RP2040_TIMER0_MICROS_WRAP_TICKS - 16_000_000
        )
        rows[1]["reference_timestamp_ticks"] = "0"
        rows[2]["reference_timestamp_ticks"] = "16000000"
        _csv(snapshots, list(rows[0]), [list(row.values()) for row in rows])
    monitor_path = candidate / "strata/monitor/csv/forwarded_monitor_snapshots.csv"
    monitor_rows = list(
        csv.DictReader(monitor_path.open(newline="", encoding="utf-8"))
    )
    for index, row in enumerate(monitor_rows):
        row["snapshot_sequence"] = str(((1 << 32) - 1 + index) & ((1 << 32) - 1))
        row["reference_sequence"] = str(((1 << 32) - 1 + index) & ((1 << 32) - 1))
        row["reference_timestamp_ticks"] = str(
            (RP2040_TIMER0_MICROS_WRAP_TICKS - 16_000_000 + index * 16_000_000)
            % RP2040_TIMER0_MICROS_WRAP_TICKS
        )
    _csv(
        monitor_path,
        list(monitor_rows[0]),
        [list(row.values()) for row in monitor_rows],
    )

    result = analyze(candidate)

    assert result["terminals"]["programme"] == (
        "d9_d6_candidate_bundle_ready_for_physical_authority"
    )
    assert result["strata"]["monitor"]["terminals"]["d6_monitor"] == (
        "d6_forwarded_clock_monitor_qualified_as_diagnostic_only"
    )


def test_seal_writes_immutable_machine_and_human_artifacts(tmp_path: Path) -> None:
    result = analyze(_candidate(tmp_path))
    seal_value = seal(tmp_path, result)

    assert (tmp_path / ANALYSIS_PATH).exists()
    assert (tmp_path / REPORT_PATH).exists()
    assert (tmp_path / SEAL_PATH).exists()
    assert seal_value["programme_terminal"] == "d9_d6_candidate_bundle_ready_for_physical_authority"
