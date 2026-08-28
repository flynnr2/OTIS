# Current Known Limitations

- The supported current instrument includes a continuously draining sole-owner
  host carrier. Indefinite hostless operation, an on-device durable spool, and
  continuity-preserving generalized detach/reattach are not implemented.
- USB TX obstruction is bounded to 2,000 ms of total pending-frame time;
  intermittent byte progress does not extend the bound. The resulting partial
  stream and drained queues invalidate evidence continuity; recovery is reset
  and a new session, not an in-place resume.
- Serial ownership is procedurally checked. OS-enforced exclusivity across all
  supported platform serial stacks remains a Q1 real-I/O experiment.
- Offline hostile-input tests establish bounded loop work and queue failure
  semantics, not a measured physical maximum service interval. That interval
  remains a Q1 measurement.
- The completed GNSS baud-envelope composite qualifies the installed PA1616S
  UART path through 115200 under the exercised OTIS/USB workload. Its 115200
  strata retained 23,100 confirmed-online seconds, zero UART transport/parser
  fault deltas, and peak raw-ring use of 208/1024; ordinary firmware now targets
  115200. This is finite physical evidence for the installed topology, not a
  timeless failure-rate guarantee or qualification of arbitrary receivers,
  wiring, workloads, or firmware service changes.
- The first baud-envelope physical attempt reached and held confirmed 57600,
  then ended at
  `programme_invalid_due_to_platform_or_evidence_failure`. That terminal and
  its run-global failure classification remain immutable. The retained prefix
  can supply only its provenance-bound completed S01 through S05 plus S06
  transition and `ordinary_entry` evidence to a separately frozen composite
  analysis. Three later exact-profile entries retained checksum-valid 57600
  NMEA with zero UART/ring/parser loss while bounded PMTK605 writes completed
  at the RP2040 peripheral without a PMTK705 response. Peripheral completion
  alone does not establish D1 waveform delivery or receiver acceptance, so
  those entries are attachment evidence gaps rather than successful programme
  attachments.
- The PA1616S/MT3339 selected baud persists across an MCU reset or flash while
  the receiver remains powered; only a receiver power cycle restores its 9600
  module default. Continuation attachment therefore cannot assume 9600 after
  MCU reset. It uses the sealed 57600 observation only as a PMTK605/PMTK705
  discovery hint, then falls back through the complete frozen five-rate scan.
  No PMTK251 is permitted before fresh identity at an allowed baud.
- A continuation from logical S06 `peak_status` creates a real capture-session
  and firmware boundary. The final result is necessarily a multi-artifact
  composite: counters may be differenced only within one source artifact, and
  the result cannot claim one continuous 12-hour acquisition. This limits
  continuity claims even if all logical segment durations and classification
  gates are eventually satisfied.
- Q1 real-I/O, Q2 inhibited-actuator, Q3 physical no-write, bounded lower-side
  frequency acquisition, the complete range map and mapping-informed Part B
  have physical evidence. Those results qualify only their exact
  bundles and claims; they do not make future firmware or host changes
  physically qualified.
- The exact stale-uptime attachment event described historically was not
  observed. The source-level causal defect was the absence of a post-attach
  boundary; current authority uses a solicited nonce and generation instead of
  an uptime threshold.
- CX319's lower reacquisition is inferred rather than a third physical Part B
  acquisition. Its original upper traversal is a right-censored bounded
  non-pass; a separate upper completion and host-only finalizer supersession do
  not erase that terminal.
- The last confirmed CX320 state is `FAIL_STATIC` at `0xA836`, DAC epoch 2. A
  flash or reset makes the physical code unknown until a new exact setup
  acknowledgement propagates through all consumers.
- CX320 physically demonstrated one firmware-driven, phase-material combined
  correction, but did not qualify active-hybrid control. The six-code step's
  modeled response (`0.000981445..0.001040041 Hz`) lies below the frozen
  `0.003333332 Hz` empirical response-detection floor. The exact 1,500-second
  observation was therefore healthy but indeterminate and failed the separately
  required positive-sign checkpoint. This bounded non-pass cannot be repaired
  by reinterpreting the same evidence or repeating the consumed bundle.
- CX321 v2 selects a separate 21-code plant-sign qualification transaction
  using a dedicated 1,500-second, three-count estimator before unchanged
  600-second natural hybrid control. Its zero observed null detections over
  18,219 eligible fixed-code placements in both legal exclusion-boundary phases
  are finite-record separation, not a
  calibrated false-positive probability. The estimator and gate are not
  implemented, rehearsed, bundled, physically authorized or qualified on a
  future bundle. They do not make the uncalibrated plant model generally
  control-ready or turn an indeterminate natural material response into
  observed sign.
- The retained Prompt 02 package physically established the compile-time
  D8/GPIN0 to D9/GPOUT0 output/readback identity and a zero-authority D6
  loopback monitor. Its 90 same-reference D8:D6 comparisons differed by zero
  or one cycle within the frozen two-cycle diagnostic tolerance, with healthy
  authoritative D14/D8 capture. It still does not provide a physically
  qualified D9 delivered timing output: no oscilloscope or independently
  referenced frequency counter evidence was retained. With only a multimeter
  and the D6 digital sidecar, voltage levels, duty cycle, rise/fall behavior,
  ringing, propagation delay, jitter, load sensitivity, and independently
  referenced frequency remain unmeasured. A successful D6 count comparison
  cannot close those claims or authorize the 24-hour output soak. The exact D9
  terminal is `output_function_correct_but_waveform_evidence_incomplete`, the
  soak is `frequency_only_d9_output_soak_incomplete`, and unchanged CX322 is
  `cx322_integration_blocked_by_d9_output_gate`.
- The Prompt 03 metadata-hold, phase-degradation, low-efficiency, fail-static,
  and optional-evidence semantics are deterministic non-effective reference
  code with a host-compiled native parity fixture. They are not emitted by a
  live firmware profile or wired into the live parser, supervisor, controller,
  or telemetry schema. No D9/D6/CX322 integrated binary or process-topology
  rehearsal exists, by design, because the valid Prompt 02 D9 gate blocked
  promotion. These semantics grant no DAC, arm, flash, serial, or trial
  authority.
