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
