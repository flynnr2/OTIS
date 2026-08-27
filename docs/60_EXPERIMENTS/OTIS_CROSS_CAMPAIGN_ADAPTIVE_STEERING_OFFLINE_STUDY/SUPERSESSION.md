# V1 supersession record

`analysis_contract_v1.json`, `study_report_v1.json`, and the local derived
package `runs/derived/cross_campaign_adaptive_steering_offline_v1` are retained
unchanged as an audit record. They are not decision-bearing.

An independent pre-completion review found that V1 did not bind every
one-second interval to the canonical raw D14 endpoints, synthesized a Boolean
control-decision eligibility state that the retained GNSS metadata cadence
cannot establish, encoded unavailable metadata-hold chronology as zero, and
carried incomplete per-row source provenance. The same review also found that
selected frequency was incorrectly coupled to phase availability.

Those are normalization and evidence-authority defects, not new evidence and
not a changed acceptance criterion. V2 was prospectively refrozen before any V2
candidate result was generated. It keeps the V1 source set, controller set,
thresholds, own-law replay rules, model gates, and terminal outcomes, while
correcting the joins and unavailable-state semantics. The V2 overlay binds its
preserved base contract by semantic digest.

V1 must not be silently repaired or used to support the programme decision.
The decision-bearing artifacts are `analysis_contract_v2.json`,
`study_report_v2.json`, the V2 completion report, and the separately retained
local V2 derived package.
