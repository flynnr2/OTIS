# CX320 Stage 5 Attempt 4 Firmware-Handoff Terminal and Attempt 5 Recovery

## Attempt 4 terminal

Attempt 4 (`stage5_live_attempt4_20260820T1128Z`) flashed the exact attempt-4
UF2, retained the CX320 hybrid fields through the repaired host atomic status
handoff and correctly withheld setup through startup qualification. At firmware
uptime 611 seconds, the exact prewrite contract became ready. One setup request
for `0xA83C` was accepted and physically applied at DAC epoch 1 with
`i2c_ok=true`. The host confirmed setup, the applied code remained 43068 and no
automatic controller application occurred.

Repeated complete post-setup firmware snapshots nevertheless remained
`SETUP_PENDING/setup_consumers_pending`. The source path made the consequence
deterministic: the first completed 600-second estimate would fault because the
hybrid engine had never been initialized. Continuing could not yield a
scientific decision, so the operator-authorized independent host abort was
invoked. One priority abort was delivered before clean capture close.

The physical seal is a bounded nonpass with semantic SHA-256
`beee391ac711497be6b6c9662703115cd9243a19c6464b356aedb56f819250e4`
and file SHA-256
`d880659a30631562baeee405f4a9f719aebde417d6a3fc3a9c5edd9db8699cb9`.
The registered package content SHA-256 is
`2f9a0f888b9854a464bce9bef8dbeffdcf872c1d6dbde740435118242301f1f4`.
This is a firmware defect under intended setup stress, not a controller or
scientific rejection.

## Cause and correction

The dual-core `Applied` setup-acknowledgement path correctly recorded manual
start and propagated the new code/epoch to the frequency and phase preview
consumers. It did not then call
`otis_cx317_active_live_confirm_setup_consumers`. A later periodic fallback was
unreachable for this purpose because successful setup had already made
`manual_start_allowed` false. The hybrid engine therefore remained deliberately
uninitialized.

The applied-acknowledgement path now performs the missing confirmation
immediately after both preview consumers receive the exact epoch. Confirmation
checks frequency-preview identity and phase-preview code/epoch before
initializing the hybrid engine. Failure latches the existing actuator
acknowledgement mismatch fault. The first emitted hybrid state after this
handoff is consequently the engine's frozen `FREQUENCY_ACQUIRE` state, not a
host-inferred transition.

A deterministic firmware source guard traces the real acknowledgement branch
through both consumers, engine initialization and the first status consumer.
Before physical re-entry, a consolidated setup-to-analysis audit superseded the
initial attempt-5 candidates. It found and corrected six additional
pre-entry-detectable contract mismatches: setup-to-first-application cadence,
post-setup DAC-epoch qualification, response-horizon replay chronology,
same-phase-epoch analysis, firmware-consumed evidence acknowledgement, and the
live monitor schema. It also separated response classification from observed
commanded-sign evidence. These are implementation and observability corrections;
they do not change the scientific policy or acceptance boundary.

The final affected exact firmware profile compiles successfully. Seventy focused
firmware, policy, supervisor, replay, analyzer, transaction and monitor checks
pass. The current non-historical suite records 863 passes, with 27 historical
tests excluded by policy. The complete accelerated and real-process host
operational-path rehearsals pass, including setup propagation, first-decision
cadence, response replay, progressive release, transport obstruction, priority
abort, analysis, sealing and registration. They do not claim the RP2040
cross-core, physical DAC or D14/D8 boundaries; attempt 5 is the shortest
remaining physical gate.

No scientific policy, threshold, acceptance criterion, duration, command
envelope or progressive-authority limit changed.

## Attempt 5 identity and gate

Attempt 5 is a separately identified successor under the operator's expanded
recovery authority. It is not an automatic retry or restoration.

- firmware source/configuration identity:
  `38a03e6224bba6b92e3737b2c89ebdd208cee772b0ada1f4a5f80167e70e7a60:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256:
  `ebeb4fbe406daa37e66daf269cf201769cf1f9e3db9a4dbac341b3c5c5065d26`;
- bundle semantic SHA-256:
  `a0912f956bd066e9d648b0626b59efcf2cfa579ccc2b54564331459c3c1e532e`;
- successor proposal semantic SHA-256:
  `9fe4f80013d232872c631006da07da2853fbba0e66c69ca88a1d6290340671ec`;
- operational rehearsal semantic SHA-256:
  `1f0e23e8328e48e259e4a63c06b55db8f7546c867e2b5f4f48f2fcd067a53fb5`;
- effective activation semantic SHA-256:
  `9399945cdf6969129447abf5ed57ef9f2010d9d5c61bebe2542eadce34c0de40`.

The shortest remaining affected gate is exact physical Stage 5 attempt 5.
