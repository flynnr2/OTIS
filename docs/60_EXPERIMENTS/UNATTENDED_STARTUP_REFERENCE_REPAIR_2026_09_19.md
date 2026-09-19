# Startup D14 reference wait repair — 19 September 2026

The pre-write repair succeeded, but the subsequent bench attempt retained a
review hold at 17:18:39Z when reference qualification briefly returned to acquiring.
SETUP at 0xA84D was exact; no ARM or correction had occurred and there was no
qualified origin. Capture remained clean. The four reported mismatches were
acquiring/tracking and accepted-anchor qualification on PPS and ACTIVE snapshots.
A fresh estimate later established acceptance epoch 2, but the general verifier
hold could not clear. This was a host startup-policy defect, not scientific
rejection or evidence that physical capture failed.

The closed bench archive arrived and its portable sealed package verified with
complete capture. Its archive SHA-256 is
`e2848f543688c3e167417ef10de383449d8d8426d85c1adbcf0f015f41143d79`;
package identity is
`02b9084a055358f1a5baba77cd286a51181027f3fcf85df1e38f9a64184ee0ef`.
The small retained fixture contains unchanged observed fields and the actual
recovered estimate, with explicit provenance for the consumer frontier. Original
evidence and verdicts are unchanged.

## Finite correction

Before any qualified origin or ARM, after exact SETUP, reference acquisition can
wait with no new actuation while the same session, setup code, DAC epoch 1, zero
movement and clear transaction state are exact. Only known reference/anchor
qualification differences are tolerated. Capture loss, missing/contradictory or
stale cohorts, queue faults, identity changes, existing review holds and pending
transactions are excluded. The existing platform/firmware checks remain active.

ARM remains inhibited until a full fresh 600-accepted-sample estimate is coherent
with current PPS and ACTIVE acceptance epochs, session, DAC epoch and frontier.
The closing estimate must follow the loss frontier by at least a full estimator
interval in the declared exact counter domain. The first qualified origin is
then recorded with its actual counter baseline. Earlier loss evidence is neither
reset nor hidden. No epochs are summed, and no wall or admission deadline moves.

This intentionally repairs the observed startup case. After-origin loss and
pending-transaction recovery remain review-required and are not claimed to work
automatically. No existing verifier hold is cleared, no firmware changed, and no
new physical attempt was launched or authorized here.

## Verification

The retained-event regression covers the actual loss, acceptance-epoch change,
short-span rejection, ARM inhibition, and qualification as the first dependent
consumer. Negative cases include prior origin/ARM/review, different session/code,
pending evidence, capture loss and malformed qualification. The operational PTY
rehearsal injects reference acquiring after SETUP, then supplies a fresh span;
retained event ordering proves recovery before the first ARM, followed by two
completed transactions. All ten required boundaries passed, including existing
metadata recovery, unanswered review, obstruction, independent simulated abort,
ordered closure, analysis, sealing and registration. PTY status injection does
not claim physical reference-loss or firmware recovery coverage; the actual
bench fixture supplies the observed epoch-change evidence.

All 168 frozen firmware inputs remain byte-identical. The approved image/build is
reused: `d7e35695eeafdf32fe34ff196b1bfcc8cf98dc7e0b6c4184cde5c91fdf19127e`.
Frozen spec: `f7b7ae61bd50c21b253e0ff61dfafc3cb4a629bbdc3ff320b7afd95b76bd6e7c`.
Rehearsal package: `e573120144182f5cc37a0812ff6f7acc042976650821b01cf146e1dcda5cf795`.

The full current release suite passed: **785 tests in 266.95 seconds**. The final
retained-event regression, including the explicit 599-second insufficient-span
case, passed all **17 tests**. No physical I/O occurred on the development Mac.
