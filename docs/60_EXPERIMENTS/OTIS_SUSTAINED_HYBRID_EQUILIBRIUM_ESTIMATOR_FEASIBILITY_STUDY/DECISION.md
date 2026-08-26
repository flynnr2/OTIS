# Sustained-hybrid equilibrium-estimator feasibility decision

## Current terminal after recovered-source attempt

`equilibrium_state_not_observable_targeted_characterization_required`

The exact Stage 5 plan was recovered at its independently recorded SHA-256,
so the second, separately frozen zero-I/O attempt passed every source-identity
and exact-baseline gate. It reconstructed 18 identification supports directly
from bound D14 reference, D8 cumulative-count, DAC-acknowledgement, session,
and settling-policy records. It also reconstructed all 52 Attempt 4 selected
supports as a genuinely held-out physical validation set.

The first discriminating scientific failure is
`identification_complete_feasible_set_nonempty`. The complete identification
set is empty for every one of the three frozen models at minimum, nominal, and
maximum retained gain:

- the constant-equilibrium intersection becomes empty in
  `lower_interior_1` (on its second support at minimum gain and its first
  support at nominal and maximum gain);
- allowing the independently frozen `±1.91 codes/hour` slow drift still leaves
  an empty exact feasible set at all three gains; and
- the direction/history model also remains empty at all three gains. Its
  common return offset is already allowed to range over the full frozen
  `[-8,+8]` codes, but the outbound/anchor evidence is itself inconsistent.

Because identification is empty, no estimator interval exists to validate on
Attempt 4. Held-out outcomes were not fed back into identification, and no
nominal-only or favorable-history result was selected. All gain,
same-code-one-count, settling, and leave-one-complete-dwell sensitivities
therefore fail closed. There is no interval to compare with the frozen
18-code usefulness limit, and no equilibrium estimator is selected.

The immutable recovery report is
[`observability_report_recovery_v2.json`](observability_report_recovery_v2.json),
with semantic SHA-256
`dae8dcc78cd816152246e06df1886ed572e873ed2ca1fd52e38c91f80228b21b`
and file SHA-256
`325e585290ff216203101c772b78bf20ab9e25e8a4398fe544da498b1699b91a`.
The separately frozen recovery contract has semantic SHA-256
`534beecf00ac09087fdbb3f1c36f03660753c29d8a7d3d4ff0756aa9c3f24f80`
and file SHA-256
`608090d7e14806c3d6d67245d76c1031f5a25115e71cc9c2e824bad4dd0d747f`.
The recovery comparator SHA-256 is
`9fcfdbfdf08cecb0839fc6cbc7e32a4859dfa5908d74ab58de4939a3ed05a959`.

This is a finite-evidence observability rejection, not evidence that a unique
physical equilibrium does not exist. The retained quantized supports cannot
identify it under the prospectively frozen gain, drift, and history models.
The one next gate is a separately authorized, prospectively frozen targeted
characterization satisfying
[`TARGETED_CHARACTERIZATION_REQUIREMENTS.md`](TARGETED_CHARACTERIZATION_REQUIREMENTS.md).
That document is non-effective and creates no bundle or physical authority.

## Immutable first-attempt terminal

`study_invalid_due_to_evidence_or_model_binding_failure`

The retained data were not used to compute an equilibrium interval. The
required Stage 5 open-loop plan
`profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json` is unavailable,
while the plant model, Stage 5 run manifest, and immutable characterization
report all bind its exact SHA-256 as
`19609f35e285d8005054f7acdf59341675ae01c1fe986a44cea296a35f95d84d`.
A read-only Git object check also found no file at that path in the recorded
source commit `0d52df61f189eb98c8e0e1e318e8ca706fcf6e52`. The original run records
`source_state: dirty`, so the missing plan cannot be reconstructed from current
tracked history and called identity-valid.

The immutable machine report is
[`observability_report_v1.json`](observability_report_v1.json), with semantic
SHA-256
`b98bf927170c0f8f868007cf5aa497898d3d7c65a57583b30c299dacd64547c3`
and file SHA-256
`d9d8707450f486ded6091a1947a58208ce42ce83f818268a85ee1328456797c0`.
The prospectively frozen contract has semantic SHA-256
`ab2ec34269d0cb21b7895e459201e6d8c500ae050304d8f9f3bd5a829caed682`
and file SHA-256
`1fef915dfe7c23aaacfaed104db1d4d62ac0d407cfc5618e60032a26ac064902`.
The comparator SHA-256 is
`f99ebf2e358c62ee3f7875a86b67745a59e2093f5fa8e847bf2a03895eb2c29a`.

## What the first attempt reproduced

These are reconstructed results from immutable evidence and existing
comparators, not new physical observations:

- Both predecessor semantic reports reproduced exactly at their frozen
  digests and terminals.
- Attempt 4's registered evidence identity reproduced as
  `aa7ac41bb07192f4de5807547899d50b0e51b3c60bbcac4f8e9cadb6fc6a2a90`.
- Exact V1 replay reproduced 52 decisions and the eleven applications
  `-6,-1,-1,-6,-1,-1,-1,+5,+5,-5,+5`.
- The first seven applications remain phase-material, consume 17 path codes,
  and end at code 43051. The last four remain frequency-only maintenance and
  consume 20 more path codes.
- The terminal remains `prospective_low_efficiency_path` at code 43061, DAC
  epoch 12, with exact source support and one unjoined raw phase epoch.
- Attempt 4's physical qualification remains failed because its eleven
  contemporaneous pre-phase-4 response-replay attestations are absent.

All other frozen tracked, Attempt 4, Stage 5, and rapid-characterization file
bindings used by the comparator are present and exact. The failed plan binding
is therefore a specific evidence/model provenance defect, not an Attempt 4 or
predecessor replay failure.

## Derivations left unevaluated by the first attempt

Before estimator results, the contract froze three bounded hypotheses:
constant equilibrium, independently bounded slow drift, and identifiable
direction/history conditioning. It also froze exact half-count interval
arithmetic, complete-segment identification and Attempt 4 holdout, minimum/
nominal/maximum gains, separate same-code and reversal perturbations, and an
18-code maximum useful equilibrium-interval span.

The 18-code usefulness gate is derived from unchanged downstream constraints.
It limits worst integer-centre return error to nine codes; at maximum gain that
is `0.0015600609040120617 Hz`, below the one-count frequency-degradation
allowance. A one-code excursion held 6,114 seconds supplies at least one cycle
of finite area at minimum gain, and departure, intentional return, plus the
worst nine-code recovery uses 11 path codes, below the 27-code cap.

None of these frozen models was fitted or bounded. Structural identifiability,
complete feasible sets, held-out prediction, sensitivity coverage, residuals,
and usefulness are explicitly `not_evaluated_due_to_binding_failure`. This
terminal is not evidence that equilibrium is observable or unobservable.

## Claim and authority boundary

Observed facts remain the retained Stage 5 and Attempt 4 records. Reconstructed
facts are the exact predecessor and V1 replays. The usefulness limit and source
comparisons are derived. Model and nuisance rules are prospectively bounded but
unevaluated. There are no new modeled equilibrium results.

No raw phase epoch was joined, D10 did not enter the estimator, and no serial
device, firmware, GNSS transmitter, FIFO, DAC, reset, flash, arm, rehearsal, or
live acquisition was accessed. Physical actions performed are zero. The result
is neither calibration, physical qualification, lock, controller selection,
nor authority.

The exact Stage 5 plan was subsequently recovered and identity-validated as
documented in [`SOURCE_RECOVERY.md`](SOURCE_RECOVERY.md). That resolved the
initial evidence gap without altering this immutable first-attempt report. The
current terminal and next gate are the recovered-source results above.
