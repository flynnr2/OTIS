# CX319 Stabilized Tight-Deadband Programme

CX319 is the stabilized successor to the suspended CX318 programme.
It preserves the original scientific sequence—bidirectional tight-deadband
validation, combined real-reference observation and non-actuating fault tests,
then final review—while rebuilding every operational surface on the stabilized
OTIS platform.

G0, the exact physical G1 no-write qualification, and G2 offline readiness
passed on 2026-08-11. The operator then authorized the exact frozen G2 Leg A
live envelope and conditionally authorized G3 if G2 passes and a fresh upper
bundle and rehearsal pass. No G4 or phase/hybrid actuation is authorized.

The v5 G2 physical entry stopped fail-static before any setup or control action
because the firmware had latched an evidence-queue fault during the ownerless
inter-run interval. The v6 entry also stopped before any write: although the
fresh firmware had no partition or evidence fault, host attachment after the
reset allowed three ordinary telemetry records to be dropped. Both activations
are retired. The replacement path now distinguishes a cumulative pre-host
ordinary-telemetry count from post-attachment health: it freezes a stable
read-only attachment baseline and forbids any later increment, while retaining
absolute evidence, capture, partition and control gates. Neither event is a G2
scientific result. The exact v7 replacement passed structural preflight and the
accelerated operational-path rehearsal, then reached its bounded 90-minute
qualification deadline without starting qualification. The GNSS receiver was
already in identity epoch 2 when the host attached, so firmware correctly kept
reference control eligibility false; the host pre-write gate nevertheless
allowed the one exact setup stimulus. No arm or automatic correction occurred.
The failed analysis and registered evidence retire v7 and leave offline
preparation as the only permitted operation. G3 and its conditional
upper-profile flash are blocked because G2 did not pass. The cross-surface
recovery now services GNSS input ahead of the busy serial-output early return
and requires exact epoch-1 GNSS/PPS authority in the host pre-write gate. A
fresh G1 runtime gate now requires that same GNSS/PPS state throughout the
no-write qualification and shares the frozen host-attach telemetry-baseline
semantics already used by G2. The authorized recovery flash succeeded, but the
physical G1 rehearsal exposed a host timing contradiction: an inherited
30-second pre-write deadline could never admit the profile's deliberate
600-second PPS startup inhibit and clean-window qualification. The run stopped
safely with no DAC value write, setup, arm or correction. The single-flash
authority is consumed. Offline recovery now separates the 120-second fresh-host
attachment gate from a bounded 660-second GNSS/PPS qualification deadline and
must pass a complete operational-path rehearsal before proposing a fresh
no-flash G1 requalification. G2 and G3 remain blocked.

The normative programme definition is
[`00_MASTER_PROGRAMME.md`](00_MASTER_PROGRAMME.md).

G0 offline migration passed on 2026-08-11. Its reviewed result and next gate
are recorded in
[`01_G0_OFFLINE_MIGRATION_REPORT.md`](01_G0_OFFLINE_MIGRATION_REPORT.md).

The operator's narrow G1 bench authority is recorded in
[`02_G1_NO_WRITE_BENCH_AUTHORITY.md`](02_G1_NO_WRITE_BENCH_AUTHORITY.md).
Its immutable operational overlay is
`profiles/qualification/cx319_g1_no_write_bench_authority_v1.json`. The
frequency-control policy remains non-authorizing: current execution authority
comes only from the exact programme-status operation and this overlay.

The passing result and the two retained host-verification failures are recorded
in [`03_G1_NO_WRITE_BENCH_REPORT.md`](03_G1_NO_WRITE_BENCH_REPORT.md). The
programme now distinguishes structural preflight, short complete
operational-path rehearsal, and physical qualification; it permits host-only
reanalysis of immutable sufficient evidence without an unnecessary firmware
rerun.

The exact non-authorizing G2 proposal, accelerated operational-path result,
physical runner/analyzer boundary, and live envelope are recorded in
[`04_G2_OFFLINE_READINESS.md`](04_G2_OFFLINE_READINESS.md).

The effective G2 and conditional G3 operator decision is recorded in
[`05_G2_AND_CONDITIONAL_G3_LIVE_AUTHORITY.md`](05_G2_AND_CONDITIONAL_G3_LIVE_AUTHORITY.md).

The retained pre-write stop, causal evidence and recovery gate are recorded in
[`06_G2_PREWRITE_PLATFORM_STOP.md`](06_G2_PREWRITE_PLATFORM_STOP.md).

The fresh non-authorizing v6 package and physical recovery boundary are
recorded in
[`07_G2_RECOVERY_OFFLINE_READINESS.md`](07_G2_RECOVERY_OFFLINE_READINESS.md).

The operator's exact v6 live authority and fresh-restart boundary are recorded
in [`08_G2_V6_LIVE_AUTHORITY.md`](08_G2_V6_LIVE_AUTHORITY.md).

The retained v6 zero-action stop, firmware/host diagnosis and stronger recovery
boundary are recorded in
[`09_G2_V6_PREWRITE_TELEMETRY_STOP.md`](09_G2_V6_PREWRITE_TELEMETRY_STOP.md).

The exact non-authorizing v7 replacement, attachment-baseline contract and
passing offline evidence are recorded in
[`10_G2_V7_ATTACHMENT_BASELINE_OFFLINE_READINESS.md`](10_G2_V7_ATTACHMENT_BASELINE_OFFLINE_READINESS.md).

The operator's exact v7 live authority and physical boundary are recorded in
[`11_G2_V7_LIVE_AUTHORITY.md`](11_G2_V7_LIVE_AUTHORITY.md).

The operator's conditional authority for one exact upper-profile flash and G3
execution after a passing G2 seal is recorded in
[`12_CONDITIONAL_G3_UPPER_FLASH_AND_LIVE_AUTHORITY.md`](12_CONDITIONAL_G3_UPPER_FLASH_AND_LIVE_AUTHORITY.md).

The retained v7 qualification-deadline non-pass, exact evidence identities and
cross-surface GNSS pre-write escape are recorded in
[`13_G2_V7_GNSS_IDENTITY_QUALIFICATION_STOP.md`](13_G2_V7_GNSS_IDENTITY_QUALIFICATION_STOP.md).

The fresh bounded authority for one exact lower-profile flash and physical G1
requalification is recorded in
[`14_G1_RECOVERY_NO_WRITE_AUTHORITY.md`](14_G1_RECOVERY_NO_WRITE_AUTHORITY.md).

The successful exact flash, retained zero-write timing stop and corrected
recovery boundary are recorded in
[`15_G1_RECOVERY_HOST_TIMING_STOP.md`](15_G1_RECOVERY_HOST_TIMING_STOP.md).

The operator's current sequential authority for the adversarial-review Q1,
electrically inhibited or stubbed Q2, and no-write Q3 gates is recorded in
[`16_Q1_Q3_SEQUENCE_AUTHORITY.md`](16_Q1_Q3_SEQUENCE_AUTHORITY.md). Q4 and all
live actuation remain blocked.

The non-authorizing preparation prompt for the next adversarial-review Q4 gate,
which maps to the CX319 G2 lower-side finite frequency-only leg, is
[`17_Q4_LOWER_SIDE_FINITE_LIVE_QUALIFICATION_PREPARATION_PROMPT.md`](17_Q4_LOWER_SIDE_FINITE_LIVE_QUALIFICATION_PREPARATION_PROMPT.md).
It stops after offline verification and an optional non-effective authority
proposal; it grants no hardware or live-control authority.
