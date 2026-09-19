# Current Known Limitations

Current HEAD has one fixed `adaptive_hybrid_regulation` image and no historical
programme execution surface. The most important present limitations are:

- the Adafruit sensor/GNSS migration has no physical qualification yet. Its
  library boundary and stricter GNSS acceptance are documented in
  [Adafruit device integration](ADAFRUIT_DEVICE_INTEGRATION.md). Both native Mac
  compiler packages are pinned separately; neither compilation nor emulated bus
  checks establish physical sensor or receiver qualification;
- PR #177's older-Mac startup failure and PR #178's progressing-rehearsal
  cutoff exposed host scaffolding defects. The successor removes duplicated
  lifetime, monitoring and finalization responsibilities; its local verification
  is recorded in the [repair report](../60_EXPERIMENTS/CAUSAL_WAIT_REPAIR_2026_09_11.md).
  Software simulation does not establish actual USB/bootloader permission or
  physical firmware/plant behaviour on the older Mac;
- the September consolidation repairs have native/host regressions but do not
  yet establish physical qualification of metadata-hold history preservation,
  pre-carrier queue ownership, or a changed reference-continuation policy;
- raw snapshot/count replay now checks retained arithmetic and associations;
  it does not prove capture completeness or the analog cause of the reported
  D14 disturbances. Native integration exercises the real 600-accepted-span
  frequency and phase consumers; the process rehearsal uses a synthetic
  instrument and does not qualify the physical PIO/USB path;
- the accepted-reference candidate admits the first trustworthy edge inside
  the frozen inclusive ±1.25 ms window after eight acquisition intervals. It
  cannot distinguish an impostor inside that window from the intended PPS.
  Exclusion preserves raw evidence and does not establish GNSS accuracy;
- the former independent GPIO/DMA association defect is superseded by the
  [single reference owner](SINGLE_REFERENCE_OWNER_REPAIR.md). Its FIFO-service
  coordinate is not a hardware D14 timestamp, and its recognition bracket can
  withdraw qualification under delayed service. The September 13 retained
  [investigation](../60_EXPERIMENTS/REFERENCE_ASSOCIATION_DISCONTINUITY_2026_09_13.md)
  remains historical evidence;
- CPU-observed expiry places control on hold while a paired hardware boundary
  is delayed. It does not prove a physical missing pulse. Source-coordinate
  ambiguity ends model qualification without inventing a missing timestamp;
- the new APS/EST/phase/active wire contracts require a matching firmware and
  host bundle. Current code has no compatibility reader for an earlier wire
  version; historical packages use their recorded revision;
- D10/channel 0 is reserved for external-event evidence, and the host contract
  preserves ingest, storage, replay, and zero-authority isolation, but firmware
  does not yet implement a capture backend that is safely isolated from D14;
- the current 72-hour contingent hybrid programme is not physically qualified;
  the completed inhibited zero-write acquisition established its own bounded
  no-actuation claim only and does not qualify closed-loop control;
- the current-only host implements the genuine process/FIFO/command/
  acknowledgement/obstruction/abort/handoff/analysis/sealing rehearsal, but
  live activation remains fail-closed unless the exact frozen bundle has a
  successful sealed rehearsal and explicit operator authority; the separate
  structural preflight remains non-authorizing;
- D9/D6 evidence establishes digital forwarding/monitor behavior only; it does
  not qualify analog waveform shape, jitter, loading, or independent frequency;
- the supported instrument still requires a continuously drained sole-owner
  host carrier for supervised steering. Internal receiver/DAC metadata service
  now runs before carrier and pending-frame branches, but that does not enable
  autonomous steering or preserve full replay through a transport fault;
- startup census observes current firmware before lease or control admission.
  It admits a proven fresh start. A pending acknowledgement from a previous
  supervisor process cannot reuse its monotonic deadline and remains a review
  hold; automatic restart continuation and arbitrary active-state campaign
  adoption are not implemented. Unowned or incoherent state remains observational;
- runner review-hold publication and supervisor consumption are separate
  recorded facts. If retained storage fails, controller inhibition cannot be
  claimed solely because the runner requested it;
- software-stage observations begin at actual FIFO/service/queue observations.
  No D14 GPIO ISR endpoint remains. Hardware-latch-to-service, electrical-edge
  timing and fractional D8-cycle timing remain unavailable; see
  [service-latency baseline](SERVICE_LATENCY_BASELINE.md);
- a process rehearsal does not establish the older Mac's actual launch-context
  permission to access a USB bootloader volume; that exact context must be
  exercised before a physical campaign; and
- source edits after this reset require a new exact build identity and the
  proportionate rehearsal/physical gate before live use.

The remaining entries preserve limitations of historical evidence. They are
scientific context only and do not imply that their profiles, programme CLIs,
compatibility readers, or authority exist on current HEAD.

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
  module default. Ordinary 115200 firmware handles the two legitimate
  operational starts—reset-default 9600 or retained-operational 115200—by
  sending the same fixed `PMTK251,115200` packet once at 9600 and once at
  115200, waiting 1200 ms after each physical UART drain, then remaining at
  115200. This deterministic transaction does not inspect responses or discover
  the current rate, is never retried after boot, and requires exact ordered
  completion/epoch telemetry before control. The separate baud-
  characterization continuation retains its sealed discovery and PMTK605/
  PMTK705 rules; those experimental rules do not govern ordinary operation.
- The 2026-08-28 D9/D6 frequency-only attempt 5 preserved healthy D14/D8 and
  D9/D6 digital evidence and issued no DAC write, but failed GNSS startup. Its
  implementation changed UART rates and queried identity immediately after
  RP2040 peripheral completion, repeatedly truncating the receiver stream.
  Peripheral completion did not prove receiver parsing/application. That run
  remains an identity/evidence failure; the exact per-rate settle and permanent
  post-bootstrap 115200 contract are a platform correction, not a
  reinterpretation of the failed acquisition. Rates other than 9600 and 115200
  are characterization-only; returning from such a profile to ordinary
  firmware requires that characterization's explicit final transition.
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
  cannot close those claims. The historical Prompt 02 terminals remain
  `output_function_correct_but_waveform_evidence_incomplete`,
  `frequency_only_d9_output_soak_incomplete`, and
  `cx322_integration_blocked_by_d9_output_gate`. Later explicit operator
  authority permits separate 24-hour frequency-only and 72-hour hybrid
  engineering acquisitions without waveform instrumentation. Those runs may
  establish digital continuity and control-performance evidence, but cannot
  revise the historical terminal or qualify the delivered D9 waveform or load.
- The Prompt 03 metadata-hold, phase-degradation, low-efficiency, fail-static,
  and optional-evidence semantics remain deterministic non-effective reference
  code for their original frozen contract. The later engineering long-run
  profiles implement the applicable `GNSS_METADATA_HOLD` transaction semantics
  in the existing live firmware, parser, supervisor, and telemetry path; that
  implementation is bound only by each run's separate effective activation.
  It does not retroactively make the Prompt 03 oracle effective or grant that
  historical contract DAC, arm, flash, serial, or trial authority.
- Campaign19 Attempt 12 retry 1 retained 74,741 supervisor-qualified D14/D8
  apertures and fifteen applications, ending at code 43,076 (`0xA844`), DAC
  epoch 16. A firmware defect treated a timestamp-less ordinary service poll
  during metadata requalification as an identity contradiction, latched a
  terminal transaction fault and then masked it as `GNSS_METADATA_HOLD` in
  status. The frozen host also treated two rejected-window and one
  interval-anomaly lifetime-counter increments as a permanent hold after
  current capture health recovered. Abort submission and one carrier write are
  recorded, but firmware consumption was not confirmed before bounded close.
  The retained prefix remains physical evidence and its active-hybrid
  transaction replay is exact; acquisition and offline finalization failed,
  and corrected replay or segmented accepted-aperture accounting cannot supply
  the missing endpoint, terminal acknowledgement or scientific acceptance
  within the original single-session claim. A distinct composite recovery
  contract may bind the validated prefix and a corrected-firmware continuation
  while declaring the firmware/session boundary and excluded gap.
- Prompt 04 verified the complete current Release matrix, three exact separated
  build manifests, the unchanged CX322 policy, the non-effective Prompt 03
  contract, and the retained sealed D9/D6 PTY operational path. It deliberately
  did not create a combined D9/D6/CX322 binary, live Prompt 03 telemetry path,
  integrated rehearsal, or 72-hour proposal. A later one-application,
  21-code, 7,200-second smoke profile combined unchanged CX322 with fixed D9
  forwarding and D6 diagnostics. Still later explicit operator authority
  created distinct 24-hour frequency-only and 72-hour unchanged-CX322
  engineering programmes with cadence-derived sustained-authority ceilings.
  Their exact activations and complete operational-path rehearsals are required
  before bench entry. Neither can be promoted into a waveform, qualified-load,
  jitter, independently referenced frequency, or public delivered-output
  claim.

## Single-owner FIFO capture candidate

The DMA/GPIO association path is replaced by one bounded PIO FIFO owner.
SNP v2 preserves CPU service time and a conservative PIO-recognition bracket;
it does not provide a hardware-latched MCU-domain D14 timestamp or measured
capture-to-service latency. Qualification requires the whole bracket to satisfy
the unchanged tolerance. Delayed foreground empty sampling can therefore
withdraw qualification even when the count is preserved. The unchanged PIO
program observes D14 at D8-dependent checkpoints, so electrical D14 timing
under stopped/slow D8 remains unmeasured. Native tests and host rehearsal do
not establish physical interrupt timing. See SINGLE_REFERENCE_OWNER_REPAIR.md.

The current 10 MHz [capture assessment](PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md)
adds a conditional ten-PIO-clock bound from D14 high presented to the SM to its
count snapshot, assuming 4–9-clock synchronized D8 dwells and no FIFO stall.
This does not bound the electrical input path, characterize metastability or
confirm the actual bench duty/edge quality. No per-event hardware clock
coordinate or hardware-to-service latency becomes available.

The periodic Core 0 report now uses one frozen view and bounded per-row USB
admission; other existing synchronous output paths are unchanged. Desktop
regressions establish framing, ordering, independent abort scanning and fixed
obstruction deadlines, not a target worst-case service-time guarantee. The
combined image leaves 470 bytes below the unchanged static RAM ceiling; live
heap/stack reserves remain required physical evidence. See
[the prepared service/capture handoff](SERVICE_CAPTURE_BENCH_HANDOFF.md).
