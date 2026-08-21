# CX320 Bounded Active-Hybrid Programme

CX320 asks whether a deliberately capped D8-relative-to-D14 phase term can
materially influence the same bounded DAC requests used by authoritative slow
frequency control, improve the prospectively declared phase metric and preserve
frequency performance.

The governing preparation prompt is
[`../ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md`](../ACTIVE_HYBRID_PHASE_FREQUENCY_QUALIFICATION_PROMPT.md).
The implementation and authority contract is
[`../../50_SOFTWARE/CX320_ACTIVE_HYBRID_CONTRACT_AND_AUTHORITY.md`](../../50_SOFTWARE/CX320_ACTIVE_HYBRID_CONTRACT_AND_AUTHORITY.md).

Current status: Stage 5 reached a decision-bearing physical terminal in
attempt 9. Firmware applied one genuine combined phase-frequency correction
from `0xA83C` to `0xA836`. Its exact 1,500-second response replayed as
`healthy_indeterminate_near_resolution`, but the observed zero response did not
satisfy the separately frozen positive-sign checkpoint. The programme is a
bounded scientific non-pass, not a capture or replay failure. The attempt-9
activation is consumed, later authority remained blocked, the instrument is
`FAIL_STATIC` at `0xA836`, and no attempt 10 is authorized.

The superseding offline seal preserves the original terminal record while
correcting its host-side classification. The frozen scientific policy,
thresholds and criteria were not changed after observation. The selected CX321
offline v2 successor design resolves the observability precondition with a
separately identified 21-code plant-sign transaction on a dedicated 1,500-
second estimator while leaving 600-second natural hybrid controller requests
unchanged. It remains non-effective and requires implementation, a new bundle,
rehearsal and separate authority. See the
[`CX321 design decision`](../CX321_BOUNDED_ACTIVE_HYBRID_SUCCESSOR/README.md).

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
- [`12_STAGE5_ATTEMPT9_RESPONSE_OBSERVABILITY_TERMINAL.md`](12_STAGE5_ATTEMPT9_RESPONSE_OBSERVABILITY_TERMINAL.md)
