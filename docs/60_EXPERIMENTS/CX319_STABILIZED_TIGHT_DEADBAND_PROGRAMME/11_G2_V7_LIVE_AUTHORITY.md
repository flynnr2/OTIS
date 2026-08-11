# CX319 G2 v7 Live Authority

## Operator decision

On 2026-08-11 the operator explicitly authorized the exact CX319 G2 v7
attachment-baseline package and confirmed physical presence at the bench.

This authority is bound to:

- proposal bundle
  `f92f41854306bba103afd8ef0fe1aa560360aa0da81c94547624165028b68dd4`;
- accelerated operational-rehearsal content
  `549d93a5227482515a5824a044ff6b2e7a7530473074c42a0e33f6c52c179b43`;
- operational-rehearsal seal
  `be8973fb35b33c2015887d8af81e2329bd8e3400c5266afbf3a148c92836ec0c`;
- v7 readiness record
  `docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/10_G2_V7_ATTACHMENT_BASELINE_OFFLINE_READINESS.md`
  at SHA-256
  `ac07ba52c874533aa7d234e3aedd2609d3a8937bc57008ec109eef07c13752aa`;
- the unchanged G1-qualified firmware identity; and
- the exact expected board and device identity recorded by the activation.

## Permitted operation

The authority permits:

1. one ordinary board restart, with no firmware flash;
2. immediate continuously drained host attachment;
3. two consecutive complete health emissions at one cumulative ordinary
   telemetry-drop value, frozen as the attachment baseline;
4. pre-write proof of firmware uptime no greater than 120 seconds and every
   other bound identity, evidence, capture, preview, partition, control and
   zero-write invariant;
5. one exact `DAC SET 0xA808` setup transaction only after that proof passes;
6. positive automatic corrections only, with at most four corrections, 21
   codes per correction and 84 codes cumulative; and
7. the frozen supervisor, analyzer, seal and evidence-registration path.

Any ordinary telemetry increment after the frozen attachment baseline, or any
absolute health-gate failure, stops fail-static at the last confirmed code. The
prior cadence, settling, fresh-support, qualification, finite-duration, range,
one-request, no-retry, no-restore and phase/hybrid-zero-authority limits remain
exact.

The retired v5 and v6 activations are not reusable. A failed or bounded-nonpass
v7 run does not authorize a retry. G3 remains conditional on a passing G2 v7
seal and a fresh upper-side bundle and rehearsal. No G4 or phase/hybrid
actuation is authorized.
