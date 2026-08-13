# CX319 Q4 Lower-Side Manual-Restart Pre-Write Stop

## Outcome

The manually restarted Q4/G2 entry stopped before setup on 2026-08-13. The
runner retained and registered the primary terminal correctly:

`active live-health snapshot did not complete within 2.000 s: generation=2`.

No setup stimulus, DAC value write, control arm or automatic correction
occurred. This is not a scientific Q4 result.

## Physical restart and evidence

The observer was armed before the operator's one reset-button press. The BSD
device node remained present, but independent kernel records prove that the
Nano USB device was destroyed at `09:30:49.667 +01:00` and re-enumerated at
`09:30:50.159 +01:00`, 492 ms later. The same board serial was then observed.

- Run: `live_leg_a_manual_restart_20260813T083106Z`.
- Activation content identity:
  `73eb4dac26ecf9be89dcd2af67efd330d336e5376e6f4dcfbd593bb79114d15d`.
- Activation file SHA-256:
  `fa4366b659f45f3f42a00f5ea70cd4fc95ba8d39c916886258be71f9a8cd860f`.
- Restart observation SHA-256:
  `349ad8e0a47cf27a5aa1116d4a50307378f33d29acf9cc146ddccbd5f72f201d`.
- Run-manifest SHA-256:
  `5d54612b7468f9fd9e9428a5cabc6c92203dc5a1fc86def066f08eac4f9da0fb`.
- Registered interrupted evidence:
  `38002306a1f6885105502da78ab91fb42063b2def384a2cf9accae98c749e3bb`.
- Raw serial SHA-256:
  `cdc6f50a2f5aafc1ad0da59d9426c131c2fd748363518e703365b26761ffb536`.
- Failure report SHA-256:
  `db90d2bc1da9855637de33646008554df1909cc51fc146216bca9ba6c6046e8e`.

Capture retained 70,450 device bytes, 709 lines, zero reconnects, zero parser
errors and one independently submitted emergency abort. One malformed UTF-8
line was retained explicitly. No control command was issued.

## Mis-sized host deadline

The two-second snapshot-completion bound was copied from the unrelated Q1 USB
pending-frame obstruction horizon. It was neither a Q4 design criterion nor a
safety boundary. A host waiting for an atomic snapshot has no actuator
authority, so the shorter timeout provided no protection and caused avoidable
bench work.

The completion wait now uses the existing 30-second pre-write grace. A complete
atomic snapshot and every existing health predicate remain mandatory before
setup; there is no fallback to partial or old state. A genuinely stuck
generation still stops 90 seconds before the 120-second attachment ceiling.
A focused regression covers a 25-second bounded post-reset serial burst and
the finite 30-second stop.

## Underlying firmware entry result

Although generation 2 was incomplete as an atomic control input, its canonical
rows are valid individual observations. Before the host deadline fired they
already recorded:

- `cx317_active.state=FAULT`;
- `cx317_active.reason=session_change_clears_arming`; and
- `cx317_active.fail_static=true`.

Therefore simply relaxing the host deadline does not make the retained Q3
binary a viable restart entry. The Q4 transfer audit had already identified
this exact limitation. Current firmware source contains the tested pristine
pre-setup session-rebinding behavior, but that newer binary was deliberately
not substituted for the Q3-qualified image.

The next meaningful gate is a fresh lower-profile build followed by the
shortest physical no-write requalification needed to bind that firmware. Only
after it passes should a new Q4 candidate and separate live authority be
considered. Repeating the same Q3 binary would only reproduce a known stop.
