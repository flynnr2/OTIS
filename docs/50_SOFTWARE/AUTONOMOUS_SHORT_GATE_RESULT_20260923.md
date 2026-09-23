# Autonomous instrument short physical gate — 23 September 2026

The bench Mac completed the frozen short integration gate and reported PASS.
The development Mac independently verified the returned archive identity, all
1,613 listed evidence-file hashes and the four recordings' raw integrity. This
establishes transfer and retained-byte integrity; scientific findings below are
bound to the bench report and its raw records, not inferred from hashes alone.
No extended run was started by this gate.

## Identity and retained evidence

- Handoff source: `b0cc91ba36f4f3383009e388aaddebd1d729b9bf`.
- Firmware audit revision: `82f60eae9cbbfc7f6695cc47e9484f9191c65609`.
- Firmware input SHA-256: `e00d4d02522405321c16046f796127306a178d3d82d3d031f72fecde13ea1a39`.
- Configuration SHA-256: `7b971d9a5c2fa63abd20037be23b94e117d0a73f092644b10b45abb08f407585`.
- UF2 SHA-256: `60e94ea2cf4f43b4b7c0a14287940dbd6f4fd9c84f4d9bece0f965a7990d013d`.
- Returned inner ZIP SHA-256: `c74b29a95ccd11d756f392665a429014dd3ed7eb3b53950fdcbca42ae2cdf28c`.
- Exchange wrapper: `~/Documents/OTIS_DATA/autonomous-integration-20260923-results.zip`.
- Wrapper SHA-256: `5eed6e5fcf5d5d85b1eec9e4354b2032c13c69d340c18cd94ee152763e307798`.
- Inner archive: `autonomous-integration-20260923-result-20260923T164744Z.zip`.
- Canonical report inside it: `return-package/RESULT_REPORT.md`.

The verified development copy is retained locally under
`runs/autonomous-integration-return-20260923/return-package/`. Raw recordings,
transcripts and frozen manifests remain unmodified and untracked. The short-gate
procedure is [retained separately](AUTONOMOUS_BENCH_INTEGRATION.md).

## Results

All four recordings closed on their configured durations, with recorder and
monitor exit zero, no recording error, and verified raw bytes. Recorded durations
were 240, 120, 3,600 and 2,700 seconds. REF/SNP/CNT counts each matched those
segment durations. Deliberate hostless gaps remain gaps.

Late attachment discovered startup AUTO at code 43085, epoch 1 and one application.
HOLD then FIXED 43086 were acknowledged and applied. Reattachment retained the
same boot session, code and epoch. Warm restart created a new boot session and
restored startup code 43085. The second session completed HOLD, FIXED 43085,
CHARACTERIZE 43086 for 30 seconds, then AUTO for 5,400 seconds within the frozen
300-second entry limit.

The characterization application propagated through phase and frequency consumers
and the first dependent selected decision. Metadata hold and fresh causal recovery
were physically exercised without injected faults. A qualified decision requested
one bounded correction, 43086 to 43075, and exact write/application evidence advanced
the DAC to epoch 4. The later response was classified
`healthy_evidence_below_empirical_detection_floor`; this is the classifier's stated
result, not a claim of independently resolved analog response magnitude.

The AUTO deadline was `5636579273`; the HOLD transition was `5636579412` in the
same `rp2040_timer_us64` domain: 139 microseconds later. Final retained status was
OBSERVE_HOLD, code 43075, epoch 4, no fault, no pending write and no incomplete
response. The bench reported no recorder/monitor still active and no serial owner.
Those were endpoint observations, not a promise about subsequent bench state.

## Evidence limits and next decision

Critical, evidence, observation, phase-preview and telemetry drop counters remained
zero. `direct_rows_dropped` reached 28 in the first session and 16 after restart;
these include attached-output loss as well as deliberate no-reader intervals.
Missing direct rows are not reconstructed from unchanged counters or later status.
The attached-loss review below establishes the extended-run evidence boundary;
output loss alone does not grant host abort or control-veto authority.

Startup IAP timestamps were not recorded. IAP establishes successful driver
completion, not an independent analog DAC readback. D9 pin waveforms were not
measured. D10, injected wiring faults, no-write executor rejection, service
starvation, fresh-DAC contradictions, repeated alternation and generic fault
clearing remain unexercised. The failed direct picotool reset attempt was retained
as a no-op; the documented bootloader/reset sequence subsequently completed.

The fault mapping remains conditionally approved. This gate supports preparation
of the authorized 72-hour autonomous observation, with durable local supervision,
a firmware-owned finite HOLD endpoint and automatic evidence packaging. Sustained
qualification, correction/response behavior, recovery and evidence continuity are
extended-run questions; this short result does not establish them.

## Attached-output review

A read-only scan of the retained raw files found seven missing ENV IDs in
`auto-a` (944, 1966, 2988, 4030, 5052, 6074, 7116) and five in `auto-b`
(8166, 9128, 10090, 11052, 12014). Each lies between adjacent SHT4x
`vcocxo_near` rows. From the source's SHT4x-then-BMP280 emission order, these
are inferred missing BMP280 `pressure_reference` rows. Sampled direct-drop
counter deltas match exactly: 2→9 and 11→16. This is a source-order inference
for these recordings, not a guarantee about future missing rows.

Fixed-state reattachment has 12 missing two-row ENV pairs; both sensors are
inferred absent for those cycles. Its last sampled drop counter precedes the
last ENV gap, so 28 must not be presented as an exact end-of-stream loss total.
Within each attached segment, STS, REF, SNP and CNT sequences are continuous;
EST and CTL sequences are also continuous where present. The review does not
bridge the deliberate no-reader gaps or declare all environmental samples known.

At the frozen source revision, `otis_transport_serial.cpp` lines 18–26 define
the two-row direct queue, and lines 41–54 count whole-row rejection when it is
full. `otis_nano_rp2040_connect.ino` lines 1956–2027 publish the internal SHT4x
update before emitting the two ENV rows without two-slot admission. Other row
producers can therefore leave insufficient direct-output capacity for ENV.
The loop's partial-frame return at lines 2552–2557 can also skip sensor sampling
without increasing an ENV sequence or the drop counter. A zero counter is not
proof of complete environmental sampling.

No firmware repair is required solely for the observed optional ENV losses.
The extended-run analyzer must retain and classify sequence gaps, report
unexplained or decision-bearing coverage loss for review, and avoid full
ENV-replay claims. An output gap alone must not select HOLD. Complete
environmental sampling would be a separate requirement, needing explicit
per-source sampling/loss accounting independent of USB admission.

The deterministic review details remain in the preparation bundle under
`verification/direct-output-review/`, including raw hashes, exact gap lists,
adjacent source roles, raw line numbers and counter samples.
