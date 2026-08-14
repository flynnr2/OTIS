# Range-Spanning Part A Survey-Prefix Result

## Outcome

The first finite segment of the CX319 range-spanning Part A survey completed
successfully on 2026-08-14. The exact firmware was flashed once, eight
externally commanded setup points were applied in frozen increasing order, and
each point produced two fresh authoritative 600-second integer-edge-count
decisions from its own DAC epoch. The runner then stopped cleanly before the
wall deadline because less than the predeclared 3000-second margin remained for
another point.

This is a **passing Part A survey prefix**, not completion of Part A or the
programme. It establishes one coarse increasing-direction transition bracket:

| Prior state | Last outside point | First tight-entry point | Current bracket |
|---|---:|---:|---:|
| `OUTSIDE` | `0xA800`, `[-5, -6]` | `0xA820`, `[-2, -2]` | `0xA800..0xA820` |

The bracket is 32 codes wide and therefore does not meet the eventual target
of at most two codes. It is useful survey evidence for the later monotonic fine
pass. Points `0xA820..0xA844` all entered `TIGHT_INSIDE` after requalification
in their new DAC epochs. The last confirmed applied code is `0xA844`.

## Point results

| Point | DAC code | Fresh 600 s edge errors | Terminal state | DAC epoch |
|---:|---:|---:|---|---:|
| 1 | `0xA800` | `[-5, -6]` | `OUTSIDE` | 1 |
| 2 | `0xA820` | `[-2, -2]` | `TIGHT_INSIDE` | 2 |
| 3 | `0xA824` | `[-2, -2]` | `TIGHT_INSIDE` | 3 |
| 4 | `0xA828` | `[-2, -1]` | `TIGHT_INSIDE` | 4 |
| 5 | `0xA82C` | `[-1, -1]` | `TIGHT_INSIDE` | 5 |
| 6 | `0xA830` | `[0, -1]` | `TIGHT_INSIDE` | 6 |
| 7 | `0xA834` | `[0, 0]` | `TIGHT_INSIDE` | 7 |
| 8 | `0xA844` | `[+2, +2]` | `TIGHT_INSIDE` | 8 |

One count here is one D8 edge relative to the nominal count over 600 D14 PPS
intervals. At nominal 10 MHz the denominator is approximately
`600 * 10,000,000 = 6,000,000,000` edges. Thus `+/-2` counts is approximately
`+/-0.003333 Hz`, or `+/-3.33e-10` fractionally, before reference, aperture,
quantization-distribution, and other unavailable uncertainty components.
`TIGHT_INSIDE` is satisfaction of the frozen hysteretic policy; it is not a
claim of traceable accuracy, phase lock, or zero error.

## Authority and zero-actionability result

The operator subsequently superseded the offline-only boundary in
`36_RANGE_SPANNING_BIDIRECTIONAL_AND_HYBRID_PREVIEW_PREPARATION_PROMPT.md` and
authorized exact-bundle flash, serial access, reset, bounded DAC setup writes,
rehearsal, Part A mapping, and the prospectively gated Part B frequency-only
traversal. The frozen machine-readable authority is
`profiles/qualification/cx319_range_spanning_programme_v1.json`.

Part A frequency-control authority was false. Phase and hybrid actuation were
false. The live package contains eight `manual_apply` rows and zero active
transactions. Every hybrid-preview record remained non-actionable and bound to
the same applied code and DAC epoch as its upstream phase and frequency
consumers. Part B remains gated on a complete Part A boundary result and a
separate exact transition. Nothing in this result authorizes phase or hybrid
actuation.

## Exact final bundle and evidence

| Item | Identity |
|---|---|
| Run | `part_a_segment_v4_20260814T030300BST` |
| Terminal UTC | `2026-08-14T08:08:37Z` |
| Terminal | `healthy_stop:finite_wall_deadline_before_next_point` |
| Bundle semantic identity | `de32dcd4befff3f2e86874d942cfd668e73ff13d47588e74909ef951ec022969` |
| Bundle file | `7978aa9e8e855f05ea03870c73f4cb82c9181cc2367b38582254b1dd9429d5b2` |
| Live activation | `39aa751aebad5d2c519abbc4520d5badc9806eca212f6041b5edbb6ce3344e8e` |
| Recorded Git revision/state | `8d06148e58fc4f454a0b9b9dbc6d4ee7b759ccb8`, dirty |
| Firmware source identity | `40c87848b46b7b8e2c4392008d2a6e93166eb3c16050b4a35363c099078a7e0a` |
| Frozen programme file | `fc2e38e1bac1d1ba7c3d4d16da4bc85416e3cf3d419cf270f66bd135a54d198d` |
| Firmware build manifest | `2fefc510708df67a7dd538f12dd2f4bdbb6a665aa8cdddc7ae05b3ddfa14a29d` |
| Firmware UF2 | `fe42354162615ac9719684d06bfb4e1b52d7b62ab340aae12b94fd8264b13af2` |
| Operational rehearsal result | `c291b71a97b0ac087f70d250f49706a63031accebaea354e1f3a9b8408732113` |
| Operational rehearsal seal | `7681b54ac75a9ae4c229cf3dc43452fb0c5320b2644ed558737711f4a18cc52d` |
| Analysis semantic identity | `991a146447ca603fa18321baad309eb728ddcd6965078b92175db6e93db9f3d2` |
| Analysis file | `a4b4031c3b558a25ae5ca03cdfcf110f05b4f215b60d50709da81e1ad430641a` |
| Result seal | `6e5262e778e92385a55ffa72505296995cd4dad7ad5c903cc4fb9a4d09b80715` |
| Evidence manifest file | `478391d77f6e7665c96c372863def2deda36808a3da1f95a754c79828b9d7938` |
| Evidence snapshot digest | `b42b15ec5ea3ea92a2241507ba69f302146d15d469984da4f2e57e283b31ddcc` |
| Registered package | `ebc0b396c42804ceb6aec51b13c8f6fd26328cdd48e16ca21d93ce3771153153` |

The registered package contains 31 files and 146,275,375 bytes. Generic run
validation passed: 21,907 raw events, count observations, PPS snapshots,
relative-phase observations, phase-estimator outputs, and hybrid previews were
retained; all declared contracts validated. Header-only association-loss,
diagnostic, active-transaction, pseudo-PPS, and reference-observation streams
are expected for this profile and are not missing evidence.

The frozen programme file deliberately retains its pre-execution `status`
field so its hash continues to identify the contract actually bundled and
run. Current lifecycle state is recorded separately in
`profiles/programme_status_v2.json`; changing the frozen file in place would
break the evidence binding.

## Platform repairs and verification

Three earlier finite attempts stopped fail-static and remain registered:

| Registered package | Effect before stop | Escape and correction |
|---|---|---|
| `4798dfc1a99954c65b813971e203ab076e9e40fca279cc0058c1e78dcf9d7b65` | zero DAC writes | Startup `metadata_control_eligible=false` was incorrectly treated as a runtime loss; startup qualification is now separated from post-gate loss. |
| `eeaf873c2786148d708042156ff3d2117f4a1f64e24b471c2d7cb616c3824d60` | one `0xA800` setup write | A same-code setup opened a firmware epoch but the host accepted a stale hybrid epoch; propagation now requires the strictly newer epoch through the first hybrid consumer. |
| `286d7b4feced649451a3b433b713b1d0114574f0bbdd3e962bb7e46a68285cb7` | point 1 completed; point 2 timed out | The host used the ideal 2100-second point duration even though full-history alignment can delay the second policy-bearing window to 2700 seconds; the frozen timeout is now 2820 seconds and a new point requires 3000 seconds of wall margin. |

Each stop delivered the independent priority abort and retained immutable
evidence. Focused regressions cover both sides of each escaped handoff and the
first decision-bearing consumer. After the final timing repair, 22 focused
tests and the exact operational rehearsal passed.

Before physical entry, Release verification passed 743 tests with 27 declared
deselections. All three current profiles (`cx319_tight_lower`,
`cx319_tight_upper`, and `cx319_range_map_part_a`) compiled successfully and
all five expected-failure profiles failed for their required reasons.
After result and lifecycle documentation were synchronized, current Release
passed 744 tests with 27 declared deselections; the same three passing profiles
and five verified expected failures completed again.

## Decision and next gate

Observed facts support these bounded conclusions:

- the actual lower increasing-direction entry lies somewhere after `0xA800`
  and no later than `0xA820` for this visit;
- the point-average response then trends nondecreasing through approximately
  zero at `0xA830..0xA834` and reaches `+2` counts at `0xA844`;
- exact same-code and changed-code setup applications propagate coherent new
  DAC epochs through tight-deadband and hybrid-preview consumers; and
- the frozen 2700-second worst-case point-duration bound is physically
  supported by the completed sequence.

The evidence does **not** yet establish the other three state-dependent
transitions, a two-code boundary bracket, repeatable hysteresis, matched
bidirectional response, shorter cadence, Part B viability, or hybrid-preview
acceptance.

The next gate is a state-preserving Part A continuation. Because hysteretic
history matters and the last confirmed code is `0xA844`, the continuation must
not silently flash, reset, or restart at `0xA800`. It must freeze and rehearse
an exact continuation bundle that attaches to the current board, proves the
same firmware/profile identity and applied `0xA844` state, re-establishes fresh
D14/D8 qualification, and continues monotonically at `0xA848` and `0xA84C`
before proceeding through the remaining outbound-and-return survey. If that
state cannot be established, the survey visit must be restarted under a new
identity rather than spliced across an unknown hysteretic history.
