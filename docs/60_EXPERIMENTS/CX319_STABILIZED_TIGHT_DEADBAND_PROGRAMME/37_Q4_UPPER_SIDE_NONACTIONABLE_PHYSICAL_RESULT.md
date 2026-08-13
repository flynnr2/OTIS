# Q4 Upper-Side Non-Actionable Physical Result

## Outcome

The CX319 Q4/G3 upper-side physical run reached its frozen four-hour qualified
endpoint on 2026-08-13. It did not pass G3 because the exact `0xA848` setup
stimulus never produced an actionable upper-side condition. All 25 selected
600-second estimates were inside the state-retaining range:

| Result | Observed value |
|---|---:|
| Selected estimates | 25 |
| `+1` count | 3 |
| `+2` counts | 20 |
| `+3` counts | 2 |
| Mean | `+1.96` counts |
| Automatic applications | 0 |
| Automatic responses | 0 |
| Final DAC code | `0xA848` |

The tight-deadband controller therefore correctly held throughout. The result
is **stimulus non-actionable with stable tight hold**. It is not a controller
rejection, an upper-direction qualification, or evidence that the previously
characterized local plant response is nonlinear. In conjunction with the
barely actionable lower result, it shows that matched nominal offsets did not
provide adequate margin around the actual crossing and quantized hysteresis
boundaries.

## Exact physical evidence

| Item | Identity |
|---|---|
| Run | `g3_upper_live_20260813T173645Z/live_leg_b` |
| Setup confirmed | `2026-08-13T17:47:13Z` |
| Qualification began | `2026-08-13T18:17:01Z` |
| Terminal | `2026-08-13T22:17:01Z` |
| Terminal reason | `stage5_finite_qualified_endpoint_nonpass` |
| Proposal bundle | `1db8416d1d2577b07c954a9bfb339fa6eda48559ff14d32f4dd540656e919b02` |
| Activation | `78380c29c8987db004a35460bd7b23cd9384556fc03437fe0be3d75f72bf6471` |
| Run manifest file | `139c1df45f8e79ba69e3618342fe683df440f022944d55e6b1fc8cf37265cea8` |
| UF2 | `0fb15bc7b5b4f63d174aabaffcefc27bd096d4cdc76723863b1f712d7628edb4` |
| Raw serial | `b2de3345804fabbf5e497f1277aa558a89c2ce80d5c691cd85eab77431cd73ae` |
| Evidence manifest file | `b656961e0751cc493b52218795ef265983415dc7328ebc6ed9e34722ee7b2ff7` |

The acquisition had zero reconnects, parser errors, malformed UTF-8 records,
command rejections, association-loss decisions, or post-attachment telemetry
drops. Every declared CSV contract passed. Measurement, controller,
tight-deadband and response replay were exact. Controller replay correctly
handled three legitimate `rp2040_timer0` timestamp rollovers.

## Terminal platform escape

The supervisor submitted the required independent `ACTIVE ABORT` when the
finite non-pass endpoint was reached. The runner observed the terminal and
stopped capture concurrently; capture closed before consuming the emergency
FIFO record. Evidence distinguishes the two events:

- supervisor abort submissions: 1;
- capture priority abort sends: 0;
- capture closed physically with the same serial owner and otherwise clean
  counters.

This is a terminal orchestration race after complete scientific acquisition.
It does not change the observed non-actionable stimulus, but it prevents the
overall package from claiming a clean bounded-nonpass terminal. The original
failed seal remains preserved. A provenance-linked superseding analysis keeps
overall status `failed` while separating the scientific and platform results:

| Item | Identity |
|---|---|
| Original seal file | `8abef620eaf83ce30e0f9b699660b0d3b1e281518bf1bd352c81d14facf97a21` |
| Original seal content | `0616db0271ed0cd5e7b1c727994cb0beb882223c3f7f693eda0241620571f310` |
| Superseding seal file | `e363ca240823a9650c5f7641f32019862c5926f7b28e3bc60ba72cbb85c4bb19` |
| Superseding seal content | `9cccf5a9a063a126c4f9807c719afca5d1b0ee90faae7a80c212918b0939975e` |
| Superseding registered package | `df25581561d80f2c69880f04502a386c87f5c6b6febf67dd37c9eeba764b0d9b` |
| Failure class | `terminal_abort_delivery_race_after_scientific_bounded_nonpass` |
| Scientific outcome | `stimulus_nonactionable_stable_tight_hold` |

The runner now keeps capture alive after any aborting terminal until capture
records the priority abort as latched and sent, or records a bounded delivery
failure. Focused regression covers that ordering. No physical rerun is needed
to diagnose or repair this platform defect.

## Next gate

The one-run G3 authority is consumed. Another guessed single-point upper retry
would provide little decision value. The next authorized activity is offline
preparation under
`36_RANGE_SPANNING_BIDIRECTIONAL_AND_HYBRID_PREVIEW_PREPARATION_PROMPT.md`:

1. map all four state-dependent entry and release regions using a monotonic,
   range-spanning trajectory;
2. use endpoints with several counts of prospective margin, derived from all
   retained physical evidence rather than nominal geometric symmetry;
3. let frequency control own each automatic return to the deadband in both
   directions;
4. run the selected hybrid path continuously with zero actuation authority;
5. derive shorter activation, settling and correction timings from matched
   response evidence; and
6. make legal counter and timestamp rollover behavior automatic from each
   declared time-domain contract.

Any new physical execution, firmware flash, DAC movement, control arm, or
hybrid actuation requires a new exact machine-readable bundle and a separate
operator decision.
