# CX320 Offline Readiness and Non-Effective Authority Proposal

## Readiness decision

Offline Stages 0--4 pass. One exact 12-hour-qualified, 16-hour-wall programme is
frozen and its accelerated operational path passes. The physical authority
proposal remains non-effective. This report does not authorize a flash, reset,
serial-device open, command FIFO, setup application, DAC write, arm, physical
rehearsal or live acquisition.

The exact bundle is
`runs/cx320_active_hybrid/exact_bundle_passing_20260820/cx320_active_hybrid_exact_bundle_v1.json`:

- file SHA-256:
  `4a7ee9f08fea39759ca15cbff4547ce51d556235a94a39ba6fa16671a8ea9d9d`;
- semantic `bundle_sha256`:
  `62ee48c2e8e20e78f30b5c77d7457b37f6f8495b0a536a6b349f59c777d50fae`;
- source/configuration build identity:
  `6fc392da0562a77b0e80845738e57f61e7d8e44b3c41ade2ebc1292bb66b2206:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- UF2 SHA-256:
  `95864a904e4407b159b30bf45ba8f9d185ad33938cb2a10e50aea4bc712de777`.

The tracked proposal is
`profiles/qualification/cx320_active_hybrid_authority_proposal_v1.json`. Its
file SHA-256 is
`22c0c0df67757ae50bdc8ea11b45b69c4508456d82200907c6cf95b2cc56b3ca`
and semantic `proposal_sha256` is
`153577ae94dce4faaf5942a80b4118cd51817e9e291f496b80d75e0a200d38f4`.
Every current physical permission in it is `false`.

## Gates passed

- Predecessor audit: the CX319 programme seal and all bound evidence identities
  revalidated; the expected 38,993/22,787 preview corpus and 22/12/9/7/0/0
  proposal summary were recomputed.
- Replay: the selected policy passed its declared budget, checkpoint, clamp and
  fail-static selection checks across all four frozen source streams and the
  measured plant-gain envelope.
- Host/firmware parity: both directions, zero/small/capped phase, material and
  non-material rounding, acquisition/entry, every global limit, chatter,
  epoch/identity/reference/response faults and terminal clearing passed.
- Structural preflight: semantic SHA
  `24d327260a1d5e5c5de0cc0f030850d490948fd626330ec85ea6bbfbec7ddb93`;
  file SHA-256
  `b2dfc10d937d291a7014bb5d004030b66a20ce885f13ba2df3e87112c9782032`.
- Accelerated operational rehearsal: semantic seal
  `9ef2cfa5f1a9b31e527146baf38ba87751effceed83189464eb2812e7b1096bb`;
  evidence content
  `9b974b84bd31a9c9aea4d6e1e819c45d2e68a2725a981657295eff8c8872064d`;
  external registration validation passed.
- Verification: Fast 99 tests; Campaign 242 tests; Release 802 current tests
  with 27 historical tests excluded by policy. All seven supported firmware
  profiles passed and all six expected-failure guards failed for their declared
  reason.

The rehearsal exercised exact setup propagation, one frequency-only and two
phase-material modeled applications, the mandatory first response replay before
`ACKE`, conditional later release, clean phase-only degradation, shared
fail-static, USB/transport obstruction, distinct priority-abort submission and
delivery, failed-delivery owner retention, sole serial ownership, logical
rotation, analysis, sealing and registration. It exercised the real host
controller, contracts, replay guard, supervisor state contract and finalizers.
It did not exercise firmware cross-core runtime, physical D14/D8 capture, a DAC
write, the CX317 plant or a USB device.

The initial preflight attempt caught and preserved an offline harness defect:
an expected `false` value for “physical actions performed” was incorrectly fed
to an all-true aggregate. The predicate was corrected to the positive
`no_physical_actions_performed` check, the host-tool identities were rebound,
and the exact preflight and rehearsal were rerun. No firmware or physical input
changed.

## Separate decision required

Physical execution may proceed only after an explicit operator decision names
bundle
`62ee48c2e8e20e78f30b5c77d7457b37f6f8495b0a536a6b349f59c777d50fae`
and makes the proposal's progressive envelope effective. That future authority
is consumed by the first physical terminal. No retry, tuning, threshold change
or duration extension is implied. Until that decision, stop here.
