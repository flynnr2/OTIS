# OTIS D9 Output and Adaptive-Steering Integration Programme

## Status

The historical Prompt 02–04 terminals remain valid for their frozen inputs.
Subsequent explicit operator directions now authorize two separate engineering
long runs despite the unavailable oscilloscope/counter waveform evidence:

- the 24-hour frequency-only programme bound by
  [`d9_d6_frequency_only_digital_endurance_contract_v1.json`](d9_d6_frequency_only_digital_endurance_contract_v1.json);
- the 72-hour unchanged-CX322 hybrid programme bound by
  [`cx322_d9_d6_72h_integrated_engineering_contract_v1.json`](cx322_d9_d6_72h_integrated_engineering_contract_v1.json).

The frequency-only run has passed by provenance-linked host-only supersession.
All four 72-hour hybrid attempts stopped before the endpoint. Attempt 3
isolated a firmware ACTIVE-status admission defect after 8,460 qualified
seconds of otherwise healthy live hybrid steering. Attempt 4 then retained
40,849.108902 qualified seconds with healthy timing/output/GNSS evidence and
exactly exposed a quantization-driven `prospective_repeated_alternation`
terminal in the unchanged request law, plus three host-platform escapes. An
unchanged Campaign18 restart is not successor-ready. See
[`05_FREQUENCY_ONLY_24H_ATTEMPT9_RESULT_AND_72H_READINESS.md`](05_FREQUENCY_ONLY_24H_ATTEMPT9_RESULT_AND_72H_READINESS.md),
[`06_HYBRID_72H_ATTEMPT2_RESULT_AND_RESTART_READINESS.md`](06_HYBRID_72H_ATTEMPT2_RESULT_AND_RESTART_READINESS.md)
and
[`07_HYBRID_72H_ATTEMPT3_TELEMETRY_ADMISSION_TERMINAL.md`](07_HYBRID_72H_ATTEMPT3_TELEMETRY_ADMISSION_TERMINAL.md),
then
[`08_HYBRID_72H_ATTEMPT4_CONTROLLER_TERMINAL.md`](08_HYBRID_72H_ATTEMPT4_CONTROLLER_TERMINAL.md).

This authority supersedes the original Gate B waveform dependency and the
Prompt 04 stop boundary only for these explicitly identified engineering
acquisitions. It does not change the Prompt 02 waveform terminal, qualify the
delivered D9 waveform or load, or promote a public output claim. Oscilloscope
and independently referenced counter evidence remain unknown and deferred,
not failed and not required for the non-waveform tests.

Both live entries require fresh `capture_device --auto-detect` for every
enumeration, exactly one device at 115200 baud, exact post-attachment D9
source/divider/GPIO/readback, D14/D8 continuity and control eligibility, D6
present or explicitly local-degraded, same-receiver GNSS metadata, exact
DAC-code/epoch identity, one serial owner and an independent abort path. The
bench connection is D9 to D6 through a 1 kΩ series resistor. D14 remains the
sole timing reference, D8 the sole oscillator/control truth, D9 an output, and
D6 a fail-local zero-authority diagnostic.

Every exact live firmware start first executes the ordinary configuration-blind
GNSS bootstrap: the fixed set-115200 packet is sent once in the frozen
9600 then 115200 order, with 1200 ms receiver-side settle after each physical
UART drain, followed by permanent UART0 operation and qualification at 115200. No
host or runtime baud command, response-driven discovery, fallback scan or
post-bootstrap promotion retry is permitted. Pre-write readiness requires the
exact ordered bootstrap completions/counters/rate mask, local UART baud and
epoch, zero post-bootstrap PMTK251 attempts or baud changes, fresh same-receiver identity/configuration and
current metadata. A bootstrap or qualification failure keeps DAC authority at
zero while D14/D8 and D9/D6 acquisition continue.

The 24-hour authority envelope permits at most 48 automatic applications,
1,008 cumulative absolute codes and 49 total physical writes including setup.
The 72-hour envelope permits at most 144 automatic applications, 3,024
cumulative absolute codes and 145 total writes including setup. Both retain a
21-code maximum step, 1,800-second minimum application cadence, one outstanding
transaction, no retry or restoration, and an exact 1,500-second endpoint
response reserve. These limits are cadence-derived safety ceilings, never
targets or early completion conditions; authority remains available throughout
the qualified interval outside the endpoint reserve.

A naturally occurring recoverable GNSS serial-metadata anomaly enters bounded
`GNSS_METADATA_HOLD`: D14/D8 capture, estimation, phase accumulation and any
already-required response continue, the last confirmed DAC code is retained,
and no new request is issued. Rearm requires fresh metadata from the same
receiver followed by causally later exact D14/D8/session/code/epoch evidence.
The programme does not deliberately create a physical GNSS anomaly. Actual D14
loss remains a separate authoritative fault.

The earlier one-application engineering smoke contract remains preserved as
[`cx322_d9_d6_integration_engineering_contract_v1.json`](cx322_d9_d6_integration_engineering_contract_v1.json)
and does not constrain either long-run authority envelope.

Prompt 04 has closed at
`non_effective_semantics_verified_promotion_blocked_by_d9_gate`. The complete
current Release gate, exact separated builds, retained D9/D6 operational-path
evidence, and non-effective Prompt 03 semantics have been verified without
creating a combined D9/D6/CX322 profile or trial proposal. See
[`PROMPT04_BLOCKED_PROMOTION_VERIFICATION.md`](PROMPT04_BLOCKED_PROMOTION_VERIFICATION.md).

Prompt 02 closed with the D9 waveform gate incomplete and the unchanged CX322
integration blocked. See
[`PROMPT02_QUALIFICATION_AND_CONTROLLER_DECISION.md`](PROMPT02_QUALIFICATION_AND_CONTROLLER_DECISION.md)
and its machine-readable
[`prompt02_controller_decision_v1.json`](prompt02_controller_decision_v1.json).
Those historical artifacts grant no further authority. Current engineering
bench authority comes only from the later operator instruction recorded in the
integrated engineering contract.

The bundle carries the completed cross-campaign offline decision into two
decision-bearing outcomes:

1. qualify or reject the direct D8/GPIN0 to D9/GPOUT0 forwarded 10 MHz output,
   with D6 as a diagnostic zero-authority monitor, then establish a sustained
   frequency-only output baseline; and
2. implement the confirmed coherent adaptive FLL/PLL operating semantics around
   the retained CX322 request law, followed by exact-build verification and the
   complete no-hardware operational-path rehearsal needed before a separately
   authorized integrated trial.

The physical output gate deliberately precedes controller promotion. The first
D9 soak uses only the already-qualified reactive FLL. This isolates output
forwarding, load and measurement non-interference from hybrid-policy behavior.
Only after that gate may the unchanged CX322 coherent FLL/PLL law become the
integrated candidate. Its FLL term minimizes qualified D8 frequency error
relative to D14; its slower PLL term requests a bounded temporary frequency
bias to reduce same-epoch D14-relative phase movement. It does not chase every
one-second count fluctuation or assume one permanent equilibrium DAC code.

## Decision-bearing handoff

The prompt bundle is bound to the decision-bearing V2 offline study:

- contract SHA-256:
  `b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f`;
- derived manifest SHA-256:
  `705361d252782c911cea63bfca691691c6ab045956942f057f87db31827b4816`;
- tracked report SHA-256:
  `c411e44042162192228b04c4ebd567b90d73ddd77344f9d1d6f494ada863e9e5`;
- analysis tool-bundle SHA-256:
  `fbbcb152880b0079e97eb9b9d216e292aa805ceb829e78996c4e06dee282b1ca`;
- terminal:
  `provisional_cx322_unchanged_pending_d9_gate`.

V1 is superseded and cannot be used for promotion. The two changed
correction-debt candidates are not selectable because their frozen
post-divergence model failed validation. D9 evidence may confirm or block the
unchanged CX322 integration; it may not retune, rescue or substitute either
changed candidate.

## Execution order

Execute these prompts in order:

1. `00_MASTER_SEQUENCED_PROMPT.md` — durable programme contract, authority and
   cross-stage gates.
2. `01_INTEGRATION_BASE_AND_D9_D6_READINESS_PROMPT.md` — establish the exact
   post-GNSS-soak integration base, implement D9/D6 and freeze a non-effective
   physical bundle. No bench access.
3. `02_D9_WAVEFORM_AND_FREQUENCY_ONLY_SOAK_PROMPT.md` — separately authorized
   D9/D6 waveform, load and non-interference qualification followed by the
   finite frequency-only output soak.
4. `03_CONFIRMED_HYBRID_STEERING_SEMANTICS_PROMPT.md` — close the provisional
   controller decision without retuning, then implement transaction-aware
   metadata hold, phase-to-FLL fallback, low-efficiency inhibit and isolated
   shadow semantics in the existing Python/C++ parity path.
5. `04_EXACT_BUILD_AND_OPERATIONAL_REHEARSAL_PROMPT.md` — run proportionate
   verification, build the exact profile, exercise the complete no-hardware
   operational path and freeze a non-effective integrated-trial proposal.

Prompt 03 remains non-effective safety architecture. The later engineering
profile does not compile or select those reference semantics and does not
authorize a renewed D9/FLL soak.

Prompt 03 has now reached
`operational_semantics_implemented_promotion_blocked_by_d9_gate`. See
[`PROMPT03_NON_EFFECTIVE_OPERATIONAL_SEMANTICS.md`](PROMPT03_NON_EFFECTIVE_OPERATIONAL_SEMANTICS.md).

Prompt 04 verified the resulting historical non-effective boundary. Its three exact
builds remain intentionally separated: non-actuating D9/D6, compile-only
unqualified frequency control, and retained standalone CX322. The later
engineering profile and authority are a superseding, separately identified
bench programme; they do not alter that historical result or create the
Prompt 04 72-hour promotion proposal.

## Stop boundary

The stop boundary above is the historical Prompt 04 boundary. The operator has
since supplied the separate authority decision required there. Neither revised
long run may start from that instruction alone: its current exact source,
firmware binary, contract, capture inventory, command envelope, abort path,
analyzer, finalizer and evidence destinations must first be frozen into an
effective activation, and the same operationally significant bundle must pass
the complete real-process rehearsal. A changed operational input invalidates
that activation and requires the shortest affected rebuild or rehearsal before
bench entry.
