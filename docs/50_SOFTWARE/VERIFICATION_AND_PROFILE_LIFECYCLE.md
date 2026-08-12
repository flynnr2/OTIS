# Verification and Firmware-Profile Lifecycle

## Status

Normative for `CX319_EVIDENCE_EPOCH_1`. Current HEAD has two supported firmware
profiles and five expected-failure guards in
`firmware/arduino/firmware_matrix.json`.

The only lifecycle values are:

- `keep_active`: a supported CX319 build;
- `keep_compile_only`: a current structural expected-failure guard.

Archived profiles are not dormant entries in the current matrix. Reproduce one
by checking out the revision recorded in its manifest, bundle, or reviewed
report. A historical build is not a current release result.

## Offline tiers

All commands below are no-hardware checks.

### Fast

Current unit, contract, source-guard tests and the `cx319_tight_lower` firmware
smoke build:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
```

### Campaign

Current CX319 capture, serial ownership, abort, rotation, transaction,
supervisor, replay, analyzer, evidence, sealing, registration, and accelerated
operational-path tests, plus both supported firmware profiles:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
```

### Release

The complete current Python/native suite and both profiles plus all five
expected-failure guards:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

Release continues to enforce the firmware resource budget, current wire
parity, command and authority boundaries, fail-static paths, and evidence
finalization. It does not compile retired profiles.

### Historical

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier historical
```

This prints reproduction guidance and executes nothing. Use the package's
recorded source revision (or an explicit archival tag if one is later created),
then use that checkout's own commands and matrix. There were no archival tags
at the compatibility reset, so the recorded commit is the authority.

## Bench

Bench work is outside these commands and still requires an exact frozen bundle,
the applicable programme operation in `profiles/programme_status_v2.json`, and
explicit operator authority. This repository reset authorizes no serial access,
flash, arm, or DAC write.

## Change rule

A new current profile requires an explicit retained purpose, verification-tier
membership, exact policy/build provenance, and any required expected-failure
guard. Do not add historical profiles back to the current matrix to reproduce
an old package.
