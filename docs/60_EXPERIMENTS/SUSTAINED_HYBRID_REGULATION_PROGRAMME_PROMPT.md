# Codex Prompt: Sustained Hybrid Regulation and Reversal Challenge

You are operating in the OTIS repository on the same computer as the connected,
continuously powered bench rig. Execute this programme as one decision-bearing
successor to the completed bounded hybrid fact-gathering campaign. Move through
healthy offline gates without asking for routine confirmation, but stop for a
separate explicit operator decision before any physical action.

The programme is intentionally ambitious. It must use the already working
instrument to answer a material control question, not create preliminary
campaigns for temperature, PPS, oscillator or plant properties that the
datasheets and accumulated evidence already support.

## Decision to be delivered

Answer this question:

> Can the existing D14-referenced hybrid phase/frequency controller use finite
> bidirectional authority to reach and sustain bounded regulation over 24
> hours, including a verified direction reversal and post-reversal recovery,
> while preserving frequency performance and exact end-to-end provenance?

Attempt 7 already established that phase influence is useful, has credible
direction, materially changes DAC requests and approximately halves the
matched phase-slope magnitude. It stopped because the frozen four-application
budget was exhausted before the controller could apply the requested reverse
movement. Do not repeat that experiment merely to reconfirm its plant,
temperature or reference premises.

## Naming rule

Do not create any new campaign, programme, run, profile, seal, proposal,
terminal or report identifier of the form `CX###`. That historical convention
was derived from the CX317 component name and is confusing when used for whole
campaigns.

Use descriptive identities based on
`OTIS_SUSTAINED_HYBRID_REGULATION_V1` and descriptive/date-based run names.
Legacy paths and identifiers must remain unchanged when cited as historical
evidence. Component-specific names such as CX317 remain correct when they
actually identify the VCOCXO, its model or existing source interfaces.

## Initial authority boundary

This prompt initially authorizes only:

- evidence inspection and deterministic replay;
- successor design and frozen-contract creation;
- focused implementation, tests and exact-profile builds;
- structural preflight and complete operational-path rehearsal;
- creation of a non-effective exact-bundle authority proposal; and
- tracked documentation needed to present the decision.

It does **not** initially authorize firmware flash or reset, serial-device
access, a GNSS transmission, DAC setup or challenge stimulus, control arming,
physical rehearsal or live acquisition. Stop after producing the exact bundle,
passing evidence-bearing rehearsal and non-effective proposal. Physical work
may proceed only after a later operator decision explicitly identifies and
authorizes that exact bundle and physical envelope.

Authority is consumed by the first physical terminal. Do not retry, extend or
change a criterion after observing live evidence without a new operator
decision.

## Read first and preserve

Read and validate at least:

- repository-root `AGENTS.md` and the applicable foundations and terminology;
- `docs/60_EXPERIMENTS/CX322_BOUNDED_HYBRID_FACT_GATHERING/README.md`;
- `docs/60_EXPERIMENTS/CX322_BOUNDED_HYBRID_FACT_GATHERING/01_STAGE5_ATTEMPT7_TERMINAL.md`;
- Attempt 7's immutable seal, evidence snapshot, exact bundle and registered
  package;
- `profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json`;
- `profiles/estimators/cx317_pps_gated_selected_v1.json`;
- `profiles/estimators/cx318_relative_phase_selected_v1.json`;
- `profiles/plant_models/cx317_pps_gated_v2.json`;
- `profiles/discipline/cx317_response_classification_v2.json`;
- `docs/50_SOFTWARE/CX317_PPS_GATED_SELECTED_ESTIMATOR.md`;
- `docs/50_SOFTWARE/CX317_RX_ONLY_GNSS_RECEIVER_CONTRACT.md`;
- `docs/30_ANALYSIS/PPS_REFERENCE_CHARACTERIZATION.md`;
- the local CX317, PA1616S and Adafruit receiver documentation; and
- `docs/datasheets/PMTK command packet-Complete-C39-A01.pdf`.

Preserve every predecessor artifact and its claim boundary. Do not rename
historical material merely to remove its legacy campaign identifier. `runs/`
remains ignored experimental evidence and must never be force-added.

## Accepted physical facts and working premises

Treat the following as accepted premises for this programme unless the new
run produces concrete contradictory evidence:

1. D14 is the sole authoritative PPS/reference input. D8 is the sole
   authoritative oscillator/count input. D10 remains the independent external
   event input and must not become a PPS witness, reference-validity input or
   control input.
2. The PA1616S is the installed GPS/GNSS antenna/receiver package and the
   receiver chipset is the MTK3339. GNSS serial metadata qualifies the same
   receiver that supplies D14; it does not replace D14 timing authority.
3. The installed serial wiring includes the RP2040-to-receiver transmit path.
   The current firmware nevertheless configures that direction as inactive and
   has operated as receive-only. Preserve the distinction between a physically
   connected wire and current firmware authority.
4. No independent equipment is available to characterize PA1616S/MTK3339 PPS
   time error or CX317 intrinsic stability. Use manufacturer specifications
   and accumulated OTIS evidence as priors that are assumed true until
   contradicted. Do not claim traceable UTC, independently calibrated PPS
   accuracy or an independent CX317 datasheet qualification.
5. The CX317's documented stability and the accumulated temperature evidence
   are adequate for this control experiment. Temperature is a recorded
   covariate, not a prerequisite characterization campaign or control veto.
   Reopen the temperature model only if a prospectively meaningful residual or
   repeated response failure contradicts the premise.
6. The rig is continuously powered and already thermally hot. Flashing resets
   the RP2040 but does not power-cycle the PA1616S/MTK3339, CX317, DAC or other
   continuously powered bench devices. Do not impose a new oscillator or GNSS
   warm-up after a flash. Still require the declared post-reset session,
   estimator, setup, DAC-epoch and settling evidence before control authority.
7. The established positive DAC-code-to-frequency direction and retained plant
   gain envelope remain adequate priors. Attempt 7's matched first six-code
   step is an additional consistency observation, not a replacement plant
   calibration.

These are scientific assumptions, not facts to conceal. Record them in the
manifest and final report. If the run contradicts one, preserve and report the
contradiction as a decision-bearing result rather than rescuing the premise
with another preliminary campaign.

## Bounded disposition of PPS sawtooth and PMTK diagnostics

Do not allow PPS sawtooth to become a side programme.

The available PMTK command document contains no documented sawtooth-correction
output, PPS timing-mode control, calibrated cable-delay command or PPS pulse
configuration for the MTK3339. It does document read-only queries for firmware
release, DGPS mode, SBAS enable/mode, NMEA output configuration and EASY state.
Those queries require the currently inactive RP2040-to-receiver serial
direction.

For this programme:

- do not implement or send PMTK configuration commands;
- do not change NMEA rate/output, SBAS/DGPS, AIC, EASY, datum, restart or power
  modes;
- do not add a receiver-query implementation as an entry requirement;
- retain the existing RMC/GGA/GSA qualification, fix quality, satellite count,
  HDOP, parser and identity telemetry; and
- record that the receiver's internal sawtooth correction state and PPS error
  are unobserved and governed by the datasheet/evidence premise.

Attempt 7's GGA fix quality 2, fresh 3D GSA state, satellite count and HDOP are
useful operational qualification. They do not prove which internal SBAS/DGPS
or PPS corrections are configured, and this programme does not need that proof.

The 600-second cumulative-count estimator makes sub-cycle PPS jitter primarily
an endpoint-noise contribution, while the raw phase observable has 100 ns D8
cycle granularity. Such noise can affect near-resolution short-horizon response
classification; it does not by itself explain the multi-cycle phase ramps and
long-window slope changes seen in Attempt 7. Only reopen this question if the
new evidence shows a coherent low-frequency reference anomaly capable of
changing the regulation decision.

If a future programme wants the documented read-only PMTK queries, it must
freeze a narrow transmit whitelist, exact query/response transcript, parser
behaviour and receiver-state non-mutation proof under separate authority. It is
not part of this campaign.

## Preserve the existing measurement and response windows

Do not redesign the estimator merely because a longer run is planned. Retain:

| Meaning | Frozen value |
|---|---:|
| Authoritative frequency estimate | 600 s non-overlapping cumulative snapshot span |
| Diagnostic frequency estimate | existing 60 s overlapping estimate, no authority |
| Post-DAC settling exclusion | 900 s |
| Fresh authoritative support after settling | 600 s |
| Earliest decision-bearing response checkpoint | 1,500 s after application |
| Phase-qualification residence | 1,800 s |
| Minimum applied cadence | 1,800 s |
| Phase pull-in horizon | 21,600 s |
| Absolute phase-bias cap | `1/600 Hz` |

Continue to retain response views at 600, 1,500, 3,600 and 7,200 seconds when
the same DAC epoch survives long enough. Label the 600-second post-application
view diagnostic and not settling-complete. The 1,500-second view is the first
response checkpoint because it comprises 900 seconds excluded for settling
plus 600 seconds of fresh authoritative support. Never fill a right-censored
horizon with zero or carry evidence across a DAC epoch.

## Default 24-hour authority envelope

Use the unchanged natural hybrid control law as the numerical baseline. Do not
change its frequency term, phase term, gain, rounding, anti-windup,
direction-coherence rule, tight-band semantics, step size or cadence merely to
obtain a reversal.

Freeze the following default successor envelope unless deterministic replay
finds a concrete safety, reachability or decision-sufficiency defect:

| Quantity | Limit or rule |
|---|---:|
| Qualified duration | 86,400 s |
| Absolute wall-clock limit | 108,000 s |
| Maximum automatic controller applications | 12 |
| Maximum combined automatic step | 21 codes |
| Maximum cumulative active movement | 84 codes |
| Hard DAC range | `0xA800..0xAB00` |
| Minimum applied cadence | 1,800 s |
| Outstanding requests | 1 |
| Deliberate reversal challenges | at most 1 |
| Automatic retry or terminal-code restoration | forbidden |

The setup transaction is separately identified. Every controller application
and any deliberate challenge consume the same 84-code cumulative active-path
budget. The deliberate challenge does not consume one of the twelve natural
controller applications, but it is a physical application, opens a new DAC
epoch and is subject to the same range, transaction, acknowledgement,
settling, evidence and fail-static rules.

Normal controller recovery after the deliberate challenge is the purpose of
the challenge and is allowed. "Terminal-code restoration" means an unrelated
automatic return to a nominal or starting code after stop, fault or abort; that
remains forbidden.

The default twelve-application count is intended to release the constraint
that stopped Attempt 7 without enlarging step, path, range or cadence. Compare
only a small bounded sensitivity set around this default during replay. Do not
turn selection into a broad controller-tuning search.

## Natural reversal and deliberate reversal challenge

The run must not merely hope that a natural reversal occurs.

Give the unchanged controller the first 43,200 qualified seconds to produce a
natural applied direction reversal. A natural reversal means a nonzero
automatic controller application whose sign is opposite to an earlier nonzero
automatic controller application in the same healthy phase epoch. A held
request or counterfactual demand is not an applied reversal.

If a natural applied reversal occurs before that boundary, cancel the
challenge and continue the controller unchanged for the full 24-hour qualified
duration.

If no natural applied reversal has occurred by 43,200 qualified seconds,
execute at most one prospectively frozen deliberate reversal challenge inside
the same campaign at the first eligible boundary and no later than 50,400
qualified seconds, provided all of these are true:

- capture, D14/D8 authority, GNSS qualification and the phase epoch are healthy;
- the controller is disarmed at a clean decision boundary;
- no request, application, response or replay acknowledgement is outstanding;
- the exact current code and DAC epoch are confirmed at every consumer;
- at least 36,000 qualified seconds remain for recovery observation;
- range and remaining cumulative-path authority permit the frozen challenge;
- the challenge transaction and the subsequent first dependent decision have
  already passed exact-bundle rehearsal; and
- the independent priority-abort path is healthy.

The default challenge magnitude is 21 codes because it remains inside the
existing per-step envelope and is large enough to be resolved by the selected
600-second estimator under the retained plant model. Freeze the exact value
after replay; a smaller value is acceptable only when it still provides a
decision-bearing perturbation. Do not exceed 21 codes.

Choose direction by a deterministic frozen rule:

1. if every preceding nonzero automatic application has sign `s`, apply the
   challenge with sign `s`, extending the existing movement so healthy recovery
   requires a later automatic application of sign `-s`;
2. if no nonzero automatic application exists, use a negative challenge under
   the established positive code-to-frequency plant direction, so the expected
   recovery application is positive; and
3. if a direction reversal has already occurred, do not challenge.

The challenge is an exogenous, fully provenance-bound disturbance, not a
natural controller output. Report natural and challenged reversals separately.
Do not fabricate a phase offset, reset the phase zero, overwrite raw phase or
inject synthetic evidence into a physical run.

If a challenge is ineligible because of range, path, timing or health, retain a
bounded `bidirectional_recovery_not_exercised` result. Do not widen authority.
If the challenge is applied but no opposite-sign automatic recovery is applied
with adequate post-response support, retain a scientific
`deliberate_reversal_recovery_not_demonstrated` result.

## Environment evidence

Retain the complete environment stream:

- SHT41 nearby-air temperature is the primary environmental covariate for the
  CX317 response analysis;
- SHT41 relative humidity is retained as secondary context;
- BMP280 pressure and secondary temperature are retained as secondary context;
  and
- missing or unusual pressure/humidity alone is not a control veto unless a
  separate declared health condition depends on it.

Analyze temperature beside DAC epoch, phase slope and frequency residuals, but
do not fit or promote a temperature-compensation controller in this programme.
Pressure and humidity must not be forgotten or discarded; report them
descriptively and investigate only a concrete association capable of changing
the result.

## Stage 1: evidence synthesis and frozen successor contract

1. Validate Attempt 7's exact identities, final static code, application
   sequence, zero crossing, held reverse demand and terminal evidence.
2. Recompute the matched first-step gain-consistency observation and clearly
   separate it from the retained plant-model calibration.
3. Replay the observed decision stream through the twelve-application,
   84-code, 24-hour candidate across the retained plant-gain bounds. Include
   the conditional challenge branch and sufficient timing for post-reversal
   observation.
4. Freeze exact definitions for natural reversal, challenged reversal,
   sustained final regulation, phase excursion, long-window phase slope,
   frequency preservation, chatter, efficiency and scientific rejection.
5. Use the existing measurement floor and retained evidence to choose these
   thresholds before live acquisition. Do not require the current apparatus to
   prove the independent PA1616S/MTK3339 or CX317 datasheet specifications.
6. Create one descriptive versioned programme profile and update programme
   status to point to it as offline and non-effective.

Do not add a thermal campaign, PPS characterization campaign, sawtooth
campaign, new plant map or independent-instrument prerequisite.

## Stage 2: implementation and deterministic proof

Implement only the changes needed for the longer authority envelope,
prospective challenge transaction, terminal semantics, monitoring, replay and
analysis. Preserve the one combined controller output and existing
request-authority-acceptance-application-response path.

Deterministically cover at least:

- natural negative-to-positive and positive-to-negative applications;
- no natural reversal by the halfway trigger;
- challenge eligibility, challenge cancellation and every ineligibility reason;
- challenge direction with prior negative, prior positive and no prior
  application;
- range, cumulative-path and application-count interaction;
- exact challenge code/epoch propagation and post-challenge recovery;
- a challenge that does and does not produce opposite-sign recovery;
- the 900 + 600 = 1,500-second checkpoint and all right-censoring boundaries;
- phase-direction coherence, quantization alternation and no hidden demand;
- legal RP2040 rollover in every exact elapsed-time comparison;
- reference loss, GNSS metadata loss and phase-epoch invalidation;
- stale-but-coherent versus contradictory downstream status;
- abort submission, abort delivery and terminal serial-owner ordering; and
- final static code with zero outstanding authority.

Use focused deterministic regressions plus the affected current firmware
profile, Campaign checks and materially affected Release checks. Do not run a
historical compatibility campaign.

## Stage 3: exact-bundle integration and rehearsal

The central lesson from the predecessor is non-negotiable:

> "All components passed separately" is insufficient. Entry readiness means
> that the exact frozen firmware binary and actual host path have successfully
> propagated every decision-bearing identity through the complete
> multi-transaction sequence.

Freeze one immutable bundle containing the exact firmware source revision,
build profile, compile-time configuration, UF2 identity, estimator and policy
profiles, capture, supervisor, replay, analyzer, finalizer, sealer,
registration tools, timing contract, identity/status query transcript, command
envelope, challenge rule, abort path, stop conditions and expected identities.

Rehearse the actual operational host topology through at least:

1. continuous capture and exact firmware/profile/session identity;
2. exact setup request, acknowledgement, applied code and new DAC epoch;
3. first controller request, acceptance, application, response and replay
   acknowledgement;
4. second controller transaction and its first dependent later decision;
5. retained repeated identities through later-authority release;
6. no-reversal halfway trigger and deliberate challenge transaction;
7. opposite-sign recovery request/application after the challenge;
8. transport obstruction and independent priority-abort delivery before
   capture closes;
9. sole serial-owner logical rotation; and
10. the real analyzer, seal and registration path.

Verify exact run, session, firmware, configuration, estimator, phase epoch,
request, acceptance, application, applied code, DAC epoch, response,
acknowledgement, evidence frontier, protocol phase and budget identities at
every consumer and through the first decision that depends on each transition.

A host fixture does not prove firmware compile guards, cross-core propagation,
the device driver or the physical plant. The readiness receipt must state
which real boundaries were exercised. It must also state how the exact frozen
firmware binary participated. If the existing rehearsal machinery cannot
exercise that binary through the complete multi-transaction sequence, do not
declare entry ready: prepare a bounded exact-bundle physical rehearsal proposal
and stop for explicit operator authority. A short platform rehearsal is not a
new scientific characterization campaign.

Produce a concise readiness report, machine-readable rehearsal receipt and
non-effective authority proposal, then stop for operator review.

## Stage 4: physical execution after exact authorization

Only after explicit authorization of the exact bundle:

1. Keep the controlling Codex turn active and poll authoritative supervisor
   state and retained evidence until a terminal state.
2. Confirm that the PA1616S/MTK3339, CX317 and rig remained continuously
   powered. Treat RP2040 uptime as a new firmware session, not a cold bench.
3. Establish capture and exact identity before setup or arm.
4. Re-establish the exact starting code through one acknowledged setup
   transaction, open a new DAC epoch and verify every consumer before arm.
5. Accumulate the normal estimator, qualification and phase-residence evidence;
   do not add a hardware warm-up delay.
6. Execute the unchanged controller under progressive authority, including the
   first two complete physical transactions before relying on wider authority.
7. At the 43,200-second boundary, either record the natural applied reversal or
   execute the frozen challenge at the first clean eligible boundary, no later
   than 50,400 qualified seconds.
8. Continue until the 86,400-second qualified endpoint or the first frozen
   terminal condition.
9. On every aborting terminal, keep the sole serial owner alive until priority
   abort is recorded as delivered or as a bounded delivery failure.
10. Analyze, replay, seal and register every terminal, including prewrite,
    challenged, incomplete and scientific non-pass terminals.

Do not tune, change a threshold, send a PMTK command, add authority, extend the
wall clock or restart after seeing behaviour.

## Live discriminating gates

Abort or hold fail-static immediately for identity, ordering, authority,
capture, transaction, range, path, cadence, serial-owner, queue, replay or
abort-path faults. Catch these at their first decision-bearing boundary rather
than waiting for final analysis.

Do not convert estimator quantization into a false scientific abort. One
near-resolution wrong-sign or zero 600/1,500-second response is retained
evidence. Prospectively define a persistent, resolvable wrong-direction or
growing-error rule using multiple complete same-epoch windows. When that rule
fires, inhibit further automatic applications and seal a scientific controller
or plant-model rejection separately from a platform fault.

Monitor and report state transitions, application and challenge milestones,
reversal, phase excursion, reference freshness and stale evidence. Process
existence or a silent terminal is not evidence of scientific progress.

## Prospective decision criteria

Freeze numerical thresholds before physical authority. The primary successful
result must include:

- complete 24-hour qualified evidence or a prospectively valid early success
  rule that still includes the required sustained post-reversal interval;
- at least one applied direction reversal, explicitly classified as natural or
  challenge-induced;
- at least six qualified hours after that reversal with exact same-session
  evidence;
- bounded raw relative phase without monotonic escape;
- a final long-window phase slope inside the frozen near-zero regulation band;
- preserved authoritative 600-second frequency RMS, tails and TIGHT occupancy
  within frozen no-material-degradation criteria;
- no persistent chatter, inefficient path consumption, unbounded alternation
  or authority exhaustion;
- exact firmware/host replay agreement for every controller and challenge
  transaction; and
- one confirmed static terminal code with no outstanding or latent authority.

Also report, without making them independent gates:

- phase excursion, slope and control effort before and after the first natural
  or challenged reversal;
- application count, net movement, cumulative path and reversals;
- per-epoch response at every available frozen horizon;
- plant-gain consistency across all sufficiently resolved applications;
- nearby-air temperature alongside response and residuals;
- relative humidity, pressure and secondary temperature context;
- GNSS fix quality, GSA dimension, satellites, HDOP, freshness and parser
  health; and
- the unresolved independent PPS, sawtooth and oscillator-accuracy claim
  boundary.

Predeclare terminal decisions that distinguish at least:

- `sustained_hybrid_regulation_demonstrated_natural_reversal`;
- `sustained_hybrid_regulation_demonstrated_challenge_reversal`;
- `sustained_regulation_bidirectionality_unexercised`;
- `deliberate_reversal_recovery_not_demonstrated`;
- `phase_or_frequency_regulation_not_sustained`;
- `controller_chatter_or_authority_exhaustion`;
- `right_censored_incomplete`;
- `measurement_authority_or_platform_fault`; and
- `operator_abort`.

## Claims boundary

Successful completion establishes regulation only for D8 CX317 behaviour
relative to qualified D14 PPS on this continuously powered rig under the frozen
controller and environment. It does not establish absolute UTC, calibrated
cable delay, independent PA1616S/MTK3339 PPS accuracy, independent CX317
datasheet compliance, phase-aligned output PPS, holdover or unrestricted
authority.

The absence of independent equipment narrows the claim; it does not block the
experiment. Manufacturer specifications and accumulated evidence remain the
working reference model until contradicted.

## Completion

For every physical terminal:

1. preserve raw evidence and original failure records;
2. independently replay the exact frozen decision semantics;
3. produce immutable analysis, evidence snapshot, seal and registration;
4. add a concise tracked terminal report under a descriptively named programme
   folder in `docs/60_EXPERIMENTS/`;
5. update programme status, roadmap, methodology and known limitations when
   the result changes them; and
6. record the final confirmed DAC code and leave the controller static.

Do not finish with a list of individually passing components. Finish only with
an end-to-end decision, exact provenance, explicit assumptions and the next
scientific consequence.
