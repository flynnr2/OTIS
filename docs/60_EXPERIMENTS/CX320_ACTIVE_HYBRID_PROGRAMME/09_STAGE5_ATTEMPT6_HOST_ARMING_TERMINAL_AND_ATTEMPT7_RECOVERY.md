# CX320 Stage 5 Attempt 6 Host-Arming Terminal and Attempt 7 Recovery

## Attempt 6 terminal

Attempt 6 (`stage5_live_attempt6_20260820T1347Z`) crossed every earlier failed
boundary. The exact image and identities passed, one setup application placed
`0xA83C` at DAC epoch 1 with `i2c_ok=true`, the 12-hour qualified clock began,
and five exact 56-field hybrid decisions traversed firmware, capture and the
live supervisor without parser, transport or integrity error.

The controller entered `PHASE_QUALIFY` after two fresh 600-second estimates
established `TIGHT_INSIDE`. After 1800 seconds of continuous qualified phase
residence, firmware decision 5 calculated the first phase-material request:
frequency term `-0.001666666940 Hz`, phase term `-0.000277777778 Hz`, combined
demand `-0.001944444718 Hz`, raw demand `-5.608756175380` codes, and a rounded
request of `-6` codes from 43068 to 43062. The phase term was material because
the frequency-only counterfactual was `-5` codes.

The host had not armed that decision, so firmware correctly retained it as
non-actionable and made no DAC write. The applied code and epoch remained
43068/1. Continuing could never exercise phase actuation, so the independent
bounded abort was submitted. Firmware accepted one priority abort, published
the complete fail-static snapshot, and capture closed cleanly with one serial
owner and zero parser errors. The physical seal is a bounded nonpass with
semantic SHA-256
`d414035380ccbb6684717705823fe2048a6443118dbbb07b492fe95270ad9259`
and file SHA-256
`358e3828cbe0533a92862cf79523ef48334ea83e40ca4af0e4b005fcef69a97d`.
No automatic application occurred and no scientific controller verdict is
claimed.

## Cause and bounded correction

The live supervisor reused the CX319 helper that predicts whether the next
selected interval satisfies an 1800-second decision cadence. In CX320, the
frequency-only predecessor preview remains available at each 600-second
selected estimate. The helper consequently redefined every latest preview as
the cadence origin, always projected only 600 seconds forward, and returned
false forever after the initial one-shot arm. The firmware policy, by
contrast, correctly treats 1800 seconds as the minimum cadence between actual
applications and safely consumes early or zero-delta arms without writing.

The CX320 supervisor now arms one fresh selected-estimate epoch when the exact
firmware arm/evidence/progress gates permit it. It no longer uses the CX319
preview-cadence predictor. Firmware remains the owner of applied-action
cadence, range, step, count, cumulative movement and one-outstanding-request
limits. A deterministic regression reproduces the attempt-6 condition—three
continuously available 600-second predecessor previews for which the old
predictor is false—and proves that `PHASE_QUALIFY` nevertheless submits the
one-shot arm after a fresh progress reset. The focused host, runner, topology,
activation, contract, firmware-parity and formatter checks pass.

No firmware controller mathematics, scientific threshold, acceptance
criterion, duration, topology, setup code, actuator limit or progressive
authority rule changed. Attempt 7 requires a fresh exact build and identity
binding, structural preflight, complete operational-path rehearsal and a
separate immutable activation before physical re-entry.

## Attempt 7 entry gates

The bounded correction is frozen in source revision
`78c7899cba3b7e12716aef7c1e3be0731f3fba01`. The clean exact build retained
the unchanged firmware source semantic SHA-256
`5a97de4d0fd9681a7af5cd31ffd38c2cfcfc2fda45894640a5982df4c2072d7b`
and configuration SHA-256
`f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
its exact UF2 SHA-256 is
`c625fa9b08bece7b0b0bbec14490e09bbe020a1be3d5e53c1fc628f9a5d555a0`.

Successor bundle v14 has semantic SHA-256
`df7e9efd0c1609bfd4a8cc2ef5d3854727b09cb74547fb04fa8ddc527bdbcf71`.
Proposal v14 has semantic SHA-256
`1b69c33aa9e04fe5f3148c2e7ed466c2b98b5e4ab2a2732c6c557af8c8a33334`
and retains the original operator-authority lineage. Structural preflight v14
passed with semantic SHA-256
`88203a30605a17db0e2fffcef4b423e83bf08d9b2c50765c55088602d62751ce`.

The complete PTY operational-path rehearsal passed with semantic SHA-256
`6d2201f5d47542e7f7266344ef26d056a38dc26fae7961a8c182437eef8b9ed8`.
It exercised the real capture and live-supervisor processes, sole serial
ownership, the exact 56-field hybrid record, normal-FIFO saturation after an
acknowledged command, independent priority-abort delivery, complete post-abort
snapshot, logical rotation, accelerated controller boundaries, analysis,
sealing and registration. It made no physical-action or qualification claim.
Attempt 7 remains offline-only until its separate exact activation is issued.

The first activation attempt correctly remained no-I/O but rejected the
attempt-6 seal because its validator treated a passed acquisition gate and
replayable offline finalization as proof that no new physical interval was
needed. Those fields mean only that the retained acquisition is valid and its
offline consumers can be replayed; they cannot supply the missing automatic
application or 12-hour physical qualification. The validator now accepts an
exactly delivered bounded operator abort only when the terminal also declares
the endpoint incomplete and the frozen 12-hour acceptance check false. The
existing failed-acquisition path retains its stricter non-replayable gate.
Because activation validation is part of the frozen host bundle, this narrow
correction supersedes the v14 entry artifacts and requires one exact refreeze,
preflight and operational-path rehearsal before activation. No physical action
was attempted.

The final refreeze binds source revision
`dcb67906ec974856dd7bafd3c94851bd7372e590` and exact UF2 SHA-256
`86bbd57c5a14c153c62ece7badd66e42df18e45b40a58235434037d7759c5df1`.
Successor bundle v15 has semantic SHA-256
`f3f3c87dd23e792061da22e49dd3400ac05fb12463e8156da7b55b3a8bdc8fb8`;
proposal v15 has semantic SHA-256
`7959b6b21102d3b39da0b37e17fb66a0b78b805a6d0620cd045a88e144168fc5`;
preflight v15 passed with semantic SHA-256
`e6dcbb3f1b3aca1f54f4d656043f297f58a677b01c7c55c8499ed8f273c2323f`;
and the repeated complete operational-path rehearsal passed with semantic
SHA-256
`5110659ab8c7e4c53ab70d415f1da4c7c566982bb9267407406bae2fc98fe8ea`.
These are the attempt-7 entry artifacts eligible for separate activation.

Attempt-7 activation v7 is effective with semantic SHA-256
`1ad46ad921cb6e017711e4782c8954e550de658f99150b6a78e4a73483656738`.
It binds predecessor attempt-6 seal
`d414035380ccbb6684717705823fe2048a6443118dbbb07b492fe95270ad9259`,
the exact v15 bundle and rehearsal, board serial `503533748A919118`, serial
device `/dev/cu.usbmodem14601`, one flash, one setup application, one live
acquisition and the unchanged progressive authority envelope. It is not an
automatic retry and is consumed by the first physical terminal.
