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
- The last confirmed predecessor state is `TIGHT_INSIDE` at `0xA83C`, DAC epoch
  1. A flash or reset makes the physical code unknown until a new exact setup
  acknowledgement propagates through all consumers.
- Active-hybrid behavior remains physically unqualified. The CX319 hybrid
  corpus is counterfactual and zero-authority; CX320 implementation, replay and
  offline rehearsal do not constitute observed phase steering.
- OTIS still does not provide a qualified D9/GPOUT0 delivered timing output.
