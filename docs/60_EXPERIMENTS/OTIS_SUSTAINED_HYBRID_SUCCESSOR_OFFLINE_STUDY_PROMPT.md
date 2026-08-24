# Codex Prompt: Close Sustained Hybrid V1 and Select an Offline Successor

You are working in the OTIS repository on the computer attached to the bench
rig. Complete the smallest decision-bearing programme that closes the rejected
V1 controller safely, diagnoses its low-efficiency path from retained Attempt 4
evidence, compares a small prospectively frozen set of changed controllers, and
prepares a genuinely changed successor only if the evidence supports one.

Do not stop after writing a plan or design note. Carry the work through the
offline decision terminal, with implementation and exact non-physical
rehearsal when a candidate passes. Do not rescue a preferred controller when
the bounded comparison rejects it.

## Authority boundary

This prompt authorizes:

- read-only inspection and validation of retained evidence;
- correction of tracked programme status, authority guards, tests and current
  documentation so they agree with the Attempt 4 terminal;
- creation of a bounded offline successor-study contract;
- deterministic replay, counterfactual modeling and small committed fixtures;
- focused host and firmware implementation for a selected changed successor;
- exact-profile builds, structural preflight and complete PTY or fixture-based
  operational-path rehearsal that performs zero physical actions;
- analysis, reviewed reports and a non-effective exact-bundle proposal; and
- proportionate verification of the changed risk surface.

This prompt does **not** authorize:

- firmware flash or reset;
- serial-device access or ownership;
- GNSS transmission;
- DAC setup, challenge stimulus or any other DAC write;
- control arm or live command FIFO use;
- physical rehearsal or live acquisition;
- restoration, retry, Attempt 5, or a new 24-hour physical run; or
- treating stale tracked authority as permission for any physical operation.

The current machine-readable status incorrectly leaves V1 live execution
enabled. That status is a defect to repair, not authority to use. Do not open a
serial device or call a live runner even if an existing guard would permit it.
Stop after an offline decision and, when applicable, an exact non-effective
bundle and zero-I/O rehearsal. Any physical successor requires a later explicit
operator decision naming the exact bundle and finite envelope.

## Decision to deliver

Deliver one of two outcomes:

1. **Selected changed successor:** one bounded policy materially outperforms V1
   under the frozen Attempt 4 comparison and deterministic perturbation matrix,
   preserves the required phase and frequency behavior, has exact host/firmware
   parity, and passes the complete non-physical operational rehearsal; or
2. **No controller successor selected:** none of the bounded changes is robustly
   better, so record a controller-study rejection and move the next gate to an
   estimator or architecture revision without creating a live proposal.

The selected result, if any, is a new programme. It is not Attempt 5 and must
not reuse the V1 policy, programme, bundle, activation or run identity.

## Naming rule

Use descriptive OTIS identities. Do not create a new `CX###` campaign or
programme identifier.

Use `OTIS_SUSTAINED_HYBRID_SUCCESSOR_V1` as the provisional successor programme
identity only if a changed policy is selected. Use a descriptive offline-study
identity before selection. Preserve every historical V1 path and identity
unchanged.

## Read first

Read and apply at least:

- repository-root `AGENTS.md` and all applicable nested instructions;
- `docs/00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md`;
- `docs/00_FOUNDATIONS/OTIS_ARCHITECTURE_OVERVIEW.md`;
- `docs/00_FOUNDATIONS/OTIS_NON_GOALS.md`;
- `docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_REGULATION_V1/README.md`;
- the V1 `04_ATTEMPT4_PHASE4_ATTESTATION_AND_SCIENTIFIC_TERMINAL.md` report;
- Attempt 4's immutable run manifest, activation, exact bundle, physical seal,
  evidence manifest, AHY, ACT, selected-estimate, tight-band, phase and raw
  observation records under
  `runs/otis_sustained_hybrid_regulation_v1/live_attempt4_20260823T2148Z`;
- the final attestation-repair bundle and rehearsal retained under `runs/`;
- `profiles/programme_status_v2.json` and its execution-guard tests;
- `profiles/discipline/otis_sustained_hybrid_regulation_v1.json`;
- `profiles/estimators/cx317_pps_gated_selected_v1.json`;
- `profiles/estimators/cx318_relative_phase_selected_v1.json`;
- `profiles/plant_models/cx317_pps_gated_v2.json`;
- `profiles/discipline/cx317_response_classification_v2.json`;
- `host/otis_tools/active_hybrid_policy.py` and the matching firmware policy
  engine;
- `host/otis_tools/active_hybrid_replay.py`;
- `host/otis_tools/sustained_hybrid_synthesis.py`;
- `host/otis_tools/active_hybrid_evidence_guard.py`;
- `host/otis_tools/active_hybrid_live_analyze.py`;
- the active-hybrid programme, bundle, activation, preflight, rehearsal and run
  guards; and
- the focused sustained-hybrid, policy-parity and programme-status tests.

Validate cited identities before using the evidence. Preserve `runs/` as
ignored local scientific evidence. Never force-add an ignored artifact or
weaken `.gitignore`. Commit only reviewed summaries, contracts, policy files,
small purpose-built fixtures and deterministic tools.

## Frozen Attempt 4 facts that the baseline must reproduce

Treat the following as observed facts only after validating them against the
retained package:

- run `live_attempt4_20260823T2148Z` is complete and capture closed cleanly;
- the physical qualification is formally failed because all eleven required
  contemporaneous pre-phase-4 response-replay attestations are absent;
- the missing attestations cannot be reconstructed into a physical pass;
- the retained measurement, transaction, response, command, application,
  dependent-consumer, setup, budget and terminal-static evidence replays
  exactly;
- the unchanged controller reached the prospectively frozen
  `prospective_low_efficiency_path` terminal;
- V1 recorded 52 AHY decisions, eleven natural automatic applications, 37
  codes of cumulative natural movement and seven codes of net movement from
  setup, ending static at 43061 (`0xA835`);
- the first seven applications were phase-material, moved monotonically by 17
  codes from 43068 to 43051, and consumed 17 path codes;
- the last four applications were phase-nonmaterial/frequency-driven
  `+5, +5, -5, +5`, consumed another 20 path codes and moved net +10;
- the next frequency-driven `+5` request would have produced a 42-code path
  with only two codes net displacement from setup and therefore triggered the
  frozen low-efficiency rule;
- the authoritative estimator uses non-overlapping 600-second outputs with one
  count equal to `1/600 Hz`;
- the V1 gain `2884.5027706464516 codes/Hz/decision` maps one count to
  approximately 4.8075 codes, rounded half away from zero to five codes;
- the late `+/-5` requests arose from `+/-1` authoritative count estimates
  while the band state was `TIGHT_INSIDE`;
- the late requests were not held by the minimum applied cadence; and
- the V1 tight hysteresis qualifies control state and phase authority but does
  not suppress the frequency term inside the tight band.

The baseline replay must reproduce these identities, decisions, integer
requests, applications, path accounting and terminal before any successor
comparison is accepted. A mismatch is a tool or evidence-binding defect; stop
candidate selection until it is resolved.

## Current working hypothesis

Use this as a hypothesis to discriminate, not a conclusion to assume:

> The low-efficiency maintenance path was driven primarily by converting
> quantized `+/-1` count frequency observations into `+/-5` code applications
> while already `TIGHT_INSIDE`. Estimator resolution is the upstream condition,
> and the missing small-error actuator hold is the immediate control-law
> mechanism. The early phase-material path is not the same phenomenon.

The current evidence does not support blaming decision cadence alone: the
actual requests were not cadence-limited. A modest gain adjustment is also
unlikely to remove the observed mechanism. To round a one-count frequency term
to zero without another rule would require gain below about 300
codes/Hz/decision, roughly one tenth of V1, which could materially weaken
outside-band acquisition. Test these statements; do not merely repeat them.

## Stage 0: close V1 authority before controller work

Repair the operational contradiction first.

1. Update `profiles/programme_status_v2.json` so V1 records Attempt 4 and its
   two distinct outcomes:
   - formal physical qualification failure from missing contemporaneous
     attestation source evidence; and
   - causal scientific rejection of the unchanged controller at
     `prospective_low_efficiency_path`.
2. Set V1 physical authority false, remove its live operation, record Attempt 4
   authority as consumed, and replace the stale Attempt 4 pending gate.
3. Do not leave V1 as the active live programme. Either set no active programme
   until the offline study contract exists or add a separately named
   offline-only successor-study status entry. Follow the existing status schema
   and fail-closed conventions.
4. Make every live entry guard reject an unchanged V1 run, including the exact
   operation used by `run_active_hybrid_qualification`.
5. Update tests so they prove V1 live execution is blocked and the new study is
   offline-only. Delete or replace assertions that deliberately keep stale live
   authority enabled.
6. Update the repository README and V1 programme README so the current support
   boundary and next gate agree with the terminal report and programme status.
7. Preserve the Attempt 4 terminal report and physical seal unchanged except
   for a concise tracked next-gate reference if useful. Never rewrite the
   original physical failure into a pass.

Run the narrow status and authority regressions immediately. Do not proceed
while any tracked operational surface can still authorize V1 live execution.

## Stage 1: freeze the offline study contract

Before evaluating changed candidates, create a concise machine-readable study
contract and a reviewed design document under a descriptive successor-study
folder in `docs/60_EXPERIMENTS/`.

The contract must freeze:

- Attempt 4 run, seal, evidence-content and source-file identities;
- the exact V1 baseline policy and replay expectations;
- observed-versus-derived-versus-modeled field provenance;
- the candidate set and exact semantics of each changed state transition;
- diagnostic ablations that cannot be selected as policies;
- the plant-model envelope and every modeled uncertainty;
- the perturbation corpus;
- comparison metrics, selection thresholds and rejection rules;
- deterministic ordering and tie disposition;
- output schema, tool identity and canonical report hashing;
- the no-I/O authority boundary; and
- the terminal outcomes `selected_changed_successor`,
  `no_controller_successor_selected`, and `study_invalid_due_to_evidence_or_replay_mismatch`.

Freeze the contract before producing candidate result rows. Do not move a
threshold after seeing which candidate wins.

## Two analysis layers with different claims

Keep these layers explicit and separate.

### Layer A: exact evidence replay and causal ablation

Replay the unchanged V1 policy through the retained AHY and ACT histories and
reconstruct every integer request and transition exactly.

Then use the retained decision frontier for diagnostic ablations, including:

- phase term removed;
- frequency term removed while `TIGHT_INSIDE`;
- one-count frequency term held;
- V1 gain and rounding contribution;
- cadence changed without changing estimator observations; and
- estimator-count sequences grouped at longer support only as a derived
  diagnostic.

These ablations may identify which term generated an observed V1 request. They
do not establish what the plant would have observed after a different DAC
application. Do not call post-divergence ablation output an exact physical
replay.

### Layer B: closed-loop counterfactual continuation

Once a candidate requests a different code, its later frequency and phase
inputs are counterfactual. Reconstruct them using an explicit model that:

- preserves canonical raw Attempt 4 observations unchanged;
- subtracts or projects only the declared effect of the actual-versus-modeled
  code path;
- carries exact decision time, counter domain, DAC epoch and support-window
  semantics;
- evaluates the retained minimum, nominal and maximum plant gains;
- includes the retained hysteresis/repeatability uncertainty where applicable;
- never joins raw phase epochs with a guessed offset;
- identifies every modeled value and assumption; and
- refuses a physical or causal claim that the retained model cannot support.

The existing `active_hybrid_replay.py` and `sustained_hybrid_synthesis.py` may
provide reusable mechanics, but neither is the Attempt 4 successor comparator:
the former is bound to older sources and phase-pull-in candidates, while the
latter uses the CX322 predecessor and a static continuation model. Reuse shared
semantics without relabeling their old evidence as this study.

## Bounded candidate set

Compare V1 plus no more than three changed controller candidates. Use these
default candidates unless the frozen contract identifies a concrete semantic
or replay impossibility before results are generated:

1. **V1 baseline** — unchanged, retained only as the exact comparator.
2. **One-count tight hold** — while `TIGHT_INSIDE` and the authoritative
   accumulated error is `-1`, `0` or `+1` count, set the frequency contribution
   to zero and retain the existing phase term, phase cap, direction coherence,
   rounding, range, cadence, transaction and budget semantics.
3. **Tight phase-only mode** — while `TIGHT_INSIDE`, use only the phase term;
   retain frequency acquisition outside the tight band and preserve all
   current hysteretic entry/release semantics.
4. **Persistent one-count release** — hold an isolated `+/-1` count frequency
   term while tight and release it only after two consecutive fresh,
   non-overlapping, same-sign, same-session, same-DAC-epoch authoritative
   estimates. Reset persistence on zero, opposite sign, invalidity, session or
   DAC-epoch change, settling exclusion, reference loss, or authority loss.

Do not conduct a broad gain, deadband, cadence or estimator grid search. Gain
and cadence variations are diagnostic ablations unless the bounded candidates
all fail and the study terminal explicitly moves the next gate to a new
architecture decision. A longer authoritative estimator is a separately
identified estimator-policy change, not a quiet controller tuning parameter.

## Deterministic perturbation corpus

Exercise every candidate through the exact Attempt 4 source sequence and a
small frozen corpus that discriminates the mechanisms without overfitting:

- isolated count sequences `0,+1,0`, `0,-1,0`, and `+1,0,-1`;
- persistent `+1,+1` and `-1,-1` sequences;
- alternating `+1,-1,+1,-1` and the inverse;
- zero crossing with small nonzero phase terms on both sides;
- phase terms immediately below, at and above integer-rounding boundaries;
- legitimate slow frequency drift that requires eventual outside-band
  acquisition;
- natural negative-to-positive and positive-to-negative demand reversals;
- no natural reversal followed by the existing bounded challenge and recovery
  branch if the successor programme retains that requirement;
- minimum, nominal and maximum retained plant gain;
- retained hysteresis/repeatability extremes that can affect code-domain
  response;
- exact cadence boundaries and long zero-demand dwell;
- DAC-epoch, session, estimator-reset and settling-support transitions;
- stale-but-coherent versus contradictory observation identity; and
- cumulative-path, application-count, range, abort and fail-static boundaries.

Each case must preserve exact source and modeled identities. Do not infer that
different counters or classifications are mutually exclusive merely because
their names differ.

## Prospectively frozen selection gate

A candidate is selectable only when all of the following pass:

1. The V1 baseline first reproduces all frozen Attempt 4 identities and the
   same scientific terminal exactly.
2. The candidate never wins merely by applying no control. It still exercises
   at least two material phase applications where the scenario supplies the
   required phase evidence.
3. It preserves the V1 programme's raw-phase bounds and matched phase
   improvement criteria, including at least 10% and one cycle of matched
   improvement where those metrics are applicable.
4. It preserves authoritative frequency RMS, tail and tight-occupancy behavior
   within the original frozen no-material-degradation criteria and is not
   materially worse than V1 under the same modeled case.
5. At the Attempt 4 terminal horizon it uses at most 27 natural path codes, a
   reduction of at least 25% from V1's 37, while retaining meaningful net
   regulation and without triggering low-efficiency or alternation rules.
6. It does not produce three reversals in four natural applications, exhaust
   count or path authority, clamp unexpectedly, overlap transactions, reuse
   stale evidence or hide latent demand.
7. It tolerates a legitimate demand reversal without treating bidirectionality
   itself as chatter. It must not manufacture oscillation merely to satisfy a
   reversal requirement.
8. It passes every frozen zero-crossing, persistent-sign, alternation, plant
   gain, hysteresis and identity case. A nominal-only win is insufficient.
9. Its behavior is deterministic, replayable, expressible with explicit state,
   and implementable identically in firmware and host reference code.
10. All selection claims remain within the modeled counterfactual boundary; no
    offline result is described as physical qualification.

If more than one candidate passes, select the smallest semantic change only
when the frozen ranking rule resolves the result. Otherwise retain an
undecided or no-selection terminal rather than tuning after inspection.

## Stage 2: publish the offline decision

Produce one immutable comparison report containing:

- all frozen source identities;
- exact V1 baseline results;
- causal-ablation results and their limited claims;
- every candidate/case metric and terminal;
- raw, derived and modeled provenance labels;
- selection checks with explicit pass/fail reasons;
- rejected candidates and the first discriminating failure;
- sensitivity to plant gain and retained hysteresis;
- limitations and unexercised physical boundaries;
- the selected candidate or no-selection decision; and
- a canonical semantic digest and tool identity.

Promote a concise reviewed decision report under `docs/60_EXPERIMENTS/`. Do not
commit the Attempt 4 raw package or a large generated matrix when a compact
reviewed summary and a small deterministic fixture are sufficient.

If no candidate passes, update programme status to the offline estimator or
architecture revision gate and stop. Do not implement a controller, create a
bundle or propose a physical run merely to continue momentum.

## Stage 3: implement only a selected changed successor

If and only if one candidate passes:

1. Freeze a new descriptive policy and programme identity. Do not mutate the
   V1 policy or reinterpret its evidence.
2. Implement the changed semantics in the host reference and firmware policy
   engine with exact state, reset, rounding, cadence, counter-domain and failure
   reasons.
3. Preserve D14 as sole reference authority, D8 as oscillator/count input, and
   D10 as external event input only.
4. Preserve one combined output, one outstanding transaction, exact applied
   code and DAC epoch propagation, response capture, pre-acknowledgement replay
   attestation, first dependent consumer, fail-static behavior and independent
   abort.
5. Add host/firmware parity fixtures covering every new branch and reset
   boundary, the exact Attempt 4 baseline, and all selected perturbations.
6. Give the successor a new firmware profile and source guard. Prove the exact
   profile compiles and emits every required status and decision field.
7. Update contracts, schemas, terminology, architecture, methodology and known
   limitations only where behavior or meaning materially changes.

Avoid a generalized controller framework. Extract shared semantics only when
the existing V1 and new concrete successor demonstrate a genuine repeated
need.

## Stage 4: exact non-physical readiness gate

For a selected and implemented successor, freeze one exact bundle containing:

- clean source revision and source state;
- firmware profile, compile-time configuration, build identity and UF2 hash;
- policy, estimator, plant model and response-policy identities;
- capture, supervisor, replay, analyzer, finalizer, sealer and registration
  tools;
- exact command envelope, deadlines, acknowledgement phases and stop rules;
- status and query transcript;
- serial ownership, obstruction and independent abort behavior;
- evidence paths and manifest rules; and
- the prospective finite physical envelope, marked non-effective.

Run structural preflight and the complete actual host topology through a PTY or
equivalent zero-I/O path. The rehearsal must include:

1. capture and exact identity establishment;
2. setup and DAC-epoch propagation to every consumer;
3. first and repeated changed-controller transactions;
4. an isolated one-count hold and a release condition appropriate to the
   selected policy;
5. response retention and durable replay attestation before every phase-4
   acknowledgement;
6. first dependent decisions after acknowledgements;
7. natural reversal plus no-natural-reversal challenge/recovery branches where
   required;
8. transport obstruction and independent priority abort delivery;
9. sole serial ownership through logical rotation and clean close; and
10. the real analyzer, seal and registration path.

State which real boundaries the rehearsal exercises. A PTY fixture does not
establish RP2040 cross-core, USB driver, AD5693R, D14, D8 or plant behavior.

Create a non-effective authority proposal and stop. It must explicitly require
a later operator decision and a fresh setup acknowledgement before any
physical action. Do not create an activation or run a physical rehearsal.

## Verification discipline

Use proportionate verification:

- run focused status/authority tests immediately after Stage 0;
- run exact replay and comparator tests while developing the study;
- run host/firmware parity and the affected exact profile when a candidate is
  selected;
- run Campaign checks for changed active-control, transaction, replay,
  analyzer, bundle or rehearsal surfaces; and
- run materially affected Release checks only when shared protocol, transport,
  build, verifier or safety boundaries change.

Do not run historical compatibility programmes as current validation. Do not
expand a narrow defect into unrelated repository cleanup. After a direct
regression, affected build and required rehearsal pass, return to the
decision-bearing path.

## Stop conditions

Stop and publish the corresponding bounded terminal when:

- Attempt 4 identities or V1 replay cannot be reproduced exactly;
- canonical evidence is missing, changed or contradictory;
- the comparison would require an unsupported physical-response claim;
- no changed controller passes the frozen selection gate;
- candidates remain tied under the frozen ranking rule;
- host and firmware parity cannot be established;
- the exact successor profile does not compile or emit required evidence;
- complete zero-I/O rehearsal does not pass; or
- any next step would require flash, reset, serial access, DAC activity or
  another physical authority expansion.

Do not weaken a criterion, add a candidate, expand a sweep, or move a threshold
after seeing a failure without recording a new separately authorized study.

## Completion deliverables

Finish with:

1. V1 programme status and live guards closed consistently;
2. updated current-support documentation;
3. an immutable offline-study contract;
4. an Attempt 4-bound replay/comparison tool and focused deterministic tests;
5. an immutable comparison report and concise scientific decision;
6. if selected, a separately identified successor policy with exact
   host/firmware parity and exact-profile build evidence;
7. if selected, a complete zero-I/O operational rehearsal receipt and
   non-effective exact-bundle proposal; and
8. one explicit next gate: estimator/architecture revision, operator review of
   a named non-effective successor bundle, or invalid-study repair.

Report observed facts, derived results, modeled counterfactuals, assumptions
and remaining physical gaps separately. The result is an offline controller
decision and possibly readiness for later authorization; it is never a
physical qualification.
