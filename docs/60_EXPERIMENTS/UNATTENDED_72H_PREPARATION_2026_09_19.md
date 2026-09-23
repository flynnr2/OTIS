# Unattended 72-hour preparation — 19 September 2026

This is development-Mac preparation, not physical qualification. Physical launch
remains conditional on satisfactory review of the latest bench result. No device
was opened, reset, flashed or actuated here. Preparation starts from merged
service/capture repairs through `4f9a1ca`; the original dirty development checkout
was preserved. PR work uses an isolated checkout.

## Resulting behavior

The host operates without an available Codex reviewer and owns a fixed 72-hour
monotonic window after capture readiness. It closes new ARM admission 2,111
seconds before the deadline. Exact pending transactions may complete; an exact
static/disarmed endpoint closes capture and packages evidence automatically.
A retained diagnostic does not prevent this scheduled closure when endpoint
state is independently proven; it remains review-required and is not converted
to a scientific success or failure. Unknown final actuator/transaction state
retains the protective hold and capture. No timeout grants approval.

The final change leaves the current firmware/controller profile and limits
unchanged: 144 applications, 3,024 cumulative codes, 21-code steps, 1,800-second
applied cadence and DAC `0xA800..0xAB00`. The earlier seven-day proposal is not the
delivered operating requirement. Accepted-aperture coverage remains distinct
from host elapsed duration; `endurance_complete` does not claim 72 accepted hours.

A detached local wrapper retains the production command owner and capture
worker. A read-only observer records transitions, stale raw/capture evidence,
stalled ownership service, holds, milestones, storage pressure and process exit.
No API/model budget, notification response or network service is required.
Observer failure cannot kill/restart the owner. Restart is rejected against
retained state so it cannot silently reopen a clock or create another owner.

## Verification

- Full release suite: **753 passed**, including repeated-transaction graceful
  shutdown with and without pending review, zero-write closure, current native
  firmware regressions and existing evidence/transport checks.
- After final monitor freshness and clock-domain naming refinements: **100
  focused tests passed**. The separate final monitor run passed all four cases.
- Fixed approved Intel build and resource audit passed: **230,672 program bytes,
  156,816 static RAM bytes and 105,328 runtime RAM bytes**, retaining **470 bytes**
  above the fixed minimum reserve. The resource limit was not relaxed.
- Public compile/reproduction path reproduced the frozen provenance and UF2
  byte-for-byte. Build session `6100190920260072`; UF2 SHA-256
  `d7e35695eeafdf32fe34ff196b1bfcc8cf98dc7e0b6c4184cde5c91fdf19127e`.
- Unchanged assembled PIO proof retained both historical and current-envelope
  sweeps, each 7,936 cases and 55,552 adjacent intervals, within one count.
- Exact final operational rehearsal is retained with its receipt/package in
  the delivery archive. It runs production capture and supervision over a PTY
  through the detached launcher after the invoking process exits: startup,
  two progressive transactions and dependent consumers, metadata hold/recovery,
  unanswered review beyond a real lease cycle with continuing capture/service
  and no new SETUP/ARM, normal FIFO obstruction, independent priority abort,
  ordered closure, analysis, sealing and registration.
- Accelerated endpoint integration tests preserve the original recorded deadline;
  replay correctly refuses to label their short execution as completed endurance.
  Their real host process closure requires no abort, including when review is
  pending. These tests do not establish physical elapsed duration.

The artifact identities, final rehearsal verdict, relocation preflight and
payload inventory are in the archive. A PTY cannot establish real board USB,
cross-core service timing, receiver state or plant response; existing live
pre-actuation gates remain mandatory. Loss of power, logout, USB, the capture
owner or storage is not claimed to recover automatically.

## Delivery

One file is prepared for the shared exchange:
`~/Documents/OTIS_DATA/otis-unattended-72h-20260919.tar.gz`.
The archive README and HANDOFF.json give the exact checkout, frozen inputs,
compile/entry command, local monitoring and abort procedure, and return path.
Tracked source travels through the PR. Raw rehearsals and binary artifacts stay
outside Git. The handoff must distinguish verified local placement from actual
arrival on the bench Mac; a blocked copy is reported rather than assumed.
