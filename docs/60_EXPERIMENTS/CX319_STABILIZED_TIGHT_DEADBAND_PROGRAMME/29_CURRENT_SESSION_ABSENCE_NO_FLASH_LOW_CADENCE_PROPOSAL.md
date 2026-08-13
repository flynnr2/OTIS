# CX319 Current Session-Absence No-Flash Low-Cadence Proposal

## Result

Offline preparation is complete for one separate operator decision on a
no-flash, manual-reset, low-cadence check of the exact current firmware already
installed on board `503533748A919118`.

This document and its machine-readable proposal are non-effective. They grant
no reset, serial, physical or live authority.

## Frozen inputs

- Installed UF2 SHA-256:
  `e62cfb7c5df58a4471425a2045cc7d7fba03ed57d35eccb8cdd45ad34c7bf510`.
- Source flash-record SHA-256:
  `9c204517b022778c0473c2244f4a93b8ab84481a42e4cd75689dbe216791b0ea`.
- Canonical no-flash bundle identity:
  `bfc5c11d8fc75787c15d6a9acd8d2ade54ec7e970a37bbde222e26f8d44c464c`.
- Bundle file SHA-256:
  `5943b69ef7575062d8cbd52551db58f6b2e7237c41ae59af62cf974a7d9fb5ed`.
- Preflight file SHA-256:
  `d30d1179b372ddd1048e3528c27ff615b4146a428d409412eca10de268291a27`.
- Operational-rehearsal result file SHA-256:
  `a682d81d0d10b2d6b516c0b94a364d2f00cc3f260105942ac01d55f59dcacbf4`.
- Operational-rehearsal analysis identity:
  `0c432f181eb1207a27c7545615f0c04ed70bd96482d0fee6cc16355a31991ea1`.
- Operational-rehearsal seal:
  `ddcb52e2e8ffba29c68966df22b391c663c3efd4fa97114eefa2d45f5cf01b47`.

The exact bundle validates the installed board and prior flash without
granting another flash. Structural preflight and the actual analyzer, seal and
temporary registration replay pass with every hardware-operation counter zero.

## Proposed physical check

If separately authorized, the finite attempt would:

1. arm a restart observer and continuous capture path;
2. ask the physically present operator to press the board reset button once;
3. establish the sole continuously draining serial owner immediately after
   re-enumeration;
4. issue `CONFIG?` once;
5. issue exactly three nonce-bound `ACTIVE SNAPSHOT` queries, separated by at
   least five seconds; and
6. close capture after the third complete snapshot or a 30-second post-attach
   deadline, whichever occurs first.

Firmware flash, setup, DAC writes, leases, control arms, automatic correction,
transport obstruction, owner rotation and Q2/Q3 repetition remain forbidden.

## Frozen pass criterion

A pass requires all three requested generations to be complete and to retain
the exact build/profile/run identities. Every generation must record:

- `state=DISARMED`;
- `fail_static=false`;
- `manual_start_confirmed=false`;
- a nonzero session identity;
- correction count, cumulative movement and DAC epoch all zero.

The capture must record zero reconnects and parser errors. Ordinary telemetry
drops must have a stable post-attach baseline and no later increment. Active-
transaction and DAC-step row counts must remain zero. A fault, incomplete
requested generation, identity mismatch, telemetry-drop increment, forbidden
command or deadline is a non-pass.

This criterion targets the actual historical distinction: the old image
faulted after reset while its emitted session remained `1`, whereas the current
image must tolerate transient session absence without requiring an observable
different nonzero session or a `pre_setup_session_rebound` reason. The
criterion is frozen before any new physical evidence.

A passing result would authorize only preparation of a fresh Q4 candidate and
another separate live-authority decision.

