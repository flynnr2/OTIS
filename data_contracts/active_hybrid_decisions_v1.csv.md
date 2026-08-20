# active_hybrid_decisions_v1.csv

## Status and scope

`AHY` schema version 1 is the canonical CX320 per-decision active-hybrid
evidence record. It describes the one combined frequency/phase controller
decision before any request is created. Serialized evidence is always
`actionable=false`; authority remains exclusively in the existing private
request, acceptance, application and response transaction.

The exact field order is `ACTIVE_HYBRID_DECISION_V1_FIELDS` in
`host/otis_tools/contracts.py`. The capture splitter writes record type `AHY`
to `csv/active_hybrid_decisions_v1.csv`.

## Identity and observations

`run_identity`, `build_identity`, `profile_identity`, both estimator SHA-256
identities, active-policy SHA-256 and response-policy SHA-256 bind the complete
decision context. `capture_session`, source sequences, `phase_epoch`, phase
observation sequence, current code and DAC epoch preserve the input identities.

Frequency is the authoritative fresh 600-second D8 count estimate relative to
D14. Phase is cumulative D8 oscillator-cycle movement relative to qualified
D14 PPS inside one continuous phase epoch. D10 is not a reference or authority
input. `phase_continuous`, `phase_current`, `phase_step_detected` and the exact
phase-side code/epoch state make invalidity explicit. `phase_recorder_published`
must be true: the source phase record must enter the non-droppable recorder
before the decision may be published.

## Controller reconstruction

Each row preserves:

- progressive state before and after, tight-band state and explicit reason;
- frequency term, capped phase term, combined demand and raw controller delta;
- final integer delta/code after step and range limiting;
- the integer frequency-only counterfactual under identical limits;
- materiality, defined exactly as a nonzero phase term whose removal changes
  the final rounded integer request;
- cadence, count and cumulative-budget holds plus the prior budget state; and
- current transaction identity/status and the actual downstream code/epoch.

`requested_code` must equal `current_applied_code + requested_delta_codes` and
remain inside `0xA800..0xAB00`. A held decision cannot retain a nonzero delta.
Every decision requires `downstream_epoch_exact=true`; missing or mismatched
code/epoch evidence is never interpreted as unchanged.

The request, acceptance, application and response identities are zero or
`unavailable` when they do not yet exist at decision time. The later `ACT`
records bind those transaction phases back to the same decision sequence. For
the first phase-material transaction, the host's phase-4 response
acknowledgement additionally requires the durable independent replay described
by `active_transactions_v1.csv.md`.

## Claims boundary

An `AHY` decision records implemented controller behavior, but only a matching
successful `ACT` application and fresh response can establish physical
actuation. Offline rehearsal `AHY` records are explicitly non-qualification
evidence and must not be called observed plant response. Raw phase, modeled
phase and counterfactual phase remain distinct, and phase epochs are never
joined using a guessed offset.
