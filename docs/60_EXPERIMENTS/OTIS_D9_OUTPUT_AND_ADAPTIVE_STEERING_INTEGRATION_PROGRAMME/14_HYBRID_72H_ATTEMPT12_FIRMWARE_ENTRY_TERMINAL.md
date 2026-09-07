# Hybrid 72-Hour Attempt 12 Firmware-Entry Terminal

## Verdict

Campaign19 Attempt 12 stopped at firmware entry before acquisition. The exact
board was identified and reset into the RP2040 UF2 bootloader, but the
independent service-launch context was denied access to the mounted bootloader
volume. No UF2 copy completed, no setup or DAC write occurred, no capture
owner or supervisor started, and no D14/D8 qualification aperture was
admitted. This is a platform launch-mechanism escape, not a firmware,
controller, timing-capture, or scientific result.

The retained attempt directory is
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt12`.
It must not be reused. Its firmware-entry record file SHA-256 is
`5d23dd65a55e0735d72e59a06488f77c8ced9d1cf0fb95c4091edeecf3bb9499`;
the orchestration-failure record file SHA-256 is
`fb7036c0548b3c01e1c51ba5a4077e5dcfd8c9c5009cd4b4077f23bb9d1185e8`.

## Entry evidence

At 2026-09-07T11:58:02Z the runner identified Arduino Nano RP2040 Connect
serial `503533748A919118` at `/dev/cu.usbmodem14401`, using activation semantic
SHA-256
`683df2d81ff9fc8293f989acbe40624af0fbaea1f018956e7e16ff452cc805bc`.
The command bound the unchanged Attempt 11 firmware image, UF2 SHA-256
`0d5b17cec8b83fb17ba1763650562b96ea60622b2556c7fb5c50493b7b045ca8`.
The board reset and mounted `/Volumes/RPI-RP2`, but `uf2conv.py` failed while
opening `INFO_UF2.TXT` with `PermissionError: [Errno 1] Operation not
permitted`. The firmware-entry record closed at 2026-09-07T11:58:05Z with
`board_after=null`, `usb_reenumerated=false`, `firmware_flash_count=1` and
`dac_value_write_attempts=0`.

The launcher inferred a keep-alive policy and invoked the runner again after
the terminal, contrary to the intended one-shot process lifecycle. Those
later invocations were rejected by the existing Attempt 12 directory before
firmware entry and performed no second reset, flash, serial open, setup or DAC
write. Both launch services were then removed. No OTIS runner, supervisor,
capture owner or monitor remains. The board remains idle in the UF2 bootloader.

## Gate separation and recovery boundary

- Offline replay and response-attestation reconstruction: passed.
- Fast verification: 389 tests and the fast firmware matrix passed.
- Campaign verification: 647 tests and the campaign firmware matrix passed.
- Structural preflight: passed.
- Accelerated operational-path rehearsal: passed, including unattended
  analysis, sealing, registration and evidence-index verification.
- Firmware entry: failed before UF2 transfer completed.
- Physical acquisition: not started.
- Scientific acceptance: not evaluated.
- Physical finalization, sealing and registration: not applicable because no
  acquisition package or run manifest was created.

Attempt 12's activation permits no automatic retry and its flash limit has
been consumed by the failed entry operation. A further firmware-entry attempt
therefore requires a fresh operator decision and a fresh attempt directory and
activation. Before such a decision, rehearse the detached launcher itself in a
no-I/O process-persistence check. That bounded check subsequently passed with
the installed detached terminal multiplexer: its session remained alive and
read `/Volumes/RPI-RP2/INFO_UF2.TXT` successfully, then was removed. A later
physical entry should use that one-shot launcher, which inherits the
interactive process's removable-volume authority, and must not use the
keep-alive service-launch context that produced this terminal.
