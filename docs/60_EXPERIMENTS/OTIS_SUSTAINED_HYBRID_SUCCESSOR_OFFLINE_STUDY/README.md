# OTIS sustained-hybrid successor offline study V1

## Decision and claim boundary

This study asks whether one of three prospectively frozen, changed controller
policies is robustly better than the rejected sustained-hybrid V1 controller on
the immutable Attempt 4 evidence and a small deterministic perturbation corpus.
It separates exact historical replay and causal term ablation from modeled
closed-loop continuation. A counterfactual row is never a physical observation
or qualification result.

The machine-readable contract is
[`study_contract_v1.json`](study_contract_v1.json). Its thresholds, candidates,
ordering, modeled uncertainty, and rejection rules are frozen before candidate
result rows are generated. The comparator must validate the contract's own
semantic digest and every bound source identity before evaluating a candidate.

## V1 closeout and source authority

Attempt 4 has two different outcomes. The physical qualification failed because
none of the eleven required contemporaneous pre-phase-4 response-replay
attestations was retained. That absence cannot be repaired into a physical
pass. Independently, exact replay of the retained AHY, ACT, estimator, phase,
tight-band, DAC-epoch, response, and first-dependent-consumer evidence passes,
and V1 reached the frozen `prospective_low_efficiency_path` terminal.

The immutable source package is
`runs/otis_sustained_hybrid_regulation_v1/live_attempt4_20260823T2148Z`, with
registered content SHA-256
`aa7ac41bb07192f4de5807547899d50b0e51b3c60bbcac4f8e9cadb6fc6a2a90`.
Its evidence snapshot validates with no failures or warnings: 80 files and
409,352,510 bytes. The physical seal remains unchanged and failed.

The exact baseline must reproduce 52 AHY decisions, the eleven natural applied
deltas `-6,-1,-1,-6,-1,-1,-1,+5,+5,-5,+5`, 37 path codes, seven codes net
movement from setup, terminal code `0xA835`, and the next held five-code request
at `prospective_low_efficiency_path`. Candidate evaluation is invalid until the
baseline and all cited identities reproduce exactly.

## Frozen candidates

V1 is a non-selectable comparator. The changed candidates are:

1. `one_count_tight_hold_v1`: while `TIGHT_INSIDE` and the fresh authoritative
   accumulated error is -1, 0, or +1 count, zero only the frequency
   contribution. Preserve the phase term and every other V1 semantic.
2. `tight_phase_only_v1`: while `TIGHT_INSIDE`, zero the frequency contribution.
   Frequency acquisition remains enabled outside tight state.
3. `persistent_one_count_release_v1`: while tight, hold the first isolated
   +/-1 count; release on the second consecutive fresh non-overlapping estimate
   with the same sign, session, and DAC epoch. Reset on every transition named
   in the contract.

The ranking first rejects any candidate that misses a gate. Among remaining
candidates it prefers, in order: more passed perturbations, lower Attempt 4
natural path, smaller worst-case frequency degradation, then the contract's
prospective semantic-complexity order. An unresolved equality produces no
selection; thresholds are not moved after inspection.

## Analysis layers

Layer A replays the real V1 chronology exactly, then performs term-removal,
one-count, gain/rounding, cadence, and grouped-support diagnostic ablations at
the retained decision frontier. These identify which retained term generated a
request. They make no post-divergence plant claim.

Layer B preserves every raw Attempt 4 value and projects only the declared
effect of the modeled-versus-actual DAC code path. It carries decision time in
`rp2040_timer0_extended`, the candidate DAC epoch, 900-second settling plus
600-second fresh-support semantics, and unjoined raw phase epochs. It evaluates
the retained minimum, nominal, and maximum gains. The retained hysteresis and
repeatability extremes are exercised as explicitly labeled sensitivity cases,
not silently folded into observations.

## Authority

This study is offline-only. It may not open a serial device, flash or reset
firmware, write a DAC, arm control, use a physical command FIFO, run a physical
rehearsal, or create a live activation. Selection would create the new
programme identity `OTIS_SUSTAINED_HYBRID_SUCCESSOR_V1`; it would not create
Attempt 5 or inherit V1 authority. Any physical successor still requires a
later exact non-effective bundle, explicit operator decision naming that
bundle, and a fresh setup acknowledgement.

## Terminal outcomes

- `selected_changed_successor`
- `no_controller_successor_selected`
- `study_invalid_due_to_evidence_or_replay_mismatch`

If no candidate passes, the next gate is an estimator or controller-architecture
revision. No successor policy, bundle, or live proposal is created merely to
continue the programme.

## Result

The frozen comparison reached `no_controller_successor_selected`. Every changed
candidate first fails the independent one-cycle matched phase-improvement gate
at minimum retained plant gain. The one-count and persistent candidates also
miss the 27-code Attempt 4 path cap at nominal gain; tight phase-only meets that
cap but fails tight occupancy and both natural demand-reversal cases. See
[`DECISION.md`](DECISION.md) and the immutable
[`comparison_report_v1.json`](comparison_report_v1.json). The next gate is an
estimator or controller-architecture revision; no successor implementation or
bundle was created.
