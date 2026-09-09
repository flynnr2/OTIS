# OTIS Platform Surface Reduction Audit

## Purpose and claim boundary

This audit inventories the current build and operational surface before the
planned recovery-state-machine and platform simplification work. It is a
decision aid, not deletion authority. Historical packages remain reproducible
from their recorded revisions; current HEAD does not need to retain obsolete
entry points merely to emulate those revisions.

The repository has no `Makefile`, included make fragment, CI workflow or
`pyproject.toml` console-script entry point. The effective “target” surface is:

- 28 entries in `firmware/arduino/firmware_matrix.json`; and
- directly executable modules under `tools/`, `host/otis_tools/` and firmware
  validation scripts.

The matrix currently labels 20 passing profiles `keep_active`, while
`profiles/programme_status_v2.json` identifies only
`cx323_d9_d6_72h_adaptive_hybrid` as the active programme. This disagreement
is itself support-surface debt.

## Firmware-profile disposition

### Current supported programme

- `cx323_d9_d6_72h_adaptive_hybrid`

### Current component verification

- `d9_disabled_no_control_baseline`
- `d9_forwarded_output_no_control`
- `d9_d6_forwarded_output_no_control`

### Historical-only passing profiles

CX319:

- `cx319_tight_lower`
- `cx319_tight_upper`
- `cx319_range_map_part_a`
- `cx319_range_part_b_lower`
- `cx319_range_part_b_upper`
- `cx319_range_part_b_upper_completion`

Superseded active-hybrid programmes:

- `cx320_active_hybrid`
- `cx321_active_hybrid`
- `cx322_direct_hybrid`
- `cx322_d9_d6_integration_engineering`
- `cx322_d9_d6_72h_sustained_engineering`
- `otis_sustained_hybrid_regulation_v1`

Completed GNSS characterization:

- `otis_gnss_baud_envelope_characterization_v1`
- `otis_gnss_baud_envelope_characterization_continuation_v1`
- `otis_gnss_baud_envelope_characterization_resume_v1`

Completed frequency soak:

- `d9_d6_frequency_only_lower`

### Expected-failure profiles

Retain as current generic guards:

- `invalid_gnss_uart_tx_disabled`
- `invalid_pps_ratio_with_pio_capture`
- `invalid_pseudo_pps_nonisolated_resources`

Replace before removal:

- `invalid_active_missing_gnss` protects a current invariant through a CX319
  profile. Replace it with a CX323-specific negative build.

Obsolete predecessor guards:

- `invalid_cx321_enable_value`
- `invalid_cx321_active_hybrid_parameters`
- `invalid_cx320_active_hybrid_parameters`
- `invalid_cx319_lower_parameters`

Before predecessor guards are removed, CX323 should gain focused negative
builds for its authority, maintenance-evidence, D9/D6-isolation and parameter
constraints.

## Build frontend

`tools/firmware_matrix.py` is the actual firmware build frontend.

Retain:

- `--tier fast|campaign|release`
- `--profile`
- `--list`
- `--check-environment`
- `--prepare-ide`
- `--supported-only`

Remove or correct:

- `--all-profiles` currently duplicates the default release selection because
  every entry has the release tier and the loader rejects archived lifecycle
  values. Its historical-profile help text is false.
- The no-hardware `historical` tier executes nothing. Treat it as lifecycle
  guidance, not a verification target.

## Recommended supported operator surface

Keep the documented public interface small:

1. `verify fast|campaign|release`;
2. firmware `list`, `check-environment`, `build PROFILE` and
   `prepare-ide PROFILE`;
3. CX323 `bundle`, `preflight`, `activate`, `rehearse`, `run`, `monitor` and
   `recover-finalization`; and
4. evidence `snapshot`, `register`, `validate`, `list` and `mothball`.

The following are current internal components and should normally be reached
through the supported runner/bundle rather than presented as independent
operator workflows:

- `active_hybrid_bundle`, `active_hybrid_activation`,
  `active_hybrid_preflight`, `active_hybrid_live_rehearsal`,
  `active_hybrid_live_supervisor`, `active_hybrid_live_analyze`,
  `active_hybrid_analyze`, `active_hybrid_finalize`,
  `active_hybrid_rehearsal`, `active_hybrid_proposal` and
  `active_hybrid_evidence_audit`;
- `capture_device`, `capture_serial`, `capture_segment_rotation`,
  `abort_transport` and `serial_commands`; and
- `evidence`, `evidence_finalization`, `plant_model`,
  `pps_cumulative_span_estimator` and `tolerance_provenance`.

## Straightforward leaf removals and consolidations

- `send_command.py` is an alias for `serial_commands.main`.
- `parse_baseline_serial.py` is obsolete and broken: it imports the removed
  `host.otis_tools.report_run` module.
- `capture_owner_handoff` is a CX318 predecessor; current operation uses
  same-owner segment rotation.
- `no_write_qualification_recover` is a one-defect Q1 recovery entry point
  with no current references.
- `pps_fault_alignment`, `pps_fault_scoring`, `pseudo_pps_acceptance` and
  `service_plane_probe` are early bring-up utilities referenced only by
  historical material.
- `q2_transaction_run` and its rehearsal/bundle family are historical-only.
- `d9_hybrid_promotion_audit` and `d9_d6_candidate_bundle` belong to the
  closed Prompt 02–04 gate.
- The `d9_d6_frequency_only_*` and `gnss_baud_envelope_*` families belong to
  completed programmes.
- `targeted_equilibrium_*`, `sustained_hybrid_*_study`,
  `adaptive_steering_offline_study` and `cx323_successor_offline_study` are
  completed study executables.
- The CX319 `bounded_tight_deadband_*`, `conditional_part_*`,
  `range_spanning_*`, `no_write_qualification_*`,
  `cx319_part_b_programme_seal` and
  `stabilized_tight_deadband_offline_gate` families are historical operational
  surfaces.

## Current entanglement that prevents bulk deletion

The current CX323 roots have a 71-module transitive import graph. Several
historically named modules still own current shared semantics:

- `active_hybrid_bundle` imports
  `cx322_d9_d6_72h_engineering.load_contract`;
- current supervisor, analyzer, transactions and contracts import
  `cx321_plant_sign_evidence_guard`;
- current supervisor, rehearsal and setup authority import
  `bounded_tight_deadband_prewrite_contract`;
- `capture_device` dynamically imports `bounded_tight_deadband_activation`,
  pulling much of the CX319 bundle graph into current capture;
- `active_hybrid_evidence_audit` imports CX319 conditional/range-spanning
  validators; and
- current bundle construction may hash predecessor-named tools even without a
  direct Python import.

Those paths are historical as operator workflows but remain current internal
dependencies. Extract their live shared semantics into plainly named current
modules before deleting the predecessors.

## Obsolete early bring-up surface

These SW1 modes have no supported matrix profile:

- `SW1_SYNTHETIC_USB`
- `SW1_GPIO_LOOPBACK`
- `SW1_GPS_PPS`
- `SW1_TCXO_OBSERVE`

Arduino builds now require `otis_build_profile.generated.h`; the sketch
README’s manual-mode-selection instructions are stale.
`OTIS_SW1_MODE_H1_OCXO_OBSERVE` remains the common internal base for current
profiles, but its public “manual H1 bring-up” meaning is obsolete.

These selectors have no enabled passing profile:

- `OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW`
- `OTIS_ENABLE_CX318_STAGE4_PREVIEW`
- `OTIS_ENABLE_CX318_STAGE5_PREVIEW`
- `OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP`
- `OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL`
- `OTIS_ENABLE_H1_DAC_SWEEP`
- `OTIS_ENABLE_PSEUDO_PPS_GENERATOR`

The deprecated Pico SDK `CMakeLists.txt` is archival and has no current build
consumer. Non-historical documentation also advertises nonexistent targets
including `report_run`, `h1_characterize`, `observe_only_discipline_replay`,
`phase4_observe_only` and `phase5_qualification`.

## Safe reduction order

1. Correct lifecycle documentation and stale command examples.
2. Add an inventory regression so closed profiles cannot silently remain
   `keep_active`.
3. Add CX323-specific expected-failure guards.
4. Remove historical passing profiles and predecessor-specific failure
   profiles from the current matrix.
5. Remove broken aliases, dead options and unreferenced leaf recovery tools.
6. Extract current shared contracts and helpers from predecessor-named
   modules, verifying CX323 producer-to-consumer behavior and bundle identity.
7. Remove historical CLI entry points, then newly unreachable historical
   implementation modules and current-HEAD tests.
8. Remove dead SW1 selectors and conditional firmware branches one at a time,
   compiling CX323 and the three retained D9 component profiles after each
   bounded change.
9. Remove the deprecated Pico SDK scaffold last, or retain it only as clearly
   non-buildable historical documentation.

No multi-day bench qualification should begin during this reduction. The
recovery state machine, deterministic fault-injection matrix, exact current
profile build and complete operational-path rehearsal must be established
before the corrected physical continuation.
