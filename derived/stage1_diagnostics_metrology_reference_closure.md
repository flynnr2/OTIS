# Stage 1 Diagnostics, Metrology, and Reference Closure

## Decision

The software programme defined by staged prompts 04, 05, and 06 is complete
for no-hardware acceptance. The next evidence gate is bench testing. Nothing
in this closure authorizes DAC actuation.

## Prompt 04 — First-class diagnostics

- `diagnostics_v1` defines stable identifiers, episodes, transitions, severity,
  confidence, hysteresis, exact first/latest evidence, algorithm/configuration
  identity, independent effects, and explicit clear reasons.
- Host and firmware use deterministic reducers. The complete rule catalogs and
  canonical configuration hash are parity-tested.
- Implemented Phase 4/5 findings cover reference cadence and authority,
  counter aperture, sequence continuity, interpolation support, invalid or
  saturated count windows, resource registry/capture failure, plant-model
  applicability, output loss, and estimator identity.
- Sealed fixtures cover raise/update/clear, hysteresis, duplicate and missing
  evidence, sequence regression, effects, eventual output-loss reporting after
  queue recovery, and structural non-actuation.
- A dropped derived frame rolls back tentative diagnostic transitions, so
  backpressure cannot silently consume the diagnostic that reports it.

Completion gate: the same sealed normalized evidence and rule configuration
produce identical native-firmware and host transition rows and effects.

## Prompt 05 — Measurement uncertainty

- `estimates_v2` removes the ambiguous version-1 uncertainty label and keeps
  `dispersion_hz` explicitly separate.
- The versioned component budget distinguishes quantization, physical
  aperture, reference, calibration, model, combined, coverage, and expanded
  uncertainty.
- Missing evidence emits incomplete/unavailable with empty combined values.
- Implemented combination policies are one-component identity and explicitly
  independent root-sum-square; validators recompute both and reject unsupported
  correlation claims.
- Live and replay `EST v2` fields match for unavailable and incomplete cases.
- `measurement_semantics_usage_inventory.csv` is the generated,
  repository-wide line inventory and is freshness-tested.
- Historical `estimates_v1` remains readable with its legacy meaning explicit.

Completion gate: no current producer emits sample dispersion as measurement
uncertainty.

## Prompt 06 — Reference qualification

- `reference_observations_v1` separates cadence, capture health, receiver
  authority, UTC traceability, metadata freshness, uncertainty, and overall
  qualification while preserving raw `REF` bytes.
- Good cadence without metadata is
  `cadence_valid_authority_unknown`, never qualified.
- Host STS metadata supports receiver/firmware identity, timing/fix/holdover,
  antenna, leap/UTC, sawtooth, cable delay, pulse configuration, calibration,
  uncertainty, and staleness. Unsupported values remain unknown/empty.
- Identity changes create deterministic epochs when the producer supplies no
  explicit epoch.
- Native/host sealed fixtures cover missing metadata, bad cadence with healthy
  metadata, stale and future-dated metadata, holdover, UTC invalid, antenna
  fault, sequence regression, and qualification.
- The current live hardware profile formally declares receiver metadata
  unavailable; it cannot promote PPS cadence to authority.

Completion gate: reference qualification is explicit, evidence-backed, and
enforced in estimator eligibility.

## Bench boundary

Bench testing must now supply physical evidence that software cannot invent:
target USB/backpressure behavior, receiver metadata if a decoder is connected,
PPS-gated physical aperture and latency, reference/calibration uncertainty,
long-run reconnect behavior, and measurement-backend qualification. Until that
evidence is promoted through versioned contracts, uncertainty remains
incomplete and reference authority remains unqualified on the live PPS-only
profile.
