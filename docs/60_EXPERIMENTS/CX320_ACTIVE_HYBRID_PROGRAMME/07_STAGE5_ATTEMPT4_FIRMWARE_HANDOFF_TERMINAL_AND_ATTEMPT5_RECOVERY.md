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
The affected exact firmware profile compiles successfully, 34 focused firmware
and host parity checks pass, and the broader current non-retired suite records
854 passes. The complete host operational-path rehearsal also passes. It does
not claim the RP2040 cross-core boundary; attempt 5 is the shortest physical
gate for that corrected boundary.

No scientific policy, threshold, acceptance criterion, duration, command
envelope or progressive-authority limit changed.

## Attempt 5 identity and gate

Attempt 5 is a separately identified successor under the operator's expanded
recovery authority. It is not an automatic retry or restoration.

- firmware source/configuration identity:
  `ffdac3de0370a086cb04df19acca7254e1e098506b4c0c3771f032c483ba222c:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256:
  `f03418251c1002fd5ea2b2a236ea538a667ff949641a8f4ca732b9a61f3fcb1e`;
- bundle semantic SHA-256:
  `7ca36f272f8d3210822452b1b7bac83ef12ed8c5d544bccc87dfe9e894228559`;
- successor proposal semantic SHA-256:
  `cbfa8bf5a78973aefc0b48589c270e7be70a3d741af3230c0da5f34f300f894c`;
- operational rehearsal semantic SHA-256:
  `baa3a62b5f0fab34c7f765d6663cf07d447f28e58f589d45b18628238240691b`.

The shortest remaining affected gate is exact physical Stage 5 attempt 5.
