# Hybrid 72-hour Attempt 4 controller terminal

## Verdict

Hybrid Attempt 4 is a **failed unchanged-CX322 physical qualification with a
valid controller-policy terminal and three host-platform escapes**. It is not a
72-hour result, and its qualified prefix must not be accumulated with another
run.

The run completed 40,849.108902 qualified seconds (11 h 20 min 49.109 s).
D14/D8 timing authority, D9 configuration/readback, D6 diagnostic loopback,
same-receiver GNSS metadata at 115200 baud, exact actuation propagation, queue
health and single serial ownership remained healthy. Twelve automatic
applications moved the DAC from setup code `0xA83C` through
`[0xA846, 0xA84D, 0xA84F, 0xA851, 0xA853, 0xA855, 0xA856, 0xA857,
0xA852, 0xA84D, 0xA852, 0xA84D]`, for 47 cumulative absolute codes. Seven
applications were phase-material. Ten responses were `healthy_detected`; two
were `healthy_indeterminate_near_resolution`.

At `2026-08-31T06:59:25Z`, decision 51 observed one negative accumulated D8
count over the selected 600-second window: `-0.001666666940 Hz`. The retained
plant gain converted that single-count frequency quantum to
`+4.807505405755` raw codes, rounded to a prospective `+5`-code request. The
preceding natural application tail was `-5, +5, -5`; the prospective `+5`
therefore satisfied the frozen `prospective_repeated_alternation` guard. The
firmware issued no unsafe request, retained `0xA84D` at DAC epoch 13 and
entered `FAIL_STATIC` exactly as implemented.

This is a quantization-driven maintenance limit cycle in the unchanged request
law, not evidence of D14, D8, D9, D6, GNSS, transport or plant instability.
The final prospective reversal followed approximately 2.75 hours without an
application, so it is not rapid chatter in wall time; nevertheless an
unchanged restart has no evidence-based reason to complete 72 hours.

## Host-platform escapes

Three independent host defects were exposed:

1. The live supervisor first recorded the intended Campaign18 transition
   `controller_authority_inhibited_acquisition_continues`, then its next
   start/arm check reinterpreted the same firmware `FAULT` record as a generic
   device fault. It submitted and delivered the priority abort and ended
   capture instead of retaining passive D14/D8 acquisition to the exact
   endpoint.
2. The Campaign18 profile identifier was absent from the phase-4 hybrid
   transaction dispatch. The host acknowledged all 12 response records but did
   not create the required replay attestations before those acknowledgements.
   Those contemporaneous proofs cannot be recreated after the fact.
3. Offline replay accepted the explicit Campaign18 `144`-application and
   `3,024`-code envelope but constructed its controller with the generic
   four-application/84-code policy. It therefore reported a false numerical
   divergence after the fourth application.

The supervisor now recognizes only the exact already-latched Campaign18
controller-local inhibit reasons in the first downstream arm/start consumer.
Unrecognized or unlatched firmware faults remain terminal. Campaign18 now uses
the phase-4 replay-attestation path and passes its compiled authority envelope
to replay. Offline replay composes an explicitly larger campaign envelope into
the controller while preserving lower external authority caps.

Focused regressions cover the controller-inhibit handoff and its first
downstream consumer, unrecognized-fault rejection, Campaign18 attestation
creation before ACK, authority propagation and replay beyond the generic
four-application limit.

## Preserved acquisition and superseding replay

- Run:
  `runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt4`
- Wall setup application: `2026-08-30T19:08:50Z`
- Qualified origin: `2026-08-30T19:38:35Z`
- Controller and host terminal: `2026-08-31T06:59:25Z`
- Qualified frontier: `692016476336` RP2040 timer ticks
- Qualified delta: `653585742432` ticks at 16 MHz
- Frozen failed seal SHA-256:
  `925993082994c9c5831444bc5b9866a3805e379d389f04789c50e171a2586bef`
- Registered evidence content SHA-256:
  `e6f5cf5e9d6138a9dad86698a45f98691903f923735df6d8660508048ca5b747`
- External superseding host replay:
  `runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt4_superseding_host_replay_v1.json`
- Superseding replay SHA-256:
  `d7c8210c8c49515739beea3b1103ac9855798e8d16ad1ae3c2fa08513d35717c`

The acquisition gate passed. With the corrected host tool, all 51 AHY
decisions, all 12 transaction histories and response horizons, all response
classifications, the exact AT2/AH2 lifecycle joins and the controller terminal
replay exactly. The superseding analysis remains failed solely because the 12
pre-ACK attestations are absent. It does not modify the sealed run or turn the
qualification into a pass.

The frozen primary decision remains
`cx322_d9_d6_72h_identity_or_evidence_fault` because finalization evidence is
incomplete. The separate physical-controller terminal is
`prospective_repeated_alternation`; the generic identity/evidence label must not
be presented as the physical cause.

## Successor boundary

Do not launch an unchanged Campaign18 Attempt 5. The alternation guard remains
valid and must not be removed, relaxed or reinterpreted after observing this
evidence. A changed request law is not another run of the frozen unchanged-
CX322 contract: it requires a new prospective policy, profile/run identity,
contract, build identity, bundle and activation.

The smallest candidate delta is the already selected architecture direction:
persistent same-sign accepted-window evidence plus provenance-bearing
fractional correction debt using the retained positive plant-gain envelope.
Exact aggregation, persistence, debt, integer-release, cadence and anti-windup
rules must be frozen before retained replay. Host and firmware parity, a replay
comparison against Attempt 4, response-attestation-before-ACK, more-than-four-
application authority, controller-inhibit acquisition continuity, exact
identity propagation and the complete operational path must pass before a new
72-hour physical entry.

