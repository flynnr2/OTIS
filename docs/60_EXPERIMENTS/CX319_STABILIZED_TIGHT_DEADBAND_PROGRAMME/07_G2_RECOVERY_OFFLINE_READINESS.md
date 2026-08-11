# CX319 G2 Recovery Offline Readiness

Date: 2026-08-11  
Gate: fresh G2 recovery package after the pre-write platform stop  
Result: passed offline; awaiting exact v6 authority and a fresh board restart

## Decision

The G2 recovery changes are ready for an operator decision. They do not grant
serial access, a board reset, a setup stimulus, a DAC write, a control arm or
automatic correction. The physical envelope is numerically unchanged from v5;
the operational host/runtime contract is materially different and therefore
uses a new proposal, preflight and rehearsal identity.

## Retained stopped attempt

The v5 entry stopped before actuation and is registered as
`interrupted_campaign` with content identity
`a22a32c7716db791ab7d348abeabe3445a4789667095d78aece2c653c6c6442d`.
It had zero setup stimuli, DAC writes, control arms and automatic corrections.
The v5 activation is retired.

## Exact v6 offline evidence

| Artifact | Identity |
|---|---|
| Source revision | `ec95f268fc756bf69efa20bc4211883f9bcdb09a` |
| Proposal bundle | `8726590f586a3c1ff97adbaa02aa3d216e89cad61d155489e1988d07860e7df5` |
| Proposal file | `0731671cabbc3ffc9ccc1800852ff8233caf242f53b171ac7b422b3c2f2d1c7a` |
| Structural preflight file | `38f8b3d125ae256d2df359b020318f224e4cd9172c755f672f48064699ef7f03` |
| Operational rehearsal result file | `12fc3178a4a743868524ed3a6caf30131faaba0b10b7063c34fb1436845c45bf` |
| Operational rehearsal content | `558314ac16ee9d12a97c7d557e71e5c4a8401cabafeb30206710f111adfa6c54` |
| Operational rehearsal seal | `e11e77d788407c873844ac236260921a335da11f4498839074f7f62b4efad25b` |
| Operational rehearsal seal file | `276a5a31c203561dcc29ac4bb8cc9487d4315ec63b6cd3428ba5bc9e8532a434` |
| Registration-path rehearsal file | `5e99db1ca7a7871d1af377c0da96df659be9b21c3ea1b104e6757395c53d94e0` |

The proposal is `proposed_not_authorized`. Preflight passed all eight checks
with zero hardware operations. The accelerated operational-path rehearsal
passed the actual supervisor, analyzer and seal path and performed real
registrations through a temporary external evidence index for both
`completed_campaign` and `interrupted_campaign`; both registered package
identities revalidated before the temporary index was discarded.

The repository suite passed with 1058 tests.

## Changed operational contract

The recovery package:

- maps passed and bounded-nonpass finite runs to the existing
  `completed_campaign` evidence-index classification;
- maps platform, integrity and finalization failures to
  `interrupted_campaign`;
- preserves the primary orchestration or analyzer error even if external
  registration also fails;
- requires the first complete pre-write status snapshot to report firmware
  uptime no greater than 120 seconds; and
- retains all prior exact identity, queue, partition, zero-write, transaction,
  direction, range, cadence, budget, phase/hybrid-zero-authority and clean
  closure checks.

The firmware binary is unchanged from the G1-qualified artifact. No firmware
flash is permitted. The fresh-uptime predicate requires one ordinary board
restart immediately before runner entry, followed by continuous serial
drainage through physical closure. A stale but otherwise clean session is not
accepted.

## Physical envelope

If separately authorized, v6 permits the same one finite Leg A run:

- one exact `DAC SET 0xA808` setup transaction;
- positive automatic direction only;
- at most four automatic corrections, 21 codes each and 84 codes cumulative;
- 1800-second minimum applied cadence;
- 900-second settling exclusion and 600 seconds fresh support;
- 90-minute qualification deadline and four-hour maximum qualified duration;
- no retry, restore or firmware flash; and
- phase and hybrid preview continuously non-actionable.

## Operator boundary

The next step requires both:

1. explicit authorization of proposal v6 and this unchanged physical
   envelope; and
2. the operator being at the bench to restart the board once and confirm
   immediately, allowing the runner to establish capture and prove the
   `uptime <= 120 s` clean pre-write state.

If G2 passes, the prior conditional G3 decision remains subject to a fresh
upper-side bundle and rehearsal. The fresh-session and registration repairs
must be carried into that G3 path.
