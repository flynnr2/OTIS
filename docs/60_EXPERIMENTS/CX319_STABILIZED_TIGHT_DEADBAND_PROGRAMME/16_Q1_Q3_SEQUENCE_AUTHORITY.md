# CX319 Q1–Q3 Qualification Sequence Authority

## Operator decision

On 2026-08-12 the operator directed Codex to execute the Q1 through Q3
sequence recorded in the current adversarial architecture review and to stop
for any required input, decision, or physical action. The operator separately
directed that the installed firmware must not be assumed and that an exact
flash may be required to establish a known starting point.

This record is the current execution authority for Q1, Q2, and Q3 only. It
does not revive any retired G2/G3 activation and does not authorize Q4 or any
live oscillator-control campaign.

## Sequential gate

The gates execute strictly in order and a later gate cannot compensate for an
earlier failure:

1. Q1 is an exact-current-bundle real-I/O rehearsal using physical serial and
   zero DAC value writes. One exact lower-profile flash is permitted to
   establish the known starting image.
2. Q2 is permitted only with a bundle-bound stub actuator or after explicit
   confirmation that the physical oscillator control input is electrically
   inhibited. It may exercise only the finite transaction cases named in the
   review. It cannot move the physical oscillator or promote live authority.
3. Q3 is a fresh exact-bundle physical no-write qualification. If Q2 used a
   different diagnostic image, Q3 must restore the exact Q1 operational image
   with a recorded exact flash rather than infer what remains installed.

Q4 remains forbidden. Any Q1 or Q2 non-pass stops the sequence and is retained
as failed-gate evidence.

## Q1 exact scope

Q1 permits the following operations on `/dev/cu.usbmodem14601`, expected board
serial `503533748A919118`:

- one build-manifest-bound `cx319_tight_lower` upload and its automatic reset
  and USB re-enumeration;
- one exclusive sole-owner serial carrier;
- read-only configuration, DAC-status, timing-status, and nonce-bound active
  snapshot queries;
- non-zero capture leases and observation of one natural lease expiry;
- short deliberate detach/reattach intervals strictly below the declared
  2,000 ms pending-frame transport horizon;
- one competing-open rejection probe;
- bounded normal-ingress obstruction and the independent priority abort;
- same-owner logical evidence rotation; and
- actual close, analysis, snapshot, seal, and temporary-index registration.

Q1 permits zero DAC value writes, setup stimuli, control arms, automatic
corrections, pseudo-reference generation, sweep activity, or live promotion.

The first Q1 entry on 2026-08-12 established the exact image with its one
permitted upload, then stopped before the evidence-bearing interval when the
host's intentional detach cut a partial device record. Following the
operator's direction to continue, the shortest affected-gate recovery may use
one observed ordinary board restart and immediate carrier attachment. The
recovery bundle must bind the successful original flash record and
byte-identical UF2, permit zero further uploads, retain the failed package as
failed-rehearsal evidence, and repeat Q1 in full. This recovery authority does
not extend Q2, Q3, or live-control authority.

The full recovery attempt then reached the 660-second boundary with clean host
transport but correctly rejected the installed firmware. The receiver carried
a valid differential GGA fix and three-dimensional GSA state, while the status
burst reused an earlier millisecond sample after interleaved UART service. The
resulting small negative ages wrapped near `UINT32_MAX` and falsely inhibited
freshness. The failed package is retained and the sequence remains stopped.
On 2026-08-12 the operator explicitly authorized the narrow freshness-anchor
repair, one new build-manifest-bound exact lower-profile flash, and one complete
Q1 retry. Write, setup, arm, automatic-correction, Q2, Q3, and Q4 boundaries
remain unchanged.

## Q2 physical prerequisite

The Q2 transaction authority is not executable until the retained bundle names
the stub or inhibited topology and records the operator's confirmation that the
physical oscillator control input cannot move. This is a physical
configuration prerequisite, not permission to broaden the experiment.

## Stop conditions

Stop and retain the shortest affected evidence package on any identity or
hash mismatch, unexpected serial owner, flash/re-enumeration failure, detach
gap at or beyond 2,000 ms, undeclared record loss, partition fault before the
planned obstruction, DAC/setup/arm/automatic activity during Q1 or Q3,
analyzer non-pass, seal/registration failure, or any uncertainty about the Q2
inhibition state.
