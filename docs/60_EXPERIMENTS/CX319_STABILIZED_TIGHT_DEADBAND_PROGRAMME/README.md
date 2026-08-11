# CX319 Stabilized Tight-Deadband Programme

CX319 is the stabilized successor to the suspended CX318 programme.
It preserves the original scientific sequence—bidirectional tight-deadband
validation, combined real-reference observation and non-actuating fault tests,
then final review—while rebuilding every operational surface on the stabilized
OTIS platform.

G0, the exact physical G1 no-write qualification, and G2 offline readiness
passed on 2026-08-11. Current authority remains offline preparation only. A G1
repeat, DAC write, setup stimulus, control arm, automatic correction, live
promotion, or G2 physical execution is not authorized. The next gate is an
explicit operator decision on the exact G2 Leg A activation.

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
