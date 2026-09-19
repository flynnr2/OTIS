# Arduino-Pico 6.1.0 baseline migration

Date: 2026-09-19. Target remains Arduino Nano RP2040 Connect at 133 MHz,
`rp2040:rp2040:arduino_nano_connect:freq=133`. This is a core dependency
migration, not a change to D14 reference authority, D8 oscillator authority,
the PIO aperture, or control authorization. D10 capture remains unimplemented.

The current fixed build manifest replaces the 6.0.0 pin with 6.1.0. Historical
images retain their recorded core identity; they are not rebuilt or relabeled.
The installed global 6.1.0 package was already present and was not modified.

## Exact identities

| Item | Identity |
| --- | --- |
| Core archive SHA-256 | `63e69c45285e25ccd8acaf87db16c25ff67d834776bd3ce1b582ecc7782527dc` |
| Installed core tree SHA-256 | `638bc436b7b00a9a4421c9b3c8d60f0aca0b9a31fa152e7c1b87b4ba489c9cdc` |
| Arduino CLI | `1.4.1` |
| Compiler package | `pqt-gcc@5.0.0-9576866` |
| Compiler | `arm-none-eabi-g++@16.1.0` |
| Verified arm64 macOS compiler tree SHA-256 | `cd81889182bd89b30a63c3ddfff14a27098dfae86bd695183211221734e01071` |
| Verified Intel macOS compiler tree SHA-256 | `2f5dd0d916934d55f12f5ca70848b62dcad447a819baab1563e0799c4aee3910` |

The archive was hashed directly from the cached distribution. The installed
core was hashed using `tools.build_firmware.installed_tree_hash`, which is also
the builder's verification algorithm. Board-details metadata independently
matched the version and archive checksum. The compiler pin and per-host hash
allowlist are unchanged. Both approved packages passed environment verification
on the M2 Mac, with the Intel compiler invoked under Rosetta. This is not a
bench-host execution claim.

## Bounded dependency review

The upstream [6.1.0 release notes](https://github.com/earlephilhower/arduino-pico/releases/tag/6.1.0)
identify a GPIO mode-change glitch fix and allocator locking changes. Review
compared the installed 6.1.0 tree against the separately retained, previously
hash-verified 6.0.0 tree. Relevant findings:

- All 10,114 files in `pico-sdk` are byte-identical, with no added or removed
  files. This includes PIO, GPIO, timer, IRQ, DMA, mutex and TinyUSB sources.
  The Nano variant's four files and all 324 Nano `boards.txt` entries are also
  identical. `platform.txt` changes only the reported version/name.
- `wiring_digital.cpp` replaces `gpio_init` in `pinMode` with explicit SIO
  function selection, retaining input direction/pull configuration and output
  drive/direction. This avoids clearing an existing output latch during mode
  changes. OTIS configures D14 as an input before capture; its PIO backend
  explicitly establishes the D14/D8 PIO functions with `pio_gpio_init`.
  Neither the application PIO program nor its count aperture is changed.
- `SerialUSB.cpp`, `USB.cpp` and the TinyUSB FIFO, CDC and device-task sources
  are identical. `CoreMutex.cpp` changes only debug newline formatting. Its
  cross-core blocking behavior remains: `CoreMutex(false)` is not a try-lock.
  OTIS optional diagnostics therefore retain a direct `mutex_try_enter` and
  capacity-admitted single CDC FIFO write under `USB.mutex`. USB task reset
  callbacks use that mutex. This proves local FIFO acceptance, not physical
  delivery after cable loss. No polling or transport wait was added.
- `malloc-lock.cpp` and `lib/core_wrap.txt` move allocation wrappers to newlib's
  reentrant `_malloc_r` family and include `_memalign_r`. `main.cpp` adds
  `exit`/`atexit` wrappers; termination is not a normal instrument path.
  These changes require a fresh link/resource audit even though the compiler
  is unchanged. Diagnostic queues remain fixed-size and allocation-free.
- `SerialUART.cpp` adds a compile-time check requiring paired UART device
  overrides. The Nano board mapping is unchanged. `PIOProgram.cpp` changes
  debug formatting only; it does not alter allocation/PIO semantics.

This review does not assert that a dependency update has zero effect on ISR
service timing, execution cost, or linked image size. Those are separately
observable; hardware-owned D8 aperture semantics do not derive from ISR speed.

## Verification and remaining gate

The standard builder environment check passed using the normal Arduino CLI
and installed 6.1.0 core. The isolated Intel environment at
`/private/tmp/otis-core61-intel/arduino-cli` also passed the same check without
changing global packages; it selects the retained Intel compiler and the exact
6.1.0 core. This temporary wrapper is an offline build aid, not a bench
prerequisite. The bench uses its native Intel Arduino installation and the same
manifest checks. Focused build-contract, USB diagnostic-admission,
hardware-resource ownership and queue-resource inventory tests passed: 27 tests.

The integrated fixed Intel-compiler image passed compilation, binary-contract
verification and the resource audit: 227,952 program bytes, 154,664 static RAM
bytes and 107,480 runtime RAM bytes (2,622 bytes above the required reserve).
Build session: `6100190920260001`; firmware audit revision:
`308fc13` (full revision retained in the build manifest). UF2 SHA-256:
`eceadd16188a9bfce20c7ed83fc82800dbc5f15a2a1300d83631cfc3615bd7ee`.
The bench reproduces this image through the prepared specification; see
[the handoff](BENCH_CORE_6_1_0_HANDOFF.md).
The source comparison and native tests are offline evidence, not physical
timing qualification. Firmware upload and acquisition are not performed by
this migration subtask. Preserve the resulting binary/build manifest and
capture identities when exercising the new image.
