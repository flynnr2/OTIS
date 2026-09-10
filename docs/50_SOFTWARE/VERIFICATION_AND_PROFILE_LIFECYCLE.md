# Verification and Fixed-Firmware Lifecycle

## Current build contract

Current HEAD has one buildable fixed firmware image, `adaptive_hybrid_regulation`,
defined by `firmware/arduino/firmware_build_manifest.json` and built by
`tools/build_firmware.py`.

There is no firmware profile matrix, lifecycle registry, expected-failure
profile collection, or historical compatibility tier. Policy, model, and
estimator JSON files describe current semantics; they do not select alternate
firmware programmes.

Historical reproduction requires the revision recorded by the evidence
package or reviewed report. That checkout's source and instructions are the
authority for the historical result.

## No-hardware tiers

### Fast

Runs the architectural guards, current controller and transaction contracts,
GNSS hold/requalification checks, D14/D8 authority and D9/D6/D10 isolation
checks, native parity, and the fixed firmware build:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
```

### Campaign

Adds current serial, capture, abort, evidence, entry-point, and package-boundary
checks, including the deliberate activation fail-closed boundary, then builds
and audits the same fixed image:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
```

### Release

Runs every retained current test and the same fixed build/binary/resource audit:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

Use `--list` to inspect the commands without executing them.

## Structural guards

Current verification fails when:

- the generated firmware projection of the current firmware/host contract is
  stale, or its runtime ID/digest differs from host admission;
- a current record tag, schema version, ordered layout, ACTIVE status
  generation, command grammar, queue frontier or declared cross-field relation
  differs across firmware and host;
- a documented raw-only boot diagnostic or bounded late-attach suffix is
  misclassified as a canonical record or unknown-tag discrepancy;
- a retired CX318-CX323 identity appears in executable code, configuration, a
  filename, schema, profile, or test;
- CX317 is used as a software/campaign identity rather than the physical
  oscillator component;
- a second firmware image, profile selector, historical tier, or retired
  backend appears;
- a current host module is unreachable, imports a missing internal module, or
  creates an orchestration cycle;
- `EVT` and `REF` records do not match D10/channel 0 and D14/channel 1;
- D10 or D6 evidence enters D14/D8 validity, regulation eligibility, actuation,
  or terminal decisions; or
- fixed-image identity, provenance, required binary markers, or resource
  budgets differ.

## Bench boundary

These tiers touch no hardware and do not establish bench readiness. Current
activation remains deliberately fail-closed unless it binds a passing,
registered result from the genuine process-level operational-path rehearsal.
Bench work requires explicit operator authority, one immutable campaign bundle,
a rehearsal of that exact bundle, exact firmware identity, singular serial
ownership, and independent bounded abort delivery.
