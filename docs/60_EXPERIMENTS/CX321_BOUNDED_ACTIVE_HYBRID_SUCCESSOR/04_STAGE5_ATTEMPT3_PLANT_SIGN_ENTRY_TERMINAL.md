# CX321 Stage 5 Attempt 3 Plant-Sign Entry Terminal

## Decision

CX321 v2 reached its first decision-bearing physical gate in
`stage5_live_attempt3_20260821T1543Z`. The result is the bounded non-pass
`plant_sign_qualification_not_exercised`.

At the unchanged setup code `0xA83C`, firmware retained two contiguous,
non-overlapping, same-epoch 1,500-interval estimates:

```text
pre1 total = 15,000,000,003   signed error = +3 counts
pre2 total = 15,000,000,002   signed error = +2 counts
difference = -1 count
```

Both estimates were `TIGHT_INSIDE` and within the prospective nonzero five-
count entry band. They did not satisfy the separately frozen exact-equality
precondition. Firmware therefore entered `PLANT_SIGN_NOT_EXERCISED`, retained
the confirmed `0xA83C` code and applied neither the 21-code identification
stimulus nor any natural hybrid-controller correction.

This does not reject the plant gain or infer a DAC sign. It establishes that
the v2 attribution precondition was not met in this physical placement. The
one-count adjacent-window change is also inside the earlier observed two-count
fixed-code range, so weakening the equality condition after observation would
move the frozen gate and is not permitted.

## Acquisition and replay

- setup application: 2026-08-21 15:54:07Z, DAC epoch 1;
- qualified origin: 2026-08-21 16:24:02Z,
  `est:cx317:selected600:000541`;
- `pre1` close: approximately 16:34Z;
- `pre2` terminal: 2026-08-21 16:59:15Z;
- parsed records: 158,488;
- parser errors, reconnects and rejected commands: zero;
- priority abort submissions/deliveries: one/one;
- final confirmed code: `0xA83C`.

The original supervisor recorded the firmware's `active_fail_static` as the
generic `measurement_authority_or_platform_fault` before consuming the exact
terminal PSQ row. The original record and seal are preserved. A deterministic
offline consumer correction over the unchanged evidence now verifies the raw
snapshot reconstruction, PSQ rejection predicate, ACT identity, no-natural-
handoff condition, abort ordering and static terminal:

- original seal semantic SHA-256:
  `6c998caaa8a042c46f03c6ad1dab92792700c72fd1892221172cf487297ae684`;
- superseding seal semantic SHA-256:
  `dcea9b4077781fed352c47607c4017595d88764735ed5bb72439333bac2d2694`;
- superseding seal file SHA-256:
  `50df6312fd4616802a070a8f699e83e22fe3ddfcae7f224e8f6475450db1536c`;
- registered superseding package content SHA-256:
  `5601b3de7cdedc6fee686790652246c78c65eeb43afc6e4de1547fb86b6cd3bb`.

The correction changes no raw record, firmware behavior, estimator, threshold
or scientific verdict. The final acquisition and offline-finalization gates
both pass.

## Next gate

Do not repeat attempt 3 under the same activation. Its single-use authority is
consumed and its exact-equality gate has already produced a valid result. The
next decision is offline: either accept CX321 as the terminal bounded non-pass,
or prospectively design a successor attribution method that admits measured
fixed-code variation without confusing it with a DAC response. A new physical
programme would require a new frozen design, bundle, rehearsal and authority.
