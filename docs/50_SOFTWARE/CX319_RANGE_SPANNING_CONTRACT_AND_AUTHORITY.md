# CX319 Range-Spanning Contract and Authority Addendum

## Status

Current addendum for the separately identified CX319 range-spanning
programme. `CURRENT_CONTRACT_AND_POLICY_AUTHORITY.md` and
`00_MASTER_PROGRAMME.md` remain byte-identical because the frozen G0 policy
binds their hashes; their old offline-only language records the authority at
that gate and is not the current lifecycle state.

Current lifecycle state is in `profiles/programme_status_v2.json`. The frozen
range-spanning experimental contract and operator transition are in
`profiles/qualification/cx319_range_spanning_programme_v1.json`. The first live
prefix is reviewed in document 38. The subsequent complete 30-point survey,
offline analyzer supersession and current fine-pass gate are reviewed in
`docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/39_RANGE_SPANNING_PART_A_COMPLETE_SURVEY_RESULT.md`.

## Part A firmware boundary

`cx319_range_map_part_a` is a current supported firmware profile with these
deliberate properties:

- bounded manual `DAC SET` setup stimuli are enabled only inside
  `0xA800..0xAB00`;
- automatic frequency-control authority is compiled out;
- phase and hybrid actuation are compiled out;
- the selected frequency, relative-phase, tight-deadband, and hybrid-preview
  paths continue to run as evidence consumers; and
- all hybrid authority fields remain false.

Every accepted command emits one exact `manual_apply` acknowledgement.
`ManualDacApplication` carries the application from the Core 0 DAC owner to
Core 1 and opens a new Part A DAC epoch. A same-code application also opens a
new epoch: equality of the DAC code does not prove that downstream consumers
observed the new setup transition. The host therefore requires the strictly
newer epoch through the tight-deadband decision and first hybrid-preview
consumer before accepting point evidence.

## Time-domain boundary

Current validators and consumers derive rollover behavior from the declared or
contract-inherited domain. `rp2040_timer0` modular handling is automatic; a
caller cannot enable it with an optional switch. Unknown, absent,
contradictory, backward, cross-session, or ambiguous progression fails closed.
The normative rules are in
[`TIME_DOMAIN_AND_ROLLOVER_CONTRACT.md`](TIME_DOMAIN_AND_ROLLOVER_CONTRACT.md).

## Current authority boundary

The operator authorized exact-bundle flash, serial access, reset, bounded setup
stimuli, rehearsal, Part A mapping, and the Part-A-gated Part B frequency-only
traversal. Further interactive approval is not required once the next exact
bundle satisfies the frozen authority and prerequisites. Phase or hybrid
actuation remains unauthorized.

The earlier `0xA844` state-preserving continuation gate is retired. Its first
attempt exposed a carrier-loss output-service defect and stopped before a new
point. The repaired programme deliberately restarted under a fresh firmware
and run identity and completed all 30 frozen survey points, ending at
`0xA800`, `OUTSIDE`. No later result may splice onto the old `0xA844` visit.

The current gate is an exact fresh-entry, survey-derived one-code fine pass.
Its bundle must freeze monotonic scans around the measured lower and upper
transition regions, an adaptive two-to-six-observation stopping rule, and at
least four fresh selected observations at each candidate boundary. It must
also bind a revised zero-authority hybrid candidate or explicitly retain the
current candidate as a known rejected baseline. The candidate's
`prospective_low_net_excess_path` result must not be reset, waived or hidden
merely to obtain a passing preview.

Part B remains non-executable until the fine pass closes Part A with honest
mixed intervals or tested transition brackets no wider than two codes and a
reviewed matched-direction timing and budget decision. A separate exact Part B
transition is still required.

An ordinary USB carrier absence is a segment-handoff condition, not a present
carrier obstruction. Firmware continues capture, estimation, diagnostics, and
state service while discarding bounded outbound-only records. It abandons any
partially transmitted frame, resets the frame arbiter and the per-carrier
`CONFIG?` provenance emission, and starts the next carrier on a complete
record boundary. This recovery is available only before the two-second
present-carrier obstruction deadline; a transport already latched faulted
remains fail-static until reset. Thus reconnecting cannot erase a genuine
obstruction fault, and a new evidence segment cannot inherit the tail of an
old serial frame or omit its build-provenance sentinel.
