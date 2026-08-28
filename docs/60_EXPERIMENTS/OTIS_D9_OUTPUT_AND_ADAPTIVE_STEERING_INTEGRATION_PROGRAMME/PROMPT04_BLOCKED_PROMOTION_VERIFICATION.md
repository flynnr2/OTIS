# Prompt 04 Blocked-Promotion Verification

## Terminal

Prompt 04 closed at the exact non-effective boundary required by the valid
Prompt 02 result:

`non_effective_semantics_verified_promotion_blocked_by_d9_gate`

The blocked-promotion audit report is retained at
`runs/d9_adaptive_steering_integration_20260828/prompt04/blocked_promotion_report_v2.json`.
Its file SHA-256 is
`32316b97c13a74b17a816243814ce5b3eb194ca9a3dfe2fc8ca68219030a978d`.
It binds clean candidate source revision
`8cba3eece39779b8d2d4271a83257d27c8a3cb71`, the Prompt 02 decision,
the Prompt 03 non-effective contract, all three separated build manifests, the
unchanged CX322 policy, and the retained Prompt 01 operational rehearsal.

The audit reports `effective: false`, `physical_authority: false`, and
`trial_proposal_created: false`.

## Verification results

The exact changed source passed the following gates:

| Gate | Result |
|---|---|
| Prompt 04 focused Python/native, firmware-parity, transaction, CX322, D9/D6 source-guard, monitor, binary-contract, and audit tests | 43 passed |
| Current Release test gate | 1,278 passed; 62 historical tests explicitly deselected |
| Current Release firmware matrix | 25/25 verified: 17 expected-pass builds passed and 8 expected-failure guards failed as declared |
| Exact separated candidate builds | 3/3 passed and verified |
| Blocked-promotion identity/authority audit | passed |

The Release command was:

```text
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

The exact audit command supplied all three named build manifests, the retained
Prompt 01 rehearsal report, and one exclusive output path to:

```text
.venv/bin/python -m host.otis_tools.d9_hybrid_promotion_audit
```

The first Release attempt found one stale generated measurement-semantics
inventory after 1,277 other tests passed. The inventory was regenerated, its
direct 10-test regression passed, and the complete Release gate above then
passed. This was a deterministic repository-generation escape; it did not
affect firmware behavior, retained physical evidence, or bench state.

## Exact separated builds

No combined profile was permitted. The clean revision produced these mutually
exclusive profiles and manifest identities:

| Profile | Authority class | Configuration SHA-256 | Manifest SHA-256 |
|---|---|---|---|
| `d9_d6_forwarded_output_no_control` | non-actuating D9/D6 | `02f4b7ac6bc66d5463dec2d56dc125175f6f8eded20bac2f3d04148031fc5cfb` | `da5635e173cf42809c6f393e14bef09998b80271290d2b1a7035691ca0eb79d4` |
| `d9_d6_frequency_only_lower` | compile-only, unqualified active frequency control | `66fe21057030fc3fefc3149ff3dd69ca31705734632598d3aeda27434cb923c7` | `6b27a8a0c3f38f16ada0127a963f285cbbed5d7e4034c1f7b7a2b9410cb25ab1` |
| `cx322_direct_hybrid` | retained standalone CX322, not D9-integrated | `20b8aed10a2e6e84f43de5e08d35370a552e06e9f69158af917def718ad237cf` | `56b9fbc1d5f85413c62a1eb9d109033ab321c709ab689d698498650121a2c038` |

Each manifest identifies the same clean source revision and contains verified
ELF and UF2 artifact records. The firmware matrix proves that the retained
CX322 profile does not select D9 or D6, and that the non-actuating D9/D6 profile
does not select DAC or active-control authority. The frequency-only profile is
kept explicitly compile-only; it is not mislabeled as non-effective or
qualified.

## Operational-path evidence and claim boundary

The retained Prompt 01 deterministic PTY rehearsal input is
`82f0582e79855544828b2ad222db51ea66af487168b615b891b06e87eb631614`.
Its report SHA-256 is
`02419dcbec08c2be4f896f93f16415baa379d5c6ce2655ea01552530be1ec550`,
its semantic seal is
`1c2082d53a092ffadf54e6c2ab36a84341d6970ce6d32d56856f49afb51991c0`,
and its temporary registration validated. It exercised the production capture
path over a PTY, repeated configuration acknowledgement, transport
obstruction, independent abort delivery, same-owner rotation, analysis,
sealing, content snapshot, and temporary registration. It performed zero
physical actions and supplied no qualification evidence.

That retained rehearsal is reused only for the D9/D6 capture/FIFO/abort/
rotation/analyzer/sealer boundaries whose decision-relevant inputs remain
unchanged. Prompt 03's deterministic Python/native reference implementation
supplies the metadata-hold, transaction, phase-fallback, low-efficiency, and
optional-evidence semantics. It does not pretend those new states are wired
through a board binary or the live host process topology.

Consequently, this Prompt 04 result intentionally does not claim or create:

- an integrated D9/D6/CX322 firmware profile or binary;
- live Prompt 03 state fields in firmware telemetry;
- a complete integrated producer-to-consumer PTY rehearsal;
- physical Core 0/Core 1, DAC, or VCOCXO propagation evidence;
- D9 voltage, waveform, duty, edge, ringing, load, delay, jitter, or
  independently referenced frequency evidence; or
- a 72-hour trial proposal or any physical/control authority.

Creating an integrated binary or rehearsal package while the D9 waveform and
qualified-load gate is incomplete would weaken the sequenced programme gate.
The missing integrated package, seal, handoff ledger, and trial proposal are
therefore blocked deliverables, not silently waived successful ones.

## Remaining decision

The D14/D8 measurement path and D6 zero-authority continuity sidecar are
healthy. Controller promotion remains blocked solely because a multimeter and
the D6 loopback cannot establish the required delivered-output waveform, load,
or independently referenced frequency evidence. Future progress requires a
separately frozen oscilloscope/counter qualification; it must begin with fresh
device auto-detection and the live pre-actuation identity/readback gate.
