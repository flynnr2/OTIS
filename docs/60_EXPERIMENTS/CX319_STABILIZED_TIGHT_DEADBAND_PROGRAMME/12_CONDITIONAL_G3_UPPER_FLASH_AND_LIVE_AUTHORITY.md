# Conditional G3 Upper-Profile Flash and Live Authority

## Authority disposition

This one-run authority was consumed by
`g3_upper_live_20260813T173645Z/live_leg_b` on 2026-08-13. The run reached its
finite endpoint without an actionable upper-side condition and does not
authorize a retry. The result, evidence identities and next gate are recorded
in `37_Q4_UPPER_SIDE_NONACTIONABLE_PHYSICAL_RESULT.md`.

## Operator decision

On 2026-08-11 the operator explicitly authorized, if and only if G2 passes,
one exact `cx319_tight_upper` firmware flash and G3 execution under the existing
bounded envelope.

This decision extended the conditional G3 authority in
`05_G2_AND_CONDITIONAL_G3_LIVE_AUTHORITY.md`. Before its execution it did not
authorize an unidentified image, an early G3 entry, a G2 retry or any
additional firmware operation.

The operator further directed on 2026-08-13 that G2 and G3 remain a matched
pair. G3 must preserve G2's firmware and host semantics, cadence behavior,
gates, monitoring, analysis, and stop rules, changing only the upper-leg
profile, `0xA848` setup code, and negative required direction. Cadence
acceleration is deferred until both approach directions have completed.

## Conditions before execution

The authority becomes executable only when:

1. the active G2 v7 run completes and its immutable analysis and seal report
   `passed`;
2. programme status records that exact passing evidence;
3. a new upper-side bundle binds the `cx319_tight_upper` build manifest, UF2,
   source/configuration identity, setup code `0xA848`, negative direction,
   device identity, host tools, analyzer, seal and stop conditions;
4. structural preflight and a fresh accelerated complete operational-path
   rehearsal pass against that exact bundle; and
5. a G3 activation binds those exact artifacts and the passing G2 evidence.

## Permitted operation

Once every condition passes, the authority permits:

- one exact build-manifest-bound `cx319_tight_upper` firmware flash;
- the resulting automatic reset and bounded USB re-enumeration;
- read-only host attachment and the same stable ordinary-telemetry attachment
  baseline rule proven for G2 v7;
- one exact `DAC SET 0xA848` setup transaction;
- negative automatic corrections only, with at most four corrections, 21
  codes each and 84 codes cumulative;
- the existing 1,800-second cadence, 900-second settling exclusion, 600-second
  fresh-support, range, deadline, finite-duration, no-retry, no-restore and
  phase/hybrid-zero-authority limits; and
- the exact G3 analyzer, seal and evidence-registration path.

No manual reset is expected if the exact upload resets and re-enumerates the
board normally. If upload, identity confirmation or re-enumeration fails, the
workflow must stop without improvising and request operator assistance.

If G2 does not pass, G3 and the flash remain forbidden. A failed or bounded
non-pass G3 does not authorize a retry. No G4 or phase/hybrid actuation is
authorized by this decision.
