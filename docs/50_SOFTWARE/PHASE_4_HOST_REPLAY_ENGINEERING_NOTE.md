# Phase 4 Host Replay Engineering Note

## Decision

The Phase 4 host vertical slice is complete for deterministic, observe-only
estimation and correction preview. It adds no firmware, serial command, DAC
write, arming, or active-control path.

The authoritative safety state remains:

```text
plant model status.control_ready=false
plant model status.actuation_enabled=false
CTL preview_only=true
CTL actuation_authorized=false
CTL actionable=false
```

Firmware observe-only parity, live measurement qualification, and every active
actuation gate remain incomplete.

## Contracts and configuration

The normative derived record contracts are:

- `data_contracts/estimates_v1.csv.md`;
- `data_contracts/control_previews_v1.csv.md`.

Strict field ordering and semantic validation live with the existing host CSV
contracts in `host/otis_tools/contracts.py`. The default replay configuration
is `profiles/discipline/phase4_host_replay_v1.json`, with its machine-readable
shape in `schemas/phase4_replay_config_v1.schema.json`. The canonical
configuration is SHA-256 hashed into every `EST` and `CTL` row.

Unknown numerical values remain empty CSV fields. Reason fields use stable,
non-empty machine codes. In particular, observation validity, diagnostic
health, estimator confidence, model applicability, and preview eligibility are
not collapsed into one flag.

## Deterministic adapter and estimator

`host.otis_tools.phase4_replay` resolves source files through the run manifest
and validates their existing contracts before replay. It adapts:

- canonical `REF` rows;
- canonical `CNT` rows;
- compatibility `STS` diagnostics;
- latest confirmed `DAC` evidence;
- manifest domain, oscillator, topology, and backend identity;
- plant-model version 3.

Accepted reference intervals qualify the count gate and, when the gate
boundaries match reference captures, define its elapsed reference time.
Otherwise the latest accepted reference interval calibrates the local capture
tick rate. Reference flags, age, cadence, and continuity remain explicit.
Count zero, saturation, flags, age, and sequence continuity remain separate
conclusions.

The estimator is a bounded arithmetic mean of accepted frequency observations.
Its confidence is based on configured sample count, dispersion, observation
age, continuity, diagnostic health, and startup qualification. Drift
estimation is present only as an unavailable contract field and is forced off
by both configuration validation and the `EST` validator.

## Observe-only state and preview policy

The implemented state subset uses the roadmap vocabulary:

```text
BOOT -> WARMUP_INHIBIT -> QUALIFYING -> ACQUIRE_PREVIEW
                                      -> HOLDOVER_PREVIEW
                                      -> RECOVER_PREVIEW
                                      -> FAULT
```

Reference loss enters preview holdover; return requires clean-window
requalification. A zero, saturated, missing, stale, discontinuous, or otherwise
invalid count after qualification latches `FAULT` for the replay.

The preview policy requires:

- an estimator-eligible `EST`;
- healthy timing-path diagnostics;
- a valid model-version-3 artifact;
- matching topology and measurement backend identity in the manifest;
- an applied DAC code within model applicability;
- a count sequence not excluded by the model;
- a finite, non-zero local `Hz/code` gain.

It converts frequency error through the model sign/gain, rounds
deterministically, limits the signed movement by
`manual_preview_max_step_codes`, and then clamps the result to the disabled
candidate automatic range. Both limit effects are recorded. A bounded proposal
is available for review only; it is never actionable.

## Replay command and artifact boundary

From the repository root:

```bash
python3 -m host.otis_tools.phase4_replay /path/to/local/run
```

Optional `--plant-model` and `--config` arguments select explicit versioned
inputs. The default inputs are the current Run 020-backed model and the Phase 4
host profile.

For a preview to be model-applicable, the run manifest must bind its replay
input identity explicitly:

```json
{
  "phase4_replay": {
    "hardware_topology_id": "h1_run_020_g17_reworked_d14_d10_pps_witness",
    "measurement_backend": "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE with LOCAL_PPS_INTERPOLATED host estimator"
  }
}
```

Missing or mismatched identity still permits EST replay but inhibits the CTL
proposal. It never falls back to assumed topology.

The command writes only:

```text
<run>/derived/phase4_replay_v1/estimates_v1.csv
<run>/derived/phase4_replay_v1/control_previews_v1.csv
<run>/derived/phase4_replay_v1/replay_report_v1.json
```

Files outside `derived/` are hashed before and after replay. Any change aborts
the command. Existing managed outputs are accepted only when byte-identical;
the command refuses to replace a non-identical artifact. The report records
source hashes, derived hashes, configuration, state transitions, reason-code
counts, model identity, and the disabled phase boundary.

`runs/` remains ignored and locally retained. Replay does not add or force-add
run evidence.

## Verification fixtures

The focused fixture matrix covers:

- constant free-running frequency offset;
- a DAC-state change interpreted through Run 020 H1 gain;
- startup inhibit and clean-window qualification;
- PPS outlier, loss, staleness, and return;
- zero, saturated, missing/sequence-discontinuous, and stale count evidence;
- post-qualification measurement fault;
- unavailable and invalid plant models;
- model identity mismatch, excluded sequence, and out-of-applicability input;
- correction beyond both maximum preview step and candidate range;
- repeated execution with byte-identical EST, CTL, and report products;
- source-evidence hashes unchanged before and after.

Verification on 29 July 2026:

```text
python3 -m pytest -q tests/test_phase4_replay.py tests/test_diagnostics_contract.py tests/test_plant_model.py tests/test_run_020_preflight.py
32 passed, 2 skipped in 0.28s

python3 -m pytest -q
175 passed, 2 skipped in 7.95s
```

The two skips are the legacy preflight checks that execute the locally retained
Run 020 operator script when that ignored run is present. A fresh clone now
skips them in accordance with the repository evidence policy instead of
failing because `runs/` is absent.

## Risk assessment

| Risk | Assessment and mitigation |
|---|---|
| Preview mistaken for permission to actuate | Contract validation forces preview-only, unauthorized, and non-actionable fields; no write/serial module is imported. |
| Candidate range mistaken for a safe active range | It is labelled disabled in contracts and policy; both model readiness flags remain false. |
| Bad PPS accepted because the closing edge looks clean | Replay checks all available reference intervals spanning the current count gate, plus freshness and flags. |
| Unknown diagnostic or DAC state silently accepted | Unknown remains explicit and inhibits preview. |
| Historical topology replayed with the Run 020 model | Manifest topology/backend identity must match the model; missing identity inhibits preview. |
| Invalid count after acquisition retains an old proposal | Post-qualification count faults latch `FAULT`; inhibited CTL rows contain no proposed code. |
| Model dynamics overstated | Preview uses only the static local gain and existing manual step/range limits; no settling controller, PI/PID, Kalman, thermal, or holdover predictor is implemented. |
| Replay damages evidence | Non-derived files are content-hashed before/after; managed outputs never replace different bytes. |
| Host/firmware meanings diverge | Firmware parity is explicitly the next gate and remains unclaimed. |

## Gate effect

This change passes roadmap milestone M2, host observe-only discipline replay.
It does not pass M3 firmware parity, M4 live discipline measurement, or any
guarded-actuation milestone.

Subsequent Phase 4 work implements and fixture-qualifies the live firmware
engine; see `PHASE_4_LIVE_OBSERVE_ONLY_ENGINEERING_NOTE.md`. M3 still remains
open pending target upload, deliberate service-plane load/reconnect testing,
and the required long live observe-only run.
