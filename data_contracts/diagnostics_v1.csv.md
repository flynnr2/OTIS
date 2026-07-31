# diagnostics_v1.csv

## Status and scope

Normative additive diagnostic transition contract for live observe-only
operation and deterministic replay. `DIAG` records explain evidence-backed
quality, health, applicability, and eligibility conclusions. They do not
replace raw evidence, establish timing truth, or authorize actuator writes.

## Transition semantics

A stable `diagnostic_id` identifies a diagnostic rule. `episode_id` identifies
one raise-to-clear episode. A producer emits `raised`, meaningful `updated`,
`cleared`, or bounded `snapshot` transitions rather than repeated periodic
copies.

`first_evidence_refs` never changes within an episode.
`latest_evidence_refs`, `last_seen_ticks`, and `occurrence_count` advance only
when new evidence is accepted. A `cleared` transition requires an explicit
`clear_reason_code`.

Evidence is processed in recorded acquisition order. Duplicate evidence is
idempotent. Sequence regression or reordering is evidence for a separate
diagnostic and must not rewrite earlier state. Reset or reconnect starts a new
source-identity epoch.

## Fields

| Field | Meaning |
|---|---|
| `record_type` | Always `DIAG`. |
| `schema_version` | Always `1`. |
| `diagnostic_seq` | Strictly increasing output sequence. |
| `diagnostic_id` | Stable rule identifier. |
| `episode_id` | Stable identifier for one active/cleared episode. |
| `subsystem` | Owning diagnostic subsystem. |
| `severity` | `INFO`, `DEGRADED`, `WARN`, `FAULT`, or `CRITICAL`. |
| `state` | `active`, `cleared`, `latched`, `suppressed`, or `unknown`. |
| `transition` | `raised`, `updated`, `cleared`, `latched`, `suppressed`, `snapshot`, or `unknown`. |
| `diagnostic_confidence` | Confidence in the diagnosis, `0..1`, or `unknown`. |
| `reason_code` | Stable reason for the finding. |
| `clear_reason_code` | Required only for a clear transition. |
| `first_seen_ticks` / `last_seen_ticks` | Episode evidence range in `time_domain`. |
| `time_domain` | Native evidence time domain. |
| `occurrence_count` | Accepted occurrences in the episode. |
| `persistence_state` | `candidate`, `confirmed`, `recovering`, `cleared`, or `latched`. |
| `first_evidence_refs` | Exact evidence that opened the episode. |
| `latest_evidence_refs` | Exact most recent evidence. |
| `algorithm_version` | Diagnostic reducer identity. |
| `config_hash` | Canonical diagnostic configuration hash. |
| `observation_effect` | Effect on observation validity. |
| `reference_effect` | Effect on reference qualification. |
| `model_effect` | Effect on model applicability. |
| `control_effect` | Effect on control eligibility. |

The four effect fields are independent. Service-plane loss may reduce trust in
telemetry completeness but must not redefine timing or reference truth.

## Configuration identity

The canonical configuration payload is compact JSON with sorted keys and no
whitespace. It contains `schema_version=1`, the diagnostic algorithm version,
and the complete ordered rule table including identifiers, reasons, effects,
and raise/clear/update counts. `config_hash` is the lowercase SHA-256 of those
bytes.

Host policy is declared by `DEFAULT_DIAGNOSTIC_SPECS`; firmware policy is
declared by `otis_diagnostic_catalog.*`. A sealed native-C++/Python parity
fixture compares the complete transition rows and fails if either catalog,
effect, hysteresis count, algorithm version, or hash diverges.

If a derived frame cannot be queued, its tentative diagnostic state changes
are rolled back. The same transition is retried against the next accepted
evidence, so output backpressure cannot silently consume its own diagnostic.
