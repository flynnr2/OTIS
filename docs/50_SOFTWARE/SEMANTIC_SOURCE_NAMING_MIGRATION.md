# Semantic Source Naming and Compatibility Reset

## Decision

Current reusable source is named for its physical quantity or responsibility.
Programme sequence remains data in profiles, manifests, wire records, and
reviewed historical reports. Current HEAD supports only
`CX319_EVIDENCE_EPOCH_1`.

## Extracted current mechanics

| Responsibility | Current module |
|---|---|
| abort-only priority transport | `abort_transport` |
| active transaction parsing, validation, and durable phase release | `active_transactions` |
| active controller policy | `active_control_policy` |
| current shared control transport and fail-static mechanics | `active_control_supervisor` |
| serial-owner, capture-state, and obstruction checks | `capture_runtime_checks` |
| frequency control replay and supervision | `frequency_control_replay`, `frequency_control_supervisor` |
| measurement reconstruction | `measurement_replay` |
| integer-count tight-band policy | `tight_deadband_policy` |
| current analyzer replay helpers | `control_evidence_replay` |
| finalization helpers | `campaign_finalization` |
| phase and hybrid metrology | `reference_relative_phase_estimator`, `phase_frequency_hybrid_preview` |
| same-owner segmentation | `capture_segment_rotation`, `capture_owner_handoff` |

The extraction is not a forwarding layer: retired campaign modules and their
state modes were deleted after current consumers moved.

## Retained historical-looking identities

The deployed current wire and firmware still emit `cx317_*` identities, use
the `h1_cx317_ocxo_10mhz` clock-domain name, and bind profile/model/estimator
files whose names record their origin. The current owner-handoff transition
also retains `CX318_STAGE5_TRANSITION_SPOOL`. These are exact scientific
provenance and current wire contracts, so they remain unchanged.

They are not import aliases and do not keep historical campaign readers,
profiles, CLIs, or tests executable. Historical tool IDs in reviewed reports
remain records; helper modules without a current executable entry point do not
claim those IDs.

## Removed surfaces

The reset removed H0/SW1 examples and wire-validation workflow, H1 campaign
CLIs/templates, Phase 4/5 replay and qualification readers, CX317 Stage 6–8
campaign orchestration, CX318 Stage 4 and suspended Stage 5 operational tools,
archived matrix profiles, and dedicated compatibility tests. Reviewed
experiment reports and evidence digests remain unchanged.

Verification is offline and follows
`docs/50_SOFTWARE/VERIFICATION_AND_PROFILE_LIFECYCLE.md`.
