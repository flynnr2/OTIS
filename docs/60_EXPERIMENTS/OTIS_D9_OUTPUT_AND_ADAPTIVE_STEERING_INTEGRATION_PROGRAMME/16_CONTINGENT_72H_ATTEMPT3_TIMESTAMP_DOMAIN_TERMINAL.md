# Contingent 72-Hour Attempt 3 Timestamp-Domain Terminal

## Verdict

The resumed contingent Attempt 3 is an interrupted physical campaign, not a
replacement attempt and not a scientific rejection of the hybrid controller.
At 2026-09-10T14:30:37Z, after 56,440 supervisor-qualified D14/D8 apertures,
firmware latched `adaptive_hybrid_decision_timestamp_domain_mismatch`. The
fault was caused by a firmware integration race between two observations of
the same boundary: an exact extended D14 capture timestamp and a separately
sampled foreground whole-second uptime. D14/D8 acquisition, GNSS qualification,
the dual-core partition and the retained actuator identity were healthy.

The fault was terminal in the running firmware. Its transaction state had
latched `FAULT`; setup was already consumed and no command could clear or
reconstruct that state without reset. Following operator direction, the host
submitted the independent priority abort, kept the sole serial owner through
delivery, observed the resulting firmware `ABORTED` state, and only then closed
capture. No reset, reflash, restoration write or renewed authority occurred.

## Causal evidence

The last valid active snapshot was generation 10,854 in `ARMED`, with
`fail_static=false`. Its selected estimate was
`est:frequency_regulation:pps_gated_frequency:053230`, sourced from D14/D8
observation sequence 58,840 at raw `rp2040_monotonic_us32` tick 3,007,425,030.
After exact 32-bit wrap extension, that boundary is 58,841,999,878 us and
therefore projects to whole second 58,841.

The production integration instead populated the active decision's
whole-second field from a later `millis()/1000` foreground sample. Processing
crossed the next second before that sample, so the active decision combined
whole second 58,842 with exact ticks 58,841,999,878. The downstream guard
correctly requires
`timestamp_s == timestamp_ticks / 1,000,000`; it rejected the contradictory
pair and latched fail-static. This is a cross-sampling defect, not a failure of
the exact-domain guard or evidence that the captured D14 edge moved backward.

The terminal retained code is 43,076 (`0xA844`), DAC epoch 5, capture session
1, after four automatic applications and 19 codes of cumulative absolute
movement. The supervisor admitted 30 natural ARM submissions. The campaign did
not reach the 259,200-aperture endpoint.

## Stop, seal and registration

The supervisor terminal is `adaptive_hybrid_operator_abort`, reason
`independent_host_abort_fifo`, at 2026-09-10T15:03:35Z. Capture recorded exactly
one `emergency_abort_sent` marker at 15:03:36Z, followed by firmware reason
`device_abort_command_via_core0` and `ABORTED`. Capture closed cleanly at
15:04:21Z with zero reconnects, parser errors, rejected commands or malformed
UTF-8 records.

Offline finalization preserved and registered the package with content
SHA-256
`b48d9f4b2399acf3048e0b2db90616d3515b9cc8e500d574f52a0c51e6676551`.
The physical seal's semantic identity is
`10f79f9121f7f0f60ed43b0c257904547468a7092f12949ca3255c90170bf0e1`.
Its status is `review_required`: the aborted campaign cannot pass, and response
classifications for requests 2 and 4 do not reproduce exactly. All CSV
contracts, exact lifecycle records, transactions, maintenance replay,
transaction capsules and D14/D8 measurement replay pass. The response-replay
discrepancy is retained as a separate offline-review fact; it is not the cause
of the firmware fail-static terminal.

## Repair and verification

The firmware integration now derives both active-decision timestamp fields
from the same extended captured D14 boundary. If exact extension is
unavailable, it supplies no fabricated exact timestamp and retains the
existing fail-static behavior.

A deterministic C++ regression reproduces the exact fault geometry: captured
boundary 58,841,999,878 us with foreground uptime already at 58,842 s. It
asserts that the active decision retains the exact ticks and projects its
whole-second field to 58,841. The direct regression, adjacent active-contract
tests and full real-process no-hardware operational rehearsal test pass: 12
focused tests total.

The exact affected Arduino Nano RP2040 Connect 133 MHz profile also builds with
verified binary contract. The unflashed repair build has firmware-source input
SHA-256
`bd3db13d7d61b30357173b758e586188dd9f0edff8a1fb3a40561cad90e1c2c6`
and UF2 SHA-256
`2edca48b96ddacc9bdeef6f5cee166476130ea866f1305d313aaea787b9d4fc3`.
Because the repair remains an uncommitted working-tree change, it is not yet a
clean frozen campaign bundle and grants no flash, reset, retry or renewed bench
authority.
