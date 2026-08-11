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

The three records were lost before the host attached and therefore were never
part of an evidence-bearing host interval. The meaningful runtime question is
whether the firmware is healthy when the host attaches and remains healthy
afterwards. Requiring a zero lifetime value would confuse a cumulative startup
diagnostic with post-attachment scientific or control integrity.

## Recovery direction

The replacement path must:

1. attach read-only and treat ordinary `telemetry_dropped` as not yet
   baselined;
2. wait for two consecutive complete health emissions with the same cumulative
   value before permitting setup;
3. record that value and the status sequence at which it was frozen;
4. stop immediately on any subsequent increment;
5. continue to require absolute zero loss/fault state for evidence, capture,
   PPS boundary, preview, partition, critical and control paths; and
6. make the analyzer replay the complete telemetry-drop history against the
   recorded attachment baseline.

Any replacement bundle requires a new exact operator authorization. The
conditional G3 authority remains dormant unless G2 later passes and the fresh
upper-side bundle and rehearsal also pass.
