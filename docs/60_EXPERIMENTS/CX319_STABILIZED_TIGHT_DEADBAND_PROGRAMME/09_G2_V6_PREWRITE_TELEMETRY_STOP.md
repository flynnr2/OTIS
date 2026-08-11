# CX319 G2 v6 Pre-Write Telemetry Stop

## Outcome

The authorized G2 v6 entry at 2026-08-11T16:29:57Z stopped fail-static at
the host pre-write gate. It is not a G2 scientific result and grants no retry
authority.

The retained package is
`runs/cx319_stabilized_tight_deadband/g2/live_leg_a_v6_20260811T162957Z`,
registered as `interrupted_campaign` with content SHA-256
`e30e7f32edff77e05e7ebc867d75edca27f819698b9af194a485ee83ebf2d05c`.

## Proven zero-action boundary

The retained active status and CSVs prove:

- fresh firmware uptime of 11 to 14 seconds;
- no setup transaction, DAC row, active transaction, arm or correction;
- DAC epoch, correction count and cumulative movement all zero;
- partition fault `none`, fail-static `false`, evidence queue high-water zero;
- preview telemetry dropped frames zero; and
- capture and PPS-boundary drop counts zero.

The v6 activation is retired. Programme status now permits offline preparation
only.

## Discriminating diagnosis

The one observed failure was `dual_core.telemetry_dropped=3`. The telemetry
queue reached its 192-record capacity before the host attached after the
operator reset. Firmware source and partition tests establish that ordinary
telemetry publishing is intentionally lossy and increments this counter
without latching a partition fault; boot telemetry, evidence, critical and
control paths have distinct fail-static handling.

This does not make the three lost records acceptable campaign evidence. The
host began ownership after the reset, so human-to-runner latency was inside the
operational path and allowed an avoidable queue overflow. Merely accepting a
non-zero baseline would preserve the counter but would not repair that larger
host/firmware boundary.

## Recovery direction

The replacement path must retain the absolute zero-drop live criterion and:

1. establish one read-only serial owner before the planned board reset;
2. tolerate exactly that pre-live reset and immediately resume drainage;
3. prove a fresh boot, zero telemetry loss and zero-write health while still
   non-authorizing;
4. rotate the same owner into the live G2 segment without an ownerless gap;
5. make any post-promotion disconnect or reconnect fail-static; and
6. exercise this reset, reconnect, promotion, supervisor, analyzer, seal and
   registration path in the replacement operational rehearsal.

Any replacement bundle requires a new exact operator authorization. The
conditional G3 authority remains dormant unless G2 later passes and the fresh
upper-side bundle and rehearsal also pass.
