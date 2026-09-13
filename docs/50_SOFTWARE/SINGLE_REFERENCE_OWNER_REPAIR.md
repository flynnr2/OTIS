# Single reference owner: bounded repair proposal

Status: feasibility established in a bounded model; **not implemented in the
instrument**, not a campaign bundle and not permission for a physical run.
Context: [September 13 association loss](../60_EXPERIMENTS/REFERENCE_ASSOCIATION_DISCONTINUITY_2026_09_13.md).

## One decision before downstream use

The operator's requested boundary is one reference-acceptance decision before
an event reaches qualified measurement, phase estimation or control. Hardware
must first preserve the raw candidate needed to make that decision. Rejected
candidates remain raw diagnostic evidence and cannot independently advance
qualification or actuation. Existing raw interval diagnostics may remain, but
must not become a competing acceptance gate.

The intended path is:

`PIO count capture → one immutable raw record → one acceptance gate → accepted span consumers`

The record owns its session, ordinal and raw oscillator count together. Phase,
frequency, preview and control consumers receive the same selection result.
No independent GPIO event queue decides which count belongs to a reference.
GPIO evidence, if retained at all, is diagnostic only and cannot advance or
veto reference authority. GNSS serial metadata retains its separate receiver
qualification role; it does not become timing authority.

## Preferred finite implementation

Keep the current 15-instruction PIO counting/snapshot program unchanged.
Replace authoritative DMA drainage with the state machine's RX-FIFO-not-empty
interrupt on Core 1. The pinned SDK provides this per-state-machine interrupt
source. The interrupt drains already-latched, immutable FIFO count words into
one bounded software ring. Identity advances once per FIFO word read, never
once per IRQ invocation. Remove the mandatory GPIO reference stream, separate
boundary queue and association guard from the authoritative path.

This removes the independent-detector matching problem and the DMA-commit/IRQ
race without adding instructions to the counting path. It does not move the
count aperture into the CPU: no per-PPS stop, restart or late read of live X is
allowed. The optional output monitor retains its own disabled IRQ source and
its existing zero-authority status. Repository sources currently install no
PIO CPU IRQ handler; the pinned linked image and libraries must still be
checked before claiming exclusive ownership. Prefer a source-filtered shared
handler if exclusivity cannot be established.

## Required limits, not follow-up features

- Drain at most eight words per IRQ entry, the joined FIFO capacity. A source
  still asserted after the bounded budget, software-ring exhaustion, or RXSTALL
  must latch integrity loss and disable the source/state machine. Never return
  into an unbounded level-triggered interrupt storm.
- Preserve all words already read, with their actual identity. A stalled
  autopush is not a committed FIFO word and must not acquire an invented record.
- A batch already containing multiple words has ambiguous edge timestamps.
  Preserve actual service coordinates and mark the batch; do not manufacture
  spacing. Hold qualification at the common gate. Define exact fresh-session
  recovery before implementation, without auto-resuming a broken campaign.
- Even a singleton's CPU timestamp is a **PIO FIFO service timestamp**, not a
  hardware-latched D14 timestamp or measured capture-to-service latency. One
  queued word alone does not prove a latency bound. Current GPIO timestamps
  are also ISR observations, but their source semantics cannot silently carry
  over. Update producer, contracts, replay, freshness and tolerance consumers
  together. The D8 count must not be used to pretend an independent local-clock
  timestamp was captured.
- Disable source and state machine before rearm; clear FIFO and stale pending
  IRQ, reset ring/session with IRQ excluded, restore X/start PC, then enable
  state machine and source. Prove that prior-session data cannot be published
  under a new identity. If sharing a CPU IRQ, clearing/dispatch must respect
  other sources.
- Software storage of 128 records does not provide 128 hardware capture slots
  while IRQs are masked. Only eight FIFO slots exist. Measure static RAM and
  document the servicing envelope; remove obsolete queues rather than retain
  both transport designs.

## Feasibility checks performed

`python tools/probe_pps_fifo_irq.py` reuses the existing instruction model with
the unchanged 15 PIO words, a modeled 10 MHz oscillator and two-flop inputs.
It demonstrates the proposed FIFO transport rule in five bounded cases:

1. Two ordinary boundaries produce two raw records.
2. A one-system-cycle candidate at cycle 501 is missed by PIO and produces no
   extra FIFO record; a separate hypothetical GPIO notification cannot create
   an authoritative count through this transport.
3. A wider PIO-recognized extra candidate remains a third raw record for the
   common selector to assess; it is not silently discarded.
4. Delayed IRQ service preserves both queued words and identities, while the
   model explicitly marks their shared service batch timestamp-ambiguous.
5. With service withheld, a ninth candidate encounters the eight-word FIFO's
   RXSTALL condition; the model does not invent a ninth committed observation.

This is a transport feasibility model, **not the production ISR, native-driver
regression, selector integration, interrupt-latency measurement or hardware
qualification**. No existing qualification is promoted by it. The model's
marking of ambiguity describes the proposed rule, not implemented behaviour.

An alternative inserting non-waiting IRQ instructions after the two snapshot
instructions was also sampled locally: 768 phase/duty cases at each of 10 and
16 MHz had at most one edge of cumulative span error. That limited sweep is
not the full digital proof. It also increases the program to 17 instructions;
two separate copies would exceed PIO instruction RAM, and IRQ flags can coalesce.
The FIFO-level approach avoids those extra changes and is preferred. Never use
`irq wait`, which would make oscillator counting wait for CPU service.

## Finite implementation gate

Implement the replacement as one producer-to-consumer change. Native tests must
exercise actual driver code for singleton, batch, refill, ring exhaustion,
RXSTALL and pending IRQ across rearm, then pass the first clean record through
the actual selector, count/phase/frequency and first control decision. Verify
that GPIO-only events have no authority and PIO-recognized early candidates are
excluded by the one selector. Include timestamp ambiguity/age cases rather than
assuming a singleton is fresh.

Then run the affected current release checks, exact-profile build/resource
audit and genuine operational-path rehearsal. Only that complete replacement
can become a bench candidate. Do not merge a half-connected alternate runtime,
change the ±1.25 ms criterion implicitly, or start another 72-hour attempt to
substitute for these deterministic checks.
