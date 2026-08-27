# Cross-campaign adaptive-steering offline programme completion report

## Outcome

**Terminal:** `provisional_cx322_unchanged_pending_d9_gate`

Provisionally retain the unchanged CX322 request calculation. Neither minimal
changed candidate is selectable from these packages. This is the frozen
fail-closed fallback, not a claim that unchanged CX322 outperformed them: the
prospectively frozen static post-divergence model failed three of four held-out
validity gates, so changed-candidate performance after first divergence is
unavailable and non-decision-bearing.

All own-law replays are exact. The operational containment requirements remain
independent of policy selection: GNSS metadata loss must become a
transaction-aware control hold rather than a D14/D8 measurement failure; phase
loss must fall back locally to FLL; low efficiency must be component-attributed
before automatic actuation is inhibited.

## V2 correction and authority

V1 is preserved unchanged and superseded. Independent pre-completion review
found incomplete raw-event joins, unsupported Boolean control eligibility,
unavailable metadata-hold chronology encoded as zero, phase-coupled frequency
selection, and incomplete per-row provenance. `SUPERSESSION.md` records the
defects and preservation rule.

V2 was refrozen before V2 candidate results. It retains the same sources,
candidates, thresholds, replay laws, model gates and terminals. Its contract
digest is
`b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f`.

This programme performed offline reads only. It did not access serial devices,
control a process, build or edit firmware, flash/reset hardware, write a DAC,
control the active GNSS soak, or modify any source package.

## Frozen evidence ledger

| Source | Retained role and terminal | Full-tree SHA-256 | Size |
|---|---|---|---:|
| CX317 Stage 7 Part B | Qualified FLL baseline; pass | `ff21bd5e21e9838f72f159f2af63c7393f2aa1b0cce6f9e3e136d8408c0e5b6b` | 489,226,798 B |
| CX322 attempt 7 | Positive coherent controller; passed / healthy stop | `f71ddb6479c0a140e8f8377998bc37d3556f1e554853ed6476c626fe1400fddf` | 429,428,776 B |
| Sustained Attempt 4 | Maintenance/reversal chronology; formal failed qualification, scientific terminal `prospective_low_efficiency_path` | `aa7ac41bb07192f4de5807547899d50b0e51b3c60bbcac4f8e9cadb6fc6a2a90` | 409,352,510 B |

Pre/post full-tree identities were exact for all three packages: zero files
added and zero bytes changed. Attempt 4's failed physical seal remains a fact;
its replayable scientific chronology is not relabeled as a passed campaign.

## Corrected derived view

Every one-second interval requires exact D14 raw-event endpoints, valid and
adjacent snapshots, exact CNT/D8 wire domains and gates, modulo counter parity,
and frozen file identities. Hybrid phase additionally binds the exact RPH and
PHE configuration/frontier. D10 is never joined. Selected-frequency rows are
the recorded selected-600 estimator products replayed against their exact 600
D14/D8 intervals, independently of phase availability.

| Source | Qualified 1 s intervals | Selected 600 s rows | Phase method | Applications |
|---|---:|---:|---|---:|
| CX317 | 93,828 / 93,828 | 151 | Reconstructed adjacent D14/D8 integer phase | 1 |
| CX322 | 45,604 / 45,604 | 66 | Native `CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1` with exact PHE join | 4 |
| Attempt 4 | 42,939 / 42,939 | 52 | Native `CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1` with exact PHE join | 11 |

The local derived package contains 182,371 normalized intervals, 269 selected
windows, 657 phase rows, 1,156 stability rows, 160 response rows, 67 retained
transaction rows, 124 controller/terminal episode rows and 807 environmental
associations. All analytical CSV rows carry a canonical mapping of every
material source-relative path to its frozen SHA-256. Normalized interval rows
also retain the exact opening/closing D14 event sequences and flags, count
flags and clock domains, snapshot status fields, and each available native
phase observation frontier rather than discarding those identities after
validation.

The derived manifest digest is
`705361d252782c911cea63bfca691691c6ab045956942f057f87db31827b4816`.
The tracked report digest is
`c411e44042162192228b04c4ebd567b90d73ddd77344f9d1d6f494ada863e9e5`.
The generator, exact-state primitive and contract-loader bundle is bound as
`fbbcb152880b0079e97eb9b9d216e292aa805ceb829e78996c4e06dee282b1ca`.

## Frequency, phase and stability

These are D8-relative-to-D14 results, not UTC traceability, calibrated
accuracy, delivered D9 behavior, or oscillator-only stability.

| Source | Selected-600 RMS | Absolute p95 | Occupancy within ±1 count/600 s | DAC path | Net/path efficiency |
|---|---:|---:|---:|---:|---:|
| CX317 FLL | 0.003204 Hz | 0.004167 Hz | 20.53% | 19 codes | 1.000 |
| CX322 | 0.001421 Hz | 0.001667 Hz | 96.97% | 14 codes | 1.000 |
| Attempt 4 | 0.001132 Hz | 0.001667 Hz | 98.08% | 37 codes | 0.189 |

CX322 tightened this retained frequency chronology relative to the older FLL
baseline inside its finite four-application envelope. Attempt 4 has lower RMS
but used eleven applications, 37 codes of path and three reversals, and ended
at the low-efficiency scientific terminal; frequency alone does not establish a
better controller.

At the 21,600-second segment-origin phase horizon, reconstructed CX317 had four
available windows (median absolute OLS slope 0.002918 cycles/D14-second; maximum
excursion 87 cycles). CX322 had one available window (0.000868; 19 cycles).
Attempt 4 had no complete unjoined 21,600-second segment and is explicitly
unavailable at that horizon. Across all horizons, 479 phase rows are available
and 178 carry exact insufficiency/censor reasons rather than favorable zeros.

Settled same-code overlapping Allan deviation at 600 seconds, expressed as a
10 MHz-equivalent frequency, is 0.000842 Hz for CX317, 0.000878 Hz for CX322
and 0.000711 Hz for Attempt 4. At 1,500 seconds it is 0.000382, 0.000366 and
0.000223 Hz respectively. Missing longer-tau support remains unavailable.

## Response, environment, actuator and hold evidence

Application-anchored response rows use exact complete trailing and settled
windows. They censor later applications/DAC epochs, incomplete settling,
phase/identity breaks and the terminal. Of 160 requested response estimands, 64
are available; the remainder retain their specific censor reason.

Environment association uses exact `sht4x/vcocxo_near` rows and keeps
`bmp280/pressure_reference` separate. RP2040 TIMER0 timestamps are reconstructed
through the declared 36-bit rollover before causal age/lag comparisons. All
three lag-0 fits pass the frozen 30-sample and 0.05 °C-range gates; their slopes
are positive (CX317 0.000349, CX322 0.002291 and Attempt 4 0.001209 Hz/°C), and
the leave-one-campaign-out sign diagnostic is consistent. These are nearby-air
associations only, with zero causal or control authority; temperature-rate
diagnostics are retained separately.

Actuator exposure is reported against named measurement-qualified,
control-input-eligible and settled-same-code durations. Historical
control-decision eligibility is **unavailable** because the retained GNSS
metadata cadence exceeds the frozen 3-second freshness bound. Transaction-aware
metadata-hold duration and lost opportunities are likewise unavailable, not
zero. The episode table retains one explicit unavailable hold-chronology row
per source plus each recorded hybrid decision and terminal.

## Replay and finite candidate adjudication

CX317, CX322 and Attempt 4 replay exactly under their own recorded laws and
finite authority. Unchanged CX322 also replays exactly on CX322. Applying its
four-application envelope to Attempt 4 first differs at decision 16.

| Changed candidate | CX322 first different application | Attempt 4 first different application | Result |
|---|---:|---:|---|
| Tagged debt + bounded back-calculation | 11 | 13 | Not selectable; model invalid |
| Tagged debt + back-calculation + two-window same-sign persistence | 11 | 9 | Not selectable; model invalid |

The persistence calculation uses exact count-quantization intervals; an
interval containing zero has no sign. Exact candidate traces stop inclusively
at the first different request and never rejoin a physical claim.

The frozen held-out model used twelve exact settled 1,500-second responses:

| Gate | V2 result |
|---|---|
| At least 6 exact settled responses | pass: 12 |
| Positive-direction fraction ≥ 0.8 | fail: 0.667 |
| Median gain error ≤ 0.0001667 Hz/code | fail: 0.0001701 Hz/code |
| Frozen gain-envelope coverage ≥ 0.6 | fail: 0.000 |

Because that prerequisite failed, the all-case continuation is explicitly
`not_executed` for each changed-candidate × source × three-gain ×
three-residual case (18 required entries per candidate, zero generated
continuation rows). Frequency/phase/actuator and material-improvement gates are
`not_evaluated`, not false or zero. First-divergence gain/residual algebra is
retained only as a nonphysical, non-selection sensitivity diagnostic.

## Operational semantics and implementation map

`OPERATIONAL_SEMANTICS.md` freezes the required state table, transaction
ownership ordering, telemetry additions, host/firmware change map and
fault-injection matrix. It does not authorize implementation during the active
soak and does not claim the historical packages measured metadata-hold duration.

The key required states are `ACTIVE`, `GNSS_METADATA_HOLD`,
`PHASE_DEGRADED_FLL`, `LOW_EFFICIENCY_INHIBIT`,
`ACTUATOR_PROVENANCE_FAIL_STATIC` and terminal/aborted. D14/D8 capture continues
during metadata hold; no new correction is issued; an outstanding transaction
has one exact owner and outcome; rearm requires fresh metadata followed by a
causally later complete D14/D8 observation.

## Verification

Completed verification includes:

- V1/V2 semantic contract digests and exact consumed-file/full-tree bindings;
- historical evidence snapshot and terminal-attestation validation;
- strict raw D14→snapshot→CNT interval parity and exact hybrid EST/RPH/PHE joins;
- exact own-law and unchanged-CX322 replay;
- analytic OADEV/OHDEV, rational rounding, demand interval, tagged-debt,
  transaction, hold/fallback and persistence fixtures;
- private-versus-released request ownership through metadata loss, accepted
  completion and response-pending hold ordering;
- phase-material low-efficiency fallback followed by repeated FLL-local static
  inhibit, with D14/D8 measurement continuation;
- shadow kill/stall/corruption/rejection invariance and D10-local
  absence/noise/invalidity/overflow/queue-failure isolation;
- rollover-aware environment role/freshness checks, frozen fit gates, explicit
  insufficient phase support and complete source-provenance tests;
- model-invalid short-circuit coverage proving all required continuation cases
  are unavailable and dependent gates remain `not_evaluated`;
- source full-tree identities before and after generation; and
- derived artifact hashes plus manifest/report semantic digests.

The focused V2 contract, generator and state-primitive selection passes 67/67.
No firmware build is part of this offline programme.

## Stop boundary and next gate

The offline programme stops here: source ledger, frozen V2 contract, normalized
evidence, cross-campaign analysis, exact replay, finite adjudication,
deterministic host tests, operational state table and implementation map are
complete. Post-divergence changed-candidate comparative performance remains
unavailable; it is not hidden work.

Only after the unrelated GNSS baud soak has been stopped, finalized and sealed
under its own programme: integrate the already-finalized UART work, qualify
D9/GPOUT0 and D6 under unchanged FLL, run the D9 waveform/frequency-only output
soak, and use that gate only to confirm or block integration. It must not
silently retune or rescue either changed candidate.

The executable successor sequence is frozen in
`docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/`.
It separates non-effective preparation, separately authorized D9 physical
qualification/soak, confirmed coherent FLL/PLL operational-semantics
implementation, and exact-build/complete-rehearsal handoff. It stops before
the separately authorized 72-hour integrated trial.
