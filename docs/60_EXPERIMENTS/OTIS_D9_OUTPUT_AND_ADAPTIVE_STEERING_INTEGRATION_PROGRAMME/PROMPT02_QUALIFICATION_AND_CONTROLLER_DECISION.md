# Prompt 02 Qualification and Controller-Decision Closure

## Terminal

Prompt 02 is closed from the retained physical qualification package
`runs/d9_adaptive_steering_integration_20260828/prompt02/qualification_readback_repair`.
The machine-readable reviewed decision is
[`prompt02_controller_decision_v1.json`](prompt02_controller_decision_v1.json),
semantic SHA-256
`3ab6a0a004788e5856eabe27b45956160ec2b66d05a8a42237c7cf4325bda82f`.
Its exact terminals are:

| Boundary | Terminal |
|---|---|
| D9 delivered output | `output_function_correct_but_waveform_evidence_incomplete` |
| D6 diagnostic monitor | `d6_forwarded_clock_monitor_qualified_as_diagnostic_only` |
| Authoritative D14/D8 acquisition | `d14_d8_acquisition_healthy` |
| Frequency-only output soak | `frequency_only_d9_output_soak_incomplete` |
| CX322 integration decision | `cx322_integration_blocked_by_d9_output_gate` |

The controller decision retains the unchanged CX322 candidate without retuning
or selecting either rejected correction-debt candidate. It is a gate result,
not a claim that D9 has disproved the D14/D8 measurement, estimator, or
frequency-only request law.

## Retained evidence and repaired identity

The first analysis is retained, not overwritten. It ended at
`readiness_invalid_due_to_identity_or_verification_failure` because a generic
capture manifest identified `cx319_tight_lower`, while the retained firmware
boot status identified the exact D9/D6 profile. This was an evidence-identity
failure, not a D14/D8 capture failure or a D9 electrical failure.

The repair created derived manifests that retain the original capture manifest,
its SHA-256, the reason for derivation, and the boot profile as the
authoritative identity. The corrected analysis reached
`d9_d6_candidate_bundle_ready_for_physical_authority` under
`OTIS_D9_D6_READINESS_CONTRACT_V1` semantic SHA-256
`a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d`.

| Stratum | Derived manifest SHA-256 | Original capture-manifest SHA-256 |
|---|---|---|
| D9 disabled baseline | `15db867d2b57278953e87fa513fdfcc21293615844b9269b18641863ccaa1c43` | `ec5317d2d395715a4c38d4531c2535c30ac5ef2feda32f9e8fc517000bbc8934` |
| D9 output, D6 monitor disabled | `032bf649e256a45fb906697d3814584a34dd632076201080aa24785c24715af3` | `ee8367d4929ea31bad61e16d68f868520eb30fb295e214928bd08a0e05726638` |
| D9 output with D6 monitor | `cef59902f47ce42c48cdecc92fe0cdfeb80f5dd37de1e8348da8e0afccac209f` | `9445ec6103f21f4c4dd8dd50c25aded73333d9b99d76c0e2d0a257e05342c929` |

The retained corrected analysis SHA-256 is
`41bed1fa23fd4984bb19baf43389244ce9a8122c028e05fc165e1d1a07df27a3`;
its report SHA-256 is
`055a958e81317f1c9091dc2fa26577ea5243b83cd6586136fae6d31a9b772063`.
The retained failed-attempt analysis SHA-256 is
`dda63b9bdee053a20308b34aa0f19292a2f282de8513199aead0468d020b5d14`.

## Observed and not observed

Across the corrected package, all authoritative D14/D8 intervals accepted by
the analyzer were continuous and status-clean: 60 baseline intervals, 59 D9
output intervals, and 90 D9-plus-D6 intervals. The monitor stratum produced
90 same-reference D8:D6 comparisons. Their absolute count difference was zero
or one cycle, within the frozen two-cycle diagnostic tolerance. This qualifies
the D6 monitor only as a D14-gated digital continuity sidecar.

No oscilloscope export or independently referenced frequency-counter evidence
was retained. The available multimeter cannot establish D9 high/low levels at
speed, duty cycle, rise/fall behavior, ringing, propagation delay, jitter,
load sensitivity, or independently referenced frequency. D6 count agreement
cannot supply any of those missing facts. The direct output is therefore not
`qualified_10mhz_forwarded`, and the 24-hour frequency-only soak was not
started or extended.

## Final physical and authority state

The board was left in the exact D9-disabled baseline profile. The DAC code is
unknown after the power-cycle; it was neither written nor restored. No receiver
command was issued. The host carrier baud was 115200. D9 and D6 remained
zero-authority: neither entered D14/D8 validity, estimation, control
eligibility, actuator requests, abort, or a terminal decision.

Any future direct-output qualification must use a separately frozen and
authorized waveform/load/instrument procedure. It must re-establish exact
identity and retain primary external evidence; it must not reinterpret this
D6 result as a waveform qualification or resume the incomplete soak.
