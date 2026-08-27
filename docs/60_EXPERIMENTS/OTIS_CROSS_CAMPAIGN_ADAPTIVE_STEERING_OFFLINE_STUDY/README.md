# Cross-campaign adaptive-steering offline study

This directory contains the tracked, reviewable result of
`OTIS_CROSS_CAMPAIGN_ADAPTIVE_STEERING_OFFLINE_PROGRAMME_PROMPT.md`.

The decision-bearing study is V2. V1 is preserved unchanged as a superseded
audit record; `SUPERSESSION.md` records why it cannot support the decision.

The finite adjudication provisionally retains the unchanged CX322 request law,
pending the later D9 waveform and frequency-only FLL-output soak gate. This is
a fail-closed fallback, not evidence that the unchanged law outperformed the
two changed candidates: the prospectively frozen held-out plant model is
invalid, so post-divergence changed-candidate performance is unavailable.

## Authority boundary

This study has no device, serial, process-control, firmware-build,
firmware-edit, flash, actuator, soak-control, or live-run authority. It reads
three completed local packages from a separately supplied evidence repository
and writes a new derived package outside every source package.

The `runs/` inputs and derived packages are intentionally local filesystem
evidence and are not tracked by Git. The tracked JSON report binds the local
derived manifest by digest. No input package is copied into this worktree.

## Files

- `analysis_contract_v2.json` — prospectively refrozen correction overlay,
  strict normalization/provenance semantics, and V1 contract binding.
- `study_report_v2.json` — compact machine-readable decision and exact local
  derived-package binding.
- `COMPLETION_REPORT.md` — evidence ledger, results, finite decision,
  limitations, and verification.
- `OPERATIONAL_SEMANTICS.md` — transaction-aware metadata hold, phase fallback,
  low-efficiency inhibition, telemetry, implementation map, and fault matrix.
- `SUPERSESSION.md` — immutable V1 supersession record.
- `analysis_contract_v1.json` and `study_report_v1.json` — preserved,
  non-decision-bearing V1 audit artifacts.

## Reproduction

From the isolated worktree, with the three completed packages present under the
local OTIS repository:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/richardflynn/git/OTIS/.venv/bin/python \
  -m host.otis_tools.adaptive_steering_offline_study \
  --evidence-repository /Users/richardflynn/git/OTIS \
  --no-tracked-report
```

The default local output is:

```text
runs/derived/cross_campaign_adaptive_steering_offline_v2
```

The output location must be absent or empty. A later reproduction must use a
new `--output` path or deliberately archive the earlier local derived package.
`--no-tracked-report` prevents a reproduction from trying to overwrite the
reviewed tracked report.

## Successor execution prompts

The gated successor programme is in
`docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/`.
It deliberately qualifies D9/D6 and completes the frequency-only output soak
before confirming the unchanged CX322 coherent FLL/PLL law, implementing the
frozen operational degradation semantics and preparing the later integrated
trial.
