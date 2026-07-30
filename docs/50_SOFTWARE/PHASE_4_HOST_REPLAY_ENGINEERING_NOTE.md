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

Host/live estimator parity is covered by native fixtures. Live measurement
qualification, physical gate-aperture qualification, and every active
actuation gate remain incomplete.

## Verified pre-change finding

The mismatch was confirmed before correction:

- `profiles/plant_models/cx317_h1_bench_v2.json`,
  `plant_response.applicability.measurement_backend`, declared the PIO
  long-gate backend "with LOCAL_PPS_INTERPOLATED host estimator."
- `host/otis_tools/h1_characterize.py`,
  `LocalPpsTimeMapper.map_tick()` and `estimate_gate()`, derived the Run 020
  frequency observations by mapping `gate_open_ticks` and `gate_close_ticks`
  independently through the accepted-PPS segment, then calculating
  `counted_edges / (pps_time_close - pps_time_open)`. Those observations feed
  dwell medians, centre brackets, `Hz/code`/`Hz/V` gain, settling, and crossing
  calculations used by the plant model.
- the former `host/otis_tools/phase4_replay.py::_frequency_observation()`
  handled exactly PPS-aligned endpoints by reference index, but for a
  non-aligned gate used only the last two PPS observations at or before the
  close: `r = (pps_last - pps_previous) / nominal_pps_seconds`, then
  `f = counted_edges / ((close_ticks - open_ticks) / r)`. With fewer than two
  PPS observations it used nominal capture-domain rate.
- the former live path in
  `firmware/arduino/otis_nano_rp2040_connect/otis_phase4_observe_preview.cpp`,
  `otis_phase4_observe_preview_on_count()`, always used
  `last_reference_ticks - previous_reference_ticks` as the tick rate for the
  complete gate. It had no independent open-boundary mapping.

Thus the H1 method used two independently selected bracketing PPS pairs, while
Phase 4 generally used one closing-adjacent interval for both boundaries.
They agree only in special cases, such as uniform PPS intervals or exactly
aligned endpoints, and are materially different estimators.

At review time H1 unwrapped `rp2040_timer0` rollover before interpolation and
split support at cadence-rejected intervals. Phase 4 host also unwrapped input
ticks, while live used modular gate arithmetic plus a run-wide reference epoch.
Host/live checked reference flags, cadence, age, and monotonicity, but those
validity checks did not change the one-interval frequency formula. The
corrected contract now makes clean flags, increasing sequence, 0.8..1.2 s
cadence, one timing domain, no cross-gap interpolation, and no extrapolation
part of the estimator itself.

## Contracts and configuration

The normative derived record contracts are:

- `data_contracts/estimates_v1.csv.md`;
- `data_contracts/control_previews_v1.csv.md`.

Strict field ordering and semantic validation live with the existing host CSV
contracts in `host/otis_tools/contracts.py`. The default replay configuration
is `profiles/discipline/phase4_host_replay_v2.json`, with its machine-readable
shape in `schemas/phase4_replay_config_v2.schema.json`. The canonical
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
- plant-model version 4.

`LOCAL_PPS_BOUNDARY_INTERPOLATED_V1` is the only model-applicable observation
method. Let `P(t)` be a piecewise-linear mapping between adjacent accepted PPS
captures. For count-window ticks `t0`, `t1` and edge count `N`:

```text
P(t0) = P0 + (t0 - T0) * (P1 - P0) / (T1 - T0)
P(t1) = Q0 + (t1 - U0) * (Q1 - Q0) / (U1 - U0)
gate_reference_seconds = P(t1) - P(t0)
frequency_hz = N / gate_reference_seconds
```

`T0,T1` independently surround the start; `U0,U1` independently surround the
end. They may be different PPS pairs many intervals apart. The method never
substitutes raw gate ticks multiplied by one recent PPS scale factor.

Accepted support has clean reference flags, strictly increasing reference
sequence, one timing domain, and adjacent cadence in 0.8..1.2 nominal seconds.
RP2040 capture ticks are unwrapped before mapping. Rejected intervals split
support into separate segments. No extrapolation is allowed. Missing preceding
or following support, a segment crossing, support loss/overwrite, invalid
count window, non-positive mapped duration, or impossible result makes the
frequency observation unavailable and preview-ineligible.

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
- a valid model-version-4 artifact;
- an estimator-method contract equal to the executed method and definition hash;
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
    "measurement_backend": "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE"
  }
}
```

Missing or mismatched identity still permits EST replay but inhibits the CTL
proposal. It never falls back to assumed topology.

The command writes only:

```text
<run>/derived/phase4_replay_v2/estimates_v1.csv
<run>/derived/phase4_replay_v2/control_previews_v1.csv
<run>/derived/phase4_replay_v2/replay_report_v2.json
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

The fixture matrix additionally covers aligned and non-aligned boundaries,
different local PPS intervals at each boundary, jitter/non-uniform cadence,
many-interval gates, rollover, missing support, flagged/anomalous PPS,
sequence regression, invalid windows, a deliberate one-interval-scaling
counterexample, and exact native-firmware estimator parity.

## Historical compatibility

Existing `derived/phase4_replay_v1/` outputs retain estimator identity
`phase4_frequency_mean_v1`. That algorithm used the latest adjacent PPS
interval to scale a whole non-aligned count gate and could fall back to the
nominal capture rate. It is deliberately not relabelled as the corrected
method and is not applicable to the version-4 plant model.

Corrected products are regenerated only under `derived/phase4_replay_v2/`.
They carry policy identity `phase4_observe_preview_v2`; the historical v1
policy identity is not reused for the strengthened applicability check.
Raw `REF` and `CNT` evidence is never changed. The old
`cx317_h1_bench_v2.json` model remains historical; the current
`cx317_h1_bench_v3.json` / model version 4 carries the method contract.

Verification is run with:

```text
python3 -m pytest -q tests/test_phase4_boundary_estimator.py \
  tests/test_phase4_replay.py tests/test_phase4_firmware_parity.py
```

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
| Host/firmware meanings diverge | The exact production C++ estimator is compiled on the host and compared with replay for valid results, invalid results, reason codes, and boundary provenance. |
| Semantic correction mistaken for aperture qualification | Explicitly separate: estimator consistency is corrected; physical PPS-gated aperture, latency, and uncertainty qualification remain unresolved. |

## Gate effect

This change corrects the Phase 4 estimator semantics and deterministic
host/live parity. It does not qualify the physical gate aperture, establish
traceable uncertainty, pass the long live measurement gate, or authorize any
guarded-actuation milestone.

Subsequent Phase 4 work implements and fixture-qualifies the live firmware
engine; see `PHASE_4_LIVE_OBSERVE_ONLY_ENGINEERING_NOTE.md`. M3 still remains
open pending target upload, deliberate service-plane load/reconnect testing,
and the required long live observe-only run.
