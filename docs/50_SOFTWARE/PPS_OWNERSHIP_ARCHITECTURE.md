# PPS Ownership Architecture

One PIO state machine owns D8 counting and its D14-recognized count boundary.
The bounded FIFO IRQ transports immutable words and adds a CPU service
coordinate; foreground maps each record into REF/SNP and derived observations.
There is no independent GPIO reference observer, DMA transport or ordinal
association between independent streams. See the detailed
[single-owner contract](SINGLE_REFERENCE_OWNER_REPAIR.md).

```text
D8 / GPIO20 → PIO WAIT / X--
D14 / GPIO26 → same PIO JMP PIN / IN X,32
                        ↓
                 joined RX FIFO
                        ↓
        bounded Core 1 FIFO IRQ / software ring
                        ↓
           same-record REF + SNP v2 + raw CNT
                        ↓
             common accepted-reference gate
                        ↓
                phase / frequency / control
```

| Evidence | Owner | Meaning |
|---|---|---|
| Cumulative D8 down-counter | PIO state machine | Immutable count at PIO recognition of D14 |
| Snapshot session and sequence | Sole FIFO record owner | Source continuity, independent of IRQ invocation count |
| REF/SNP service coordinate | CPU timer after FIFO read | RP2040 operational coordinate, not electrical-edge timing |
| Recognition uncertainty | Empty-FIFO/service observations | Conservative bound used by acceptance; no fabricated hardware timestamp |
| Raw CNT | Adjacent snapshot arithmetic | Same-session cumulative difference modulo `2^32` |
| Accepted span | Common reference selector | Explicit admitted endpoints retaining intervening raw evidence |

Hardware FIFO stalls, exhausted service budgets and ring exhaustion stop the
source without clearing retained evidence. Explicit rearm requires a new
session; runtime cannot repair continuity through automatic recovery. A first
snapshot is an anchor; a count interval requires valid endpoints. A stopped D8
can delay D14 recognition because the PIO program waits on oscillator levels.
No independent physical-PPS presence claim survives that limitation.

Capture service remains independent of host attachment. Foreground progress,
canonical publication and optional diagnostic export are different stages;
missing telemetry never proves a missing physical pulse. GNSS serial metadata
qualifies the receiver but is not timing authority. D6 and future D10 evidence
remain fail-local, and D10 capture is not implemented.

The [service-latency baseline](SERVICE_LATENCY_BASELINE.md) observes exact
software endpoints without entering capture or control decisions. It does not
restore a GPIO ISR or change the count aperture. The
[instruction proof](PPS_PIO_PROOF_AND_VERIFICATION.md) binds unchanged PIO words;
backend native tests separately check bounded transport, loss preservation,
source identity, restart and the first dependent decision. Physical timing and
USB behavior require the authorized frozen-bundle bench gate.
