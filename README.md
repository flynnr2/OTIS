# OTIS

OTIS is an open, provenance-preserving timing instrument for deterministic,
reference-centric measurement and replayable analysis. Hardware capture is
timing truth; host services preserve, validate, replay, and analyze evidence.

The design principles are in
[`docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md`](docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md).

## Current support boundary

Current HEAD supports only `CX319_EVIDENCE_EPOCH_1`. The exact package floor,
retained deployed wire identities, fail-closed rules, and historical
reproduction procedure are in
[`docs/50_SOFTWARE/CX319_EVIDENCE_EPOCH_1.md`](docs/50_SOFTWARE/CX319_EVIDENCE_EPOCH_1.md).

H0/SW1, H1, Phase 4/5, CX317, and CX318 operational readers, profiles, campaign
CLIs, and regression obligations are retired from current HEAD. Their reviewed
reports and provenance remain scientific records under `docs/60_EXPERIMENTS/`
and Git history. Reproduce a historical package from the exact revision named
by its manifest, bundle, index record, or report; do not treat a successful
historical reproduction as current validation or authority.

The active CX319 programme currently permits offline preparation and one
explicitly bounded no-flash, no-write, low-cadence physical check, as recorded
in `profiles/programme_status_v2.json`. This does not authorize firmware
flashing, DAC writes, control arming, Q2/Q3 repetition, or live execution.

The scientific claim remains limited to bounded experimental frequency and
arbitrary-epoch relative-phase evidence. OTIS does not claim traceable absolute
frequency, calibrated phase, UTC, lock, or holdover.

## Evidence policy

`runs/` is intentionally ignored and contains local scientific evidence. Never
force-add it or weaken `.gitignore`. Preserve raw packages unchanged; promote
only reviewed conclusions, contracts, models, schemas, and small purpose-built
fixtures. Every current non-template package requires canonical
`run_manifest.json`, `raw/serial.log`, and immutable
`evidence_manifest.json`.

## Verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

The `historical` tier prints revision-checkout guidance and runs no current
compatibility tests. See
[`docs/50_SOFTWARE/VERIFICATION_AND_PROFILE_LIFECYCLE.md`](docs/50_SOFTWARE/VERIFICATION_AND_PROFILE_LIFECYCLE.md).

## Repository map

| Directory | Purpose |
|---|---|
| `data_contracts/` | current deployed contract documentation |
| `firmware/arduino/otis_nano_rp2040_connect/` | current firmware platform |
| `host/otis_tools/` | current capture, control, replay, and evidence tools |
| `profiles/` | current CX319 policy, model, estimator, and authority bindings |
| `schemas/` | current machine-readable schemas |
| `tests/` | current platform and CX319 regression tests |
| `docs/60_EXPERIMENTS/` | reviewed current and historical scientific record |

## License

MIT License.
