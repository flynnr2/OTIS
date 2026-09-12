# PPS configuration interleave repair — 2026-09-12

## Retained physical result

The inhibited attempt at source `0c2d8a085102267831528648cde88854db5b4866`
entered a host-verifier hold at `2026-09-12T12:47:02Z`. It was closed by one
explicit operator abort: submission at 14:23:20Z, recorded serial transmission,
firmware `abort_accepted_on_core1`, and capture closure at 14:23:22Z. The bench
reported no remaining processes or serial owner. There were no SETUP/ARM
commands, active transactions or DAC writes. Analysis retained review-required,
undetermined evidence; two elapsed hours did not constitute a pass.

Diagnostic delivery SHA-256:
`9a67320e58bbb7d708ce8fb2e5d76d89dab74ccdd0b5d8da6f992b89f6243a1c`
(696,706 bytes). All 36 manifest entries were independently verified on the
development Mac. Original acquisition-package identity:
`87930a952faddc37282f77238278c2bd7694bcd42d8b0e4f8b57b248fd210f91`.
Original files and verdict remain unchanged.

## Cause and finite replacement

PPS generation 240 spans STS 82426–82541. A core-0 CONFIG response occupies
STS 82458–82504 inside it. PPS `boundary_owner` at STS 82441 was repeated at
82466; `aperture_backend`, `backend_qualified`, and `boundary_ring_capacity`
were also emitted by both owners. The first repeated key latched the strict
host reducer invalid. This is a platform integration escape into a campaign,
not evidence of a physical D14/D8 failure.

Delete the four redundant core-0 PPS emissions. Core 1 already publishes these
fields in its snapshot, and CONFIG already requests timing configuration from
that owner. Keep duplicate rejection, snapshot completeness, identity checks,
authority rules and the frozen two-hour criterion unchanged. No compatibility
reader, duplicate-value exception, extra command lock or host timer is added.

The escaped assumption was that multi-record status groups arrive contiguously.
Serial framing protects each record; it does not make a whole status cohort
atomic across independent emitters. A source-ownership guard and retained
producer-to-consumer regression protect this boundary; the public PTY fixture
now forces CONFIG interleaving inside PPS and ACTIVE groups.

## Verification and next decision

The direct cohort regressions passed (13 tests), followed by all 682 current
tests in 87.68 seconds. The affected pinned firmware build passed at repair
revision `59ad01a`: 222,860 bytes program, 154,140 bytes static RAM and 108,004
bytes remaining RAM. The isolated pinned core/toolchain matched the retained
6.0.0/16.1.0 identities; the default system Arduino installation is different
and was not used for the build. The expanded PTY path passed in the focused and
full suites. Final image reproduction and candidate-bound public rehearsals
remain to be completed after the independent offline findings below are
resolved; this is not a bench-ready or physical qualification claim. The next physical decision remains one inhibited zero-write
attempt; no further physical operation is authorized by this document.

The retained offline report also fails a `control_previews_v1` timestamp
progression check (`previous=0`, `current=3057757369`, ambiguous gap) and emitted
estimate replay. These are separate unresolved findings; the diagnostic lacks
the preview and estimate files needed for exact replay. The full sealed
inventory is 36 files / 71,422,436 bytes before compression. Receive the closed
package and investigate offline before declaring another candidate bench-ready.
Do not infer a hardware cause or weaken the frozen criteria from this report.

Read-only source triage found that `adaptive_hybrid_replay.py` treats every
non-selected estimator version as a failure. The firmware intentionally emits
`accepted_reference_frequency_diagnostic_60s_overlap_v1` as zero-authority
60-span diagnostic EST records alongside the selected 600-span estimator.
All ten selected comparisons in this report pass; the aggregate over 6,223
emitted estimates nevertheless fails. Original EST rows are still needed to
exclude further defects and verify any corrected replay.

The firmware capture-fault preview path supplies literal timestamp `0u` in
`rp2040_monotonic_us32`. That is a concrete candidate explanation for the
reported preview gap, but the preceding preview row is absent from this
supplement and the exact invocation cannot yet be established. Preserve the
original criterion and raw values. The full closed package is requested for
local replay; no hardware operation is needed for this investigation.

## Full acquisition received and offline scope repair

The complete closed-acquisition archive arrived with SHA-256
`a1acca0b41c66d71e49a2aab59146524d555c06e618ef838781232268efdf9c7`
(10,021,570 bytes). All 36 manifest payloads and the original package identity
were verified locally. No acquisition, flash, reset or serial operation was
repeated. The source archive and sealed package remain immutable.

The EST file contains exactly ten selected 600-span estimates and 6,213
60-span diagnostic estimates. The former all matched their APS sources in the
original report; the old host incorrectly made the latter fail selected
estimator replay solely because their estimator identity differed. Scope replay
by the explicit estimator identity, retain diagnostic findings separately, and
prevent diagnostic or unknown estimates from satisfying selected-source joins.
Use a shared ordinal index for bounded source-window reconstruction rather than
scanning every aperture for each overlapping diagnostic estimate.

The CTL file has twelve rows. Rows with control sequence 0 and 2 reference
selected estimates that do not exist; sequence 2 also carries the literal zero
timestamp. The other ten rows match real selected EST identities and timestamps.
This confirms unsupported preview publication, not a timestamp rollover defect.
Remove the three producer emission sites without a successfully published
selected EST (warmup, invalid interval and capture fault). Keep internal engine
evaluation and validity withdrawal, and retain existing PPS/association fault
records. The remaining selected-estimate path emits a truthful CTL source and
coordinate. No generic timestamp exception or historical raw-value repair is
introduced.

The private operational device now emits a diagnostic EST before each selected
EST, preserving their different source windows and eligibility. Native firmware
regression covers absent previews at startup/fault/discontinuity and fresh
selected evidence on recovery. The full archived capture is replayed separately
with the corrected host; its original held/incomplete verdict and invalid CTL
records are retained. This acquisition cannot be promoted to a pass by an
offline repair.

All 691 current tests passed in 89.14 seconds, including native preview
publication and complete host process tests. The corrected external analysis
replayed all ten selected and 6,213 diagnostic estimates exactly, with all 6,223
EST sequence/identity checks passing. Raw D14/D8 and accepted-span replay also
remain exact. The archived preview CSV still fails its original timestamp
criterion, and the retained host hold still prevents a successful acquisition
verdict. The corrected report is separate and linked to the unchanged source
package; no historical row, hold or result was cleared.

The next hardware decision remains one finite inhibited zero-write attempt,
after the final fixed build, independent reproduction and candidate-bound
operational rehearsals. This reviewed software result is not hardware authority.

## Final consumer review

Adversarial review found that per-row CTL validation did not prove its selected
EST reference or publication ordering. The analyzer now checks the reference,
matching timestamp/domain and raw EST-before-CTL order as part of the existing
CSV verdict. EST without CTL remains legal. Selected and diagnostic replay also
check the serialized observation frequency and current provenance namespace;
the AHY source join checks the selected EST's DAC epoch. These are corrections
to evidence consumers, not new runtime owners or campaign stages.

The fixed firmware build and independent reproduction passed with identical
UF2, BIN and generated header, identical provenance and resource results. UF2
SHA-256 is `2b357f0d76a578d7995479527e30bc32806a82b17f8ddabf7fd2991b3a602e19`.
Program storage is 222,916 bytes; static RAM is 154,140 bytes with 108,004 bytes
remaining under the current resource budget.

Final release validation passed: **712 tests in 90.03 seconds**. Both frozen
public operational-path rehearsals passed, including the repeated contingent
transactions, normal-transport obstruction, independent abort delivery, closure,
analysis and sealing. Both default entry receipt consumers passed. The retained
acquisition's final external replay passes all ten selected and 6,213 diagnostic
estimates; the new raw publication join identifies exactly the two original
orphan previews while confirming the other ten. The original CSV timestamp
error and held/incomplete outcome remain visible.

The final changes do not modify the D14 acceptance tolerance, D8 counting, DAC
limits or actuation policy. No physical operation occurred. The next gate is
the already-planned two-hour inhibited zero-write attempt with this exact image
and host toolset. Real device scheduling, USB and physical capture behavior
remain live integration boundaries; these software results do not establish
physical qualification or diagnose an electrical cause for historical anomalies.
