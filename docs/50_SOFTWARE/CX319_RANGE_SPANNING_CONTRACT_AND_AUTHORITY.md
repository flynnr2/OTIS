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
result is reviewed in
`docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/38_RANGE_SPANNING_PART_A_SURVEY_PREFIX_RESULT.md`.

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
bundle satisfies the frozen authority and prerequisites. This does not remove
these gates:

- continuation of the current hysteretic visit requires an exact no-reset,
  no-flash state-preserving bundle from the last confirmed `0xA844` state;
- Part B requires a complete Part A boundary result and a separate exact
  transition; and
- phase or hybrid actuation remains unauthorized.
