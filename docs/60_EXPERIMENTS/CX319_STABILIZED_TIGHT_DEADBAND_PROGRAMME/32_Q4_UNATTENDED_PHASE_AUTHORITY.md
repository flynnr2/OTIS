# CX319 Q4 Unattended Phase Authority

## Authority disposition

This unattended authority has completed with the matched Q4/G2 and Q4/G3
physical sequence. It remains the provenance for actions taken during that
sequence, but is no longer effective and does not carry into the new
range-spanning bidirectional or hybrid-preview programme. The G2 pass and G3
bounded non-pass are recorded in
`35_Q4_LOWER_SIDE_PHYSICAL_QUALIFICATION_PASS.md` and
`37_Q4_UPPER_SIDE_NONACTIONABLE_PHYSICAL_RESULT.md` respectively.

## Operator instruction

On 2026-08-13 the operator instructed:

> consider it authorized ... I can not wait on your messages, so I can not
> always act - you should consider that you are runing this unattended, I can
> check in from time to time, but you can't rely on me for timely
> authorizations (so consider this pahse fully authorizzed), reset (for
> timeouts), etc.

This was effective authority to complete the CX319 Q4 phase unattended. It
superseded reliance on timely operator replies or physical button presses
during that phase.

## Effective operational scope

Within Q4, Codex may proceed without another per-action authorization through:

- exact firmware flashing and board reset needed for deterministic entry;
- finite reset or exact-reflash recovery from entry and timeout failures;
- no-write physical qualification and candidate preparation;
- the bounded lower-side finite live run after its candidate satisfies the
  frozen qualification gate; and
- offline analysis, sealing, registration, documentation, commit, push and PR
  maintenance.

Successful unchanged Q2/Q3 results remain reusable and must not be repeated.
Platform failures must be preserved rather than hidden by retry. Recovery must
use the shortest affected gate and remain finite.

## Boundaries that remain in force

Full phase authority does not relax the characterized DAC envelope
`0xA800..0xAB00`, candidate-specific step/cumulative limits, exact
acknowledgements, single serial ownership, bounded drainage, fail-static
behavior, independent abort, frozen scientific criteria, or provenance and
evidence requirements. Phase/hybrid actuation and G4 progression remain out of
scope. A scientific rejection is a result, not permission to move the gate.

This authority allows the host to replace a manual-reset wait with an exact
same-image flash when that is the deterministic unattended entry path. Such a
flash must be recorded and must not silently alter the firmware candidate.
