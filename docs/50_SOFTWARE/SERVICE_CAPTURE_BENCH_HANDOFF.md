# Service and capture follow-up handoff

This follow-up starts from merged PR #193 (`f76a65e`) and preserves the prepared
6.1.0 hardware/profile. All engineering and verification here are offline on the
development Mac. No serial device was acquired, flashed, reset or actuated.
The original development checkout and its uncommitted work were preserved; the
implementation used an isolated checkout.

## Findings and decisions

| Issue | Finding and delivered change | Remaining physical question |
|---|---|---|
| Recurring output queue delay | Supplied bench evidence aligns a roughly 407 ms synchronous STS block with a 438 ms D14 queue wait. The source confirms unserviced observation drainage during the block and potentially blocking byte-oriented USB calls. A frozen periodic view now emits one complete retained row per arbitration turn through a nonblocking, capacity-admitted USB writer. Later abort input bypasses a retained normal command. | Measure stage-3/4 histogram increments and matched outliers on the actual device. Formatting versus USB cost in the old observation remains unseparated. Other synchronous output paths remain. |
| Startup-only stage-2 delay | The first two count transitions produce 64/71 status rows before first phase entry; phase initialization and execution are outside this interval. That reporting now follows phase entry and precedes the unchanged health/frequency path. Raw CNT/APS order and transition evidence remain. | Compare the same stage-2 endpoints for startup sequences 0/1 and later samples. The reported 7,311/8,184 us are not desktop-measured execution costs. |
| PPS physical capture | The existing PIO copies authoritative X exactly one clock after recognizing D14; recognition can wait for D8. A conditional current-envelope proof gives at most ten clocks from D14 presented to the SM to capture. No assessed small alternative improves this while preserving proved count association and resource limits. Runtime PIO is retained. | Pad/synchronizer behavior and the actual D8 waveform are outside that digital proof. Hardware-to-service timer latency remains unavailable; no extra physical test is requested for this bounded negative finding. |

Detailed rationale: [output service](PERIODIC_STATUS_SERVICE_REPAIR.md),
[startup service](STARTUP_ESTIMATOR_SERVICE_REVIEW.md), and
[current capture assessment](PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md).
D14 is still the sole PPS authority, D8 the count authority, and D10 capture is
unimplemented. The source/package reference for the supplied baseline remains
in the output-service report; the bench package was not locally reanalyzed.

## Exact integrated build

| Item | Identity/result |
|---|---|
| Firmware audit revision | `cd3d23af1dcc9ba5439ce281f6409f7ac03de4f4` |
| Firmware source-set SHA-256 | `e4193cbdcb786854300444ada8b502f7247b9e43d1dece3c4710f2951592e400` |
| Build session | `6100190920260002` |
| UF2 SHA-256 | `87e15703e190dc962652aaa6c5ffa705630e248fe3d66998dbcf894b8141089e` |
| Core / CLI | Arduino-Pico 6.1.0 / Arduino CLI 1.4.1 |
| Compiler | approved Intel `pqt-gcc@5.0.0-9576866`, `arm-none-eabi-g++@16.1.0`, run on the development Mac through Rosetta |
| Target | `rp2040:rp2040:arduino_nano_connect:freq=133` |
| Program storage | 230,672 bytes |
| Static RAM | 156,816 bytes; +2,152 versus the reported baseline |
| Runtime RAM available | 105,328 bytes |
| Fixed static ceiling / minimum runtime reserve | 157,286 / 104,858 bytes; unchanged, 470 bytes headroom |

The new RAM is predominantly the retained queue/receiver/phase/frequency view
and one 384-byte STS row, plus small cursor/pending-state fields. No new PIO,
DMA, GPIO interrupt, heap allocation or relaxed memory reserve is introduced.
The linker's remaining runtime region is not measured free heap or stack margin;
the next observation must retain the existing live reserve evidence.

## Verification completed on the development Mac

- Full current release suite: **747 passed in 118.18 seconds**.
- Final focused production-path status, startup, abort and USB-admission tests:
  **7 passed in 2.72 seconds** after adding required compile declarations.
- Fixed Intel build: exact dependency, source, binary-contract and memory audits
  passed. The first compile exposed two missing function declarations; its log
  is retained with the corrected successful build. No failed image was delivered.
- Exact assembled PIO proof: historical 16 MHz sweep retained; current 10 MHz
  sweep adds 7,936 cases / 55,552 adjacent intervals, all within one count.
  The conditional 4–9-clock dwell proof explores 109 reachable states and
  bounds recognition at nine clocks plus one to copy X. Startup, rollover,
  stopped input and FIFO exhaustion remain covered.
- Python lint and whitespace checks passed for changed implementation tools/tests.

The first release attempt found a pre-existing test that created two independent
inhibited scenarios in the same directory, conflicting with PR #193's restart
guard. The test now uses distinct scenario directories; the production guard,
fixed 300-second deadline and rejection of deadline restart are unchanged.

The deliverable bundle retains the actual build, verification logs, inert
`run_spec.json`, `rehearsal-receipt.json`, sealed obstruction and healthy-closure
packages, no-I/O preflight, registry and `HANDOFF.json`. Rehearsal receipts identify
the exact operational tools. A later documentation-only commit does not change
those tools, firmware inputs or the successful gate.

## Bench prompt

Use the separately delivered bundle and its `HANDOFF.json` checkout revision.
The development Mac owns engineering, bundle creation and rehearsals; the bench
only installs the pinned dependencies if necessary, reproduces the exact image,
then flashes once and runs the frozen observation. Do not substitute a new
specification or image to resolve an identity mismatch.

```sh
python3 -m host.otis_tools compile /path/to/bundle/run_spec.json \
  --output-dir build/bench-service-capture

python3 -m host.otis_tools run /path/to/bundle/run_spec.json \
  --rehearsal /path/to/bundle/rehearsal-receipt.json \
  --rehearsal-package /path/to/bundle/rehearsal \
  --firmware-manifest build/bench-service-capture/artifacts/firmware_build_manifest.json \
  --run-dir runs/bench-service-capture-five-minute \
  --device /dev/cu.usbmodemACTUAL \
  --operator-ref 'operator-authorized service-output five-minute inhibited observation' \
  --reason 'measure output and startup service with zero actuator writes' \
  --flash
```

Keep the controlling Codex turn active. Read `python3 -m host.otis_tools monitor
runs/bench-service-capture-five-minute` every two seconds until the terminal is
retained. Open no additional serial monitor. Expected completion is
`healthy_stop / inhibited_zero_write_complete`, without SETUP, ARM, DAC writes
or completion ABORT. Preserve a diagnostic hold and its sole capture owner for
review; do not extend/restart the clock or invent an automatic retry.

Return the sealed package with compilation/upload identities, canonical
capture/replay result, parser/drop/queue counters, complete status cohorts and
live memory reserves. Compare stage-2 startup samples and stage-3/4 cumulative
histogram increments over the new report cadence. Match channel, capture session,
source sequence and precommit coordinate before subtracting stage 3 from stage 4;
they overlap and must never be added. Unchanged repeated maxima are not new
stalls. Preserve missing diagnostic coverage explicitly. No new actuator or
physical GPIO-marker work is authorized by this handoff.

## Frozen operational-path results

The exact `cd3d23a` operational bundle passed both real-process rehearsals over
a pseudo-terminal. These exercise actual capture/supervisor/closure/analyzer/
sealing/registration code with a deterministic synthetic device, not physical
firmware, USB or actuator propagation.

- Obstruction and independent priority abort: complete capture, terminal
  `aborted / independent_emergency_abort_fifo`, passing `interrupted_incomplete`
  analysis; helper elapsed 5.921294792 seconds. This is a deliberately injected
  rehearsal terminal, not a scientific rejection.
- Normal closure: `healthy_stop / inhibited_zero_write_complete`, complete
  capture and passing `diagnostic_complete` analysis, with no SETUP/ARM/ABORT
  command. The owner observed 13.369941916 seconds; the engineering fixture
  explicitly accelerated the wait after source-origin admission. The frozen
  300-second contract, retained original deadline and production runtime are
  unchanged. This proves closure behavior, not five physical minutes.
- Inert entry validation passed against the relocated firmware and sealed
  rehearsal package. No entry capability was consumed and no hardware I/O ran.

| Retained identity | SHA-256 |
|---|---|
| Run specification | `18749ae3fae01d400c38bab32ab7589ea1c619aba36cf2ef0581a52aeb704bfc` |
| Rehearsal receipt | `9d182da07bec1e124ae1447e4c9a21d835610e42d478068413060d25980df848` |
| Obstruction package seal | `75504bf8b3cb04fef1da32911d70103481365428c51352afac23a0861e4b9f4c` |
| Accelerated healthy package seal | `96a9c50f7dcc0f4ed981d5a959125fec381158933fef768563d31e0249b09565` |

The sealed packages and raw rehearsal records remain outside Git history. A
later offline consumer repair must replay their unchanged evidence rather than
repeat successful acquisition merely to obtain a clean consumer invocation.
