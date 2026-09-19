# Single reference owner

Status: implementation under verification. Not yet a frozen bench candidate.
Context: [September 13 association loss](../60_EXPERIMENTS/REFERENCE_ASSOCIATION_DISCONTINUITY_2026_09_13.md).

The authoritative path is:

`D14-recognized PIO D8 snapshot → immutable FIFO record → one acceptance gate → phase/frequency/control`

The unchanged 15-instruction PIO program owns the count boundary. Core 1 drains
its RX FIFO through a bounded interrupt into a software ring. A record owns its
session, ordinal, raw counter, CPU service coordinate and timing uncertainty.
An IRQ invocation is never a record identity. There is no DMA transport,
independent GPIO reference queue, count-boundary queue, association timeout or
automatic association rearm. REF is a presentation of the same PIO record;
SNP v2 is sufficient to reconstruct its count and recognition-time evidence.
D10 remains an unimplemented external-event seam with no reference authority.
The D9/D6 monitor remains optional, separately queued and without authority.

## Recognition time, not a fabricated edge timestamp

The RP2040 timer is an implementation clock. `reference_timestamp_ticks` in
SNP v2 is the CPU FIFO-service coordinate in `rp2040_monotonic_us32`, sampled
after reading the word. It is not a hardware-latched D14 edge timestamp or a
measurement of capture-to-service latency.

Before observing an empty FIFO, the timing owner samples that same timer.
The next committed snapshot therefore has a conservative recognition interval
from the last known-empty coordinate (minus one microsecond) to its service
coordinate. The one-microsecond allowance covers the unchanged IN/autopush
publication at 133 MHz and integer timer quantization; it is not an assumed
interrupt-latency limit. No empty observation means unknown uncertainty.
A multiword service batch remains explicitly ambiguous. Raw words and actual
service coordinates survive these findings.

This interval bounds the PIO snapshot recognition in integer microseconds,
not the electrical D14 rising edge. The unchanged PIO program checks D14 while
counting D8; a stopped or slow D8 can delay recognition. Neither a singleton
FIFO nor a plausible D8 count proves an independent D14 pin timestamp. D8
counts are never used to tighten this timing interval. That limitation remains
visible and is not cured by a successful qualification run.

For opening and closing intervals `[Lo,Uo]` and `[Lc,Uc]`, the possible elapsed
interval is `[Lc-Uo,Uc-Lo]`. The frozen nominal interval and ±1.25 ms tolerance
are unchanged. The single selector accepts only if the whole interval lies
inside the permitted range. It excludes an early candidate only if the whole
interval is early. A bracket crossing a decision boundary withdraws model
qualification; it does not claim the physical PPS failed. The same rule applies
during acquisition and host replay. Anchor freshness and post-DAC settling use
the conservative lower coordinate. Frequency and phase continue to use raw D8
count differences and nominal accepted reference periods; software service time
is never substituted as their metrological denominator.

## Bounded service and failure

Both a single ISR entry and repeated IRQ service before foreground progress
are bounded. The hardware FIFO holds eight words, regardless of software ring
capacity. RXSTALL, a full software ring or exhausted service budget stops the
source and state machine. Read words retain their original values and identity;
unread committed words remain available for diagnostic preservation. A blocked
autopush is not invented as another observation. Runtime does not clear evidence
or rearm automatically. Explicit reset/rearm requires a new nonzero session and
cannot make the interrupted campaign continuous.

Foreground diagnostics observe the same record owner. Adjacent raw CNT interval
classification remains diagnostic; it cannot independently admit control.
GNSS metadata separately qualifies receiver state. Capture uncertainty, host
findings and receiver metadata are not interchangeable physical fault claims.

## Verification boundary

Native tests exercise actual FIFO driver code using deterministic peripheral
stubs, including source filtering, late arrivals, batch ambiguity, exhaustion,
RXSTALL, session lifecycle and pending IRQs. Selector tests cover conservative
interval admission, uncertainty, expiry and rollover. The first dependent
phase/frequency/control decision must consume the same selected span. Current
host fixtures and replay use the emitted SNP v2 contract.

Before bench entry, complete the fixed firmware build/resource audit and the
actual operational-path rehearsal. Neither a coherent host fixture nor the
native peripheral stubs establish real interrupt timing, USB behavior or
physical pulse recognition. Preserve the live pre-actuation gate for those
remaining boundaries. No unchanged 72-hour restart substitutes for this work.
