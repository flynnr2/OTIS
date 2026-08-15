# Range-Spanning Part A Complete Survey Result

## Outcome

The frozen 30-point Part A survey completed its full outbound-and-return
trajectory on 2026-08-15. The exact firmware was flashed once, every commanded
code was acknowledged and propagated through the DAC, selected estimator,
tight-deadband policy and hybrid-preview consumer at one coherent new DAC
epoch, and the supervisor stopped healthy with
`survey_prefix_complete`. No safety, reference, capture, serial, queue,
partition, freshness or authority guard fired.

This is a **passing complete survey**, not the final fine boundary map. It
brackets all four requested state-dependent transitions, but the tested
brackets are four codes wide except for the deliberately coarse lower
increasing entry. The programme's target is at most two codes and requires the
separately frozen one-code fine pass with additional boundary observations.
Part B therefore remains blocked.

## Observed transition brackets

| Transition and scan direction | Last retained prior state | First changed state | Tested bracket |
|---|---:|---:|---:|
| lower `OUTSIDE` to `TIGHT_INSIDE`, increasing | `0xA800`, `[-6,-5]`, `OUTSIDE` | `0xA820`, `[-2,-2]`, `TIGHT_INSIDE` | `(0xA800,0xA820]`, coarse |
| `TIGHT_INSIDE` to upper `OUTSIDE`, increasing | `0xA848`, `[2,2]`, `TIGHT_INSIDE` | `0xA84C`, `[3,3]`, `OUTSIDE` | `(0xA848,0xA84C]` |
| upper `OUTSIDE` to `TIGHT_INSIDE`, decreasing | `0xA848`, `[3,2]`, `OUTSIDE` | `0xA844`, `[2,2]`, `TIGHT_INSIDE` | `[0xA844,0xA848)` |
| `TIGHT_INSIDE` to lower `OUTSIDE`, decreasing | `0xA81C`, `[-2,-2]`, `TIGHT_INSIDE` | `0xA818`, `[-3,-3]`, `OUTSIDE` | `[0xA818,0xA81C)` |

The upper transition moved by one four-code survey step between the two legs:
`0xA848` was tight on the outbound leg and remained outside on the return leg.
That is evidence of a leg- or visit-dependent transition at survey resolution;
it is not yet a calibrated or repeatable hysteresis-width claim. The fine pass
must distinguish policy hysteresis, temporal drift and integer-count
quantization rather than assigning a single threshold retrospectively.

The lower increasing bracket remains coarse because the frozen survey jumped
from `0xA800` to `0xA820`. The return leg provides a useful fine-pass design
centre near `0xA818..0xA81C`, but it does not replace the missing increasing-leg
observations.

## Complete point record

| Point | Leg | DAC code | Fresh 600 s edge errors | Terminal state |
|---:|---|---:|---:|---|
| 1 | outbound | `0xA800` | `[-6,-5]` | `OUTSIDE` |
| 2 | outbound | `0xA820` | `[-2,-2]` | `TIGHT_INSIDE` |
| 3 | outbound | `0xA824` | `[-2,-2]` | `TIGHT_INSIDE` |
| 4 | outbound | `0xA828` | `[-1,-1]` | `TIGHT_INSIDE` |
| 5 | outbound | `0xA82C` | `[-1,0]` | `TIGHT_INSIDE` |
| 6 | outbound | `0xA830` | `[0,0]` | `TIGHT_INSIDE` |
| 7 | outbound | `0xA834` | `[0,0]` | `TIGHT_INSIDE` |
| 8 | outbound | `0xA844` | `[1,2]` | `TIGHT_INSIDE` |
| 9 | outbound | `0xA848` | `[2,2]` | `TIGHT_INSIDE` |
| 10 | outbound | `0xA84C` | `[3,3]` | `OUTSIDE` |
| 11 | outbound | `0xA850` | `[3,3]` | `OUTSIDE` |
| 12 | outbound | `0xA854` | `[3,4]` | `OUTSIDE` |
| 13 | outbound | `0xA858` | `[4,4]` | `OUTSIDE` |
| 14 | peak | `0xA890` | `[10,9]` | `OUTSIDE` |
| 15 | return | `0xA858` | `[4,4]` | `OUTSIDE` |
| 16 | return | `0xA854` | `[4,3]` | `OUTSIDE` |
| 17 | return | `0xA850` | `[3,4]` | `OUTSIDE` |
| 18 | return | `0xA84C` | `[4,2]` | `OUTSIDE` |
| 19 | return | `0xA848` | `[3,2]` | `OUTSIDE` |
| 20 | return | `0xA844` | `[2,2]` | `TIGHT_INSIDE` |
| 21 | return | `0xA840` | `[2,1]` | `TIGHT_INSIDE` |
| 22 | return | `0xA820` | `[-2,-2]` | `TIGHT_INSIDE` |
| 23 | return | `0xA81C` | `[-2,-2]` | `TIGHT_INSIDE` |
| 24 | return | `0xA818` | `[-3,-3]` | `OUTSIDE` |
| 25 | return | `0xA814` | `[-3,-4]` | `OUTSIDE` |
| 26 | return | `0xA810` | `[-4,-4]` | `OUTSIDE` |
| 27 | return | `0xA80C` | `[-4,-5]` | `OUTSIDE` |
| 28 | return | `0xA808` | `[-5,-5]` | `OUTSIDE` |
| 29 | return | `0xA804` | `[-4,-5]` | `OUTSIDE` |
| 30 | closure | `0xA800` | `[-5,-5]` | `OUTSIDE` |

The final `0xA800` result differs from the opening pair by only one integer
count and retains the same state. The repeated `0xA820` pair and the repeated
`0xA858` pair match exactly between legs. These observations support run-level
closure and a stable monotonic plant response at survey resolution; they do
not establish calibrated uncertainty or a time-invariant code threshold.

## Hybrid-preview result

All 81,393 hybrid-preview records remained non-actionable with phase/hybrid
actuation false. The selected `p21600_cap1_v2` candidate nevertheless reached
its prospective low-net-path guard at preview sequence 40,519, DAC epoch 15,
on the return visit to `0xA858`. It had modeled 20 corrections and 236 codes of
cumulative path, then proposed `-15` codes. The guard rejected that proposal,
left the shadow code unchanged, and retained `FAULT_PREVIEW` through the rest
of the survey.

This is a valid zero-authority candidate rejection, not a platform or physical
run failure. The current hybrid candidate requires offline revision before it
can provide useful continuous preview in Part B. In particular, the next
proposal must state how externally commanded DAC-epoch reseeds interact with
candidate path, correction and terminal-fault lifetime; it may not erase a
guard merely to make this evidence pass.

## Platform stops and deterministic recovery

The first state-preserving continuation attempt stopped before a new point
because detaching the previous carrier left retained serial output stale. Its
immutable interrupted package is
`11b408518f795c11f9c53ce1ef19d8ca2ce59bd8ea4bde4c0761e5fdbae39a8f`.
Firmware now abandons a partial output frame and continuously services and
drains internal output when no carrier is present; deterministic cross-core
and transport regressions cover the repair. Because the installed image had
changed, the complete survey restarted under a fresh identity rather than
splicing hysteretic state.

The successful physical acquisition then exposed two deterministic offline
consumer defects after capture closed:

1. canonical validation incorrectly equated a rejected limited proposal with
   applied shadow-code movement; and
2. the failure finalizer treated the returned evidence-manifest path as a JSON
   object.

The raw acquisition remained complete and content-addressed. The source
package, failed analysis, failed seal and finalization record remain unchanged.
The validator criterion itself was not weakened: movement equality is still
required for `counterfactual_correction=true`, while a guarded non-correction
may retain a nonzero proposed delta and unchanged shadow code. A separate
host-only product replays the exact source evidence, records both tool
generations and supersedes only the failed offline verdict. No physical rerun
was performed for reanalysis.

## Exact identities

| Item | Identity |
|---|---|
| Run | `part_a_fresh_restart_v1_20260814T113000BST` |
| Terminal UTC | `2026-08-15T09:00:33Z` |
| Terminal | `healthy_stop:survey_prefix_complete` |
| Firmware source | `575da5e878fcb44c3f40cd100cdee483aaf338f481f02978517f88b646605faf` |
| Firmware build manifest | `8beb4e9c6d02b2a28c25b5acd3ca62bb1c19c29f5b495bf3acf55ebc82e09805` |
| Firmware UF2 | `f75c687150d500396d4766b268054e597ec56d4f61048fd12464357888d490f0` |
| Bundle semantic identity | `33242bc591fbc0390fa3d716fc7f8cc7d9b01da57c13573617efe4292b420df2` |
| Bundle file | `e061e1de8c91c0151000e21e6aec36d7b0805b8262c8ccf17fa591593e3f5e05` |
| Rehearsal result | `921fe629584d85d50e8e1f7f29555fcd3dad5c974069b1567b9e07847c957ca1` |
| Rehearsal seal | `e6521497f5125371239e182ac33e75368cd0cf5b6ddce07026c51d7f36d5c320` |
| Source evidence snapshot digest | `b23eed327b87efa9afa6e9bc84d89b971c42c4cec79b2ac4249667a0cdead7e1` |
| Source registered package | `802c37e01129e11a31dae027cfdace263feed3d111809dba0b8c1048ed9f36b6` |
| Original failed analysis | `aaf26c670598131e07fa1938f413ead379ad57124f508a4c226e8a0ba31149be` |
| Reanalysis | `953fbf5246d48ac8d0dae5ac68c76c81f6ed8753da749d8daf1fa750966fde54` |
| Supersession | `54598566746c32486f2af4bd9e4ec957b6ce871b9cf6126c4b26cb6ded029e4b` |
| Superseding seal | `6104ba054ebbb928e5a6921eb65e1a7aecd2a8b031689fdde9f5ab378d518264` |
| Superseding registered product | `528087470b2dc06b0b7599a9ba6dfea4f4e8a00f605979d2e5c5c41e54990a7e` |

The source package contains 81,393 raw D14 events, D8 count observations,
snapshots, relative-phase observations, phase-estimator outputs and hybrid
preview decisions; 60 selected tight-deadband decisions; 30 exact manual DAC
applications; and zero active transactions. Generic run validation passes.

After the offline-consumer repairs, Release verification passed 748 tests with
27 historical tests deliberately deselected. All three supported firmware
profiles passed, and all five expected-failure guards failed for their required
reasons.

## Decision and next gate

The survey is complete and the board finished at `0xA800`, `OUTSIDE`. Part A is
not complete because the one-code fine pass and boundary-adjacent repeated
observations remain outstanding. Part B, the disciplined-output physical
programme, and all phase/hybrid actuation remain blocked.

The next bounded result should combine two offline preparations before another
physical entry:

1. freeze an adaptive one-code Part A fine pass around the measured lower
   region (`0xA814..0xA820`) and upper region (`0xA840..0xA850`), preserving
   monotonic outbound/return state and requiring at least four fresh
   observations at each candidate transition boundary; and
2. revise and replay the zero-authority hybrid candidate's DAC-epoch,
   path-budget and terminal-fault lifetime semantics against this immutable
   survey, retaining the current candidate as a rejected baseline.

Only after the exact fine-pass bundle, affected Release verification and the
complete operational-path rehearsal pass should the authorized finite fine
map touch the bench. Part B becomes executable only after that result closes
Part A with honest mixed intervals or brackets no wider than two codes.
