# CX319 Mapping-Informed Part B Terminal Report

## Decision

CX319 is complete as frozen predecessor evidence. The mapping-informed Part B
programme established bounded frequency-only traversal evidence and sufficient
zero-authority phase/hybrid observations to proceed to a separately identified
bounded active-hybrid qualification. It does not authorize that qualification.

The immutable programme seal is
`runs/cx319_range_spanning/mapping_informed_part_b_v4_20260817/final_decision_20260818/cx319_mapping_informed_part_b_programme_seal_v1.json`.
Its file SHA-256 is
`a86569c734ca200de08f268012fb6b4db1fcbc57d27aa4442c68b174e9f6d930`
and its semantic `seal_sha256` is
`2a954fb564a91834a1d67cf09aae483fe7e73578eff5923bddca85749b02ae0e`.
The CX320 predecessor audit revalidated that seal, every nested canonical seal,
the Part A readiness record and all three evidence snapshots without modifying
the ignored packages.

## Observed facts and claims boundary

- Part B binds exactly two physical acquisitions: the original lower and upper
  acquisitions. The lower reacquisition is an inference, not a third physical
  pass.
- The original upper traversal remains a right-censored bounded non-pass. A
  separate physical upper-completion acquisition supplies the remaining raw
  evidence. The programme-level result spans those two acquisitions.
- The upper-completion finalizer correction is a host-only superseding replay
  over unchanged retained evidence. It does not erase the original terminal or
  turn it into a clean original pass.
- All frequency applications remained on the one bounded CX319 transaction
  path. Phase and hybrid authority were zero.
- The final confirmed physical state is DAC code `0xA83C` (43068), predecessor
  DAC epoch 1. A future firmware flash or reset makes the physically applied
  code unknown until a new exact setup/application acknowledgement is captured
  and propagated.

The three sealed hybrid-preview streams contain 38,993 zero-authority records,
including 22,787 `HYBRID_TRACKING_PREVIEW` records. Fresh recomputation found
22 counterfactual corrections, 12 with a nonzero phase term, 9 in which removal
of the phase term changes the final rounded delta, 7 step-limited proposals,
zero range clamps and zero `FAULT_PREVIEW` rows. Those are counterfactual
proposals, not observed phase-steering responses.

## Limitations and next decision

CX319 does not establish absolute phase, UTC alignment, calibrated cable delay,
traceable frequency accuracy, holdover, active phase steering or a delivered
D9/GPOUT0 timing output. The controlled phase quantity available to its
successor is cumulative D8 oscillator-cycle movement relative to qualified D14
PPS within one continuous phase epoch. D10 remains an independent event input
and did not enter reference or control authority.

The next bounded decision is the CX320 active-hybrid qualification defined by
`docs/60_EXPERIMENTS/ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md`.
Only offline preparation is currently authorized. Physical entry requires a
separate operator decision naming the exact frozen bundle after its operational
rehearsal passes.
