# Codex prompt: integrate first-class diagnostics across OTIS

You are working in the OTIS repository. Treat the newly added architecture
documents as normative:

- `docs/10_REFERENCE_ARCHITECTURE/MEASUREMENT_METROLOGY_DIAGNOSTICS_CONTROL.md`
- `docs/10_REFERENCE_ARCHITECTURE/DIAGNOSTICS_AND_CONFIDENCE_ARCHITECTURE.md`
- `docs/30_ANALYSIS/PPS_REFERENCE_CHARACTERIZATION.md`

The associated edits to vision, design principles, architecture overview,
telemetry philosophy/taxonomy, README, and SW2 roadmap define the intended
terminology and direction.

## Objective

Perform a documentation-and-contract consistency pass that makes diagnostics a
first-class, evidence-backed, replayable subsystem without enabling automatic DAC
actuation or disrupting the current H1/SW2 sequence.

## Required work

1. Inventory all repository uses of `measurement`, `metrology`, `telemetry`,
   `diagnostic`, `health`, `confidence`, `valid`, `eligible`, `fault`, `EST`,
   `CTL`, `STS`, and `lock`.
2. Produce a concise inconsistency report before editing. Distinguish true
   semantic conflicts from harmless wording.
3. Update documentation cross-links and terminology so that:
   - measurement means preserved observations;
   - metrology means numerical estimates with units, assumptions, provenance,
     and uncertainty;
   - diagnostics means evidence-backed quality/health/applicability conclusions;
   - control means policy-governed preview or actuation;
   - telemetry means transport/records spanning all layers.
4. Propose and document, but do not casually invent, a versioned diagnostic
   record contract. It must support stable reason codes, subsystem, severity,
   state/transition, confidence in the diagnosis, first/last seen, evidence
   references, algorithm/config version, and control consequence.
5. Explicitly distinguish observation validity, source quality, estimate
   uncertainty, model applicability, control eligibility, and diagnostic
   confidence. Do not collapse them into one Boolean or score.
6. Map current `health_v1`, `STS`, anomaly reports, estimator plans, and control
   readiness gates to the new architecture. Preserve backward compatibility.
7. Identify the smallest staged implementation packages for:
   - host-side PPS/reference distribution plots and statistics;
   - reference/count-path diagnostic reason codes;
   - estimator qualification diagnostics;
   - plant-model and DAC/actuator diagnostics;
   - live-versus-replay parity tests;
   - explainability chain from observation through applied DAC acknowledgement.
8. Add or update tests/fixtures only for non-actuating parsers, validators,
   replay, and diagnostic logic. Do not enable PPS/count-derived DAC writes.
9. Update the SW2 roadmap/package ordering only where needed to make these gates
   explicit. Do not replace the roadmap wholesale.

## Safety and compatibility constraints

- Automatic control remains disabled unless already explicitly enabled by the
  existing repository state; do not broaden it.
- Preserve canonical raw `REF`, `CNT`, `EVT`, environment, DAC, and health data.
- Never delete or suppress invalid observations; annotate, classify, and gate.
- Keep the timing-plane/service-plane separation intact.
- Do not create a second competing telemetry model.
- Unknown values remain unknown, not zero.
- Preserve existing schemas and CLI behaviour unless a versioned migration is
  explicitly documented and tested.
- Do not claim that a PPS anomaly identifies the physical root cause unless the
  evidence isolates receiver, electrical, GPIO, PIO/FIFO/DMA, firmware, or host
  path.
- Do not introduce a web UI, Kalman filter, ClockMesh/RSN/PTP implementation, or
  temperature holdover model in this package.

## Deliverables

1. `derived/diagnostics_architecture_gap_report.md` or an equivalent reviewed
   repository document describing findings and proposed migrations.
2. Surgical documentation edits and cross-links.
3. A proposed diagnostic data contract and example fixtures, clearly marked
   draft if evidence is insufficient to freeze v1.
4. Parser/validator/replay tests for any contract added.
5. A staged work-package list with exact acceptance gates.
6. A final summary listing changed files, commands run, tests passed, unresolved
   questions, and confirmation that automatic DAC actuation was not enabled.

## Acceptance criteria

- A contributor can unambiguously classify any record as measurement,
  metrology/estimate, diagnostic, control, context, provenance, or host operation.
- Current control eligibility can be reported with explicit reason codes.
- At least one PPS/reference anomaly fixture demonstrates preserved raw evidence,
  diagnostic classification, control inhibition, clearing/requalification, and
  deterministic host replay.
- At least one actuator fixture demonstrates requested versus applied DAC state,
  clamp/slew/write-result visibility, without real hardware actuation.
- Documentation and tests show that service-plane telemetry failure does not
  redefine timing truth.
- Every proposed future DAC action has a documented explainability chain.

Begin by reading the normative documents and the current SW2 roadmap/readiness,
telemetry taxonomy/contracts, host architecture, count-observation contract,
boot diagnostics, and relevant tests. Do not begin implementation until the gap
report identifies the minimal compatible path.
