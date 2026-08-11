# CX319 G2 Pre-Write Platform Stop

Date: 2026-08-11  
Run: `live_leg_a_20260811T154208Z`  
Classification: platform defect at pre-write entry; scientific G2 leg not started

## Result

The authorized G2 v5 runner opened the expected serial device and stopped
fail-static before the setup stimulus, manual-start transaction or control
arm. The retained package is registered in the external evidence index as
`interrupted_campaign` with content identity
`a22a32c7716db791ab7d348abeabe3445a4789667095d78aece2c653c6c6442d`.

The evidence proves:

- `manual_start_sent=false` and `setup_confirmed_utc=null`;
- the DAC-step and active-transaction tables contain headers only;
- `confirmed_applied_code_known=false`, `dac_epoch=0`, correction count zero
  and cumulative movement zero;
- no `DAC SET`, `ACTIVE MANUAL START` or `ACTIVE ARM` command was submitted;
- the last observed static code remained the historical `0xA828`; and
- the priority abort was sent and the physical serial device closed cleanly.

This is not a G2 scientific pass, finite non-pass or controller rejection. It
does not consume the lower-side setup stimulus because no setup write occurred,
but the exact v5 activation is retired and cannot be retried automatically.

## Primary platform fault

The supervisor rejected the pre-write health surface because firmware already
reported the latched partition fault `evidence_queue_exhausted`. The queue's
reported high-water mark was 8, equal to its compiled capacity. The G1
transition drainage physically closed serial at 14:24:44Z with firmware uptime
about 2881 seconds and no partition fault. G2 reopened serial at 15:42:11Z,
4647 seconds later; the first current status reported uptime about 7530 seconds
and the latched fault.

The best-supported causal inference is a cross-surface ownership failure:
firmware intentionally returns zero evidence-transport capacity while USB
serial has no host, the evidence producer continues, and the bounded evidence
queue fails static when it fills. Closing the final G1 drainage segment left
the running firmware without a continuously draining host owner for the full
inter-run interval. This violates the platform invariant requiring continuous
bounded drainage whenever firmware queue health depends on host consumption.

The G2 pre-write predicate correctly prevented the faulted firmware from
reaching any actuation. The missing piece was a bounded inter-run recovery or
continuous-ownership procedure, not a weaker pre-write predicate.

## Secondary host failure

Failure retention wrote the correct root-cause report, but external
registration then rejected the campaign-specific classification
`failed_live_leg`; the evidence-index contract accepts the generic lifecycle
classifications `completed_campaign` and `interrupted_campaign`. This masked
the original error at the command boundary. The package was subsequently
registered without mutation using `interrupted_campaign`.

## Recovery gate

Before another G2 physical entry:

1. map live outcomes onto the existing evidence-index classifications and
   preserve the primary error if registration itself fails;
2. make the accelerated operational rehearsal perform real registrations in
   a temporary external index, including completed and interrupted paths;
3. freeze and pass a new proposal, preflight and operational rehearsal because
   operational host bytes changed;
4. establish a bounded no-write firmware restart and immediate continuously
   drained health check, proving the partition fault is clear before a new
   setup stimulus; and
5. obtain explicit authority for that new exact activation.

G3 remains conditional on a future passing G2 seal and fresh upper-side bundle
and rehearsal. No G4 or phase/hybrid actuation is authorized.
