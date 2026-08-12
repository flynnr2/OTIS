# CX319 Compatibility Reset Report — 2026-08-12

## Outcome

Current HEAD now supports only `CX319_EVIDENCE_EPOCH_1`. It has one canonical
run-package layout, one current CX319 operational toolchain, two supported
firmware profiles, and explicit fast/campaign/release/historical verification
tiers. No hardware I/O was performed and `runs/` was not modified.

The pre-reset revision was
`c68091f534cf17747d3b548dc8f88aba1e32a4ee`. The worktree was clean before the
reset. The repository had no Git tags, so historical reproduction uses each
package or report's exact recorded commit rather than a tag.

## Compatibility floor

Current packages require canonical `run_manifest.json`, canonical `raw/`,
`csv/`, and `reports/` paths, immutable `evidence_manifest.json` for every
non-template package, complete build provenance, and exact current CX319
profile/policy/authority/analyzer/model identities. Root raw-log aliases,
legacy manifests, retired stages, historical models, PPS qualification v1,
`estimates_v1`, and retired replay/policy variants fail closed with revision-
checkout guidance.

Existing sealed CX319 packages are recognized by exact CX319 stage and current
profile identity. Their inert `h_phase` field remains provenance. Newly created
manifests declare `CX319_EVIDENCE_EPOCH_1` and omit `h_phase`.

## Retained surfaces and rationale

- Current CX319 Q1/Q2/G1/G2/G4 host workflows, programme authority ledger,
  capture, transaction, analyzer, sealing, registration, and recovery paths:
  required for the next authorized CX319 decision and current safety.
- Deployed `cx317_*` firmware/wire IDs, `h1_cx317_ocxo_10mhz`, current active
  policy/model/estimator filenames, and `CX318_STAGE5_TRANSITION_SPOOL`:
  immutable current wire provenance; renaming would reinterpret sealed data.
- Current v1 CSV contracts and schemas: they remain the emitted wire contracts;
  version number alone is not a retirement criterion.
- Relative-phase/hybrid replay corpus and selected profiles: hash-bound inputs
  to the current selected estimator/native parity surface.
- Reviewed reports under `docs/60_EXPERIMENTS/`: authoritative scientific and
  provenance record, not executable compatibility machinery.

## Removed surfaces

Retired H0/SW1 examples and wire-validation workflow; H1 campaign CLIs and
templates; Phase 4/5 readers and qualification schemas; CX317 Stage 6–8 and
older plant/campaign tooling; CX318 Stage 4 and suspended Stage 5 flash,
premise, promotion, seal, and analyzer entry points; archived matrix profiles;
and dedicated tests whose only purpose was keeping those workflows executable.

Current mechanics were first extracted into `abort_transport`,
`active_transactions`, `active_control_policy`, `active_control_supervisor`,
`capture_runtime_checks`, `measurement_replay`, `frequency_control_replay`,
`frequency_control_supervisor`, `tight_deadband_policy`,
`control_evidence_replay`, and `campaign_finalization`. No historical forwarding
layer remains.

## Size and regression comparison

| Measure | Before | After |
|---|---:|---:|
| collected tests | 1,164 | 722 |
| full Python/native suite | 126.36 s | 84.14 s |
| host Python modules | 125 | 74 |
| host Python lines | 66,293 | 31,829 |
| test modules | 130 | 93 |
| test lines | 34,429 | 18,266 |
| firmware matrix profiles | 45 | 7 |

The change deletes 62 tracked host modules, 51 tracked test modules, 27 profile
JSON files, and 85 run-template files, while adding neutral current modules and
tests. The overall patch removes approximately 67,164 lines and adds 1,111
lines (net reduction about 66,053). Host source alone falls by about 34,464
lines.

Before reset, 289 CX317/CX318-specific tests took 33.71 s. The baseline full
suite took 127.26 s wall clock; its slowest test was the 31.63 s snapshot
quantization case. The final current suite is 33% faster by pytest elapsed time.

## Verification results

- Focused extraction/removal tests: passed.
- Full current suite: 722 passed in 84.14 s (85.00 s wall).
- Fast tier: 45 tests passed in 0.53 s; `cx319_tight_lower` compiled and passed;
  wrapper wall time 108.29 s.
- Campaign tier: 122 tests passed in 5.59 s; lower and upper profiles compiled
  and passed; wrapper wall time 179.49 s.
- Release firmware matrix: both supported profiles passed and all five
  expected-failure guards failed as required; 231.51 s wall.
- Current sealed Q3 package
  `q3_physical_no_write_20260812T150928Z`: validated read-only; all declared
  current CSV contracts passed, with warnings only for header-only optional
  products.
- Explicit floor tests prove rejection of missing evidence snapshots, legacy
  root raw logs, `manifest.json`, retired epochs, and retired model/policy
  inputs.
- Import audit, `compileall`, and `git diff --check`: passed.
- Historical tier: prints exact-revision reproduction guidance and runs no
  current compatibility checks.

## Historical reproduction and reanalysis

Read the source revision from the manifest, bundle, evidence-index entry, or
reviewed report, create a separate `git worktree` at that revision, verify
artifact hashes with that revision's matrix, and run that revision's documented
command. Do not validate historical packages against the current matrix.

A current-code reanalysis is a new non-authorizing derived product. It records
source package and file hashes, old/new revisions and analyzer identities,
old/new verdicts, superseded-product identity, reason, review authority, and
UTC. It never changes the source package or original report.

## Limitations and deferred candidates

- Firmware C++ symbols and several current profile paths retain historical
  names because they are deployed wire/build identities. A future wire epoch
  may rename them only with an explicit schema and evidence transition.
- The selected phase/hybrid profiles bind a tracked replay corpus whose records
  name historical local evidence paths. Current CI validates and uses the
  tracked corpus without opening `runs/`; removal would break current selected
  estimator parity and is therefore deferred.
- Fast/campaign wall times remain compilation-dominated. Native harness inputs
  are reused within pytest sessions, but firmware matrix builds currently run
  independently across tier invocations.
- No physical bench verification was performed or authorized.
