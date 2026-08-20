# CX320 Stage 5 Attempt 9 Response-Observability Terminal

## Decision

CX320 reached a decision-bearing physical terminal in attempt 9
(`stage5_live_attempt9_20260820T1854Z`). The firmware applied one genuine
phase-material combined correction, and the complete 1,500-second response
evidence replayed exactly. The response was healthy but below the empirical
detection floor, so it did not establish the frozen positive plant-response
sign. The programme result is the bounded non-pass
`hybrid_response_wrong_or_frequency_not_reacquired`.

This is not a capture failure, firmware/replay mismatch or permission to weaken
the criterion after observing it. Later progressive authority remained blocked,
activation v9 is consumed, the instrument is `FAIL_STATIC` at `0xA836`, and no
attempt 10 is authorized.

## Physical timeline and controller action

Attempt 9 reused the exact frozen UF2 with SHA-256
`cdb6c4f413dddf768b444126ea44646ff5d88f7b3073b0ac646ef4c8c7a095ac`.
Setup applied 43068 (`0xA83C`) at DAC epoch 1. The qualified origin was selected
estimate `est:cx317:selected600:000541` at 38,421,851,680
`rp2040_timer0` ticks, or 2401.36573 seconds. Firmware entered
`PHASE_QUALIFY`, completed the frozen residence, and made its first material
phase decision at device uptime 4801 seconds:

```text
frequency term                   -0.001666666940 Hz
phase term                       -0.000370370370 Hz
combined demand                  -0.002037037310 Hz
raw controller movement          -5.875839765254 codes
rounded requested movement       -6 codes
frequency-only counterfactual    -5 codes
applied transition               43068 -> 43062 (0xA83C -> 0xA836)
applied DAC epoch                2
```

The phase term therefore materially changed the integer firmware request. The
application was acknowledged by the actuator path with no clamp or I2C fault.
The response boundary occurred exactly 1,500 device seconds after application,
at uptime 6311 seconds.

## Response evidence and frozen checkpoint

The pre- and post-application authoritative estimates both serialized a
frequency error of `0.001666667 Hz`, yielding an observed response of exactly
`0 Hz`. Firmware classified the response
`healthy_indeterminate_near_resolution` with reason
`healthy_evidence_below_empirical_detection_floor`. Independent host replay
reproduced that classification and all decision, identity, code, epoch and
transaction fields.

The separate frozen checkpoint required:

```text
delta_f_observed * delta_final > 0
```

Here `0 * -6` is not greater than zero. Response evidence was therefore exact
and healthy, while `predicted_sign_observed` and
`response_checkpoint_passed` were false. The supervisor correctly withheld the
response acknowledgement needed to release later hybrid authority, submitted
one priority abort, observed its delivery, and closed capture cleanly.

## Why this result was intrinsically difficult to observe

The frozen plant-gain envelope is
`0.00016357422282453626..0.00017334010044578463 Hz/code`. A six-code step is
therefore predicted to produce only:

```text
0.0009814453369472176 .. 0.0010400406026747078 Hz
```

The frozen empirical response-detection floor is
`0.0033333317438761396 Hz`, more than three times the nominal six-code response.
The selected 600-second estimator also moves in approximately
`1/600 = 0.0016666667 Hz` count increments. The exact attempt-9 observation of
zero is consequently plausible for the plant and estimator, but it cannot
satisfy a sign predicate.

At the lower plant-gain bound, a 20-code response is still below the floor;
21 codes are required for even the lower-bound model prediction to exceed it.
The controller's legitimate six-code action was thus too small for the frozen
one-window sign test. This is a prospective-design lesson, not a basis for
moving the attempt-9 acceptance boundary.

## Preserved evidence and corrected interpretation

Physical acquisition passed its independent gate: 211,137 records and
26,077,076 bytes were parsed with zero parser errors, reconnects or rejected
commands. Capture remained under one owner and closed after the priority abort
was recorded. The terminal evidence shows no outstanding authority and the
last confirmed code 43062 at DAC epoch 2.

The original supervisor used one generic replay-mismatch exception for both an
inexact replay and an exact replay whose frozen sign checkpoint rejected. It
therefore recorded the terminal as `measurement_authority_or_platform_fault`.
That original record and seal are preserved. A deterministic offline analyzer
correction over the unchanged acquisition now distinguishes the two cases and
produces the superseding result:

- original seal semantic SHA-256:
  `d2f197ca391dbd47006b5247a73f2562d8ae7a00b8add058243e97f7d0401e05`;
- superseding seal semantic SHA-256:
  `1ec4ebb79be358f6fd8c19aa602f81ba28cdcd45e808edefeb5bdd297f59ba22`;
- superseding seal file SHA-256:
  `cde924d0ef5f32f78123bf6eb3b4748c6c681902967a1760fe5d6feb77e0c551`;
- registered superseding package content SHA-256:
  `6cd4637660e29f40007ae2ccaa49a53017d9df84d362e24117fa973f71b51ff9`.

The corrected analyzer reports `bounded_nonpass`, exact transaction and
classifier replay, one healthy completed response classification, and a failed
response-sign checkpoint. It does not alter raw evidence or any frozen
scientific predicate.

## Next gate

Do not repeat attempt 9 under the same bundle. Its activation explicitly
forbids automatic retry and has been consumed, while another nominal six-code
step would remain below the same observability floor. The next useful work is
offline successor design: make a response-sign decision observable under the
measured plant and estimator resolution, freeze the resulting policy and
checkpoint prospectively, rehearse the exact path, and request separate
operator authority for a new bundle. CX320 itself remains a bounded non-pass.
