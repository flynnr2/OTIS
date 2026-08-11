# CX319 G2 Offline Readiness Report

Date: 2026-08-11  
Gate: G2 Leg A offline readiness  
Result: passed; awaiting explicit live authority

## Decision

The exact G2 lower-side frequency-only workflow is ready for an operator
authorization decision. This result does not grant physical execution, serial
access, a DAC write, a control arm, an automatic correction, G3 progression,
or phase/hybrid authority.

The candidate physical run will reuse the firmware already qualified by G1.
The G2 runner contains no firmware-upload operation. Before any write, the
connected board and the firmware-emitted build, profile, run, estimator, model,
policy, response-policy, numerical-policy, queue, memory and diagnostic
identities must satisfy the shared fail-closed pre-write predicate.

## Exact offline evidence

| Artifact | Identity |
|---|---|
| G2 proposal bundle | `29ee02a7d1a577668617ff0655f432bf3526f293839399526900067f91617328` |
| Source revision | `d42c5f67780c21f3e2496143852438c406c31f57` |
| G1 evidence content | `cd17f90587a321ed0ddd6c40db76c0beffc8981c68ef7afdd8e46bbc1549432d` |
| Reused UF2 | `e1b12c86476085e2e125ece141bddc66ba6891be98535d4e542ee228f03ff42e` |
| CX319 policy | `e278e5d324d9029574102c6fb3a263373888fbd701a6a44a7c913a7d1707de70` |
| Structural preflight file | `6f9cef83043c2308016bd44ebf2a24d67a621ba10a88c75314c4ab8e644e4be9` |
| Operational rehearsal result file | `52133d3a8536e6f0a3ebc74ab2145bb1ae2e3654e02eb87eb9c66949b1b84e11` |
| Operational rehearsal content | `4ac768fce52ce119441545c8b39109ce1072e7dd14e7dbcf3a994c8591f2706e` |
| Operational rehearsal seal | `6ad255a95a8916db6f4ba4290a2d7cdf8de014ba8d0ef9e8a71fbfddf3aeb01f` |

The proposal is explicitly `proposed_not_authorized`. Its physical execution,
firmware flash, serial open, setup stimulus, control arm, automatic correction,
DAC write and phase/hybrid authority fields are all false.

## Verification performed

Structural preflight passed eight checks with zero commands, serial opens,
firmware flashes, DAC writes and control arms. It bound the G1 pass, exact Leg A
identity, command grammar, runtime predicate, controller clocks and bounds, and
zero phase/hybrid authority.

The accelerated no-I/O operational-path rehearsal passed the actual G2
supervisor state transitions, representative command and acknowledgement path,
one exact setup transaction, arm and four durable evidence phases, a healthy
positive automatic transaction, two-estimate tight entry, transport
obstruction, independent priority abort, same-owner rotation, analyzer, seal
and dry registration. Its result is host operational-path evidence only; it is
not plant-response or physical-actuation evidence.

The physical package adds and binds:

- a narrow activation artifact which cannot be created unless programme status
  exposes exactly `g2_live_leg`;
- an exact live manifest retaining the proposal, activation, G1 result,
  firmware, policy, host tools and limits;
- a sole-owner capture and supervisor runner with independent abort and no
  firmware-flash path;
- clean finite closure, evidence snapshot, replay, immutable seal and external
  registration; and
- a physical live analyzer which replays raw measurement, estimator,
  controller, tight-deadband, transaction, response, command, DAC-epoch,
  phase/hybrid-zero-authority, health and closure evidence.

The shared physical-close implementation was given a direct regression test.
That test confirmed the existing implementation already accepts a clean
physical serial close; no closure-verifier repair was required. The substantive
G2 host defect caught during rehearsal was the inherited supervisor rejecting
normal `decision_cadence_hold` rows before it could arm the next eligible
boundary. That shared host path was repaired and its regression is included.

The repository verification after the physical-path implementation and
readiness-state update completed with 1053 tests passing.

## Exact proposed physical envelope

G2 is one finite Leg A run:

- one exact `DAC SET 0xA808` setup transaction, opening DAC epoch 1;
- positive automatic direction required;
- at most four automatic corrections;
- at most 21 codes per correction and 84 codes cumulative movement;
- hard range `0xA800..0xAB00`;
- at least 1800 seconds between applied automatic corrections;
- 900 seconds settling exclusion and 600 seconds fresh support after a write;
- one request outstanding, with no automatic retry or restore;
- 90-minute qualification deadline and four-hour maximum qualified duration;
- at least one complete healthy positive request/accept/application/response;
- two-estimate tight entry; and
- phase and hybrid preview continuously non-actionable and excluded from the
  frequency-controller input.

A canonical qualification-deadline or finite-endpoint non-pass is retained as
useful bounded evidence and does not permit extension, retry or threshold
change under the same run identity. An integrity, identity, ownership,
transport, transaction, range, cadence, authority or replay failure stops
fail-static and blocks progression.

## Operator boundary

No physical G2 action is presently allowed. The next action requiring operator
input is an explicit authorization of this exact G2 Leg A live envelope. If
authorized, the activation tool will bind the operator instruction, proposal,
passing operational rehearsal, exact device and no-flash physical authority
before the runner can open serial or request `0xA808`.
