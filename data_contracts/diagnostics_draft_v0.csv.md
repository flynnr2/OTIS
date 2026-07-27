# diagnostics_draft_v0.csv

## Status

Draft. This contract is an additive host/replay contract for first-class
diagnostic findings. It is not a firmware actuation contract and does not replace
`health_v1` / `STS`.

## Purpose

`diagnostics_draft_v0.csv` records evidence-backed quality, health,
applicability, and control-eligibility conclusions. Diagnostic records explain
whether evidence can be trusted or used by policy; they do not establish timing
truth and they do not write actuators.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact tag; always `DIAG` |
| `schema_version` | uint | draft schema revision; currently `0` |
| `diagnostic_seq` | uint64 | monotonic diagnostic record sequence |
| `diagnostic_id` | string | stable finding identifier within the run or replay |
| `subsystem` | enum | `reference`, `count_path`, `oscillator`, `actuator`, `estimator`, `control`, `environment`, `service_plane`, or `storage` |
| `severity` | enum | `INFO`, `DEGRADED`, `WARN`, `FAULT`, or `CRITICAL` |
| `state` | enum | `active`, `cleared`, `latched`, `suppressed`, or `unknown` |
| `transition` | enum | `raised`, `updated`, `cleared`, `latched`, `suppressed`, `snapshot`, or `unknown` |
| `diagnostic_confidence` | decimal/unknown | confidence in this diagnosis, `0.0..1.0`, or `unknown` |
| `reason_code` | string | stable machine-readable reason code |
| `first_seen_ticks` | uint64 | first evidence timestamp in `time_domain` |
| `last_seen_ticks` | uint64 | latest evidence timestamp in `time_domain` |
| `time_domain` | string | timestamp domain for first/last seen |
| `evidence_refs` | string | semicolon-separated references to raw records, estimates, status rows, manifests, reports, or configuration |
| `algorithm_version` | string | diagnostic rule/model version or hash |
| `config_version` | string | config/profile/manifest/policy version or hash |
| `control_effect` | enum | `none`, `reduce_trust`, `inhibit_acquisition`, `inhibit_actuation`, `enter_holdover`, `fail_static`, or `unknown` |
| `control_eligibility` | enum | `eligible`, `not_eligible`, `not_applicable`, or `unknown` |

## Semantics

A diagnostic record is a conclusion with cited evidence. It may cite raw
measurements, metrology/estimate products, status rows, manifests, plant models,
or actuator acknowledgement rows. It must not replace those inputs.

Do not collapse these concepts into one Boolean or score:

- observation validity;
- source quality;
- estimate uncertainty;
- model applicability;
- control eligibility;
- diagnostic confidence.

Unknown values remain `unknown` or empty according to the owning evidence
contract. They must not be encoded as zero.

## Initial Reason-Code Namespace

| Reason code | Meaning |
|---|---|
| `reference_pps_short_interval` | Adjacent PPS/reference interval is shorter than the configured nominal band. |
| `reference_pps_cleared_after_requalification` | Reference cadence gate cleared after the documented requalification window. |
| `count_path_post_inhibit_invalid_window` | Count window became invalid after startup/control inhibit expired. |
| `count_path_requalified_clean_windows` | Count path requalified after the required consecutive clean windows. |
| `estimator_underqualified_sample_count` | Estimator lacks enough eligible observations. |
| `plant_model_unknown_gain` | Plant gain/sign/applicability is unavailable or unknown. |
| `actuator_request_clamped` | Requested DAC code crossed the active safety envelope and was clamped or rejected. |
| `actuator_write_result_unconfirmed` | Requested DAC state lacks a confirmed applied/write acknowledgement. |
| `service_plane_telemetry_drop` | Transport or host logging dropped non-timing telemetry; timing truth is not redefined. |

## Example

```csv
record_type,schema_version,diagnostic_seq,diagnostic_id,subsystem,severity,state,transition,diagnostic_confidence,reason_code,first_seen_ticks,last_seen_ticks,time_domain,evidence_refs,algorithm_version,config_version,control_effect,control_eligibility
DIAG,0,1,diag.reference.pps.short_interval,reference,WARN,active,raised,0.930,reference_pps_short_interval,16000000,17000000,rp2040_timer0,raw_events.csv:REF:1000-1001;run_manifest.json:pps_cadence_anomaly_gates,pps_diag_v0,manifest:h1_run_014,inhibit_actuation,not_eligible
```

## Relationship To Existing Records

- `REF`, `CNT`, `EVT`, `ENV`, `DAC`, and `STS` remain canonical inputs.
- `STS` remains the compatibility status surface.
- Future `EST` records hold numerical estimates with units and uncertainty.
- Future `CTL` records hold policy-governed preview or actuation decisions.
- `DIAG` records explain quality, health, applicability, and eligibility.
