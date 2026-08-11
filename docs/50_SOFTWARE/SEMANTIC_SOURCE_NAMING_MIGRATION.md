# Semantic Source Naming Migration

## Decision and scope

Current reusable source is named for its physical quantity, responsibility, or
operational capability. Programme sequence remains explicit data in profiles,
manifests, authority records, and historical evidence; it is not the namespace
of shared implementations.

This migration changes source and primary implementation names without changing
wire fields, timing domains, numerical policy, command authority, or sealed
evidence. The active programme permits offline preparation only. No hardware
I/O, firmware flash, serial command, control arm, or DAC write is part of this
change.

## Classification and mapping

| Classification | Old identity | Durable identity / treatment | Reason |
| --- | --- | --- | --- |
| reusable metrology | `phase4_boundary_estimator`, `otis_phase4_boundary_estimator` | `pps_boundary_frequency_estimator`, `otis_pps_boundary_frequency_estimator` | Estimates oscillator frequency from count-window boundaries mapped by accepted PPS support. |
| reusable observe-only discipline | `phase4_replay`, `otis_phase4_engine`, `otis_phase4_observe_preview` | `observe_only_discipline_replay`, `otis_observe_only_discipline_engine`, `otis_observe_only_discipline_live` | Replays or runs the non-actuating frequency-discipline state machine. |
| reusable reference-relative phase metrology | `cx318_relative_phase` | `reference_relative_phase_estimator` | Accumulates phase relative to explicitly identified reference observations and epochs. |
| reusable counterfactual control analysis | `cx318_hybrid_preview` | `phase_frequency_hybrid_preview` | Combines reference-relative phase and frequency terms without actuation authority. |
| reusable capture platform | `cx318_capture_segment`, `cx318_capture_handoff` | `capture_segment_rotation`, `capture_owner_handoff` | Same-owner segmentation and bounded serial-owner handoff are platform responsibilities. |
| reusable firmware preview platform | `otis_cx318_preview_*`, `otis_cx318_selected_preview_engine` | `otis_phase_preview_*`, `otis_selected_phase_frequency_preview_engine` | Formatting, transport, live observation, and selected preview computation are not programme-specific. |
| reusable tight-band policy | `cx318_stage5_tight_deadband`, `otis_cx318_stage5_tight_deadband` | `integer_count_tight_deadband`, `otis_integer_count_tight_deadband` | The policy is a persistent hysteretic gate over signed 600-second accumulated edge error. |
| reusable readiness and supervision | `cx318_stage5_runtime_contract`, `cx318_stage5_supervisor`, `cx318_stage5_tight_replay` | `prewrite_readiness_contract`, `tight_deadband_supervisor`, `tight_deadband_replay` | These implement pre-write evidence gates, supervision, and deterministic replay. |
| current no-write qualification | `cx319_g1_*`, `no_write_prewrite_readiness_contract` | `no_write_qualification_*`, `no_write_prewrite_readiness_contract` | G1 is a programme gate; the software capability is exact no-write qualification. |
| current bounded control qualification | `cx319_g2_*` | `bounded_tight_deadband_*` | G2 is a programme gate; the capability builds, rehearses, supervises, runs, and analyzes a bounded tight-deadband qualification. |
| shared attachment health | `cx319_host_attach_contract` | `host_attach_health_contract` | The contract freezes a host-attachment telemetry baseline and detects later degradation. |
| current offline integration gate | `cx319_offline_gate` | `stabilized_tight_deadband_offline_gate` | The gate validates the stabilized tight-deadband configuration across policy, firmware, and replay surfaces. |
| genuine hardware specialization | `cx317` plant models, active actuator/transaction logic, H1 oscillator domain, and CX317 campaign evidence tools | retain | These bind the CX317 oscillator, its measured response, its DAC plant, or immutable CX317 experiment provenance. |
| current configuration data | `cx318_*` and `cx319_*` profile IDs, schema IDs, matrix profile IDs, programme IDs, gate/leg IDs | retain as data | Existing policies and programme authority select semantic implementations; their identities are provenance-bearing configuration. |
| immutable provenance / compatibility | historical tool IDs, telemetry component tags such as `phase4_preview` and `cx318_preview`, schema versions, report paths, sealed manifests, experiment reports | retain; readers remain explicit | Rewriting these would change interpretation or prevent deterministic replay of existing evidence. They are excluded from new source naming. |
| archived programme orchestration | CX318 Stage 4 and suspended Stage 5 orchestration tools | retain as historical compatibility surfaces unless shared by current code | Their filenames and constants identify exact completed or suspended workflows. Shared mechanics are migrated out of them. |

## Compatibility boundary

Historical identity strings are intentionally not aliases for new programme
input. They remain accepted only where an existing reader validates an old
artifact or where a wire/component identity is already sealed. New imports,
includes, primary symbols, and current tool-module paths use semantic names.

In particular, the semantic modules deliberately retain the established tool
IDs (`cx318_capture_handoff_v1`, the CX318 Stage 5 analyzer IDs, and the CX319
G1/G2 tool IDs), telemetry component/tag values (`phase4_preview`,
`cx318_preview`, `cx318_preview_depth`, `cx318_preview_high_water`, and the
existing supervisor fault events), policy and method IDs, schema/profile IDs,
and report paths. The observe-only replay continues to read the manifest key
`phase4_replay` and to write `derived/phase4_replay_v3`; its older
`derived/phase4_replay_v1` products remain historical inputs. These values are
data contracts, not source-organization vocabulary.

The migration does not rewrite files under `runs/`, historical experiment
reports, frozen profile/schema identity strings, or canonical raw records.

## Verification boundary

Verification is offline. It includes focused Python and native tests, source
guards for semantic imports/includes, current firmware profiles, and current and
historical replay/reader tests. Any check requiring a device, serial port,
firmware flash, or physical qualification is out of scope and unauthorized.
