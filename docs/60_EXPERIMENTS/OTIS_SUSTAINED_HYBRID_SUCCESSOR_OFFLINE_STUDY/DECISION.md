# Sustained-hybrid successor offline decision

## Terminal

`no_controller_successor_selected`

None of the three prospectively frozen changed controllers is robustly better
than V1 under the immutable Attempt 4 comparison and deterministic perturbation
matrix. No `OTIS_SUSTAINED_HYBRID_SUCCESSOR_V1` policy, firmware profile, exact
bundle, authority proposal, or physical run is created.

The immutable machine-readable result is
[`comparison_report_v1.json`](comparison_report_v1.json), with semantic report
SHA-256
`d3b48818b082d9e8797c9a78316b1ae286f8bdcf5eb4ef34b66f286223717523`
and file SHA-256
`1aa3f8e5766bab071af91160a8801843102ad6058e36539daf97f0efbdd52ea7`.
The frozen contract SHA-256 is
`d60c26c90d7f06f4c605f2b35159209315f4c1b035dd9831f76c78e1200ea7cf`.

## Observed Attempt 4 facts

The source package validates unchanged: 80 files, 409,352,510 bytes, registered
content SHA-256
`aa7ac41bb07192f4de5807547899d50b0e51b3c60bbcac4f8e9cadb6fc6a2a90`,
with no evidence-snapshot failures or warnings. The comparator also validates
the four exact tracked estimator, plant-model, and response-policy file
identities declared by the contract.

Exact V1 replay reproduces all 52 AHY decisions and eleven natural
applications:

`-6,-1,-1,-6,-1,-1,-1,+5,+5,-5,+5`

The controller consumed 37 natural path codes, moved net -7 codes from setup,
ended at 43061 (`0xA835`) in DAC epoch 12, and rejected the next five-code
request at `prospective_low_efficiency_path`. The formal physical qualification
remains failed because all eleven contemporaneous pre-phase-4 replay
attestations are absent.

## Derived causal result

At the retained decision frontier, the four late frequency-driven applications
`+5,+5,-5,+5` all become zero when the +/-1 count frequency contribution is
held. None of those requests was cadence-limited. V1 maps one authoritative
count to about 4.8075 raw codes; gain would have to be strictly below 300
codes/Hz/decision for one count to round to zero without a separate rule.

This supports the working diagnosis: quantized +/-1 count observations are the
upstream condition and the absence of a contextual small-error hold is the
immediate mechanism. It does not show that a blanket tight-band hold preserves
the earlier phase-material path.

## Modeled candidate comparison

All post-divergence values below are modeled, not physical observations. The
model preserves raw Attempt 4 records, projects only the candidate-versus-actual
code-path effect, evaluates the retained plant-gain envelope, keeps phase epochs
unjoined, and labels hysteresis/repeatability sensitivities separately.

| Candidate | Nominal path codes | Nominal net codes | First frozen failure | Other discriminating failures |
| --- | ---: | ---: | --- | --- |
| One-count tight hold | 28 | -10 | Minimum-gain phase behavior: 0.471 matched improvement cycles, below 1.0 | Nominal path exceeds 27; tight occupancy and every gain/uncertainty scenario fail |
| Tight phase-only | 20 | -18 | Minimum-gain phase behavior: 0.471 matched improvement cycles, below 1.0 | Tight occupancy fails; both natural demand-reversal cases hide demand |
| Persistent one-count release | 28 | -10 | Minimum-gain phase behavior: 0.471 matched improvement cycles, below 1.0 | Nominal path exceeds 27; tight occupancy and every gain/uncertainty scenario fail |

At nominal gain, all three retain more than the required 10% fractional phase
improvement, but achieve only 0.413 matched improvement cycles, below the
independent one-cycle requirement. One-count hold and persistent release also
use 28 path codes, above the frozen maximum of 27. Tight phase-only meets the
path limit but fails the phase, tight-occupancy, and bidirectional-demand gates.

The common early failure is causal to the candidate semantics: each candidate
also suppresses the +/-1 count frequency contribution during the early
phase-material decisions, changing the two observed -6 combined requests into
much smaller phase-only actions. The bounded study therefore does not justify
implementing any of them.

## Claim boundary and next gate

The exact replay claim ends at the retained V1 chronology. Candidate
continuations are static-gain and labeled retained-uncertainty counterfactuals;
they do not establish RP2040 cross-core propagation, USB transport, AD5693R,
D14, D8, or physical CX317 behavior. D10 remains an external event input only.

The next gate is an estimator or controller-architecture revision that can
distinguish late maintenance noise from early phase-material combined control.
That is a new separately frozen study. It must not tune these rejected
candidates after inspection or inherit V1 physical authority.
