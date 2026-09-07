# Hybrid 72-Hour Attempt 11 Host-Replay Hold

## Verdict

Campaign19 Attempt 11 retained an immutable physical acquisition whose active
control prefix is exactly reproducible, but it did not establish the required
qualified 72-hour endpoint or a clean disarmed terminal. It is an interrupted
campaign caused by a deterministic host replay defect, not a scientific
rejection of the CX323 controller, a firmware decision mismatch, or a D14/D8
capture failure.

The authoritative retained package remains
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt11`.
It was not modified during recovery. A provenance-linked superseding analysis
was written separately as
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt11_superseding_host_replay_v1.json`.
Its file SHA-256 is
`791e9b0aaed70f88556606b1a371fa2e50a0e674928b2083056649b98ac2ada2`;
its semantic seal SHA-256 is
`abebef32a8a66acd1afaf7aefbebd465a0d4eb7aeeb30ebf745c216fb814c164`.
It explicitly supersedes original report file SHA-256
`d9a4aa97019a338c724279f5c6e3cc6b0fa66a3179af14e4a4dee074da116226`
and semantic seal SHA-256
`e7704a424a97cd8581ef0468d19ba6ea2477121cd5a6f96400758747602c4574`.

## Physical result and boundary

Setup established `0xA84D` at DAC epoch 1. Eleven automatic applications then
moved 19 cumulative absolute codes, ending at the last confirmed code `0xA84E`
(43,086), DAC epoch 12. Ten applications were phase-material and one was
frequency-only. All eleven retained response records classify as healthy;
ten are `healthy_indeterminate_near_resolution` and one is
`healthy_detected`. The first observational checkpoint passed and later
authority was causally released.

The supervisor entered a zero-authority host verification hold at
2026-09-03T12:47:59Z after response transaction 11. It issued no further
correction. Capture and the sole serial owner continued until approximately
2026-09-06T03:24Z, so the last confirmed code was retained for about 62 hours
and 36 minutes after the hold. The retained phase stream reaches reference
sequence 280,990, but the authoritative supervisor qualification frontier was
only 53,231 accepted apertures when the hold began. Later raw capture cannot be
retrospectively relabelled as the missing supervised endpoint.

The superseding analysis therefore retains these formal failures:

- no exact 259,200-qualified-D14/D8-aperture endpoint;
- no durable capsule produced during the live run for transaction 11;
- no final disarmed, evidence-clear, no-outstanding-static-code terminal.

Acquisition and offline-finalization gates remain false. The available
performance comparisons pass their frozen thresholds, but they are incomplete
prefix results and do not qualify or reject the controller over 72 hours.

## Root cause and causal reconstruction

The first and only original replay divergence was AHM record 87, controller
decision 66. A zero-containing decision interval had correctly cleared the
current transaction's committed correction debt in firmware. The independent
host guard nevertheless formed the candidate total with the pre-decision debt
of -500,000,000,000 picocodes. It therefore compared unlike state frontiers
and latched an aggregate mismatch. The next response query, transaction 11 at
AHM record 45, encountered that stale mismatch and entered the host hold before
writing its replay attestation.

The bounded repair uses decision-effective committed debt when checking the
candidate total. It also replays each response against its causal AHM prefix
and only the AHY decision records and ACT response records reachable at that
frontier. This prevents later, valid records from changing an earlier response
attestation.

Over the unchanged snapshot, the repaired analyzer reports:

- 448 of 448 active-hybrid decisions reproduced exactly;
- all response checkpoints at decision sequences 14, 16, 18, 20, 50, 53, 55,
  58, 60, 64 and 72 passed;
- all eleven response attestations and classifiers reproduced exactly;
- transaction 11 reconstructed at retained record sequence 45 with replayed
  attestation SHA-256
  `940ab39359adfb3e37366f852a0b9afd41f4e20591feddeb8393e0d106ded44a`;
- no retained-input failure, missing source artifact, or snapshot mutation.

Attestations 1--10 remain valid for their original causal prefixes. Their
embedded analyzer identity is recorded as superseded rather than silently
rewritten. Transaction 11's reconstructed attestation is new offline evidence,
not a claim that the live host durably wrote the missing capsule.

## Identity and repeat boundary

Attempt 11 used firmware source revision
`f5ccf1975c73a26983d5460e62f71d23cc876827`, source SHA-256
`70ba83057537197f8659379548caeb3369d8d9782f423cc7128ce30ba6f587a4`,
configuration SHA-256
`78f73ca54d9cb87f46a0511742487d8c81bc4867e876a403e0707196cd98f99b`
and UF2 SHA-256
`0d5b17cec8b83fb17ba1763650562b96ea60622b2556c7fb5c50493b7b045ca8`.
The defect is confined to the host verifier. A repeat must use that unchanged
firmware image, fresh host-tool identities, a fresh activation bound to this
exact interrupted predecessor, and the complete operational-path rehearsal.

The required regression covers a nonzero debt followed by a zero-containing
interval, the exact response and its first dependent consumer, an earlier
attestation remaining invariant in the presence of later records, and healthy
terminal delivery through capture close, analysis, sealing and registration.
Only one finite Attempt 12 is authorized by the operator instruction; this
report itself neither flashes nor launches it.
