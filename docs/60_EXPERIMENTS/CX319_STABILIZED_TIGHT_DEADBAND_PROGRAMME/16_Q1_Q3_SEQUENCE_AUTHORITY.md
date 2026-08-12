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

That exact-flash retry proved the firmware repair: all 59 receiver snapshots
observed before the stop retained fresh metadata and three-dimensional GSA
state, with no unsigned age wrap. It then exposed an independent host platform
escape. Active generation 118 completed and made the runtime contract ready;
generation 119 began 3.25 ms later and completed normally 128.85 ms after that.
The supervisor read the append-only health CSV between those two record
boundaries, correctly refused to reuse generation 118, but incorrectly treated
the normal in-progress generation as permanently missing and aborted. The
failed package with registered content identity
`919b1b31a07d1a25be6e3b799a79d0f032e9c3c31b93d0be651461fa8187fdb9`
is retained as a platform escape, not a firmware or GNSS rejection.

The operator directed that execution must not stop midway through this bounded
hardening response. A host-only recovery may therefore replace the CSV-prefix
control-plane read with an atomically published, generation/nonce/provenance-
bound live-health state, rehearse that exact path offline, and repeat Q1 using
the already proven installed UF2 identity
`5d206ba17d12d83b5429f687d40f6b52ce66024262fddde9bfc1d289082b252b`.
The recovery must obtain a fresh reset/identity transcript and must stop on any
identity mismatch. It permits no additional firmware flash and does not change
any actuation or later-gate boundary.

The first atomic-handoff entry retained package `f94446dee83c8d830df7c7f202fadc466868925e06ef47f3387fef402af09035`
after the new host code used a 1,000 ms active-snapshot completion deadline
while the exact Q1 bundle deliberately permits a 1,250 ms detach within the
documented 2,000 ms pending-frame transport horizon. Generation 8 completed
normally after the detach, with zero parser errors, but the inconsistent host
deadline had already caused a fail-static abort. This is a direct platform-
contract implementation error, not new scientific or firmware evidence. The
operator authorized the exact flash and complete Q1 outcome; the shortest
affected-gate recovery may bind that successful flash and byte-identical UF2,
use zero further uploads, align the live-snapshot deadline with the existing
2,000 ms horizon, and repeat Q1 in full after an ordinary reset and exact
identity transcript.

The next reset observer timed out without a physical reset and retained package
`08619c0106bec9dcb131ef8117728635b1a58f7c7aedcdb7c2177d2dd01d0fbf` as
failed-rehearsal evidence. The following observer obtained the
reset and exact pre/post board identity, but attached the carrier 2,389.319 ms
after USB reappearance. The runner had synchronously executed
`arduino-cli board list` after reappearance and before launching the drain
owner, so the failure is a deterministic host sequencing escape, not a device
race or firmware defect. Package
`55e6e92eafa2a607a19a0e3872baee84368eef0a521c16a97d6c365cc2d5fe4e`
is retained. The correction must pre-stage the run and carrier invocation,
validate the board and installed-UF2 binding before reset, perform the declared
host-absence stimulus with no intervening enumeration or preparation, attach
the exclusive carrier, and only then complete post-reset board enumeration
while the carrier drains continuously. The immutable entry record and analyzer
must prove the monotonic order `firmware entry ready < carrier ready <=
post-reset identity start`; the 2,000 ms horizon is unchanged.
The confirmed installed UF2 for this recovery is
`0717d51bff5f14d6935ad58b85a5dfa433d8eb575d909759be63b7f2c2852d66`.

A host-only defect after complete, immutable acquisition does not require a
new physical run when the correction cannot alter commands, capture
completeness, serial ownership, timing, segmentation, firmware behavior, or
the scientific result. Re-run the shortest affected host gate against the
retained raw evidence, recording old/new analyzer identities and explicit
supersession provenance. A physical repeat remains necessary only when the
required acquisition interval itself did not complete or one of those live
surfaces can have changed.

The first carrier-before-enumeration run passed exact board identity and
attached in 308.901 ms, then retained package
`6bd5f017a976039c19728dcf217966b43c9debfb8db1eae0a65bbfb37aea18d0`
because it did not observe the required 250 ms host-absent boot record. USB
node reappearance precedes the firmware's internal serial-wait clock, so an
uncontrolled immediate launch does not deterministically exercise Q1's
declared late-attach branch. The recovery must use one explicit 750 ms
post-reappearance host-absence hold after all preparation and before carrier
launch, require the `serial_absent` boot record, and retain the existing
strictly-less-than-2,000 ms entry-to-carrier limit. The retained run otherwise
had all three planned detach gaps below the horizon and zero parser errors.

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
