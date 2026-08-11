# Verification and Firmware-Profile Lifecycle

## Status

This document is normative for the platform-stabilization programme. Executable
firmware-profile lifecycle metadata lives beside each profile in
`firmware/arduino/firmware_matrix.json`.

## Lifecycle classifications

- `keep_active`: supported platform or laboratory capability.
- `keep_diagnostic_recovery`: retained for a named diagnostic, recovery,
  characterization, or non-qualification rehearsal.
- `keep_compile_only`: structural expected-fail guard retained at Release.
- `archive_out_of_default_checks`: retained only as programme history or for an
  explicit historical investigation.
- `retire`: no current, diagnostic, safety, or evidentiary purpose; remove after
  the recorded consumer/guard check.

Lifecycle classification is not inferred from a filename, age, or successful
compile. In particular, the suspended CX318 Stage 5 profiles are archived even
though the programme-start baseline proved they still compile.

## Executable verification tiers

### Fast

Focused deterministic tests, native harnesses, contract checks, source topology
guards, and the smallest selected firmware profile. Use during narrow work.

```bash
.venv/bin/python \
  firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
```

### Standard/Campaign

Current capture ownership, bounded command framing, status snapshots,
diagnostics, fault injection, independent abort, owner-preserving handoff,
evidence, and sealing checks. The selected firmware profile is fixed-code and
non-actuating.

```bash
.venv/bin/python \
  firmware/arduino/validation/scripts/run_no_hardware_checks.py \
  --tier standard_campaign
```

### Release

The complete current Python/native suite, current firmware profiles, permanent
structural expected-fail guards, wire fixtures, and example validation/report
path.

```bash
.venv/bin/python \
  firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

The default firmware-matrix command selects this tier:

```bash
.venv/bin/python tools/firmware_matrix.py
```

Every successful firmware build is also gated by
`otis_firmware_resource_budget_v1`: the Nano RP2040 Connect must report no more
than 157,286 bytes of static dynamic-memory use, preserving at least 104,858
bytes for runtime stacks and heap. The observed compiler size report and exact
budget are sealed into `firmware_build_manifest.json`.

### Bench

The exact frozen platform bundle, real capture path, bounded obstruction,
independent abort, owner-preserving evidence rotation, analyzer, and seal. Bench
classification in the matrix identifies profiles eligible for a documented
diagnostic procedure; it does not authorize actuation.

The current executable Bench path is
`host.otis_tools.platform_rehearsal`. It accepts only the exact current
`cx317_fixed_code_baseline` build, rejects compiled actuation or preview
authority, confirms the expected board before and after one flash, and keeps
one capture process as the physical serial owner. During the run it:

1. obtains exact `CONFIG?` and disabled-`DAC?` responses;
2. stops that capture process temporarily and saturates its normal command
   FIFO;
3. enqueues `ACTIVE ABORT` through the distinct priority FIFO and proves it is
   transmitted before stale normal work;
4. confirms the same PID still solely owns the serial device;
5. rotates at a complete device-record boundary into a no-authority drainage
   segment without reopening the port;
6. closes the physical serial device once, analyzes both closure records,
   snapshots and seals the evidence, and registers its content identity in the
   external evidence index.

The exact invocation is recorded in the completion report. A failed attempt is
retained as a failed rehearsal and is never given a `COMPLETE` marker or pass
seal.

### Historical

Archived profiles are excluded from default checks. An explicit historical
matrix can be listed or built with:

```bash
.venv/bin/python tools/firmware_matrix.py --all-profiles --list
.venv/bin/python tools/firmware_matrix.py --all-profiles
```

Running this matrix is a compatibility investigation, not a current support
claim or release requirement.

## Current firmware lifecycle summary

- Active: H1 characterization, explicit operator-controlled H1 laboratory
  actuation, and the two CX319 tight-deadband candidate profiles. Profile
  lifecycle makes CX319 part of current compilation and structural checks; it
  does not grant hardware or live authority.
- Diagnostic/recovery: fixed baseline, open loop, I-only preview, Stage 4
  recovery/preview, accelerated dual-core rehearsal, GNSS smoke/preflight,
  synthetic USB, loopback, IRQ/PPS, FC0, sparse PIO, long gate, divided input,
  and pseudo-PPS.
- Compile-only: current structural authority, resource, GNSS, topology, and
  exact CX319 parameter guards.
- Archived: Phase 4/5 candidates, completed CX317 campaigns, suspended CX318
  Stage 5 profiles, completed endurance profiles, and the exact historical
  Campaign A parameter guard.

## Change rule

Adding a profile requires a lifecycle classification, at least one executable
tier unless it is archived/retired, a named retained value, and a retirement
condition. Moving a profile out of default verification requires confirmation
that current safety, diagnostic, and measurement guards remain covered.
