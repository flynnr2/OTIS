# OTIS

OTIS is an open, provenance-preserving timing instrument for deterministic,
reference-centric measurement and replayable analysis. Hardware capture is
timing truth; host services preserve, validate, replay, and analyze evidence.

The design principles are in
[`docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md`](docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md).

## Current operating surface

Current code builds one `adaptive_hybrid_regulation` image,
`OTIS_AUTONOMOUS_INSTRUMENT_V2`. Firmware starts in autonomous hybrid discipline,
writes `0xA84D`, qualifies D14/GNSS and steers D8 through the DAC without a host.
Explicit serial commands also select observation/hold, fixed-code or finite
characterization modes. Ordinary operation has no campaign correction budgets,
leases or host acknowledgements.

This is an implementation candidate awaiting physical integration. The detailed
[fault mapping](docs/50_SOFTWARE/AUTONOMOUS_INSTRUMENT_FAULT_MAPPING.md) remains
subject to operator review before long-term adoption.

The invariant bench topology is:

- D14 is the sole authoritative PPS/reference input;
- D8 is the sole oscillator/count input used for regulation;
- D10 / channel 0 is reserved for optional external-event evidence and has no
  validity, setup, control, actuation, or terminal authority;
- D9 forwards the oscillator clock; and
- D6 is a fail-local diagnostic monitor.

D10's pin, channel, host ingest, storage, and replay contract are preserved,
but the fixed firmware does not yet claim a safely isolated D10 capture backend.
The build manifest records that limitation explicitly.

GNSS serial metadata qualifies the receiver that supplies D14 PPS. A
recoverable metadata anomaly holds correction at the last confirmed DAC code
while D14/D8 acquisition and canonical evidence continue.

Historical experiments and reviewed conclusions remain under
`docs/60_EXPERIMENTS/`, local evidence remains under ignored `runs/`, and the
recorded Git revision is the compatibility mechanism. Current HEAD does not
build, load, rehearse, or validate retired campaign programmes.

## Fixed firmware build

The pinned build contract is
[`firmware/arduino/firmware_build_manifest.json`](firmware/arduino/firmware_build_manifest.json).
Build it with:

```bash
.venv/bin/python tools/build_firmware.py
```

The builder verifies the pinned board, core, toolchain, source provenance,
binary identity, required markers, firmware/host contract binding, and memory
budget. Artifacts are written to ignored local build storage. The current wire
authority is
[`data_contracts/otis_firmware_host_contract_v1.json`](data_contracts/otis_firmware_host_contract_v1.json);
its checked-in firmware projection must be regenerated with
`tools/generate_firmware_host_contract.py` whenever that authority changes.

The optional host records the stream and requests explicit state/mode operations
through one serial owner. Ending a recording leaves the instrument operating.
Start with `.venv/bin/python -m host.otis_tools --help`; the
[host architecture](docs/50_SOFTWARE/HOST_ARCHITECTURE.md) describes commands,
recorded evidence and bounded transport. Building and physical qualification
remain explicit engineering operations.

The current execution sequence is the
[`OTIS consolidation programme`](docs/90_ROADMAP/OTIS_CONSOLIDATION_PROGRAMME.md):
evidence and outcome integrity, shared experimental records, reference
acceptance, firmware/host simplification, exact-path rehearsal and sustained
qualification on the existing hardware. The older canonical work programme is
an exploratory catalogue; hardware ports and successor-board work are outside
the agreed scope.

## Evidence policy

`runs/` is intentionally ignored local scientific evidence. Never force-add it
or weaken `.gitignore`. Preserve raw packages unchanged; promote only reviewed
conclusions, contracts, models, schemas, and small purpose-built fixtures.
For bench exchange use `~/Documents/OTIS_DATA/` with exact file hashes and
explicit transfer status; acquisition remains local.

## Verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

All tiers are no-hardware checks and build the same fixed image. Historical
reproduction uses the recorded historical revision and that revision's own
instructions; there is no historical compatibility tier on current HEAD.

## Repository map

| Directory | Purpose |
| --- | --- |
| `data_contracts/` | current deployed contract documentation |
| `firmware/arduino/otis_nano_rp2040_connect/` | current fixed-image firmware |
| `host/otis_tools/` | current capture, regulation, replay, and evidence tools |
| `profiles/` | current policy, model, and estimator bindings |
| `schemas/` | current machine-readable schemas |
| `tests/` | current architecture, policy, firmware, and evidence regressions |
| `docs/60_EXPERIMENTS/` | reviewed scientific record |

## License

MIT License.
