# Phase 5 PPS-Gated Backend Qualification Report

## Decision

**Qualification result: failed — exit gate not met because Step B bench
evidence is unavailable.**

This is an evidence-gate failure, not a finding that the backend's nominal
hardware measurements are bad. Repository qualification preparation is
complete enough to begin the documented bench procedure after the Phase 4
contracts are merged. Synthetic tests and successful compilation cannot, by
themselves, qualify metrology.

The authoritative safety state is unchanged:

```text
status.control_ready=false
status.actuation_enabled=false
no PPS/count-derived DAC write is authorized
```

## Repository audit conclusion

The implementation retains one D14 PPS authority and one PIO oscillator-count
owner. The count backend consumes the same `OtisCapturedEdge` used for the raw
`REF` row and does not poll or timestamp D14 independently.

The audit found and corrected these concrete defects:

1. PPS boundary quality flags were preserved on `CNT` but did not invalidate
   the reference side of the window.
2. `pps_gate.valid` collapsed reference and oscillator-count validity.
3. Absence of the first PPS after boot was not timed out.
4. A rollover-closing `CNT` emitted an extended close value rather than the raw
   authoritative `REF.timestamp_ticks`.
5. Duplicate PPS had no physically exercisable classification band.
6. Aperture and reference-frequency uncertainty had no explicit unavailable
   hooks.
7. The counter was restarted only after derived arithmetic and serial status
   emission, making inter-gate dead time depend on service-plane activity.
8. A rejected boundary could immediately become the opening boundary of a
   nominally clean ratio window.
9. Host comparison admitted an independently named estimator with a
   mismatched backend, did not require the same source domain, and included
   valid rows outside the declared UTC comparison interval.
10. The checked-in Phase 4 live adapter used non-modular raw gate subtraction
    at rollover, while both live and host replay could collapse a
    reference-only `CNT` flag into count invalidity.

The corrected additive telemetry exposes:

- `pps_gate/reference_validity` and `pps_gate/reference_reason`;
- `pps_gate/count_validity` and `pps_gate/count_reason`;
- `pps_gate/count_resolution_edges=1`;
- `pps_gate/counter_aperture_uncertainty_ns=unavailable`;
- `pps_gate/reference_frequency_uncertainty_ppb=unavailable`.

The counter now restarts immediately after stop/read, before calculation or
reporting. A rejected edge causes one explicit
`reference_previous_boundary_invalid` re-anchoring window. Phase 4 live and
host replay use modular PPS-gate arithmetic and preserve independent
reference/count validity.

No raw bounded observation is suppressed, no PPS authority changed, and no
actuation path was added.

## Repository evidence

Deterministic repository fixtures cover nominal adjacent boundaries, raw timer
rollover, duplicate/short/long/missing PPS, boundary flags, zero and saturated
count arithmetic, startup/recovery telemetry, estimator/backend/source typing,
independent comparison, service-plane segments, immutable derived output, and
unavailable uncertainty.

The qualification analyser requires:

- explicit `pps_gated_ratio_count_v1` candidate typing;
- an authorised, separately typed independent estimator;
- exact source-domain agreement rather than mixed FC0/PIO/PPS rows;
- an authorised estimator/backend pair corroborated by boot `STS` identity and
  interval configuration;
- exact firmware name/version/config/40-hex commit agreement between boot
  telemetry and the sealed candidate manifest;
- exact candidate and independent count-sequence ranges within the shared UTC
  comparison interval;
- 100% adjacent authoritative `REF` boundary traceability;
- separate reference/count validity and their joint measurement eligibility;
- safe fault reason and inhibition evidence;
- startup-clear and post-fault recovery evidence;
- at least 600 eligible observations in every declared baseline/load segment;
- complete sealed bench evidence;
- explicit uncertainty components.

Synthetic manifests always produce `repository_validation_only`. A bench run
with missing or failed gates produces `failed`. Within the v1 10 MHz,
one-second applicability envelope, a complete passing run produces
`qualified_with_limits` because 32-bit saturation remains a synthetic-only
negative case.

## Verification completed

Repository verification on 29 July 2026:

```text
python3 -m pytest -q
215 passed, 2 skipped in 12.56s

python3 firmware/arduino/validation/scripts/run_no_hardware_checks.py
PASS: 215 tests passed, 2 local-Run-020 preflight tests skipped;
      all three wire fixtures passed;
      example run validation and reporting completed
```

The Arduino CLI matrix also compiled successfully for:

- default H1;
- Phase 5 PPS-gated candidate;
- Phase 5 PPS-gated candidate with Phase 4 live preview enabled;
- synthetic USB;
- GPIO loopback;
- GPS PPS IRQ;
- GPS PPS sparse PIO FIFO;
- TCXO FC0;
- H1 PIO long-gate;
- divided GPIO IRQ count;
- combined sparse-PIO capture plus PIO long-gate.

These are repository/compile results only. No board was uploaded or booted and
no Phase 5 bench capture was performed.

## Bench evidence and applicability

No local run under `runs/` currently contains a sealed PPS-gated candidate plus
simultaneous authorised independent comparison satisfying the v1 profile.
Therefore bias, jitter, service-load shift, aperture uncertainty, combined
uncertainty, fault-detection completeness, and recovery are unavailable.

The backend must not yet be described as trusted metrology. The intended
applicability envelope and exact acceptance procedure are frozen in
`PHASE_5_PPS_GATED_BACKEND_BENCH_RUNBOOK.md`.

## Remaining exit-gate work

1. Merge the Phase 4 contracts into the target integration branch.
2. Execute the candidate and independent simultaneous bench capture.
3. Exercise the documented safe faults and separate reconnect run.
4. Measure aperture behavior and populate only evidence-backed uncertainty.
5. Seal both local runs and execute the deterministic qualification analyser.
6. Review the compact result and update this decision to
   `qualified_with_limits` or retain `failed`.

Until those steps pass, roadmap/readiness status remains **failed / not
qualified**, and active steering remains prohibited.
