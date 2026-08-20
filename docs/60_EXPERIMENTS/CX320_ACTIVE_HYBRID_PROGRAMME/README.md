# CX320 Bounded Active-Hybrid Programme

CX320 asks whether a deliberately capped D8-relative-to-D14 phase term can
materially influence the same bounded DAC requests used by authoritative slow
frequency control, improve the prospectively declared phase metric and preserve
frequency performance.

The governing preparation prompt is
[`../ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md`](../ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md).
The implementation and authority contract is
[`../../50_SOFTWARE/CX320_ACTIVE_HYBRID_CONTRACT_AND_AUTHORITY.md`](../../50_SOFTWARE/CX320_ACTIVE_HYBRID_CONTRACT_AND_AUTHORITY.md).

Current status: Stage 5 physical entry is explicitly authorized. Attempts 1
through 6 ended as sealed platform or firmware-integration escapes before a
physical hybrid correction. Attempt 7 was the first run to apply a genuine
firmware-driven combined phase-frequency correction and observe its response;
it exposed a one-second firmware response-window boundary defect. Attempt 8
carried that correction but stopped before qualification or automatic
actuation because the host compared an exact fractional estimator timestamp
to a floored integer device-uptime value. The attempt-8 firmware and timing
stream were coherent and the bounded abort left code `0xA83C` fail-static. The
narrow host predicate and its previously integer-aligned rehearsal seam are
being corrected before a single-use attempt-9 successor is activated.

The scientific policy, thresholds, topology, criteria, 12-hour qualified
duration and progressive actuator envelope remain unchanged.

- [`01_OFFLINE_REPLAY_AND_SELECTION.md`](01_OFFLINE_REPLAY_AND_SELECTION.md)
- [`02_OFFLINE_READINESS_AND_AUTHORITY_PROPOSAL.md`](02_OFFLINE_READINESS_AND_AUTHORITY_PROPOSAL.md)
- [`03_STAGE5_AUTHORITY_AND_ENTRY.md`](03_STAGE5_AUTHORITY_AND_ENTRY.md)
- [`04_STAGE5_ATTEMPT1_PLATFORM_TERMINAL_AND_ATTEMPT2_RECOVERY.md`](04_STAGE5_ATTEMPT1_PLATFORM_TERMINAL_AND_ATTEMPT2_RECOVERY.md)
- [`05_STAGE5_ATTEMPT2_PREWRITE_TERMINAL_AND_ATTEMPT3_RECOVERY.md`](05_STAGE5_ATTEMPT2_PREWRITE_TERMINAL_AND_ATTEMPT3_RECOVERY.md)
- [`06_STAGE5_ATTEMPT3_STATUS_HANDOFF_TERMINAL_AND_ATTEMPT4_RECOVERY.md`](06_STAGE5_ATTEMPT3_STATUS_HANDOFF_TERMINAL_AND_ATTEMPT4_RECOVERY.md)
- [`07_STAGE5_ATTEMPT4_FIRMWARE_HANDOFF_TERMINAL_AND_ATTEMPT5_RECOVERY.md`](07_STAGE5_ATTEMPT4_FIRMWARE_HANDOFF_TERMINAL_AND_ATTEMPT5_RECOVERY.md)
- [`08_STAGE5_ATTEMPT5_SERIALIZATION_TERMINAL_AND_ATTEMPT6_RECOVERY.md`](08_STAGE5_ATTEMPT5_SERIALIZATION_TERMINAL_AND_ATTEMPT6_RECOVERY.md)
- [`09_STAGE5_ATTEMPT6_HOST_ARMING_TERMINAL_AND_ATTEMPT7_RECOVERY.md`](09_STAGE5_ATTEMPT6_HOST_ARMING_TERMINAL_AND_ATTEMPT7_RECOVERY.md)
- [`10_STAGE5_ATTEMPT7_RESPONSE_BOUNDARY_TERMINAL_AND_ATTEMPT8_RECOVERY.md`](10_STAGE5_ATTEMPT7_RESPONSE_BOUNDARY_TERMINAL_AND_ATTEMPT8_RECOVERY.md)
- [`11_STAGE5_ATTEMPT8_QUALIFIED_CLOCK_TERMINAL_AND_ATTEMPT9_RECOVERY.md`](11_STAGE5_ATTEMPT8_QUALIFIED_CLOCK_TERMINAL_AND_ATTEMPT9_RECOVERY.md)
