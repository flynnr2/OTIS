# Current End-to-End Validation Plan

## Scope

This plan covers only `CX319_EVIDENCE_EPOCH_1`. It is an offline verification
plan and grants no hardware authority.

## Fast

Run current contract, authority, source-guard, replay-policy tests and one lower
profile firmware smoke build.

## Campaign

Run the current capture and serial-owner topology, bounded command and timeout
behavior, independent abort under obstruction, owner-preserving rotation,
transaction acknowledgement, deterministic replay/native parity, CX319
analyzers, evidence snapshot, crash-recoverable finalization, sealing, and
registration simulations. Build both supported profiles.

## Release

Run the complete current Python/native suite. Build both supported profiles and
all current expected-failure guards. Confirm the firmware resource budget,
deployed wire-row contracts, authority boundaries, current programme status,
and fail-static paths.

## Bench

A separate exact-bundle operational-path rehearsal and authorized finite
physical qualification are required before any live campaign. They must use the
same operationally significant bundle and preserve one serial owner, bounded
drainage, independent abort, exact acknowledgements, analyzer, seal, and
registration path.

## Historical

Current HEAD does not validate historical formats or profiles. Use the exact
recorded Git revision in a separate checkout. Historical results are not part
of a current release claim.
