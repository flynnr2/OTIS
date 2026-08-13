# CX319 Stabilized Tight-Deadband and Hybrid-Preview Programme

## Status and present authority

CX319 is the stabilized-platform successor to the suspended CX318 programme.
The operator authorized offline programme preparation on 2026-08-11.

The present authority is limited to repository changes, deterministic replay,
no-I/O preflight, tests, firmware builds and review artifacts. It does not
authorize a flash, opening a serial device, creating a command FIFO, issuing a
DAC command, arming control, running a physical rehearsal or starting a live
leg. Those operations require a later explicit operator decision and a
corresponding machine-readable authority transition.

CX318 remains incomplete, unsealed and non-promotable. Its run directories,
promotion ledger, failed seals, manifests, builds and profiles are historical
evidence. CX319 must not resume or modify them.

## Decision-bearing objective

Determine, with the smallest finite sequence that preserves scientific and
operational validity, whether:

1. the integer-count tight hysteretic frequency policy acquires the selected
   band from both sides of the operating point;
2. the selected arbitrary-epoch relative-phase estimator and bounded hybrid
   preview remain replayable and non-actionable during real frequency-only
   control;
3. reference, phase, transport and service faults fail closed without creating
   phase-derived actuator authority; and
4. the evidence justifies proposing a separately authorized bounded
   active-hybrid experiment.

This is a continuation of the scientific question, not a continuation of the
old operational campaign identity.

## Inherited evidence and mandatory revalidation

CX319 may use these results as historical scientific inputs:

- the sealed CX317 bounded frequency-control result;
- the CX318 Stage 1 evidence and terminology contract;
- the selected CX318 relative-phase estimator and Stage 2 replay corpus;
- the selected CX318 bounded hybrid preview and Stage 3 comparison;
- the sealed CX318 Stage 4 non-actuating firmware-parity evidence;
- the characterized `0xA800..0xAB00` DAC operating envelope; and
- the last historically confirmed CX318 applied code `0xA828`.

Inheritance does not give an old artifact current operational authority.
Before bench entry, current code must replay the inherited evidence and bind
its exact identities. The exact current firmware profile, host workflow,
contracts, policy and analyzer must receive fresh no-write evidence.

The historical `0xA828` value is provenance for the last confirmed CX318
transaction. It is not a fresh physical DAC observation after a reset, flash or
firmware change. Physical applied-code state remains unknown until a new exact
setup transaction is acknowledged and recorded.

## Current platform foundations

The programme is derived from the stabilized platform rather than the
suspended Stage 5 bundle:

- `diagnostics_v1` is the only current diagnostics wire authority;
- `cx317_active_status_snapshot_v1` supplies one complete, fresh generation
  for any future active decision;
- `CX317_BOUNDED_ACTIVE_I_ONLY_V2` is the inherited current frequency-control
  policy root;
- platform memory, queue, PIO/DMA, transport and wait budgets fail closed;
- serial capture has one continuously draining owner;
- obstruction uses the normal bounded path while priority abort remains
  independent;
- logical evidence rotation retains the same physical serial owner; and
- analysis, sealing and external evidence registration are mandatory parts of
  the operational path.

CX319 adds a new identified policy root that binds those foundations and the
selected tight-deadband, relative-phase and hybrid-preview semantics. It does
not allow a suspended programme policy to replace the current root implicitly.

## Programme sequence

### G0 — Stabilized offline contract and migration

Create and verify the complete no-hardware vertical slice:

- new programme and policy identities;
- explicitly scoped programme authority;
- new lower- and upper-leg firmware profiles with current lifecycle metadata;
- current host/firmware policy and profile identity parity;
- deterministic tight-deadband and inherited-corpus replay;
- structural proof that phase and hybrid outputs cannot influence actual
  frequency-controller delta, eligibility, response or budget state;
- current status-snapshot, diagnostics, resource and transport contracts; and
- Fast, Standard/Campaign and Release verification appropriate to the changed
  surfaces.

G0 passes only when its report is internally consistent and every physical or
live operation remains blocked.

### G1 — Exact-bundle no-write rehearsal readiness

Build the active-campaign workflow from the stabilized platform components.
Freeze the exact source, profile, configuration, UF2, host tools, commands,
timeouts, analyzer, seal and abort conditions before physical entry.

The rehearsal must use the exact leg firmware and operationally significant
bundle intended for the live run, with setup and automatic writes unavailable.
It must run for at least 2700 seconds, obtain at least one fresh authoritative
600-second estimate after warmup, exercise bounded transport obstruction and
priority abort, retain one serial owner through logical evidence rotation, and
complete the actual analyzer, seal and evidence-registration path.

G1 requires a separate operator authorization before any hardware interaction.

### G2 — Lower-side finite frequency-only leg

After a passing exact Leg A rehearsal, apply one exact `0xA808` setup stimulus,
opening a new DAC epoch. The setup is not evidence of automatic-controller
direction.

The live leg must demonstrate at least one complete healthy positive automatic
request, acceptance, application and response transaction and two-estimate
tight entry. It remains bounded by:

- four automatic corrections;
- 21 codes maximum per automatic correction;
- 84 codes maximum cumulative automatic movement;
- 1800 seconds minimum between applied automatic corrections;
- 900 seconds settling exclusion followed by 600 seconds fresh support;
- one request outstanding;
- `0xA800..0xAB00` hard range;
- 90-minute qualification deadline; and
- four-hour maximum qualified duration.

A finite non-pass is useful evidence and stops progression. It must not cause a
threshold change, extension or retry inside the same run identity.

### G3 — Upper-side finite frequency-only leg

G3 is forbidden unless G2 passes. Use a new exact upper-leg bundle and fresh
rehearsal, then apply one exact `0xA848` setup stimulus. Demonstrate the same
bounded result in the negative automatic direction. Both G2 and G3 must pass
for bidirectional tight-deadband validation.

Treat G2 and G3 as a matched physical pair. Preserve the same firmware and
host semantics, control cadence, readiness gates, monitoring, analysis, and
stop rules; change only the leg-specific profile, setup code, and required
automatic direction. Defer any cadence acceleration until both legs have
completed so an optimization cannot weaken comparability or introduce a new
operational escape between the two decision-bearing runs.

### G4 — Combined observation and fault campaign

G4 preserves the scientific purpose of the former CX318 Stage 6 while using
new identities and the stabilized operational path.

Part A is a finite 12-hour qualified real-GNSS run beginning at the last
confirmed G3 code, without a nominal-restore stimulus. Only the selected tight
frequency policy may have authority. The hybrid preview remains zero-authority.
Limits are eight automatic corrections, 168 cumulative codes, 21 codes per
correction, 1800-second minimum cadence, a 90-minute qualification deadline and
a 16-hour absolute wall-clock ceiling.

Part B uses a separately identified non-actuating pseudo-reference or
deterministic fixture bundle. It exercises phase steps, reference anomalies and
loss, clean requalification, association loss, session restart, GNSS validity
and identity changes, service stall, backpressure, queue saturation, malformed
records and aborts. Part B must not be described as holdover evidence.

Destructive reference or power faults are forbidden while Part A frequency
authority is armed.

### G5 — Final review and next-goal decision

G5 is documentation and verification only. It does not move the DAC. Audit all
identities, observations, derived relative-phase values, diagnostics, decisions,
transactions, failures, seals and terminal physical state.

Choose exactly one result:

- `blocked_before_bidirectional_tight_deadband`;
- `tight_deadband_or_plant_model_needs_revision`;
- `tight_deadband_passed_relative_phase_or_hybrid_preview_needs_revision`;
- `relative_phase_hybrid_preview_and_tight_deadband_passed_fault_gate_failed`;
- `cx319_full_frequency_only_and_hybrid_preview_sequence_passed`.

Then recommend exactly one separately authorized next programme:

- bounded active-hybrid phase/frequency trial;
- relative-phase observable or capture improvement;
- tight-deadband or plant-model revision;
- physical waveform and delay characterization;
- reference-loss holdover preview; or
- GNSS provisioning and timing-receiver work.

There is no implied CX319 G6 or “Stage 8” actuation authority. A bounded
active-hybrid experiment is a new programme.

## Frozen candidate semantics for offline proof

The G0 candidate retains the previous integer-count experiment for direct
comparability:

| Rule | Candidate value |
|---|---:|
| authoritative estimate | fresh non-overlapping 600 s accumulated edge count |
| initial/rearm state | `REQUALIFY_OUTSIDE` |
| tight entry | absolute error at most 2 counts |
| entry persistence | 2 consecutive estimates |
| loose release | absolute error at least 4 counts |
| release persistence | 2 consecutive estimates |
| 3-count region | retain the previous band state |
| maximum automatic step | 21 codes |
| minimum applied cadence | 1800 s |
| post-write exclusion | 900 s |
| fresh support after exclusion | 600 s |
| automatic retry or restoration | forbidden |

These values are frozen for deterministic offline comparison. They do not
become live authority until G1 and subsequent explicit operator gates pass.

## Universal claims and authority boundary

Throughout CX319:

- hardware capture establishes the timing aperture;
- raw observations remain canonical;
- relative phase is arbitrary-epoch and reference-relative;
- the phase and hybrid preview are non-actionable through G5;
- modeled phase improvement is not observed active-hybrid performance;
- lock is not proof of correctness;
- reference-loss preview is not holdover; and
- no result establishes traceable absolute frequency, calibrated phase, UTC,
  physical delay, timing-grade receiver performance or combined uncertainty.

Every live write must be reconstructable from current measurements, one fresh
complete status snapshot, estimator output, diagnostic gates, policy identity,
request, acceptance, application acknowledgement and resulting state. Missing
evidence is failure, never clean or zero.

## Rabbit-hole control

Treat an anomaly as a candidate cross-surface contract failure until one
discriminating check localizes it. For each anomaly record one hypothesis, the
decision it could affect and one bounded check. Expand only when the result
affects safety, scientific validity, the next programme gate or a shared
platform invariant.

Do not patch a late analyzer around a producer/contract disagreement. Check the
complete firmware producer, host capture, manifest, analyzer and seal path for
the same semantic field. Conversely, do not redesign unrelated platform areas
to improve a narrow programme result.
