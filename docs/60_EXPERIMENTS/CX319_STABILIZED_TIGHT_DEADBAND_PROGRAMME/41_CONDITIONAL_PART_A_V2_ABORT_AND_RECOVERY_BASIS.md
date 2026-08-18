# Conditional Part A V2 Abort and Recovery Basis

## Result boundary

The first physical execution of the conditional V2 fine map began on
2026-08-15 and stopped fail-closed before completing Part A. The retained run
is `live_part_a_recovery_1_20260815T102400Z`; its evidence content digest is
`631fb6204bd8b91468970959153c0bfeb87cd455c57acabfa50493b82b0c17d9`.
The promotion result was `not_promoted`, so no Part B firmware was flashed and
no automatic correction was authorized.

The acquisition completed these decision-bearing points:

- `0xA800`: outside, selected counts `[-6, -5]`;
- first `0xA830` reference: inside, selected counts `[-1, 0, -1, 0]`;
- outbound `0xA819`: honest mixed code, selected counts
  `[-3, -3, -2, -3, -4, -2]`.

The next code, `0xA81B`, was applied and produced two partial selected counts
`[-3, -3]` before the stop. It was not a completed point and is not reused as
qualification evidence. These observations agree with the survey-derived
linear response and show that `0xA819` must be treated as a transition
candidate rather than an outside guard.

## Stop diagnosis

The runner stopped on the frozen absolute runtime guard
`health_gnss_receiver_raw_pps_control_eligible_'false'`. GNSS serial metadata
remained valid and fresh with a stable receiver identity. D14 raw event
sequences around the stop divided one normal one-second period into intervals
of approximately 747.525 ms, 185 us and 252.289 ms. Firmware consequently
recorded two rejected-short edges and three PPS-interval anomalies. The
priority abort was delivered by the sole serial owner and acquisition was
sealed without transport, parser, reconnect or rejected-command failures.

This is classified as a physical reference-input anomaly correctly caught by
the live fail-closed guard. The V2 plan is not retried: independently of the
physical stop, its lower outbound guard was honestly mixed, so that frozen
promotion contract could not pass.

## Physical intervention and no-write check

The operator inspected and reseated the D14 PPS signal and its ground return.
A subsequent 180-second no-write capture retained 180 D14 rising edges and 179
successive intervals. Every interval was within 0.99..1.01 seconds; the
observed range was 15,999,664..16,000,176 RP2040 timer ticks. The PPS gate was
valid and control-eligible, GNSS identity and metadata were eligible, the
dual-core partition was healthy, and capture recorded zero parser errors,
reconnects, malformed UTF-8 records and rejected commands.

The running image still reported the two pre-intervention rejected-short
events because those lifetime counters are intentionally latched until reset.
The recovery campaign therefore requires a fresh exact firmware flash and a
new prewrite qualification that observes zero rejected-short and interval-
anomaly counters before any DAC write.

## V3 focusing decision

The recovery plan uses the V2 lower result to move the lower transition role
onto `0xA819`, with fresh two-code guards at `0xA817` and `0xA821`. The upper
region has no new physical evidence, so it retains a more defensive two-code
ladder from `0xA845` through `0xA84D`. Both regions are traversed in both
directions with a new DAC epoch at each turnaround. Central references and
endpoint closure remain mandatory. No V2 observation is combined with the new
qualification result.
