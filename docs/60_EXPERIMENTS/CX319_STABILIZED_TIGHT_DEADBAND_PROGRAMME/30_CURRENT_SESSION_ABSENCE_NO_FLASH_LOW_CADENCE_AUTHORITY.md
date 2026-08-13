# CX319 Current Session-Absence No-Flash Low-Cadence Authority

## Effective operator authority

On 2026-08-13 the physically present operator gave the exact instruction:

> I authorize the no-flash low-cadence proposal and I am at the bench

This makes the proposal frozen in
[`29_CURRENT_SESSION_ABSENCE_NO_FLASH_LOW_CADENCE_PROPOSAL.md`](29_CURRENT_SESSION_ABSENCE_NO_FLASH_LOW_CADENCE_PROPOSAL.md)
effective for one finite physical no-write attempt on board
`503533748A919118`.

## Exact scope

The authority permits:

- zero firmware flashes;
- one press of the physical reset button;
- one physical no-write attempt using the already installed UF2 with SHA-256
  `e62cfb7c5df58a4471425a2045cc7d7fba03ed57d35eccb8cdd45ad34c7bf510`;
- `CONFIG?` once;
- exactly three nonce-bound `ACTIVE SNAPSHOT` queries, with at least five
  seconds between queries; and
- at most 30 seconds from post-reset capture attachment to completion or
  bounded stop.

The attempt is bound to canonical no-flash bundle
`bfc5c11d8fc75787c15d6a9acd8d2ade54ec7e970a37bbde222e26f8d44c464c`
and operational-rehearsal seal
`ddcb52e2e8ffba29c68966df22b391c663c3efd4fa97114eefa2d45f5cf01b47`.

Firmware flashing, setup, DAC writes, leases, control arming, automatic
correction, transport obstruction, owner rotation, Q2/Q3 repetition and Q4
live execution remain forbidden. The authority is consumed by the first
physical attempt, whether it passes, fails or stops before completion.

## Decision boundary

The pass criterion is exactly the criterion frozen in document 29. It will not
be changed after examining the new evidence. A pass authorizes only preparation
of a fresh Q4 candidate and a separate live-authority decision; it does not
itself authorize a Q4 live run.
