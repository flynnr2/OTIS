# CX320 Bounded Active-Hybrid Programme

CX320 asks whether a deliberately capped D8-relative-to-D14 phase term can
materially influence the same bounded DAC requests used by authoritative slow
frequency control, improve the prospectively declared phase metric and preserve
frequency performance.

The governing preparation prompt is
[`../ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md`](../ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md).
The implementation and authority contract is
[`../../50_SOFTWARE/CX320_ACTIVE_HYBRID_CONTRACT_AND_AUTHORITY.md`](../../50_SOFTWARE/CX320_ACTIVE_HYBRID_CONTRACT_AND_AUTHORITY.md).

Current status: Stage 5 physical entry is explicitly authorized. Attempts 1,
2 and 3 ended as sealed platform escapes before scientific control. Attempt 1
exposed pre-setup firmware integrity gating. Attempt 2 passed that boundary but
exposed a host prewrite contract that omitted the firmware's exact
setup-reference eligibility. Attempt 3 then proved exact setup acceptance and
one setup DAC application, but exposed omission of the CX320 hybrid fields from
the host's atomic status handoff. Attempt 4 proved that repaired host boundary
and exact setup again, then exposed a firmware handoff that propagated the
setup epoch to both preview consumers without confirming them to the hybrid
controller. It was proactively aborted before a foreknown first-decision fault.
All four narrow defects are corrected. Attempt 5 has a fresh exact firmware
build, successor bundle and passing operational rehearsal. The scientific
policy, thresholds, criteria, duration and progressive envelope remain
unchanged.

- [`01_OFFLINE_REPLAY_AND_SELECTION.md`](01_OFFLINE_REPLAY_AND_SELECTION.md)
- [`02_OFFLINE_READINESS_AND_AUTHORITY_PROPOSAL.md`](02_OFFLINE_READINESS_AND_AUTHORITY_PROPOSAL.md)
- [`03_STAGE5_AUTHORITY_AND_ENTRY.md`](03_STAGE5_AUTHORITY_AND_ENTRY.md)
- [`04_STAGE5_ATTEMPT1_PLATFORM_TERMINAL_AND_ATTEMPT2_RECOVERY.md`](04_STAGE5_ATTEMPT1_PLATFORM_TERMINAL_AND_ATTEMPT2_RECOVERY.md)
- [`05_STAGE5_ATTEMPT2_PREWRITE_TERMINAL_AND_ATTEMPT3_RECOVERY.md`](05_STAGE5_ATTEMPT2_PREWRITE_TERMINAL_AND_ATTEMPT3_RECOVERY.md)
- [`06_STAGE5_ATTEMPT3_STATUS_HANDOFF_TERMINAL_AND_ATTEMPT4_RECOVERY.md`](06_STAGE5_ATTEMPT3_STATUS_HANDOFF_TERMINAL_AND_ATTEMPT4_RECOVERY.md)
- [`07_STAGE5_ATTEMPT4_FIRMWARE_HANDOFF_TERMINAL_AND_ATTEMPT5_RECOVERY.md`](07_STAGE5_ATTEMPT4_FIRMWARE_HANDOFF_TERMINAL_AND_ATTEMPT5_RECOVERY.md)
