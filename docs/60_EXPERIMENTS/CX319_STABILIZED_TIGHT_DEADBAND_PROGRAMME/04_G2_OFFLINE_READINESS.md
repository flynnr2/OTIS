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
| G2 proposal bundle | `30d083772c963139d4444c6614d48efcbcc7f178f11fa8cd222c298d4b789f25` |
| Source revision | `05dbfe125a19469a3397a3410da1ef92785abc6f` |
| G1 evidence content | `cd17f90587a321ed0ddd6c40db76c0beffc8981c68ef7afdd8e46bbc1549432d` |
| Reused UF2 | `e1b12c86476085e2e125ece141bddc66ba6891be98535d4e542ee228f03ff42e` |
| CX319 policy | `e278e5d324d9029574102c6fb3a263373888fbd701a6a44a7c913a7d1707de70` |
| Structural preflight file | `402b4499fdba34acc0b664678ee945a73fba9766855abb77ccb8b685973edd10` |
| Operational rehearsal result file | `d618ee69920fcb27eae24db35325874ef3222ab2258e24800477b2b03c0e6332` |
| Operational rehearsal content | `1079c61558981037ac470b6354c6bbd22440f3e3d7b463062f244f2527905ccf` |
| Operational rehearsal seal | `ec4bf002d18ef27b9e8b9fe9a50ae8453fba9e98160499cdcfb83d487224cb8a` |

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
readiness-state update completed with 1054 tests passing.

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
