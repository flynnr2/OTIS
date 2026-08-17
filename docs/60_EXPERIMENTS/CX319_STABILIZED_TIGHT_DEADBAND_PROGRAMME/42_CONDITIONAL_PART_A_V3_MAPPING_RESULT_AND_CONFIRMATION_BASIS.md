# Conditional Part A V3 Mapping Result and Confirmation Basis

## Decision

The V3 physical acquisition is a successful transition map and a valid
scientific result. It is not a failed map. It completed all 27 frozen points,
retained healthy evidence, preserved zero control authority and returned to
`0xA800`. The observed broad mixed regions describe the interaction between
the CX317 plant and the authoritative 600-second integer-count estimator.

The separate frozen Part B promotion record remains `not_promoted`. Its
requirement that every mixed transition interval be no wider than two DAC
codes was explicit before the run. That requirement cannot be replaced after
examining the result and the same evidence then used to grant retrospective
Part B authority. A replay may clarify the scientific meaning of the result;
it may not move the frozen gate.

The methodological correction is to treat transition width as an observed
quantity, not a pass/fail target. The two-code question should have been an
estimand, not the Part B predicate. This correction does not require another
Part A mapping campaign: the sealed acquisition can be replayed against a new
contract derived from manufacturer pull range, direct OTIS gain and variance,
prior direction-paired history, and the unchanged Part B movement envelope.

That prospective replay is now frozen and passes. It establishes eligibility
to create mapping-informed frequency-only Part B proposals under the new V4
programme. It does not rewrite the historical V3 promotion, grant physical
authority, or authorize phase/hybrid actuation. Clean builds, focused checks,
the complete operational-path rehearsal and an effective physical authority
transition remain required before the first flash.

## Exact V3 result

The retained run is
`live_part_a_recovery_2_20260815T154816Z`. It stopped healthy with
`survey_prefix_complete`; all 27 points completed, no parser, reconnect,
rejected-command, reference, queue, capture, partition or authority fault was
recorded, and the final exact applied code was `0xA800` at DAC epoch 27.

The promotion tool reported these directional maps:

| Direction | Definite/mixed sequence | Mixed interval | Width |
|---|---|---:|---:|
| lower outbound | outside, mixed, mixed, mixed, inside, inside | `0xA819..0xA81D` | 4 codes |
| lower return | inside, mixed, mixed, mixed, outside, outside | `0xA81B..0xA81F` | 4 codes |
| upper outbound | inside, inside, inside, mixed, mixed | `0xA84B..0xA84D` | 2 codes |
| upper return | mixed, mixed, mixed, mixed, mixed | `0xA845..0xA84D` | 8 codes |

The midpoint displacement between outbound and return maps was two codes at
the lower transition and three codes at the upper transition. Endpoint
closure, all three `0xA830` references and both 189-code Part B movement-budget
checks passed. The non-promotion arose from the two-code width premise and the
upper guard classifications, not from invalid acquisition or a demonstrated
plant fault.

## Discriminating replay

### Hypothesis and check

The bounded hypothesis was that the mixed classifications might be an early
post-application settling effect or an estimator segmentation error. If true,
a deterministic offline correction could change the interpretation without
another plant experiment. The discriminating check joined, by exact sequence
and DAC epoch:

- `csv/dac_steps.csv`;
- `csv/tight_deadband_decisions_v1.csv`;
- the selected rows in `csv/estimates_v2.csv`; and
- the completed-point record in
  `reports/range_spanning_supervisor_state.json`.

RP2040 timer timestamps were reconstructed with the declared
`rp2040_timer0` rollover semantics. Every selected estimate was a valid
`cx317_selected_600s_nonoverlap_v1` result with a 600-reference non-overlapping
span and true count/reference continuity.

### Result

The first selected boundary observation occurred 2,098.274 to 2,099.753
seconds after its exact DAC application. This is at least 1,198.274 seconds
beyond the frozen 900-second settling exclusion. Thirteen point epochs were
honestly mixed. Twelve remain mixed after discarding the first selected
observation, and the same twelve remain mixed in their final three independent
600-second windows. The only exception is the upper-return turnaround at
`0xA84D`, whose first value was 2 and whose next five values were all 3.

Representative persistent sequences are:

| Direction/point | Counts | Inside/outside sequence |
|---|---|---|
| lower outbound `0xA81D` | `[-2,-3,-2,-3,-2,-3]` | `IOIOIO` |
| lower return `0xA81F` | `[-2,-3,-2,-2,-3,-2]` | `IOIIOI` |
| upper outbound `0xA84D` | `[2,3,2,3,2,3]` | `IOIOIO` |
| upper return `0xA849` | `[2,3,2,3,2,3]` | `IOIOIO` |
| upper return `0xA845` | `[2,2,2,3,2,3]` | `IIIOIO` |

The replay rejects the settling/segmentation hypothesis. It does not prove
that every contribution is intrinsic CX317 noise: integer quantization,
GNSS-referenced measurement variation, aging, airflow, thermal history and
direction/visit history remain combined in these observations. It does show
that the mixed regions are present in valid, late, independent estimator
windows and must be retained as physical-system evidence.

## Manufacturer and prior-evidence expectations

The Connor-Winfield CX317 manufacturer datasheet, revision 02 dated
2025-12-30, specifies:

- 10 MHz nominal frequency;
- positive tuning slope;
- 0.0 to 3.3 V control range with 1.65 V nominal;
- a minimum +/-0.5 ppm and maximum +/-1.0 ppm tuning range;
- maximum 10% tuning linearity error;
- maximum five-minute warm-up at 25 C, defined as frequency after five
  minutes being within +/-100 ppb of the frequency after 60 minutes; and
- maximum 1.0e-11 ADEV at one second under the datasheet conditions.

The tuning range and the AD5693R 2.5 V/65,536-code transfer imply a broad
manufacturer-level expectation of approximately
`0.0001156..0.0002312 Hz/code`. This is a design comparison, not a calibrated
prediction for the assembled OTIS topology.

Direct OTIS history is narrower and more applicable:

| Evidence | Positive gain or variability |
|---|---:|
| Run 020 local gain | `0.0001559..0.0001876 Hz/code` |
| Stage 5 drift-cancelled gain | `0.000163574..0.000173340 Hz/code` |
| CX319 complete survey model | `0.000179672 Hz/code` |
| V3 lower directional midpoint displacement | 2 codes |
| V3 upper directional midpoint displacement | 3 codes |
| prior Stage 5 lower interior direction-paired difference | 7.349 codes equivalent |
| prior Stage 5 upper interior direction-paired difference | 2.450 codes equivalent |

The selected estimator has a 600-second integer-count increment of
`0.001666667 Hz` and a sealed fixed-code standard deviation of
`0.000821677 Hz`. One integer count therefore spans:

- about 7.2 to 14.4 DAC codes across the broad datasheet tuning range;
- about 8.9 to 10.7 codes across the direct Run 020 gain range; and
- 9.276 codes under the CX319 survey model.

A one-code move changes the survey-model 600-second expectation by only 0.108
count; a two-code move changes it by 0.216 count. It was therefore not
scientifically reasonable to make a complete switch from all 2 to all 3
within two codes a success requirement. That width was a useful question for
Part A to answer. The V3 four-to-eight-code mixed regions are consistent with
estimator quantization, the measured positive gain and prior direction/visit
history. They are not, by themselves, an inconsistency.

## Mapping-first interpretation

The next analysis and physical confirmation must keep three outcomes
separate:

1. **Evidence validity.** Exact application, epoch propagation, estimator
   validity, capture/reference health and zero unintended authority are hard
   gates. Failure invalidates the affected evidence.
2. **Transition mapping.** Per-code count distributions, inside/outside
   occupancy, fitted positive response, transition-centre estimates,
   direction displacement, repeat-visit displacement and time/reference
   covariates are reported. Broadness and variance are results, not failures.
3. **Controller readiness.** A separately frozen rule decides whether the
   complete observed transition and repeatability envelope fits the bounded
   Part B direction, step, cadence and cumulative movement budget. A map may
   be scientifically complete while controller readiness remains blocked.

For every visited code and direction, the map should retain and report:

- all chronological 600-second integer errors;
- mean, median, sample spread and inside/outside occupancy;
- exact post-application ages and estimator source spans;
- a model-based latent crossing at mean error -2.5 or +2.5 counts, with its
  finite-run interval and assumptions;
- same-code outbound/return and between-run differences; and
- central-reference and endpoint-closure movement over elapsed time.

No per-code sample should be relabelled merely because a later value differs.
An alternating 2/3 sequence is the measurement distribution at that code.

## Mapping-informed Part B readiness

The new offline contract is
`profiles/qualification/cx319_mapping_informed_part_b_readiness_v1.json`.
It derives its gates without using the V3 width as the target:

- the minimum direct Run 020 gain gives 10.690 codes per integer count, rounded
  outward to an 11-code descriptive mixed-interval envelope;
- the prior Stage 5 maximum direction-paired interior difference of 7.349
  equivalent codes is rounded outward to an eight-code displacement screen;
- the fixed-code estimator standard deviation gives a gross two-sigma sample
  standard-deviation screen of 0.986 count and a four-sigma observed-span
  screen of two counts;
- the manufacturer pull range defines a broad positive shared-slope envelope
  of `0.069358..0.138716 count/code`; and
- the unchanged Part B envelope provides 9 corrections of at most 21 codes and
  at most 189 cumulative codes per leg.

The content-addressed replay result is `ready`:

| Readiness quantity | Replayed result | Frozen envelope |
|---|---:|---:|
| shared within-direction slope | `0.120413 count/code` | `0.069358..0.138716` |
| mixed widths, lower out/return | 4 / 4 codes | <=11 codes |
| mixed widths, upper out/return | 2 / 8 codes | <=11 codes |
| direction displacement, lower/upper | 2 / 3 codes | <=8 codes |
| maximum point sample standard deviation | 0.816497 count | <=0.986013 count |
| maximum point observed span | 2 counts | <=2 counts |
| lower setup to demonstrated inside `0xA830` | 48 codes / 3 max-size steps | <=189 / <=9 |
| upper setup to demonstrated inside `0xA830` | 96 codes / 5 max-size steps | <=189 / <=9 |

All three central references were consistently inside, both endpoint closures
were consistently outside, and the replay retained the historical
`not_promoted` V3 record unchanged. Deterministic regressions also reject a
wrong-sign response and a deliberate high-variance fixture.

No further Part A physical confirmation is required merely to reproduce the
map. The next decision-bearing experiment is the existing three-leg bounded
frequency-only Part B sequence, now under
`CX319_MAPPING_INFORMED_FREQUENCY_TRAVERSAL_V4`. Part B is itself the fresh
repeatability and controller experiment: a bounded non-pass caused by plant
variance or exhausted correction budget remains scientifically useful and
does not invalidate the Part A map.

The V4 programme is non-effective for physical entry. Before any flash, reset,
serial acquisition or DAC write it requires clean exact lower/upper builds,
focused checks, complete operational-path rehearsal, frozen proposals, and a
separate effective authority record.

## Evidence identities

| Item | SHA-256 |
|---|---|
| V3 evidence manifest file | `af4207fb2b237ec8c898950fb03327692733dd58dd0700808d2acb566c653621` |
| V3 evidence snapshot digest | `1ed8ec0ee8dc2952c12c49b960ecb56431c07dbc87f2b828d25937fceb10be47` |
| V3 raw serial | `f4c5db30fd67584b52b101ce0437aa8f890b4fad7da4206eb0f7ea91c7387e38` |
| V3 selected tight-deadband CSV | `271b19962b49fe3f7fed11d9fc060d1b3c339183e1788c791bc6c03db4759dc4` |
| V3 estimates CSV | `7a2e705c009801e970b2ba707a0d924786e347f36edb790dc1c4845217ae8896` |
| V3 DAC applications CSV | `a35986a2a85f293f2a670b1721d31c2270be495b62ce1c02c1ddb45f3a10b0e4` |
| V3 analysis semantic identity | `c66f51d8ade65fa657323460b92c8add306a11292c4bbdd9ae5ca0238764710d` |
| V3 seal semantic identity | `af4356f46242f869f5235e0afbfddc9712ae6a942743ab66379bf9aa29ac86ff` |
| V3 frozen promotion identity | `a3825e55ad8a663afef807290a9859357035b5e732b34b7a7dc522ff06d8aaa3` |
| Mapping-informed readiness contract file | `64b0202388705146f94bb3fe32c6903cb9a927bd20eb7f36f74e8b553370dfb0` |
| Mapping-informed readiness record file | `27ff502a820e0083addfe3643682f288353961051aa6b939a94b68b184457215` |
| Mapping-informed readiness semantic identity | `d1126db85b8792e2e33fbbc9fbe0ed9fe0fdd9e35aeec8c45320c478da704405` |
| Mapping-informed V4 programme file | `588e1fc2cc7adb97af6327631005344b878c90c4c99f214bec4b39a4fdd11e45` |
| CX317 manufacturer datasheet file | `424eb39219937172d9cca58824b883e61e3036d9e6a5b4936d2ccda9ed4a81eb` |
| Selected-estimator profile | `5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c` |
| Current CX317 PPS-gated plant model | `86c7acd3e22d206b1806c0ee2723b4f9051442d9624f7339982122c6caeaa0b2` |
| Stage 5 plant characterization | `4b22830013083d378f1dc0370bc9e970b8b190d6401ab1bbdfdb0c861d4effd7` |

The Stage 5 identity above is the immutable source artifact recorded in the
current plant model. The V3 promotion identity remains authoritative for the
historical V3 Part B decision. The V4 readiness identity is the prerequisite
for new mapping-informed proposals and carries no physical authority by
itself.
