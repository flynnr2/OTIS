# OTIS D9 Output and Adaptive-Steering Integration Programme

## Status

Prompt 02 has closed with the D9 waveform gate incomplete and the unchanged
CX322 integration blocked. See
[`PROMPT02_QUALIFICATION_AND_CONTROLLER_DECISION.md`](PROMPT02_QUALIFICATION_AND_CONTROLLER_DECISION.md)
and its machine-readable
[`prompt02_controller_decision_v1.json`](prompt02_controller_decision_v1.json).
This directory grants no further bench, serial, flash, receiver-command, DAC,
control-arm or live-run authority.

The bundle carries the completed cross-campaign offline decision into two
decision-bearing outcomes:

1. qualify or reject the direct D8/GPIN0 to D9/GPOUT0 forwarded 10 MHz output,
   with D6 as a diagnostic zero-authority monitor, then establish a sustained
   frequency-only output baseline; and
2. implement the confirmed coherent adaptive FLL/PLL operating semantics around
   the retained CX322 request law, followed by exact-build verification and the
   complete no-hardware operational-path rehearsal needed before a separately
   authorized integrated trial.

The physical output gate deliberately precedes controller promotion. The first
D9 soak uses only the already-qualified reactive FLL. This isolates output
forwarding, load and measurement non-interference from hybrid-policy behavior.
Only after that gate may the unchanged CX322 coherent FLL/PLL law become the
integrated candidate. Its FLL term minimizes qualified D8 frequency error
relative to D14; its slower PLL term requests a bounded temporary frequency
bias to reduce same-epoch D14-relative phase movement. It does not chase every
one-second count fluctuation or assume one permanent equilibrium DAC code.

## Decision-bearing handoff

The prompt bundle is bound to the decision-bearing V2 offline study:

- contract SHA-256:
  `b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f`;
- derived manifest SHA-256:
  `705361d252782c911cea63bfca691691c6ab045956942f057f87db31827b4816`;
- tracked report SHA-256:
  `c411e44042162192228b04c4ebd567b90d73ddd77344f9d1d6f494ada863e9e5`;
- analysis tool-bundle SHA-256:
  `fbbcb152880b0079e97eb9b9d216e292aa805ceb829e78996c4e06dee282b1ca`;
- terminal:
  `provisional_cx322_unchanged_pending_d9_gate`.

V1 is superseded and cannot be used for promotion. The two changed
correction-debt candidates are not selectable because their frozen
post-divergence model failed validation. D9 evidence may confirm or block the
unchanged CX322 integration; it may not retune, rescue or substitute either
changed candidate.

## Execution order

Execute these prompts in order:

1. `00_MASTER_SEQUENCED_PROMPT.md` — durable programme contract, authority and
   cross-stage gates.
2. `01_INTEGRATION_BASE_AND_D9_D6_READINESS_PROMPT.md` — establish the exact
   post-GNSS-soak integration base, implement D9/D6 and freeze a non-effective
   physical bundle. No bench access.
3. `02_D9_WAVEFORM_AND_FREQUENCY_ONLY_SOAK_PROMPT.md` — separately authorized
   D9/D6 waveform, load and non-interference qualification followed by the
   finite frequency-only output soak.
4. `03_CONFIRMED_HYBRID_STEERING_SEMANTICS_PROMPT.md` — close the provisional
   controller decision without retuning, then implement transaction-aware
   metadata hold, phase-to-FLL fallback, low-efficiency inhibit and isolated
   shadow semantics in the existing Python/C++ parity path.
5. `04_EXACT_BUILD_AND_OPERATIONAL_REHEARSAL_PROMPT.md` — run proportionate
   verification, build the exact profile, exercise the complete no-hardware
   operational path and freeze a non-effective integrated-trial proposal.

Prompt 03 may proceed only as non-effective safety architecture. The valid D9
gate result blocks creation of an actionable integrated profile or promotion
claim; it does not authorize a renewed D9/FLL soak.

Prompt 03 has now reached
`operational_semantics_implemented_promotion_blocked_by_d9_gate`. See
[`PROMPT03_NON_EFFECTIVE_OPERATIONAL_SEMANTICS.md`](PROMPT03_NON_EFFECTIVE_OPERATIONAL_SEMANTICS.md).

## Stop boundary

This bundle stops after the confirmed implementation, exact affected build and
complete operational-path rehearsal. It must not start the later 72-hour
integrated hybrid/output trial. That trial requires a new explicit authority
decision binding the exact firmware, controller, output contract, qualified
load, wiring, tools, stop conditions and evidence destinations produced here.
