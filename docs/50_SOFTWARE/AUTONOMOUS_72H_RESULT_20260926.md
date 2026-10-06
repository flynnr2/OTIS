# Autonomous 72-hour result — 26 September 2026

## Reviewed verdict

**The finite autonomous-operation observation passed its stated question and
endpoint, with incomplete qualified measurement coverage.** The instrument
operated for the selected 259,200 firmware seconds, applied repeated bounded
corrections, recorded every resulting response, recovered from reference and
metadata holds, and autonomously entered OBSERVE_HOLD. No repeat physical
acquisition is required to correct the offline analyzer finding.

This conclusion applies to the [frozen observation](AUTONOMOUS_72H_OBSERVATION.md).
It does not establish 72 uninterrupted hours of qualified steering, calibrated
absolute accuracy, indefinite reliability or unconditional approval of the
fault mapping. No accuracy threshold, correction quota or minimum coverage
percentage has been introduced after inspecting the evidence.

## Acquisition and endpoint

The bench acquisition ran from 23 to 26 September 2026, completing at about
19:54 BST. Its sole run-local command was AUTO sequence 5, dwell 259200, session
1396544150034562714. The exact accepted command tick was 14412682561 and the
stored deadline was 273612682561 in `rp2040_timer_us64`. The final IST transition
to HOLD was 273612682788: **227 microseconds after the stored deadline**.
The later coordinator status was observation latency, not the transition time.

The generic IST reason `operator_hold` does not mean the host sent HOLD: there
is no second ICM, and the coordinator retained `hold_submitted: false`.
Final state was OBSERVE_HOLD, code **43067 (`0xA83B`)**, DAC epoch 57,
no pending write, no terminal fault and no active reference/metadata hold.

Seven raw segments contain **914,247,488 bytes**. Recording closed at a complete
frame boundary, the retained process results establish orderly closure, and
error logs are empty. Entry, physical acquisition, firmware endpoint, raw
integrity and local packaging succeeded independently of the original offline
coverage classification.

## Corrections, responses and qualification

All **53** requested writes join their accepted applications exactly. Application
codes range from 43062 to 43083 inside the established envelope; the entry code
was 43075. All 53 applications also join unique later responses by instrument
session, capture session and DAC epoch. Write and response sequence numbers are
different namespaces. No application or response is unmatched or incomplete.

There were **43 responses detected with the commanded sign** and **10 classified
healthy but below the empirical detection floor**. Those ten do not establish a
detected physical response. No wrong-sign, growing-error, excess-response or
measurement/actuator-fault response classification occurred. The 295 decisions
include 150 zero-containing intervals; a zero correction is a valid decision.

Recorded IST transitions show 217 reference-hold episodes totaling
1960.775641 seconds and one metadata-hold episode of 1606.228801 seconds, all
recovered. The episodes do not overlap. Their durations use only the declared
`rp2040_timer_us64` domain; they describe firmware flags, not independently
calibrated receiver-outage durations. Absence of either hold is not equivalent
to active steering or qualified phase estimation. The physical or firmware
cause of repeated reference discontinuities is not established by this review.

Within the causal accepted-boundary selection after AUTO entry identity
`(acceptance_epoch=1, ordinal=14402)` through timed-HOLD identity `(222,144492)`,
there are 257,022 accepted nominal reference intervals and qualified RPH rows.
PHE contains 223,994 qualified, 33,245 initializing and 217 invalid observations;
RPH additionally contains 217 epoch-open anchors and 217 invalid observations.
The accepted spans sum to 257020556874 ticks by per-span modulo-2^32 subtraction
in `rp2040_monotonic_us32`. This is a separate raw-domain aggregate, not a
projection onto the experiment's timer-us64 deadline or a claim of continuous
qualified coverage.

## Evidence coverage and repaired analyzer

The original analyzer compared APS ordinals and RPH/PHE observation sequences
across their declared epochs. It consequently reported four APS restarts and
217 restarts in each phase stream as a canonical coverage defect. This was a
**platform analyzer defect that escaped rehearsal**, confined to the offline
consumer; no command, firmware, acquisition or raw byte changed.

Corrected analysis scopes APS by capture session and acceptance epoch, and
RPH/PHE by capture session and phase epoch. Five acceptance epochs have emitted
APS spans (labels 1, 6, 7, 221 and 222); these are not all instantiated acceptance
epochs. There are 218 observed phase epochs. Epoch transitions are reported
separately from loss. Empty acceptance epochs may have no APS rows, whereas
missing entire phase epochs remain findings because each phase increment emits
a record. Tests also retain detection of within-epoch gaps, duplicates, backward
movement, missing new-epoch prefixes, malformed scope fields, epoch re-entry and
capture-session re-entry.

REF, SNP, CNT, APS, RPH and PHE have zero detected sequence gaps, ordering faults,
scope regressions or malformed source records. Instrument records have no gap
or ordering defect; write/application joins are complete. These are claims about
delivered evidence under its contract, not independent proof of every physical
input edge.

The **9,663 optional ENV gaps remain explicit**. Sampled direct-row drops rise
from 20 to 9683, matching that loss count. Critical, evidence, observation,
phase-preview and telemetry drop counters remain zero throughout sampled status.
Environmental loss limits correlation and coverage; it does not veto firmware
control. The correction changes no environmental or scientific criterion.

## Provenance and replay

Original returned archive:
`~/Documents/OTIS_DATA/autonomous-72h-results/acquisition-20260923T1954BST-fb263fb6-883b878a-8f1fd95b.zip`.

- Archive SHA-256: `66f5feb9bba972b294adc8c4eed403da3d583d30ad2d6f7a313bfb2d3affa2f1`.
- All 34 original evidence files match inventory SHA-256
  `884ad3aedc2560e00bfca5f03efd728fbb0e96e46730b406d4c0c6f3edd567b4`.
- Frozen plan SHA-256:
  `fb263fb6e5626015f167e9e41b3e9352f5d9a9e2612b9325737e0076538810a1`.
- Original analyzer SHA-256:
  `883b878a4004e605ec44d130e165b4730f1d944fa46a4cb85d5012cc6bda9b05`.
- Acquisition source: `7c083d7467ea57caf425716c3259146b69fc4d01`.
- Firmware input closure:
  `e00d4d02522405321c16046f796127306a178d3d82d3d031f72fecde13ea1a39`.

Original extraction is retained under `runs/autonomous-72h-return-20260926/original`;
reanalysis uses a separate evidence copy. The superseding ZIP includes the old
summary, original identity verification, corrected analyzer source and patch,
regressions, independent review method/results, and this reviewed verdict.
Its versioned summary identifies the new analyzer and evidence inventory.
The original archive and summary remain unchanged. The automatic result remains
an operational assessment; this document supplies the narrower reviewed scientific
conclusion.

Validation: **453 tests passed; one pinned RP2040 core-source check was skipped
because those installed sources are unavailable on this Mac**. Native tests and
the corrected offline consumer were exercised; no firmware, serial command,
physical acquisition or operating policy changed, so no new flash or bench run
was performed.

## Remaining decision

Keep the detailed fault mapping conditionally approved. The next useful bounded
investigation is the cause of the clustered reference discontinuities and their
phase-estimator reinitialization cost, using this retained evidence first.
Optional environmental loss remains a known limitation. Independent DAC analog
readback, D9 waveform quality, calibrated absolute accuracy, D10 isolation stress
and unexercised fault cases remain outside this result.


## Follow-up investigation

[Retained-evidence investigation](AUTONOMOUS_REFERENCE_DISCONTINUITIES_20260926.md)
reproduced all 217 losses using the real frozen selector: 216 conservative
recognition-bracket rejections, plus one distinct late-boundary episode.
Ten-second timing-health publication is the leading source of the clustered
polling gaps; retained STS timestamps do not prove its Core1 duration. The finite
result and qualification limits above are unchanged. The next engineering step
is bounded timing-core publication with a collision regression, not wider
reference tolerances or a repeat acquisition for the offline correction.
