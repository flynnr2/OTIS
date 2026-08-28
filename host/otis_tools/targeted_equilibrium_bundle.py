"""Create and validate the exact targeted equilibrium characterization bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .range_spanning_bundle import (
    _atomic_new_json,
    _binding,
    _firmware,
    _read,
    _utc_now,
    canonical_sha256,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_PATH = (
    ROOT
    / "profiles/qualification/otis_targeted_equilibrium_characterization_attempt6_v1.json"
)
PROGRAMME_ID = "OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_V1"
ATTEMPT2_PROGRAMME_ID = "OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_ATTEMPT2_V1"
ATTEMPT3_PROGRAMME_ID = "OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_ATTEMPT3_V1"
ATTEMPT4_PROGRAMME_ID = "OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_ATTEMPT4_V1"
ATTEMPT5_PROGRAMME_ID = "OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_ATTEMPT5_V1"
ATTEMPT6_PROGRAMME_ID = "OTIS_TARGETED_EQUILIBRIUM_CHARACTERIZATION_ATTEMPT6_V1"
SUPPORTED_PROGRAMME_IDS = {
    PROGRAMME_ID,
    ATTEMPT2_PROGRAMME_ID,
    ATTEMPT3_PROGRAMME_ID,
    ATTEMPT4_PROGRAMME_ID,
    ATTEMPT5_PROGRAMME_ID,
    ATTEMPT6_PROGRAMME_ID,
}
RETURN_TO_9600_PROGRAMME_IDS = {ATTEMPT5_PROGRAMME_ID, ATTEMPT6_PROGRAMME_ID}
BOUNDED_RUNTIME_HOLD_PROGRAMME_IDS = {
    ATTEMPT4_PROGRAMME_ID,
    ATTEMPT5_PROGRAMME_ID,
    ATTEMPT6_PROGRAMME_ID,
}
BUNDLE_TYPE = "otis_targeted_equilibrium_characterization_bundle_v1"
TOOL_ID = "otis_targeted_equilibrium_bundle_v1"
HOST_TOOL_PATHS = {
    "bundle": Path(__file__),
    "runner": Path(__file__).with_name("targeted_equilibrium_run.py"),
    "analyzer": Path(__file__).with_name("targeted_equilibrium_analyze.py"),
    "rehearsal": Path(__file__).with_name("targeted_equilibrium_rehearsal.py"),
    "capture": Path(__file__).with_name("capture_device.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "capture_checks": Path(__file__).with_name("capture_runtime_checks.py"),
    "contracts": Path(__file__).with_name("contracts.py"),
    "time_domains": Path(__file__).with_name("time_domains.py"),
    "run_validation": Path(__file__).with_name("validate_run.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_index": Path(__file__).with_name("evidence_index.py"),
    "model_math": Path(__file__).with_name(
        "sustained_hybrid_equilibrium_estimator_recovery_study.py"
    ),
}


def _validate_gnss_source_contract(target_baud: int) -> None:
    source = (
        ROOT / "firmware/arduino/otis_nano_rp2040_connect/otis_gnss_receiver.cpp"
    ).read_text(encoding="utf-8")
    config = (
        ROOT / "firmware/arduino/otis_nano_rp2040_connect/otis_config.h"
    ).read_text(encoding="utf-8")
    required_source = (
        "9600u, 115200u, 57600u, 38400u, 19200u, 14400u, 4800u",
        "115200u, 9600u, 57600u, 38400u, 19200u, 14400u, 4800u",
        '"$PMTK251,9600*17\\r\\n"',
        '"$PMTK251,115200*1F\\r\\n"',
        '"$PMTK414*33\\r\\n"',
        "configure_live_uart(action.baud, opening_target_epoch)",
        "link->confirmed_baud == link->policy.target_baud",
        "OtisGnssLinkState::ObserveConfiguredOutput",
        "OtisGnssOutputConfirmationMethod::Pmtk314AckObservedExact",
        "link->last_identity_response_baud = link->candidate_baud",
        "kGnssObservedExtendedOutputConfigurationFields = 22u",
    )
    if any(item not in source for item in required_source):
        raise ValueError("GNSS dual-baud discovery source contract differs")
    if (
        target_baud != 9600
        or "#define OTIS_GNSS_UART_BAUD 115200u" not in config
        or "OTIS_GNSS_UART_BAUD != 9600u && OTIS_GNSS_UART_BAUD != 115200u"
        not in config
    ):
        raise ValueError("GNSS 9600-baud source contract differs")


def _compiled_gnss_target_command(
    build_manifest_path: Path, target_baud: int
) -> dict[str, Any]:
    """Bind and verify the command selected in the compiled ELF."""
    manifest_path = build_manifest_path.resolve()
    manifest = _read(manifest_path, "firmware build manifest")
    elf_entry = next(
        (
            item
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and str(item.get("name", "")).endswith(".elf")
        ),
        None,
    )
    if elf_entry is None:
        raise ValueError("firmware build manifest has no ELF for GNSS command audit")
    elf_path = manifest_path.parent / str(elf_entry["name"])
    if (
        not elf_path.is_file()
        or sha256_file(elf_path) != elf_entry.get("sha256")
        or elf_path.stat().st_size != elf_entry.get("size_bytes")
    ):
        raise ValueError("firmware ELF identity differs from its manifest")
    commands = {
        9600: b"$PMTK251,9600*17\r\n",
        115200: b"$PMTK251,115200*1F\r\n",
    }
    expected = commands.get(target_baud)
    if expected is None:
        raise ValueError("unsupported GNSS target baud for compiled command audit")
    forbidden = commands[115200 if target_baud == 9600 else 9600]
    image = elf_path.read_bytes()
    if expected not in image or forbidden in image:
        raise ValueError(
            "compiled GNSS target command does not match the programme target baud"
        )
    return {
        "elf": _binding(elf_path),
        "target_baud": target_baud,
        "command": expected.decode("ascii"),
        "opposite_target_command_absent": True,
    }


def load_programme(
    path: Path = PROGRAMME_PATH, *, validate_current_source: bool = True
) -> dict[str, Any]:
    path = path.resolve()
    raw = _read(path, "targeted equilibrium programme")
    value = raw
    if raw.get("programme_id") in {
        ATTEMPT2_PROGRAMME_ID,
        ATTEMPT3_PROGRAMME_ID,
        ATTEMPT4_PROGRAMME_ID,
        ATTEMPT5_PROGRAMME_ID,
        ATTEMPT6_PROGRAMME_ID,
    }:
        base_binding = raw.get("base_programme", {})
        base_path = Path(str(base_binding.get("path", "")))
        if not base_path.is_absolute():
            base_path = ROOT / base_path
        if (
            not base_path.is_file()
            or sha256_file(base_path) != base_binding.get("sha256")
            or base_path.stat().st_size != base_binding.get("size_bytes")
        ):
            raise ValueError("layered base programme binding differs")
        base = load_programme(base_path, validate_current_source=False)
        value = {**base, **raw}
        value["frozen_inputs"] = {
            **base.get("frozen_inputs", {}),
            **raw.get("frozen_inputs", {}),
        }
    if (
        value.get("schema_version") != 1
        or value.get("programme_id") not in SUPPORTED_PROGRAMME_IDS
        or value.get("status")
        != "operator_authorized_pending_exact_build_bundle_preflight_and_rehearsal"
    ):
        raise ValueError("targeted equilibrium programme identity or state differs")
    authority = value.get("operator_authority", {})
    required_scope = {
        "firmware_build",
        "exact_bundle_creation",
        "structural_preflight",
        "operational_path_rehearsal",
        "firmware_flash",
        "board_reset",
        "serial_access",
        "predetermined_dac_setup_stimuli",
        "finite_live_acquisition",
        "evidence_analysis",
        "evidence_sealing",
        "evidence_registration",
    }
    if not required_scope <= set(authority.get("scope", [])):
        raise ValueError("operator authority does not cover the frozen campaign")
    if any(
        authority.get(key) is not False
        for key in (
            "automatic_retry",
            "automatic_restore",
            "frequency_control_authority",
            "phase_or_hybrid_actuation",
        )
    ):
        raise ValueError("targeted campaign must retain predetermined zero control authority")
    if (
        authority.get("physical_live_run_limit") != 1
        or authority.get("firmware_flash_limit") != 1
    ):
        raise ValueError("targeted physical limits differ")

    for label, binding in value.get("frozen_inputs", {}).items():
        source = ROOT / str(binding.get("path", ""))
        if not source.is_file() or sha256_file(source) != binding.get("sha256"):
            raise ValueError(f"frozen input differs: {label}")

    firmware = value.get("firmware", {})
    if (
        firmware.get("profile_id") != "cx319_range_map_part_a"
        or firmware.get("expected_board_serial") != "503533748A919118"
    ):
        raise ValueError("targeted firmware or board identity differs")
    gnss = value.get("gnss_live_boundary", {})
    expected_qualification_state = {
        PROGRAMME_ID: "deterministically_tested_pending_one_physical_qualification",
        ATTEMPT2_PROGRAMME_ID: (
            "baud_transition_physically_qualified_output_confirmation_correction_"
            "pending_one_physical_attempt"
        ),
        ATTEMPT3_PROGRAMME_ID: (
            "baud_transition_physically_qualified_pmtk514_22_field_correction_"
            "pending_one_physical_attempt"
        ),
        ATTEMPT4_PROGRAMME_ID: (
            "gnss_configuration_physically_qualified_runtime_health_hold_"
            "correction_pending_one_physical_attempt"
        ),
        ATTEMPT5_PROGRAMME_ID: (
            "attempt4_support_coupling_corrected_9600_return_pending_one_"
            "physical_attempt"
        ),
        ATTEMPT6_PROGRAMME_ID: (
            "attempt5_compiled_command_escape_corrected_9600_return_pending_one_"
            "physical_attempt"
        ),
    }[value["programme_id"]]
    return_to_9600 = value["programme_id"] in RETURN_TO_9600_PROGRAMME_IDS
    expected_candidate_order = (
        [9600, 115200, 57600, 38400, 19200, 14400, 4800]
        if return_to_9600
        else [115200, 9600, 57600, 38400, 19200, 14400, 4800]
    )
    expected_target_baud = 9600 if return_to_9600 else 115200
    expected_target_command = (
        "$PMTK251,9600*17\\r\\n"
        if return_to_9600
        else "$PMTK251,115200*1F\\r\\n"
    )
    if (
        gnss.get("qualification_state") != expected_qualification_state
        or gnss.get("candidate_baud_order") != expected_candidate_order
        or gnss.get("target_baud") != expected_target_baud
        or gnss.get("target_baud_command") != expected_target_command
        or gnss.get("failure_action")
        != "priority_abort_and_stop_before_first_DAC_write"
    ):
        raise ValueError("GNSS target-baud transition contract differs")
    if value["programme_id"] in {
        ATTEMPT2_PROGRAMME_ID,
        ATTEMPT3_PROGRAMME_ID,
        ATTEMPT4_PROGRAMME_ID,
        ATTEMPT5_PROGRAMME_ID,
        ATTEMPT6_PROGRAMME_ID,
    }:
        expected_baud_state = {
            ATTEMPT2_PROGRAMME_ID: "passed_reused_from_attempt1",
            ATTEMPT3_PROGRAMME_ID: (
                "passed_reused_from_attempt1_and_reaffirmed_attempt2"
            ),
            ATTEMPT4_PROGRAMME_ID: (
                "passed_reused_from_attempt1_and_reaffirmed_attempt2_and_attempt3"
            ),
            ATTEMPT5_PROGRAMME_ID: (
                "115200_to_9600_return_pending_same_run_prewrite_qualification"
            ),
            ATTEMPT6_PROGRAMME_ID: (
                "115200_to_9600_return_pending_same_run_prewrite_qualification"
            ),
        }[value["programme_id"]]
        if (
            gnss.get("baud_transition_qualification_state")
            != expected_baud_state
            or gnss.get("allowed_output_confirmation_methods")
            != ["pmtk514_exact", "pmtk314_ack_observed_exact"]
            or gnss.get("direct_output_observation_ms") != 2500
            or gnss.get("required_observed_sentence_mask") != 7
            or gnss.get("forbidden_observed_sentence_mask") != 0
            or gnss.get("required_prewrite_health", {}).get(
                "last_identity_response_baud"
            )
            != str(expected_target_baud)
        ):
            raise ValueError("GNSS attempt-2 output-confirmation contract differs")
    if value["programme_id"] in {
        ATTEMPT3_PROGRAMME_ID,
        ATTEMPT4_PROGRAMME_ID,
        ATTEMPT5_PROGRAMME_ID,
        ATTEMPT6_PROGRAMME_ID,
    }:
        expected_entry_path = (
            "single_flash_continuous_sole_owner_ordinary_gnss_d14_d8_gate_then_"
            "science_promotion"
            if value["programme_id"]
            in BOUNDED_RUNTIME_HOLD_PROGRAMME_IDS
            else "single_flash_continuous_sole_owner_gnss_gate_then_science_promotion"
        )
        if (
            gnss.get("pmtk514_qualified_field_count") != 22
            or gnss.get("pmtk514_qualified_signature")
            != "0101100000000000000000"
            or gnss.get("physical_entry_path")
            != expected_entry_path
            or gnss.get("confirmation_evidence", {})
            .get("pmtk514_exact", {})
            .get("output_configuration_field_count")
            != "22"
        ):
            raise ValueError("GNSS exact physical response contract differs")
    if value["programme_id"] in BOUNDED_RUNTIME_HOLD_PROGRAMME_IDS:
        if gnss.get("runtime_qualification_policy") != {
            "bounded_hold_status_keys": [
                "metadata_control_eligible",
                "raw_pps_control_eligible",
            ],
            "hold_deadline_source": "current_frozen_operation_timeout",
            "hold_behavior": (
                "continue_capture_and_do_not_complete_the_current_dependent_"
                "predicate_until_requalified"
            ),
            "scientific_support_requires_requalified_snapshot": True,
            "all_other_gnss_mismatches_are_immediate_invariant_failures": True,
        }:
            raise ValueError("GNSS attempt-4 bounded runtime hold contract differs")
        attempt4_stops = set(value.get("stop_policy", {}).get("abort_fail_static", []))
        if not {
            "receiver_identity_configuration_or_persistent_link_fault",
            "runtime_qualification_hold_deadline_expired",
        } <= attempt4_stops:
            raise ValueError("attempt-4 runtime stop contract differs")
    if return_to_9600:
        if firmware.get("required_defines", {}).get("OTIS_GNSS_UART_BAUD") != "9600u":
            raise ValueError("9600-return firmware does not freeze 9600 baud")
        if validate_current_source:
            _validate_gnss_source_contract(expected_target_baud)
    timing = value.get("timing", {})
    if timing != {
        "initial_capture_owned_warmup_s": 1800,
        "settling_exclusion_s": 900,
        "fresh_support_s": 600,
        "fresh_supports_per_dwell": 3,
        "minimum_dwell_s": 2700,
        "dwell_wait_timeout_s": 2820,
        "minimum_remaining_wall_before_new_dwell_s": 3000,
        "minimum_scientific_duration_s": 34200,
        "maximum_live_wall_s": 39600,
        "scheduling_domain": "host_monotonic_only_for_minimum_elapsed_waits",
        "decision_evidence_domain": "rp2040_timer0_with_declared_rollover_and_session_identity",
    }:
        raise ValueError("targeted timing contract differs")

    plan = value.get("dwell_plan")
    codes = [43070, 43046, 43070, 43094, 43070, 43046, 43070, 43094, 43070, 43046, 43070, 43094]
    if (
        not isinstance(plan, list)
        or len(plan) != 12
        or [row.get("index") for row in plan] != list(range(12))
        or [row.get("code") for row in plan] != codes
        or [row.get("partition") for row in plan]
        != ["identification"] * 7 + ["held_out"] * 5
        or {row.get("history_class") for row in plan}
        != {"outbound_or_anchor", "return"}
    ):
        raise ValueError("targeted 12-dwell plan or partition differs")
    if any(not 0xA800 <= int(row["code"]) <= 0xAB00 for row in plan):
        raise ValueError("targeted plan leaves characterized DAC envelope")
    analysis = value.get("analysis_contract", {})
    if (
        analysis.get("held_out_required_coverage") != "15/15"
        or analysis.get("maximum_equilibrium_interval_span_codes") != 18
        or analysis.get("maximum_outward_reversal_dead_zone_codes") != 8
        or analysis.get("maximum_absolute_drift_codes_per_hour") != "191/100"
    ):
        raise ValueError("targeted analysis contract differs")
    if value.get("topology") != {
        "D14": "sole_authoritative_pps_reference",
        "D8": "sole_authoritative_oscillator_count",
        "D10": "external_event_excluded",
        "GNSS_serial_metadata": "qualification_only_never_timing_authority",
    }:
        raise ValueError("targeted topology differs")
    return value


def gnss_health_reasons(
    gnss_contract: dict[str, Any], health: dict[tuple[str, str], str]
) -> list[str]:
    """Return exact prewrite/stability violations for one GNSS snapshot."""
    component = "gnss_receiver"
    reasons = [
        f"{key}={health.get((component, key))!r} expected {expected!r}"
        for key, expected in gnss_contract["required_prewrite_health"].items()
        if health.get((component, key)) != expected
    ]
    allowed = gnss_contract.get("allowed_output_confirmation_methods")
    if not allowed:
        return reasons
    method = health.get((component, "output_confirmation_method"))
    if method not in allowed:
        reasons.append(
            f"output_confirmation_method={method!r} expected one of {allowed!r}"
        )
        return reasons
    evidence = gnss_contract["confirmation_evidence"][method]
    for key, expected in evidence.items():
        if key.endswith("_minimum"):
            status_key = key[: -len("_minimum")]
            observed = health.get((component, status_key))
            try:
                below = int(observed if observed is not None else "-1") < int(expected)
            except ValueError:
                below = True
            if below:
                reasons.append(
                    f"{status_key}={observed!r} expected integer >= {expected}"
                )
        elif health.get((component, key)) != expected:
            reasons.append(
                f"{key}={health.get((component, key))!r} expected {expected!r}"
            )
    return reasons


def split_runtime_gnss_reasons(
    gnss_contract: dict[str, Any], reasons: list[str]
) -> tuple[list[str], list[str]]:
    """Split bounded qualification holds from invariant contradictions."""
    retryable_keys = gnss_contract.get("runtime_qualification_policy", {}).get(
        "bounded_hold_status_keys", []
    )
    held = [
        reason
        for reason in reasons
        if any(reason.startswith(f"{key}=") for key in retryable_keys)
    ]
    invariants = [reason for reason in reasons if reason not in held]
    return held, invariants


def create_bundle(
    *,
    build_manifest_path: Path,
    output_path: Path,
    programme_path: Path = PROGRAMME_PATH,
) -> dict[str, Any]:
    programme_path = programme_path.resolve()
    programme = load_programme(programme_path)
    firmware = _firmware(build_manifest_path)
    if programme["programme_id"] in RETURN_TO_9600_PROGRAMME_IDS:
        firmware["compiled_gnss_target_command"] = _compiled_gnss_target_command(
            build_manifest_path, programme["gnss_live_boundary"]["target_baud"]
        )
    required_defines = programme["firmware"]["required_defines"]
    for name, expected in required_defines.items():
        if firmware["defines"].get(name) != expected:
            raise ValueError(f"exact firmware define differs: {name}")
    unsigned = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "programme_id": programme["programme_id"],
        "programme": _binding(programme_path),
        "operator_authority": programme["operator_authority"],
        "device": {
            "expected_board_serial": programme["firmware"]["expected_board_serial"],
            "baud": 115200,
            "serial_path_resolution": "locate_unique_current_port_by_usb_serial",
        },
        "firmware": firmware,
        "gnss_live_boundary": programme["gnss_live_boundary"],
        "entry": {
            "mode": "fresh_exact_firmware_flash",
            "firmware_flashes_allowed": 1,
            "board_resets_allowed": 1,
            "dac_writes_before_prewrite_gate_allowed": 0,
        },
        "host_tools": {
            name: _binding(path) for name, path in sorted(HOST_TOOL_PATHS.items())
        },
        "timing": programme["timing"],
        "dwell_plan": programme["dwell_plan"],
        "analysis_contract": programme["analysis_contract"],
        "command_envelope": programme["command_envelope"],
        "stop_policy": programme["stop_policy"],
        "topology": programme["topology"],
        "prewrite_gate": {
            "exact_firmware_provenance": True,
            "sole_serial_owner": True,
            "gnss_identity_stable": True,
            "gnss_metadata_control_eligible": True,
            "d14_raw_pps_control_eligible": True,
            "dual_core_partition_fault": "none",
            "dual_core_fail_static": False,
            "d10_has_no_pps_or_control_role": True,
        },
        "application_propagation_invariant": [
            "timestamped DAC SET accepted by sole capture owner",
            "DAC manual_apply records exact requested and applied code",
            "Core 0 application advances the exact DAC epoch",
            "hybrid preview observes the same code and epoch with zero authority",
            "first selected 600-second estimator result reaches the tight-deadband consumer with the same capture session and DAC epoch",
        ],
    }
    bundle = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), bundle)
    return bundle


def validate_bundle(path: Path) -> dict[str, Any]:
    value = _read(path.resolve(), "targeted equilibrium bundle")
    declared = value.get("bundle_sha256")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("bundle_type") != BUNDLE_TYPE
        or declared != canonical_sha256(unsigned)
    ):
        raise ValueError("targeted equilibrium bundle identity differs")
    programme = load_programme(Path(value["programme"]["path"]))
    bindings = [value["programme"], *value["host_tools"].values()]
    firmware = value["firmware"]
    bindings.extend((firmware["build_manifest"], firmware["uf2"]))
    for binding in bindings:
        source = Path(binding["path"])
        if (
            not source.is_file()
            or sha256_file(source) != binding["sha256"]
            or source.stat().st_size != binding["size_bytes"]
        ):
            raise ValueError(f"bundle binding differs: {source}")
    expected_firmware = _firmware(Path(firmware["build_manifest"]["path"]))
    if programme["programme_id"] in RETURN_TO_9600_PROGRAMME_IDS:
        expected_firmware["compiled_gnss_target_command"] = (
            _compiled_gnss_target_command(
                Path(firmware["build_manifest"]["path"]),
                programme["gnss_live_boundary"]["target_baud"],
            )
        )
    if expected_firmware != firmware:
        raise ValueError("bundle firmware provenance differs")
    if value["dwell_plan"] != programme["dwell_plan"]:
        raise ValueError("bundle dwell plan differs from programme")
    if value["analysis_contract"] != programme["analysis_contract"]:
        raise ValueError("bundle analysis contract differs from programme")
    if value["gnss_live_boundary"] != programme["gnss_live_boundary"]:
        raise ValueError("bundle GNSS live boundary differs from programme")
    if value["operator_authority"] != programme["operator_authority"]:
        raise ValueError("bundle authority differs from programme")
    return value


def create_preflight(*, bundle_path: Path, output_path: Path) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    bundle = validate_bundle(bundle_path)
    plan = bundle["dwell_plan"]
    checks = {
        "bundle_identity_and_all_bindings": True,
        "exact_zero_authority_firmware_profile": (
            bundle["firmware"]["profile_id"] == "cx319_range_map_part_a"
            and bundle["firmware"]["defines"]["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"]
            == "0"
        ),
        "one_flash_and_one_live_run_only": (
            bundle["operator_authority"]["firmware_flash_limit"] == 1
            and bundle["operator_authority"]["physical_live_run_limit"] == 1
        ),
        "frozen_twelve_dwell_order": len(plan) == 12
        and [row["code"] for row in plan]
        == [43070, 43046, 43070, 43094, 43070, 43046, 43070, 43094, 43070, 43046, 43070, 43094],
        "frozen_twenty_one_fifteen_support_partition": (
            sum(row["partition"] == "identification" for row in plan) * 3 == 21
            and sum(row["partition"] == "held_out" for row in plan) * 3 == 15
        ),
        "all_codes_inside_characterized_envelope": all(
            0xA800 <= int(row["code"]) <= 0xAB00 for row in plan
        ),
        "initial_warmup_and_dwell_duration": (
            bundle["timing"]["initial_capture_owned_warmup_s"] == 1800
            and bundle["timing"]["minimum_dwell_s"] == 2700
            and bundle["timing"]["minimum_scientific_duration_s"] == 34200
        ),
        "gnss_target_baud_source_contract": (
            (
                bundle["gnss_live_boundary"]["candidate_baud_order"][:2]
                == [9600, 115200]
                and bundle["gnss_live_boundary"]["target_baud"] == 9600
                and bundle["gnss_live_boundary"]["target_baud_command"]
                == "$PMTK251,9600*17\\r\\n"
                and bundle["firmware"]["defines"].get("OTIS_GNSS_UART_BAUD")
                == "9600u"
            )
            if bundle["programme_id"] in RETURN_TO_9600_PROGRAMME_IDS
            else (
                bundle["gnss_live_boundary"]["candidate_baud_order"][:2]
                == [115200, 9600]
                and bundle["gnss_live_boundary"]["target_baud"] == 115200
            )
        ),
        "compiled_gnss_target_command_matches_programme": (
            bundle["programme_id"] not in RETURN_TO_9600_PROGRAMME_IDS
            or bundle["firmware"].get("compiled_gnss_target_command", {}).get(
                "target_baud"
            )
            == 9600
        ),
        "gnss_output_confirmation_contract": (
            bundle["gnss_live_boundary"].get(
                "allowed_output_confirmation_methods",
                ["pmtk514_exact"],
            )
            in (
                ["pmtk514_exact"],
                ["pmtk514_exact", "pmtk314_ack_observed_exact"],
            )
        ),
        "bounded_runtime_health_hold_contract": (
            bundle["programme_id"]
            not in BOUNDED_RUNTIME_HOLD_PROGRAMME_IDS
            or bundle["gnss_live_boundary"].get("runtime_qualification_policy")
            == {
                "bounded_hold_status_keys": [
                    "metadata_control_eligible",
                    "raw_pps_control_eligible",
                ],
                "hold_deadline_source": "current_frozen_operation_timeout",
                "hold_behavior": (
                    "continue_capture_and_do_not_complete_the_current_dependent_"
                    "predicate_until_requalified"
                ),
                "scientific_support_requires_requalified_snapshot": True,
                "all_other_gnss_mismatches_are_immediate_invariant_failures": True,
            }
        ),
        "D14_D8_D10_topology": bundle["topology"]
        == {
            "D14": "sole_authoritative_pps_reference",
            "D8": "sole_authoritative_oscillator_count",
            "D10": "external_event_excluded",
            "GNSS_serial_metadata": "qualification_only_never_timing_authority",
        },
        "no_retry_restore_or_control_authority": all(
            bundle["operator_authority"][key] is False
            for key in (
                "automatic_retry",
                "automatic_restore",
                "frequency_control_authority",
                "phase_or_hybrid_actuation",
            )
        ),
    }
    unsigned = {
        "schema_version": 1,
        "record_type": "otis_targeted_equilibrium_structural_preflight_v1",
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "status": "passed" if all(checks.values()) else "failed",
        "bundle": {
            "path": str(bundle_path),
            "sha256": sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "checks": checks,
        "hardware_operations": {
            "serial_opens": 0,
            "board_resets": 0,
            "firmware_flashes": 0,
            "dac_writes": 0,
        },
        "claim_boundary": "No-I/O structural and identity preflight; not an operational-path rehearsal or physical qualification.",
    }
    result = {**unsigned, "preflight_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--programme", type=Path, default=PROGRAMME_PATH)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--bundle", type=Path, required=True)
    preflight.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        value = create_bundle(
            build_manifest_path=args.build_manifest,
            output_path=args.output,
            programme_path=args.programme,
        )
    elif args.command == "preflight":
        value = create_preflight(bundle_path=args.bundle, output_path=args.output)
    else:
        value = validate_bundle(args.bundle)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
