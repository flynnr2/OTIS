# CX319 Stabilized Tight-Deadband Programme

CX319 is the stabilized successor to the suspended CX318 programme.
It preserves the original scientific sequence—bidirectional tight-deadband
validation, combined real-reference observation and non-actuating fault tests,
then final review—while rebuilding every operational surface on the stabilized
OTIS platform.

Current status as of 2026-08-14: the adversarial-review Q1--Q3 sequence and the
Q4/G2 lower-side physical qualification passed. The Q4/G3 upper run was a
non-actionable stable tight hold, not a G3 pass. The operator then authorized
the separately identified range-spanning programme. Its first exact Part A
segment passed with eight points from `0xA800` through `0xA844`, coarsely
bracketing the lower increasing-direction entry by `0xA800..0xA820`. The final
package is sealed and registered. Part A is not complete: the other three
state-dependent transitions, the fine pass, matched bidirectional response,
and cadence acceleration remain open. Part B remains prospectively gated on a
complete Part A result. G4 and phase/hybrid actuation remain unauthorized.

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

The original programme definition is the hash-bound, immutable
[`00_MASTER_PROGRAMME.md`](00_MASTER_PROGRAMME.md). Its pre-execution
"present authority" paragraph is retained for the frozen G0 policy identity;
it is not current execution status. The later range-spanning successor is
governed by document 36, its exact machine-readable programme, document 38,
and `profiles/programme_status_v2.json`.

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

The operator's consumed sequential authority for the adversarial-review Q1,
electrically inhibited or stubbed Q2, and no-write Q3 gates is recorded in
[`16_Q1_Q3_SEQUENCE_AUTHORITY.md`](16_Q1_Q3_SEQUENCE_AUTHORITY.md). Q4 and all
live actuation remain blocked.

The non-authorizing preparation prompt for the next adversarial-review Q4 gate,
which maps to the CX319 G2 lower-side finite frequency-only leg, is
[`17_Q4_LOWER_SIDE_FINITE_LIVE_QUALIFICATION_PREPARATION_PROMPT.md`](17_Q4_LOWER_SIDE_FINITE_LIVE_QUALIFICATION_PREPARATION_PROMPT.md).
It stops after offline verification and an optional non-effective authority
proposal; it grants no hardware or live-control authority.

The passing Q4 offline result, exact candidate identities and Q3-to-Q4
transfer audit are recorded in
[`18_Q4_LOWER_SIDE_OFFLINE_READINESS_REPORT.md`](18_Q4_LOWER_SIDE_OFFLINE_READINESS_REPORT.md).

The proposed finite live envelope is recorded for review in
[`19_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY_DRAFT.md`](19_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY_DRAFT.md).
That draft is not effective and cannot be executed.

The operator's subsequent exact one-run authority is recorded in
[`20_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY.md`](20_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY.md).
It binds the passing candidate and rehearsal, permits no firmware flash or
reset, and is consumed by the first terminal live attempt.

The retained zero-write transport stop, evidence identities, authority
retirement, and narrow recovery gate are recorded in
[`21_Q4_LOWER_SIDE_PREWRITE_TRANSPORT_STOP.md`](21_Q4_LOWER_SIDE_PREWRITE_TRANSPORT_STOP.md).

The fresh repaired-runner candidate, reused Q1--Q3 bindings, passing focused
verification and non-effective restart-plus-retry proposal are recorded in
[`22_Q4_LOWER_SIDE_RETRY_OFFLINE_READINESS.md`](22_Q4_LOWER_SIDE_RETRY_OFFLINE_READINESS.md).

The operator's exact one-restart, one-run retry authority is recorded in
[`23_Q4_LOWER_SIDE_RETRY_LIVE_AUTHORITY.md`](23_Q4_LOWER_SIDE_RETRY_LIVE_AUTHORITY.md).

The zero-effect software restart stop and non-effective manual-button-only
replacement proposal are recorded in
[`24_Q4_LOWER_SIDE_RESTART_PATH_STOP.md`](24_Q4_LOWER_SIDE_RESTART_PATH_STOP.md).

The effective manual-reset-button-only live authority is recorded in
[`25_Q4_LOWER_SIDE_MANUAL_RESTART_LIVE_AUTHORITY.md`](25_Q4_LOWER_SIDE_MANUAL_RESTART_LIVE_AUTHORITY.md).

The retained pre-write result, relaxed diagnostic deadline and firmware entry
decision are recorded in
[`26_Q4_LOWER_SIDE_MANUAL_RESTART_PREWRITE_STOP.md`](26_Q4_LOWER_SIDE_MANUAL_RESTART_PREWRITE_STOP.md).

The operator's one-flash, maximum-120-second, zero-write authority for the
exact current firmware's session-rebinding check is recorded in
[`27_CURRENT_SESSION_REBINDING_FOCUSED_NO_WRITE_AUTHORITY.md`](27_CURRENT_SESSION_REBINDING_FOCUSED_NO_WRITE_AUTHORITY.md).
It deliberately does not repeat Q2, Q3 or unchanged transport/scientific gates
and grants no Q4 live authority. The resulting exact flash, frozen-criterion
non-pass, zero-actuation evidence and excessive snapshot-cadence process escape
are recorded in
[`28_CURRENT_SESSION_REBINDING_FOCUSED_NO_WRITE_NONPASS.md`](28_CURRENT_SESSION_REBINDING_FOCUSED_NO_WRITE_NONPASS.md).

The corrected non-effective no-flash proposal freezes one manual reset, three
snapshots at a minimum five-second cadence and a 30-second deadline in
[`29_CURRENT_SESSION_ABSENCE_NO_FLASH_LOW_CADENCE_PROPOSAL.md`](29_CURRENT_SESSION_ABSENCE_NO_FLASH_LOW_CADENCE_PROPOSAL.md).
Its structural preflight and actual analyzer/seal replay pass, but it requires
a separate operator decision before any physical action. The operator's
effective one-reset, no-flash, three-snapshot authority is recorded in
[`30_CURRENT_SESSION_ABSENCE_NO_FLASH_LOW_CADENCE_AUTHORITY.md`](30_CURRENT_SESSION_ABSENCE_NO_FLASH_LOW_CADENCE_AUTHORITY.md).
It repeats neither Q2/Q3 nor any live actuation.

The first reset occurred after an arbitrary five-minute observer wait expired,
before capture or any command. The zero-I/O platform stop and effective
one-reset recovery authority are recorded in
[`31_CURRENT_SESSION_ABSENCE_OPERATOR_WAIT_TIMEOUT_AND_RETRY_AUTHORITY.md`](31_CURRENT_SESSION_ABSENCE_OPERATOR_WAIT_TIMEOUT_AND_RETRY_AUTHORITY.md).

The operator subsequently made the remaining Q4 phase fully authorized for
unattended execution, including exact flashing and reset recovery, so progress
does not depend on timely replies. The effective scope and unchanged safety,
scientific and evidence boundaries are recorded in
[`32_Q4_UNATTENDED_PHASE_AUTHORITY.md`](32_Q4_UNATTENDED_PHASE_AUTHORITY.md).

The unattended exact-current-image reset/session-absence qualification passed
all frozen checks with stable zero telemetry drops and zero actuation. The
decision and exact registered evidence are recorded in
[`33_CURRENT_SESSION_ABSENCE_EXACT_FLASH_QUALIFICATION_PASS.md`](33_CURRENT_SESSION_ABSENCE_EXACT_FLASH_QUALIFICATION_PASS.md).

The first current-image live entry subsequently exposed a malformed `ASL`
evidence frame before any actuation. The exact root cause, firmware repair,
reproducible image, focused physical requalification and Q2/Q3 reuse decision
are recorded in
[`34_CURRENT_IMAGE_ASL_FORMATTER_STOP_FIX_AND_QUALIFICATION.md`](34_CURRENT_IMAGE_ASL_FORMATTER_STOP_FIX_AND_QUALIFICATION.md).

The successful lower-side physical result, immutable evidence identities,
offline analyzer supersession and exact G3 next gate are recorded in
[`35_Q4_LOWER_SIDE_PHYSICAL_QUALIFICATION_PASS.md`](35_Q4_LOWER_SIDE_PHYSICAL_QUALIFICATION_PASS.md).

The non-authorizing preparation prompt for a fine boundary map, deliberately
excited bidirectional frequency-control trajectory, evidence-based cadence
acceleration, automatic domain-aware rollover semantics, and continuous
zero-authority hybrid preview is
[`36_RANGE_SPANNING_BIDIRECTIONAL_AND_HYBRID_PREVIEW_PREPARATION_PROMPT.md`](36_RANGE_SPANNING_BIDIRECTIONAL_AND_HYBRID_PREVIEW_PREPARATION_PROMPT.md).

The upper-side physical bounded non-pass, immutable evidence identities,
terminal abort-delivery race, deterministic repair and exact next gate are
recorded in
[`37_Q4_UPPER_SIDE_NONACTIONABLE_PHYSICAL_RESULT.md`](37_Q4_UPPER_SIDE_NONACTIONABLE_PHYSICAL_RESULT.md).

The range-spanning implementation, three retained fail-static platform stops,
passing eight-point Part A survey prefix, immutable evidence identities, and
state-preserving continuation gate are recorded in
[`38_RANGE_SPANNING_PART_A_SURVEY_PREFIX_RESULT.md`](38_RANGE_SPANNING_PART_A_SURVEY_PREFIX_RESULT.md).
