# Diagnostics Architecture Gap Report

> Historical planning inventory. The software gaps identified here were closed
> on 30 July 2026 by the normative `diagnostics_v1` contract, deterministic
> host and fixed-capacity firmware reducers, canonical rule-table hashing,
> exact episode evidence ranges, reference/estimate/control effects, and sealed
> native/host parity fixtures. The remaining work is physical bench evidence,
> not a missing diagnostic software architecture. The draft-v0 discussion and
> term counts below are retained as the design record.

## Scope

This report inventories current repository terminology and identifies the
smallest compatible path for making diagnostics a first-class, evidence-backed,
replayable subsystem. It treats these documents as normative:

- `docs/10_REFERENCE_ARCHITECTURE/MEASUREMENT_METROLOGY_DIAGNOSTICS_CONTROL.md`
- `docs/10_REFERENCE_ARCHITECTURE/DIAGNOSTICS_AND_CONFIDENCE_ARCHITECTURE.md`
- `docs/30_ANALYSIS/PPS_REFERENCE_CHARACTERIZATION.md`

No implementation step in this report authorizes automatic DAC actuation.

## Inventory

Inventory command:

```sh
rg -n '\b(measurement|metrology|telemetry|diagnostic|diagnostics|health|confidence|valid|eligible|fault|EST|CTL|STS|lock)\b' -S .
```

Match counts by term in the current tree:

| Term | Matches |
|---|---:|
| `measurement` | 71 |
| `metrology` | 48 |
| `telemetry` | 222 |
| `diagnostic` | 62 |
| `diagnostics` | 70 |
| `health` | 98 |
| `confidence` | 31 |
| `valid` | 91 |
| `eligible` | 25 |
| `fault` | 70 |
| `EST` | 7 |
| `CTL` | 10 |
| `STS` | 221 |
| `lock` | 56 |

High-density areas are normative architecture, telemetry taxonomy, SW2 roadmap
and readiness docs, data contracts, host validation/reporting tools, Arduino
status/count code, and tests that assert current `STS`, FC0 readiness, and DAC
sweep behavior.

## True Semantic Conflicts

1. `health_v1` / `STS` is currently overloaded as the only machine-readable
   status, health, and diagnostic surface. This is backward-compatible but not
   first-class enough for replayable diagnostics because reason codes,
   persistence, state transitions, evidence references, algorithm/config
   versions, and control consequences are implicit or distributed across ad hoc
   keys.
2. `valid` appears in multiple meanings: structurally plausible observation,
   backend health, post-startup count qualification, PPS-gate acceptance, and
   control readiness. Current docs explain some of this, but the machine contract
   does not force separation.
3. `confidence` is sometimes architectural prose and sometimes could be read as
   a single quality score. The normative architecture requires separate
   observation validity, source quality, estimate uncertainty, model
   applicability, control eligibility, and diagnostic confidence.
4. `lock` remains a tempting shorthand in reference and control docs. Existing
   foundation docs correctly warn that lock is policy state, not timing truth;
   SW2 diagnostic records must preserve that distinction.
5. PPS/reference anomaly reporting has a correct host gate in manifests and
   readiness docs, but no stable diagnostic reason-code record that can be
   replayed independently of prose anomaly reports.
6. DAC evidence is preserved in `DAC` sweep rows, but requested/applied/clamped
   state, slew/write result, and control consequence are not yet connected to a
   first-class diagnostic finding contract.

## Harmless Wording

- Existing uses of `measurement` in experiment and hardware documents are mostly
  ordinary English and align with preserved observations when read in context.
- `telemetry` is used broadly, but current philosophy/taxonomy docs already
  define it as transport/records across layers rather than a semantic layer.
- `health` remains acceptable for low-level `STS` compatibility records if it is
  documented as an input/migration surface, not the replacement for diagnostics.
- Existing FC0 names are acceptable compatibility labels as long as
  backend-generic count/reference diagnostic names are added alongside them.

## Classification Rules

| Class | Meaning | Current examples |
|---|---|---|
| Measurement | Preserved observations with clock domain, sequence, flags, and provenance. | `REF`, `CNT`, `EVT`, `ENV`, DAC acknowledgements |
| Metrology / estimate | Numerical estimates with units, assumptions, provenance, and uncertainty. | H1 characterization summaries, future `EST` |
| Diagnostic | Evidence-backed quality, health, applicability, or eligibility conclusion. | draft `DIAG`; current `STS` compatibility keys |
| Control | Policy-governed preview or actuation decision and actuator result. | future `CTL`; current H1 `DAC` sweep telemetry is lab evidence only |
| Context | Environmental or operating context. | `ENV`, selected manifest fields |
| Provenance | Configuration, schema, calibration, identity, algorithm/model version. | manifest, profile, plant model |
| Host operation | Logging, reconnect, parser, storage, replay operation. | host reports, future host diagnostic records |

## Compatibility Mapping

| Current surface | New architecture role | Compatibility rule |
|---|---|---|
| `health_v1` / `STS` | Low-level state/status and migration source for diagnostics. | Preserve schema and CLI behavior; derive or mirror first-class diagnostics without removing `STS`. |
| FC0 `*_valid_for_control` keys | Control eligibility compatibility status. | Keep `fc0_*`; add backend-generic reason-coded diagnostics such as `count_path_post_inhibit_invalid_window`. |
| `pps_gate` `valid` / `control_eligible` | PPS-gated observation validity and eligibility status. | Split into observation validity, reference/source quality, and control eligibility in diagnostics. |
| Host anomaly reports | Human-readable derived diagnostics/metrology reports. | Add stable `DIAG` fixture rows that point at raw evidence and anomaly classes. |
| Estimator plans / H1 characterization | Metrology and estimator qualification inputs. | Future `EST` and estimator diagnostics must cite input ranges, rejected observations, uncertainty, and algorithm/config version. |
| `DAC` sweep rows | Measurement/control-lab evidence for requested/applied DAC state. | Do not reinterpret as closed-loop control; actuator diagnostics may cite `DAC` rows. |
| Future `CTL` | Control preview or actuation record. | Must cite `EST`, `DIAG`, plant model, policy, requested/applied DAC acknowledgement, and preview/authorization state. |

## Draft Diagnostic Contract

Add `data_contracts/diagnostics_draft_v0.csv.md` and validator support for
`diagnostics_draft_v0`. It is intentionally draft, non-actuating, and additive.

The draft record supports stable `reason_code`, `subsystem`, `severity`,
`state`, `transition`, diagnostic confidence, first/last seen, evidence
references, algorithm/config versions, and explicit control effect/eligibility.

## Minimum Staged Implementation Packages

1. Host-side PPS/reference distribution plots and statistics.
   Acceptance gate: report interval-error series, histogram/CDF, residual plot,
   rejected classes, tail counts, clean-run lengths, and assumptions; raw `REF`
   rows remain unchanged.
2. Reference/count-path diagnostic reason codes.
   Acceptance gate: PPS anomaly and count-window fixtures emit stable `DIAG`
   rows with evidence refs, inhibit reason, clearing/requalification transition,
   and deterministic replay.
3. Estimator qualification diagnostics.
   Acceptance gate: estimator sample count, age, rejected-data fraction,
   residual/dispersion, uncertainty, stale state, and under-qualified reasons are
   visible without collapsing into one score.
4. Plant-model and DAC/actuator diagnostics.
   Acceptance gate: missing/inapplicable plant model, clamp, slew, saturation,
   requested/applied mismatch, and I2C/write-result reasons are diagnosable from
   fixtures without hardware actuation.
5. Live-versus-replay parity tests.
   Acceptance gate: the same canonical `REF`/`CNT`/`STS`/`DAC` inputs and
   diagnostic algorithm/config versions reproduce the same `DIAG` findings.
6. Explainability chain from observation through DAC acknowledgement.
   Acceptance gate: every future applied DAC update traces from raw observation
   to `EST`, `DIAG`, policy/`CTL`, requested DAC code, clamp/slew handling, and
   applied/write acknowledgement.

## Roadmap Gate Adjustment

SW2 package ordering should add diagnostics gates before observe-only control
preview and before any actuation-capable PR:

1. Freeze draft diagnostic contract and reason-code namespace.
2. Add host replay diagnostics for PPS/reference and count-path fixtures.
3. Add estimator and plant-model applicability diagnostics.
4. Add actuator/DAC diagnostic fixtures.
5. Add observe-only `CTL` preview records only after diagnostics can explain
   eligibility.
6. Revisit guarded actuation only after plant model, reference validity, replay
   parity, and actuator acknowledgement gates pass.

## Explicit Non-Changes

- Automatic DAC actuation remains disabled.
- Canonical `REF`, `CNT`, `EVT`, `ENV`, `DAC`, and `health_v1` data remain
  preserved.
- Invalid observations are annotated, classified, and gated; they are not
  deleted or suppressed.
- Service-plane telemetry failure is diagnostic evidence; it does not redefine
  timing truth.
- Unknown values remain `unknown` or empty/null according to the owning
  contract, never plausible zeros.
