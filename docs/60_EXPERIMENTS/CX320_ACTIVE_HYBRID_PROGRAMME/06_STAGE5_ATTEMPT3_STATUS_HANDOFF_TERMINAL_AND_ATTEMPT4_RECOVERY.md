# CX320 Stage 5 Attempt 3 Status-Handoff Terminal and Attempt 4 Recovery

## Attempt 3 terminal

Attempt 3 (`stage5_live_attempt3_20260820T1109Z`) flashed the unchanged exact
UF2 and correctly withheld setup through the firmware startup inhibit. Exact
setup authority became ready at approximately 612 seconds. The host issued one
setup request for `0xA83C`; Core 0 accepted it, Core 1 accepted the current
setup authority and released execution, and the firmware recorded one applied
setup transaction at DAC epoch 1. No automatic controller application
occurred.

The first post-setup supervisor health check then terminated with
`CX320 hybrid firmware state is absent`. One priority abort was submitted and
delivered before clean capture close. The physical seal has semantic SHA-256
`28ce71c95575d0dab63d6f73d4046326e45f643ca0c230e670f5dc65efa104d6`
and file SHA-256
`1c377f6a709e68d810f517b174cca59fe4d7b4dfad6d2e477a2ee17904355fa7`.
The registered package content SHA-256 is
`3b268d96072576191184fd23733f1bc64552e47955fd5c4fc58f9dcd8585abb9`.

This is a platform escape into the campaign, not a scientific controller
rejection. The setup application is physical evidence, but the terminal did
not retain a post-setup active snapshot sufficient to claim an exact terminal
static code. Attempt 4 therefore re-establishes the setup code through the
same exact acknowledged path; it does not infer restoration from attempt 3.

## Cause and correction

Firmware emitted all six frozen CX320 hybrid status fields. The shared
`active_status_contract` did not list those fields, so the real atomic live
reducer silently discarded them before publishing its snapshot. The first
decision-bearing CX320 supervisor consumer therefore saw an absent hybrid
state even though the producer record was complete.

The contract now retains `hybrid_state`, `hybrid_reason`,
`first_phase_checkpoint_passed`, `phase_nonzero_application_count`,
`phase_material_application_count` and `frequency_only_application_count`.
The exact bundle also binds the shared status-contract source. A deterministic
regression passes a complete producer fixture through the real atomic reducer
and then through the first post-setup fail-static supervisor check. Replay of
attempt 3's immutable health record now retains
`hybrid_state=SETUP_PENDING`.

The operational rehearsal covers that same producer-to-reducer-to-consumer
boundary as well as the real capture/supervisor/FIFO, setup propagation,
priority-abort, logical rotation, progressive-controller, analysis, sealing
and registration paths. It records
`atomic_handoff_hybrid_state=SETUP_PENDING` and
`first_post_setup_consumer_passed=true`. No firmware source, binary, scientific
threshold, acceptance criterion, experiment duration, command envelope or
progressive-authority boundary changed.

## Attempt 4 identity and gate

Attempt 4 is a separately identified successor under the operator's expanded
recovery authority. It is not an automatic retry or restoration.

- firmware source/configuration identity:
  `495601d286cbe6c53730407d09a6dcd7d8c685b8f336514105ae7b32b12eb57b:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256:
  `b10cc09df783ef9e9f39383cff18d4600d9c2021910457d856ae0d8e10ae69fd`;
- bundle semantic SHA-256:
  `4d83a7ec30284713d315b7e171c7ea6daac78389275ac2677e37c16eb23fe774`;
- successor proposal semantic SHA-256:
  `fc6b52c3b198f7e951e19b8d389e1a2d576fd535fc5bd7589c253d3e6194d389`;
- operational rehearsal semantic SHA-256:
  `df12f75f840d2a2bf5e52c51b7fde0e690a5fb6af4e0471808910797ab2084dd`.

One hundred ten focused active-hybrid and boundary checks pass. The broader
current suite, excluding the eight intentionally blocked retired CX319 bundle
builders, records 854 passes. The shortest remaining affected gate is exact
physical Stage 5 attempt 4.
