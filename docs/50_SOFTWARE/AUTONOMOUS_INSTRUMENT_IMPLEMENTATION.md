# Autonomous instrument implementation — 23 September 2026

The accepted host-control replacement is implemented in the working tree.
Each firmware start writes `0xA84D` and selects AUTO_DISCIPLINE. Qualified hybrid
steering runs under one firmware owner without a host. Serial-selected HOLD,
FIXED_CODE and finite CHARACTERIZE remain available. A disconnect preserves
mode; a restart selects boot policy. Historical supervised protocols and host
campaign machinery are removed, with no compatibility layer.

## Operational boundary

Core 1 owns qualification, mode, numerical control and the retained pending
write. Core 0 executes an exact request once under a fixed deadline and checks
current driver/receiver/prior-code state. The confirmed application reaches
frequency and phase consumers before dependent control. Ordinary control keeps
the existing range, step, settling and cadence bounds, with no lifetime campaign
application or movement budget. Metadata interruption preserves canonical
measurement and valid phase history, cancels an unmeasurable response explicitly,
and requires fresh causal requalification.

Output queues and serial frames are bounded and independent of actuator
mailboxes. Output loss is counted and cannot stop qualified internal control.
Boot/configuration evidence is paced through complete-row staging. The optional
host records raw segments with hashes and offers status, explicit mode requests,
verification and independent local monitoring. Ending recording leaves firmware
operating. Notification output is local files; no remote notification channel or
chat automation has been configured.

See [host commands](HOST_ARCHITECTURE.md), [wire contract](../../data_contracts/otis_firmware_host_contract_v1.md),
and [current authority](CURRENT_CONTRACT_AND_POLICY_AUTHORITY.md).

## Verification scope

Native tests compile and execute the actual instrument owner, selected controller,
live adapter, parser, cross-core mailboxes and executor admission. They cover
boot, all modes, duplicate/stale commands, late physical outcomes, timed stops,
reference/metadata interruption, pending-write cancellation and repeated
corrections beyond the former campaign budgets. Actual firmware status bytes
are consumed by the real recorder parser, including a boot identity above the
signed 64-bit range. PTY tests exercise the recording/command path, byte retention,
rotation and closure. Independent monitoring tests exercise staleness and delivery
failure. Pinned USB source checks bind DTR and the 1200-baud reset behavior.

These checks do not execute physical I2C writes or establish real concurrent
scheduling, analog response, UART behavior, USB attachment or D9 waveform quality.
No board was opened, reset or flashed during this implementation.

## Initial implementation verification (before main integration)

- Full current suite: **378 passed**, 35.33 seconds, with
  `/tmp/otis-host-test-venv/bin/python -m pytest -q tests`.
- Exact pinned Nano/core 6.1.0 build, generated-contract check, binary identity
  audit and existing resource ceilings: **passed**.
- Flash usage: **173,568 bytes**; static RAM: **150,792 bytes**;
  remaining runtime RAM: **111,352 bytes**. Resource ceilings were not relaxed.
- Pinned `pioasm` instruction proof: **7,936 cases / 55,552 intervals**, with
  the declared continuously drained FIFO model. This is a digital model proof,
  not a physical edge-quality or unconditional capture-completeness claim.
- Current firmware inputs were rehashed after the final build and exactly match
  its manifest. Whitespace checks passed.

The final local artifact directory is
`runs/autonomous-integration-final3/`. It contains `build.log`,
`pytest-release.log`, `pio-proof.log`, and `artifacts/firmware_build_manifest.json`
with the UF2 and generated provenance header. These are ignored local build
artifacts, not a transferred or physically qualified bench bundle.

| Identity | SHA-256 |
| --- | --- |
| Firmware input set | `86cd710c8a23797bb214fcaf110bf6f77b7c2ffabce3376098163db25afec9c0` |
| UF2 | `7fb533b082c6022a46da40dbf9f1bff0c0b839f6ed5a4d396701231ae1953622` |
| Configuration | `7b971d9a5c2fa63abd20037be23b94e117d0a73f092644b10b45abb08f407585` |

Final integration also covers native timer operation beyond the 49-day
millisecond rollover, complete paced configuration delivery through the actual
two-row transport queue, and bounded behavior while USB is stalled. It does not
require a continuously draining host for internal control.

## PR integration verification

The PR integrates `origin/main` through `012fd8b` and retains its deferred
count-boundary reporting and expanded PIO proof. The autonomous transport keeps
one complete-row writer, explicitly flushes short USB packets, and admits
priority HOLD while a normal command is pending. Historical host supervisors
and lease-based runners remain removed.

The final merged full suite passes **394 tests** in 57.92 seconds, using
`/tmp/otis-host-test-venv/bin/python -m pytest -q tests`. The earlier test run
overlapped a test/harness rename; the stable-path full rerun passed.

The exact image binds clean firmware revision
`82f60eae9cbbfc7f6695cc47e9484f9191c65609`. Binary and resource audits passed:
flash **173,888 bytes**, static RAM **150,824 bytes**, remaining RAM
**111,320 bytes**. No resource ceiling was relaxed. Generated-contract checks
and the expanded pinned-assembler PIO proof pass: **7,936 cases / 55,552
intervals at each of 10 and 16 MHz**, plus the declared synchronized-input
4..9-clock dwell model. These remain digital-model claims, not physical pin
or service-latency qualification.

| PR image identity | SHA-256 |
| --- | --- |
| Firmware input set | `e00d4d02522405321c16046f796127306a178d3d82d3d031f72fecde13ea1a39` |
| UF2 | `60e94ea2cf4f43b4b7c0a14287940dbd6f4fd9c84f4d9bece0f965a7990d013d` |

Local build artifacts are in `runs/autonomous-pr-build/`; the expanded proof and
merged-suite logs are in `runs/autonomous-pr-verification/`. Neither directory
is committed or claimed transferred to the bench.

## Remaining decisions and physical gates

The [detailed fault mapping](AUTONOMOUS_INSTRUMENT_FAULT_MAPPING.md) is the
implemented candidate and still requires the operator's reserved review before
long-term adoption. It explicitly distinguishes qualification holds, controller
holds, internal integrity faults, optional evidence faults and output loss.

Next is a separately authorized short integration with the exact image, then
the agreed 72-hour observation; a week remains optional. That gate must exercise
hostless boot, late attachment/disconnection, mode changes and physical
application/consumer propagation. The recorder schedule itself must not become a
steering lease. A required timed stop must be explicitly selected in firmware.
