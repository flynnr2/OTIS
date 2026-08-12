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
- No offline result physically requalifies the integrated firmware, USB path,
  I2C transaction, oscillator, or measurement chain. Q1 real-I/O rehearsal,
  Q2 electrically inhibited/stubbed actuator rehearsal, and Q3 physical
  no-write qualification remain required.
- The exact stale-uptime attachment event described historically was not
  observed. The source-level causal defect was the absence of a post-attach
  boundary; current authority uses a solicited nonce and generation instead of
  an uptime threshold.
