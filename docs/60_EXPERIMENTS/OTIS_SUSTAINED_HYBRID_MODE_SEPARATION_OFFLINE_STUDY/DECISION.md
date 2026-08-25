# Sustained-hybrid mode-separation offline decision

## Terminal

`no_mode_separated_architecture_selected`

Mode separation fixes the phase-preservation failure that rejected the first
successor study, but none of the three prospectively frozen architectures
preserves the full frequency and path-efficiency behavior. No successor
policy, firmware profile, exact bundle, authority proposal, rehearsal, or
physical run is created.

The immutable machine-readable result is
[`comparison_report_v1.json`](comparison_report_v1.json), with semantic report
SHA-256
`6b971643c106fabe0cec2c267f733ded330469ad7596125fb2dd33e57a6b9aef`
and file SHA-256
`27bcdf5b3cc4ec1db23c835a3a0df11e832ed27682863bcea7a1fa5d4d2c7b07`.
The prospectively frozen contract has semantic SHA-256
`c02ce352d5224b5ed395d48d62a2ddc8a99654d08b95ad23a182186a716a37eb`
and file SHA-256
`f0af0cbcac15b9758e4ae4ba3e2246a4c9ec6dc51804f4b5df1540f503083165`.
The comparator SHA-256 is
`9fe68acc9efcd5fd60a1f1b4982a2a485e5cca1d21dbdce418189fc57d93b85a`.

## Exact retained facts

The comparator validates the unchanged Attempt 4 source package and the
predecessor contract, report, comparator, estimator, phase estimator, plant
model, and policy identities before comparison. Exact V1 replay again
reproduces 52 decisions and the eleven natural applications:

`-6,-1,-1,-6,-1,-1,-1,+5,+5,-5,+5`

The first seven applications are causally phase-material and consume 17 path
codes, ending at code 43051. The last four are frequency-only maintenance and
consume another 20 path codes. The causal classifier uses only the same fresh
decision frontier: a decision is phase-material exactly when its bounded
combined integer request differs from its bounded frequency-only integer
request.

Attempt 4's formal physical qualification remains failed because its eleven
contemporaneous pre-phase-4 response-replay attestations were not retained.
This study does not reinterpret that failure.

## Model correction

The predecessor comparator treated the complete observed hysteresis and
same-code repeatability spans as a fixed offset whenever candidate and V1
codes differed. The plant evidence does not identify that discontinuity as
the causal differential response of an arbitrary code change.

This study instead projects ordinary differential response with the retained
minimum, nominal, and maximum gain, exercises hysteresis as an outward
eight-code reversal dead-zone perturbation, and exercises same-code
repeatability as positive and negative one-count maintenance-observation
perturbations. Calibrated and combined uncertainty remain unavailable. This is
a narrower and more defensible counterfactual, not a physical calibration.

## Modeled candidate result

Every candidate preserves the exact first seven phase-material applications
under all three gain cases. Every candidate also clears the frozen phase gate:
the matched improvement is approximately 1.943 cycles, or 72.7%, under every
gain. Mode separation therefore resolves the specific early phase-response
failure from the predecessor study.

All three candidates nevertheless fail `frequency_behavior_preserved` first
in the minimum-gain scenario. Their frequency RMS degradation remains below
the frozen one-count limit, but tight-band occupancy degrades by 15.2% to
23.9%, above the permitted 10%. Their natural path is also 28 to 32 codes,
above the frozen 27-code limit.

| Candidate | Path codes, min/nom/max | Net codes, min/nom/max | Phase gate | First frozen failure | Additional perturbation failures |
| --- | --- | --- | --- | --- | --- |
| Phase-priority one-count hold | 29 / 28 / 29 | -5 / -6 / -5 | Pass | Minimum-gain frequency preservation | Gain scenarios only |
| Separated FLL/PLL maintenance | 29 / 28 / 29 | -5 / -6 / -5 | Pass | Minimum-gain frequency preservation | Both demand reversals and gain scenarios |
| Phase-priority 1200-second maintenance | 29 / 28 / 32 | -5 / -6 / -2 | Pass | Minimum-gain frequency preservation | Isolated and repeated one-count cases and gain scenarios |

At nominal gain the candidates reproduce the 17-code early phase path, then
apply `+3,+4,+2,+1,+1`. The modeled recovery is not the original late
`+5,+5,-5,+5` one-count chatter. It is the plant moving back from the early
phase-correction endpoint toward its durable frequency operating point. The
controller architecture still represents transient phase correction and
long-lived oscillator bias with one DAC state, so it must subsequently undo a
substantial part of the phase correction and requalify after each move.

The frozen evidence therefore supports a stronger diagnosis than "add a
deadband": command-mode separation is necessary but insufficient. A sensible
successor needs explicit estimator state for the durable DAC equilibrium and
for transient phase correction, plus uncertainty sufficient to decide when
each state is observable and actionable.

## Claim boundary and next gate

The exact claim ends at V1 chronology, integer decisions, and mode
classification. Candidate continuations are finite-run gain-envelope models;
they do not establish RP2040 cross-core propagation, USB transport, AD5693R,
D14, D8, or physical CX317 behavior. Raw phase epochs are never joined with a
guessed offset, and D10 remains an external event input only.

The next gate is a separately frozen
`estimator_state_and_uncertainty_architecture_revision`. It should test a
state-space or trajectory-planning architecture that separately estimates:

1. the long-lived DAC equilibrium associated with oscillator frequency bias;
2. the temporary DAC displacement used to reduce relative-phase error; and
3. the uncertainty and observability of both states from retained raw evidence.

That study must preserve causal identity, raw observations, phase epochs, and
all authority boundaries. It may compare bounded offline trajectories, but it
must not tune these rejected candidates, relax their gates, infer calibrated
uncertainty that does not exist, or inherit physical authority.
