# CX319 Current Session-Absence Operator-Wait Timeout and Retry Authority

## Result of the first entry

The first authorized runner armed its reset observer at approximately
2026-08-13 09:16 UTC with USB registry identity `0x100021ed0`. Its arbitrary
five-minute operator-wait timeout expired before the operator pressed reset.
The operator then reported the reset, and the same board serial
`503533748A919118` appeared with registry identity `0x100021f24`.

This is a platform/orchestration stop before acquisition, not a firmware or
scientific result. The retained partial directory is
`session_absence_no_flash_low_cadence_20260813T091617Z`. It contains only:

- the exact no-flash bundle;
- run manifest SHA-256
  `a5bdb18a2d4f77648b819c8112c14a654b0b87ec0cb4ed33b8e861332d3868b4`;
  and
- passing installed-firmware precheck SHA-256
  `7c3c5f74cb147976807451383e82a175d4a9c023f2e4c666a7239d45709efe1f`.

Capture was never launched. Firmware flashes, serial opens, commands, setup
stimuli, DAC writes, control arms and automatic corrections were all zero. The
first authority is consumed by the physical reset even though the acquisition
gate did not begin.

## Effective recovery authority

Before that reset, the physically present operator additionally instructed:

> you are authorized to continue with flashing the board, etc.

The shortest recovery needs no flash because the exact installed UF2 remains
confirmed. This instruction therefore makes one additional no-flash manual
reset and one physical no-write attempt effective, with every scientific and
command boundary unchanged from documents 29 and 30.

The recovery permits exactly one `CONFIG?` and three nonce-bound
`ACTIVE SNAPSHOT` queries at a minimum five-second cadence, with the same
30-second post-attach deadline. Q2/Q3 repetition, setup, DAC writes, control
arming, automatic correction and Q4 live execution remain forbidden.

The reset observer may wait up to two hours for the operator action. This is a
finite unattended-tool liveness bound only; it is not a firmware response-time
criterion and does not alter the 30-second post-attach acquisition deadline or
the frozen pass criterion.
