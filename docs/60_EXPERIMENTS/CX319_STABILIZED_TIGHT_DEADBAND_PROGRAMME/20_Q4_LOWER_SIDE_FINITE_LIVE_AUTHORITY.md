# CX319 Q4 Lower-Side Finite Live Authority

## Operator decision

On 2026-08-13, after the completed offline-readiness review and publication of
draft pull request 132, the operator instructed Codex to "move on to the
physical Q4 live run".

This record makes that instruction effective for exactly one adversarial-
review Q4 experiment, mapped to CX319 G2 lower-side frequency-only live
qualification. It does not authorize CX319 G3/G4, a second lower-side attempt,
phase or hybrid actuation, a firmware change, or an extension or retry.

## Exact authority bindings

- Candidate source revision:
  `2f46e1f01da75a17c69b259626d282df4ca1bcdc`.
- Candidate bundle:
  `f08c9a581ec92271828f9c7c0ff87b5e0d1ce04e6015c92d4100c75f7882bbfe`.
- Candidate file SHA-256:
  `4c83e4736af8ab1a5ef07840c28a6b98841932fcbf3402a0ae329c554cbf9a40`.
- Accelerated-rehearsal content identity:
  `2d45d94cdfd4477ca5f028e1007843ae385539c91add7d05abec593f43a0d7c7`.
- Accelerated-rehearsal seal:
  `4e6d20094a80e9a3ffcabc6db93302b49acfbf5d48a2da6faeaa70ebe1f65084`.
- Expected board serial: `503533748A919118`.
- Exact Q3-qualified UF2:
  `50f863a2150d1b1391504553a1d20e1cb951daae5b450a83c90628265a522083`.
- Firmware profile: `cx319_tight_lower`.
- Frequency policy SHA-256:
  `936d92a1421b7a8f3db620cd0add2c1ecd1a73dbd9aad4581beb8d8c0b8e1698`.

The candidate and passing rehearsal remain local immutable evidence under
`runs/cx319_stabilized_tight_deadband/q4/q4_offline_preparation_20260813T072443Z`.

## Authorized entry and finite envelope

This authority permits one activation and one finite `g2_live_leg` run with:

- zero firmware flashes and zero board resets;
- verify-only entry for the installed Q3 image; stop without flashing if the
  board or image identity differs;
- confirmation that the DAC analogue output remains connected to oscillator
  EFC/Vctrl, as last established for Q3;
- one exact setup write at `0xA808`, opening a new DAC epoch;
- one control arm only after the complete setup chain passes;
- at most four healthy positive automatic corrections;
- at most 21 codes per automatic correction and 84 cumulative absolute
  automatic codes;
- hard range `0xA800..0xAB00`;
- at least 1,800 seconds between applied automatic corrections;
- 900 seconds settling exclusion plus 600 seconds fresh support after every
  write;
- two consecutive fresh 600-second estimates at absolute accumulated edge
  error no greater than two counts for tight entry;
- a 90-minute qualification deadline and four-hour maximum qualified
  duration; and
- continuously zero phase-derived and hybrid-derived actuator authority.

There is no retry, restoration, threshold change, duration extension,
automatic reboot recovery, substitute firmware, or second run authority.

## Entry requirements and independent abort

Before setup, the exact activation must verify the proposal and rehearsal,
clean source state, sole serial ownership, board serial, build and
configuration identity, complete nonce-bound active snapshot, stable
attachment telemetry baseline, GNSS identity epoch 1, and metadata/raw-PPS
control eligibility. The initial applied code remains unknown until the query
and setup transaction establish a new current DAC epoch.

`ACTIVE ABORT` must remain independently writable when the normal path is
obstructed. Missing, partial, duplicated, reordered, stale, wrong-session,
wrong-generation, wrong-nonce, failed, or ambiguous setup evidence is a stop,
not a retry condition.

## Stop and terminal obligations

Stop on any identity, authority, ownership, transport, queue, partition,
GNSS/PPS, acknowledgement, application, range, cadence, budget, replay,
abort, analyzer, seal, or registration mismatch. A finite scientific non-pass
is useful evidence and consumes this authority.

At every terminal path, disarm control, confirm the independent abort, retain
the last confirmed applied code and DAC epoch, perform no automatic restore,
preserve continuous serial ownership through capture close, and run the exact
analyzer, seal and registration path. Retire this authority after the first
activation reaches any terminal result, including a pre-write stop.

## Effective status

This authority is effective now and unconsumed. Its executable operation is
the exact `g2_live_leg` entry in `profiles/programme_status_v2.json`. The host
tools must fail closed if that status or any bound identity differs.

