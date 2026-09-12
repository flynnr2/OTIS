# OTIS

OTIS is an open, provenance-preserving timing instrument for deterministic,
reference-centric measurement and replayable analysis. Hardware capture is
timing truth; host services preserve, validate, replay, and analyze evidence.

The design principles are in
[`docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md`](docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md).

## Current operating surface

Current HEAD contains one instrument programme and one buildable fixed
firmware image: `adaptive_hybrid_regulation`, policy
`OTIS_ADAPTIVE_HYBRID_REGULATION_V1`. The firmware configuration is not a
selectable profile matrix. Run duration and experiment-specific stop conditions
belong in the frozen run specification, not in the product or policy identity.

The current physical-entry surface has two exact purposes: a diagnostic
`inhibited_zero_write` acquisition and the sole authority-bearing
`contingent_72_hour_hybrid_control` programme. The latter runs to 259,200
accepted D14/D8 apertures, admits at most 144 natural corrections within the
characterized DAC envelope, and has a 280,800-second absolute wall limit. It
does not stop after setup, the first correction, or an arbitrary short prefix.

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

The host has five jobs: capture, supervise, monitor, analyse, and package.
One foreground experiment owner and one capture worker handle the live path.
Monitoring is read-only. Build and physical entry are explicit engineering
operations; ordinary observation and offline work never compile or flash.

Freeze one inert run specification, rehearse it through the actual host path,
and use its receipt with the explicit operator instruction for physical entry.
There is no bundle/proposal/activation copy chain or global registry gate.
The [host architecture](docs/50_SOFTWARE/HOST_ARCHITECTURE.md) explains ownership;
the [evidence lifecycle](docs/50_SOFTWARE/EVIDENCE_LIFECYCLE.md) explains portable
closure and later analysis. Start with `python -m host.otis_tools --help` (or
`otis --help` after installation).

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
For delivery between machines, use
[`closed evidence transfer`](docs/50_SOFTWARE/EVIDENCE_TRANSFER.md). Cloud storage
carries sealed archives; acquisition and analysis use independent local copies.

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
