# CX320 Stage 5 Attempt 2 Prewrite Terminal and Attempt 3 Recovery

## Attempt 2 terminal

Attempt 2 (`stage5_live_attempt2_20260820T1054Z`) flashed the corrected exact
UF2 and passed the attempt-1 pre-setup firmware boundary. Capture remained the
sole serial owner and the generic host prewrite contract reported ready. The
host then submitted one exact setup request. Core 1 rejected it because the
firmware's contemporaneous setup snapshot still reported
`setup_reference_eligible=false`. The host delivered one priority abort before
capture close. No DAC application, arm, automatic application or scientific
control transaction occurred.

This is a platform escape into the campaign, not a scientific rejection. The
failed physical seal has semantic SHA-256
`97f95551d7d6dabff63d379643660e6f0b438eae0e537ce7e45f953dd37269b4`
and file SHA-256
`893d58c45781ca96f240ab41b0b7608aca16982411a8dbc7d60d252b015cfb98`.
The registered package content SHA-256 is
`f26df461d1748d7840cf36fdb40f67ffb439619bc76a3bec70a690048f8ede4e`.

## Cause and correction

The immutable setup-authority snapshot gives a direct discriminating replay.
The inherited CX318 host contract returns ready, but the established
setup-authority contract rejects the same snapshot because
`gnss_receiver.raw_pps_control_eligible`, combined GNSS `control_eligible`,
and `cx317_active.setup_reference_eligible` are all false. The firmware's
Core-1 rejection therefore behaved correctly. The CX320 supervisor had omitted
the exact firmware setup-authority predicate and used the older 30-second
snapshot-completion grace as its qualification deadline.

The corrected CX320 prewrite gate requires the detailed GNSS authority fields
and all three firmware setup fields—GNSS eligible, reference eligible and
partition healthy—before retaining or issuing setup. It uses the existing
660-second qualification deadline. That boundary is grounded in the compiled
600-second startup inhibit and prior physical CX319 evidence that first
observed combined eligibility at approximately 612 seconds. No controller
threshold, acceptance criterion, duration or authority limit changed.

The regression proves that the exact attempt-2 snapshot cannot issue setup.
The operational rehearsal now accelerates the same real supervisor boundary:
it waits without setup at 30 seconds, accepts a complete qualified snapshot at
the historically observed 612 seconds and terminates if authority remains
missing at 660 seconds. It also repeats the real capture/supervisor/FIFO,
priority-abort, logical rotation, progressive-controller, analysis, sealing
and registration paths with zero physical actions.

## Attempt 3 identity and gate

Attempt 3 is a separately identified successor under the operator's expanded
recovery authority, not an automatic retry or restoration. The firmware inputs
are unchanged from attempt 2; the same exact build and UF2 are rebound because
the repair is confined to the host setup-admission path.

- firmware source/configuration identity:
  `495601d286cbe6c53730407d09a6dcd7d8c685b8f336514105ae7b32b12eb57b:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256:
  `b10cc09df783ef9e9f39383cff18d4600d9c2021910457d856ae0d8e10ae69fd`;
- bundle semantic SHA-256:
  `419f8e5da0240d5b894199768fcfa62d88cd22343d02a5346b53a4c0fcf41103`;
- successor proposal semantic SHA-256:
  `d68c46852fccffdd0c30c417e833a122fc76a70ba77cbb55b2e591a860cdb815`;
- operational rehearsal semantic SHA-256:
  `948388650b65a311667904b04065f34272adfa2fc3fd34a1961020595ff730de`.

Ninety-nine focused active-hybrid, setup-authority, supervisor, activation and
programme-status checks pass. The broader current suite records 871 passes and
eight intentional operation blocks in retired CX319 bundle builders because
CX320 is now the active programme; those blocks do not intersect this repair.
The shortest remaining affected gate is exact physical Stage 5 attempt 3.
