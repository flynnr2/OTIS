# OTIS

OTIS is an open, provenance-preserving timing instrument for deterministic,
reference-centric measurement and replayable analysis. Hardware capture is
timing truth; host services preserve, validate, replay, and analyze evidence.

The design principles are in
[`docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md`](docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md).

## Current support boundary

Current HEAD preserves `CX319_EVIDENCE_EPOCH_1` as its physical evidence floor
and retains the active-hybrid implementation, evidence readers, and offline
replay tooling with all physical live authority disabled. The retained deployed
CX319 wire identities, fail-closed rules, and historical reproduction procedure are in
[`docs/50_SOFTWARE/CX319_EVIDENCE_EPOCH_1.md`](docs/50_SOFTWARE/CX319_EVIDENCE_EPOCH_1.md).

H0/SW1, H1, Phase 4/5, CX317, and CX318 operational readers, profiles, campaign
CLIs, and regression obligations are retired from current HEAD. Their reviewed
reports and provenance remain scientific records under `docs/60_EXPERIMENTS/`
and Git history. Reproduce a historical package from the exact revision named
by its manifest, bundle, index record, or report; do not treat a successful
historical reproduction as current validation or authority.

The CX319 range-spanning programme is complete and frozen. Its mapping-informed
Part B seal binds two physical acquisitions; the lower reacquisition remains an
inference, the original upper traversal remains a right-censored bounded
non-pass, and its completion is preserved as a separate acquisition plus a
host-only finalizer supersession. The terminal report and exact claims boundary
are in
[`43_MAPPING_INFORMED_PART_B_TERMINAL_REPORT.md`](docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/43_MAPPING_INFORMED_PART_B_TERMINAL_REPORT.md).

CX320 bounded active-hybrid qualification reached a decision-bearing physical
terminal. The firmware applied one genuine combined phase-frequency correction
from `0xA83C` to `0xA836`, but the exact 1,500-second response was below the
frozen empirical detection floor and did not establish the required positive
plant-response sign. The programme is therefore a bounded non-pass; its
single-use activation is consumed and CX320 is historical only. The last
confirmed code is `0xA836` in `FAIL_STATIC`. Any future flash or
reset makes the physical code unknown until a new exact setup acknowledgement
is captured. See the
[`attempt-9 terminal report`](docs/60_EXPERIMENTS/CX320_ACTIVE_HYBRID_PROGRAMME/12_STAGE5_ATTEMPT9_RESPONSE_OBSERVABILITY_TERMINAL.md).

The OTIS sustained-hybrid V1 programme is closed after Attempt 4. Its physical
qualification failed because eleven required contemporaneous pre-phase-4 replay
attestations were absent; that missing source evidence cannot be recreated as a
pass. Separately, the retained controller path reached the prospectively frozen
`prospective_low_efficiency_path` terminal after 52 decisions and eleven
automatic applications. The unchanged V1 controller is therefore scientifically
rejected and no Attempt 5 or V1 live operation is authorized. See the
[Attempt 4 terminal report](docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_REGULATION_V1/04_ATTEMPT4_PHASE4_ATTESTATION_AND_SCIENTIFIC_TERMINAL.md).

The offline sustained-hybrid successor study rejected three simple deadband
variants because none preserved the early phase behavior. A subsequent frozen
mode-separation architecture study preserved that behavior and cleared the
phase gate, but all three architectures lost too much tight-band occupancy and
used 28 to 32 path codes. It therefore also selected no successor. Attempt 4
authority remains consumed, V1 remains closed, and there is no active
programme or physical authority on current HEAD. The next gate is a separately
frozen estimator-state and uncertainty architecture revision. See the
[mode-separation decision](docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_MODE_SEPARATION_OFFLINE_STUDY/DECISION.md).

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
| `profiles/` | current evidence, closed programme status, offline study, policy, model, estimator, and authority bindings |
| `schemas/` | current machine-readable schemas |
| `tests/` | current platform, evidence, policy, authority, and replay regressions |
| `docs/60_EXPERIMENTS/` | reviewed current and historical scientific record |

## License

MIT License.
