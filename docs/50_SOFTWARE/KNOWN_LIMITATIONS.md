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
- OTIS still does not provide a qualified D9/GPOUT0 delivered timing output.
