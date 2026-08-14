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
  frequency acquisition, and the first eight points of the range-spanning Part
  A survey have physical evidence. Those results qualify only their exact
  bundles and claims; they do not make future firmware or host changes
  physically qualified.
- The exact stale-uptime attachment event described historically was not
  observed. The source-level causal defect was the absence of a post-attach
  boundary; current authority uses a solicited nonce and generation instead of
  an uptime threshold.
- The current range survey has only a 32-code lower increasing-direction entry
  bracket, `0xA800..0xA820`. It has not yet mapped the other three hysteretic
  transitions or produced the required at-most-two-code fine brackets.
- The last confirmed range-survey state is `TIGHT_INSIDE` at `0xA844`.
  Continuing the same hysteretic visit requires a no-reset, no-flash exact
  continuation that re-establishes this state; otherwise the survey must
  restart under a new identity.
- Matched bidirectional plant response, cadence acceleration, Part B automatic
  traversal, and active-hybrid behavior remain unqualified. Hybrid output is
  currently preview-only and non-actionable.
