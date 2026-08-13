# CX319 Q4 Lower-Side Pre-Write Transport Stop

## Outcome

The one Q4/G2 lower-side authority reached a terminal pre-write stop on
2026-08-13. Capture opened the expected board path, but received no firmware
records. After 32 bounded identity, DAC-query, lease, and snapshot command
submissions, the next snapshot write timed out. Capture closed, and the active
supervisor stopped on
`capture transport state mismatch: capture_active=False, expected True`.

No setup stimulus, DAC value write, control arm, automatic correction,
firmware flash, or board reset occurred. The current applied DAC code was not
established by this attempt. Q4 therefore has no scientific pass or non-pass
result from this run.

This is classified as a **platform escape into a campaign**. The observed
facts establish a non-responsive serial/firmware evidence path; they do not
establish whether its underlying cause was the board runtime, USB CDC state,
or another part of that path.

## Exact attempt and retained evidence

- Run: `live_leg_a_20260813T074315Z`.
- Activation content identity:
  `fc138d94f9c858b1c54e73364635fc3411fe2726ea16ff357cda5ef667b294fe`.
- Activation file SHA-256:
  `9f436238a598f4860d323126a6cb3b14abf663dffa4bb0844f152dc023e7e8c2`.
- Frozen proposal bundle:
  `f08c9a581ec92271828f9c7c0ff87b5e0d1ce04e6015c92d4100c75f7882bbfe`.
- Run-manifest SHA-256:
  `aa301587e20fe935aed9e0303a53a8234f216ad9dbf20f2b59db1aa7ac5f4c0d`.
- Raw serial record SHA-256:
  `d440ea7343caee184e8de3e789969d5d4f11965caf507bfc60fa745beae8b0a6`.
- Orchestration-failure report SHA-256:
  `ec541d49382907c1f625b4aa9665465a02a670041d26bf81983d2f1228ee6ae8`.
- Registered evidence content identity:
  `ae3cbc42e62b05daa41de6502b2ed27a0a18eeb6bcfc2672f55f6c79c099ab93`.
- Evidence classification: `interrupted_campaign`.

The raw serial record contains host provenance events only. The parsed CSVs
contain headers and zero device observations. Capture recorded zero received
lines, zero parser errors, one reconnect, and a physical serial close.

## Finalization escape and repair

The active supervisor correctly recorded the primary transport terminal. A
secondary independent-abort submission then found that the capture FIFO reader
had already ended. `SystemExit` from that bounded FIFO helper escaped the
runner's best-effort cleanup handler, masking the primary reason and skipping
the ordinary failed-attempt retention path.

The retained run was recovered offline without changing its captured records:
the original finalization journal supplied the execution-tool identity, the
primary terminal was recorded, the failure report was added, and the package
was registered. The runner now treats a missing abort reader as a secondary
cleanup failure and preserves the primary orchestration reason. A focused
regression exercises that exact case.

## Authority retirement and next gate

The authority in `20_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY.md` explicitly states
that a pre-write terminal consumes the one run. It is therefore retired. The
activation cannot be reused, `g2_live_leg` is blocked again, and no reset,
retry, second run, G3, or phase/hybrid actuation is implied.

The smallest useful next gate is:

1. commit the narrow runner repair;
2. exercise the changed abort/retention path in focused tests and a fresh
   accelerated operational-path rehearsal;
3. retain the unchanged Q1--Q3 and firmware evidence rather than repeating it;
4. prepare a new non-effective Q4 candidate bound to the repaired runner; and
5. request separate authority for one board restart and one fresh candidate
   entry, because the 120-second host-attachment gate cannot be established
   from the non-responsive prior runtime.

No new physical operation is authorized by this report.
