# Hybrid 72-hour Attempt 3 telemetry-admission terminal

## Verdict

Hybrid Attempt 3 is a **failed physical qualification with a correct fail-closed
host response to an avoidable firmware telemetry-admission defect**. It is not
a 72-hour result and its qualified prefix must not be accumulated with a
successor run.

The run completed 8,460 qualified seconds (2 h 21 min) with live sustained
hybrid authority. D14/D8 timing capture, D9 configuration/readback, D6
diagnostic loopback, same-receiver GNSS metadata at 115200 baud, exact
actuation joins and serial ownership remained healthy. Three phase-material
automatic applications moved the DAC from the setup code `0xA83C` to
`0xA850`, for 20 cumulative codes. The first two responses completed and were
healthy; the third exact application was right-censored by the platform
terminal after 647 of its required 1,500 response seconds.

At `2026-08-30T18:22:11Z`, ACTIVE snapshot generation 2007 began before the
host had received all records for generation 2006. The strict coherent-snapshot
reducer correctly rejected the overlap, preserved `0xA850`, delivered exactly
one priority abort and retained a complete post-abort fail-static snapshot.
Capture then closed cleanly after abort evidence was recorded.

## Root cause

The Campaign18 firmware emitted 55 ACTIVE status fields plus the three-record
snapshot envelope, but the shared dual-core partition reserved only 33 fields
plus the envelope. A coincident periodic health burst, configuration response
and ACTIVE query admitted generation 2006 without enough queue capacity for its
entire real status vocabulary. The telemetry queue reached its 192-record
capacity and dropped the final 15 records. Generation 2007 then exposed the
incomplete predecessor to the host.

This was a producer admission-contract defect, not a D14, D8, D9, D6, GNSS,
plant or controller rejection. The host reducer remains strict. Prospectively,
the firmware derives the reservation from the real cross-profile ACTIVE field
union (63 fields), reserves 66 records per status burst and provisions the
shared queue for the 212-record maximum concurrent burst. A cross-language
regression proves that every firmware-emitted ACTIVE key is represented in that
reservation contract. Campaign18 now also declares the extended V3 status
contract it actually emits, and generic Campaign18 supervisor faults map to the
canonical identity/evidence terminal.

## Preserved acquisition and finalization

- Run: `runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt3`
- Wall start: `2026-08-30T15:21:12Z`
- Qualified origin: `2026-08-30T16:01:11Z`
- Terminal: `2026-08-30T18:22:11Z`
- Last confirmed code: `0xA850`, DAC epoch 4, correction count 3
- Raw serial SHA-256:
  `714803fab80c63c4b631e1e0539fc8dcac7a8b21edf527b6b58c0eba295e38b2`
- Run-manifest SHA-256:
  `62c8e9df998f8a4a3dec13a67adc40cc756a0b6b9aea438b24fbb58a5a785c20`
- Evidence-manifest SHA-256:
  `4461d49633e5c7e682c6e5a67a5bf5bb2459b4a78aec9c48d87bcc999d8c81db`
- Failed seal SHA-256:
  `13def98929f6bb70b357d2d1f97dcf4d73aa805a54b58832f270b2e3a5c3183b`
- Registered content SHA-256:
  `adeba1fb47fce63107bef6fedf79f31ab07a49f828bde211bbe06703b9518501`
- Registered primary decision:
  `cx322_d9_d6_72h_identity_or_evidence_fault`

The physical acquisition gate passed: frozen identity, command stream,
D9/D6 evidence, request-to-application joins, abort ordering and single-owner
capture closure were exact. The scientific acceptance gate failed because the
72-hour endpoint was incomplete and the third response was open. The retained
prefix remains valid descriptive evidence of live hybrid steering, but it does
not qualify the 72-hour programme.

## Successor readiness

Attempt 4 must start a fresh 72-qualified-hour clock and bind this registered
failed predecessor. Because firmware admission capacity, wire-contract identity
and host terminal classification changed, it requires a clean exact-profile
build and the complete operational-path rehearsal before flashing and entry.
The rehearsal must combine the real Campaign18 V3 status vocabulary with the
firmware admission-boundary regression; a host fixture alone cannot establish
the physical cross-core queue boundary.

Live entry must again prove D14, D8, D9 readback, D6 loopback, GNSS 115200,
single serial ownership, exact setup/application identity and the independent
abort path. The no-challenge hybrid policy and all 72-hour duration, cadence,
response-reserve and authority semantics remain unchanged.
