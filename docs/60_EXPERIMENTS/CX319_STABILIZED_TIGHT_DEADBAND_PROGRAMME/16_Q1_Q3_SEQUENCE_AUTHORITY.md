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
launch and retain the existing strictly-less-than-2,000 ms entry-to-carrier
limit. The retained run otherwise had all three planned detach gaps below the
horizon and zero parser errors.

The controlled retry retained package
`329c152452cd0da58cc1d9ae42bbee2bcba435744edd0e1f1f251e08c7e08daa`.
It proved a 754.269 ms interval with zero user-space serial owners, attached
the exclusive carrier at 965.993 ms, retained the complete boot banner and
build provenance, passed all three detach gaps, and had zero parser errors.
The firmware did not emit `serial_absent` because its readiness predicate is
TinyUSB `tud_cdc_connected()`: on macOS the OS CDC driver may satisfy that
predicate during enumeration without a user-space serial owner. The warning
is therefore retained as optional firmware telemetry, not used as proof of
host-owner absence. Q1 instead requires the direct monotonic hold transcript,
zero owners at both boundaries, a classifiable and quantified boot backlog,
exclusive carrier, and the unchanged 2,000 ms limit.

The next controlled run retained package
`875f4bb68d0dda35cd5a96079504e3848d2834fe79eab80b4a4438592cfc51bd`.
It held zero owners for 753.998 ms and attached at 1,302.812 ms, but the USB
backlog began with the tail of the first `BOOT` record followed by complete
`BOOT_WARN`, `BOOTDIAG`, headers, build-provenance status, and 727 parsed
records. All three detach gaps remained below the horizon with zero parser
errors. This is one observed and bounded initial-record prefix loss, which the
Q1 exit criterion already permits when explicitly declared and quantified.
The recovery must record zero or one initial BOOT-record loss from the exact
`BOOT`/`BOOT_WARN`/`BOOTDIAG` sequence and independently require the complete
post-attach firmware source/configuration hashes. Any other missing or partial
boot sequence remains a failure.

## Q1 result

Q1 passed on 2026-08-12 using run
`q1_running_attach_final_20260812T121948Z`. The 2,768-second retained capture
completed with zero DAC or active-transaction rows, one selected 600-second
estimate, zero parser errors, zero rejected commands, three declared detach
gaps below 2,000 ms, one independently delivered priority abort, and a
same-PID logical rotation with no serial reopen. The passing seal is
`0d8c4863a48930f40057b6bc665f8fa880a83548a4ff7a4b30525c3bff7639df`;
the registered package identity is
`9e3506c855ea949cc65d2a2c090334386a94e732e6d7c5a0dfdb0c6df8ba1e67`.

The physical acquisition first encountered three host-only verdict errors.
The rotation check incorrectly required the carrier's cumulative reconnect
counter to be zero after Q1 had deliberately exercised three reconnects. The
abort check required a later periodic status snapshot even though the retained
consecutive critical records `abort=queued_to_core1` and
`critical_record=abort_accepted_on_core1` bind the exact firmware state change.
Finally, generic PPS cadence validation interpreted the two non-adjacent REF
sequence pairs produced at declared detach boundaries as physical two-second
PPS intervals. The corrected checks require an unchanged reconnect counter,
accept the exact Core 1 abort acknowledgement, and exclude only sequence gaps
whose missing count and elapsed ticks agree within the manifest's declared
detach-gap budget. The original failed analyzer result is retained with an
explicit supersession record; raw serial evidence was not changed and no
physical rerun was performed.

## Q2 physical prerequisite

The Q2 transaction authority is not executable until the retained bundle names
the stub or inhibited topology and records the operator's confirmation that the
physical oscillator control input cannot move. This is a physical
configuration prerequisite, not permission to broaden the experiment.

The prepared Q2 implementation uses the existing
`cx317_dual_core_active_rehearsal` diagnostic profile and a closed
`Q2 CASE <nonce> <case-id>` vocabulary. Its 38 finite cases exercise every
initial setup predicate, every mutable current-to-stale release predicate,
every Core 0 execution recheck, six setup interruption boundaries, one
injected terminal setup-I2C failure, and one injected ambiguous automatic
outcome with explicit no-retry and fresh-transaction recovery. The diagnostic
case engine cannot call the DAC driver. After all 38 cases pass, exactly one
ordinary `ACTIVE SETUP` command must traverse the production Core 0/Core 1
authorization, acceptance, release, physical application, and acknowledgement
path. That sole physical DAC write is permitted only while the DAC analogue
output is disconnected from the oscillator EFC/Vctrl input, the oscillator
remains powered, and the DAC remains reachable over I2C.

The exact host path must continuously own and drain serial, retain every
nonce-bound case result and the complete setup authority snapshot, require one
and only one `manual_apply` DAC row, require zero automatic physical writes,
then run the independent analyzer, snapshot, seal, and temporary-index
registration path. The deterministic replay of that actual analyzer/seal/
registration path and the pinned-profile firmware compilation must pass before
the operator is asked to change the bench topology. The inhibited interval is
bounded to 30 minutes; the expected execution is 10–20 minutes. Q3 then
requires reconnection of the oscillator control input and an exact recorded
flash of the Q1 operational UF2 before its no-write qualification begins.

## Stop conditions

Stop and retain the shortest affected evidence package on any identity or
hash mismatch, unexpected serial owner, flash/re-enumeration failure, detach
gap at or beyond 2,000 ms, undeclared record loss, partition fault before the
planned obstruction, DAC/setup/arm/automatic activity during Q1 or Q3,
analyzer non-pass, seal/registration failure, or any uncertainty about the Q2
inhibition state.
