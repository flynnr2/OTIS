# Single reference owner: offline release gate, 19 September 2026

The replacement is implemented and ready for the next authorized physical
attempt. This is an offline release result, not a 72-hour qualification or proof
of the electrical cause of the earlier D14 disturbances. No hardware, serial
port, flash or live experiment was operated on this development machine.

## Resulting instrument path

`D14-recognized PIO D8 word → bounded FIFO IRQ record → one selector → phase/frequency/control`

The independent GPIO reference observer, DMA transport, association matching,
count-boundary ring, association timeout/rearm and ASL evidence path are removed.
SNP v2 retains the raw count and ordinal plus the CPU service coordinate and a
conservative recognition-time bracket. REF is a derivative of the same record.
The selector and host replay require the entire possible interval inside the
unchanged ±1.25 ms window; ambiguous timing remains unqualified. D8 count is not
used to invent a tighter timestamp. Raw count diagnostics have no independent
control-admission path. SETUP, ARM and evidence-release authorization refresh
capture health at the consuming boundary.

The PIO program remains the same 15 instruction words. The D9/D6 monitor remains
separate and zero-authority. D10 capture remains unimplemented. Standalone
autonomous steering has not been enabled by this change.

## Verification

| Gate | Retained result |
|---|---|
| Full repository suite | 717 passed in 93.17 seconds |
| Instruction-level PIO proof, pinned assembler | 7,936 phase/duty cases; 55,552 adjacent intervals; unchanged program words |
| Actual backend native regressions | Source filtering, startup and rearm, empty-check races, batch ambiguity, bounded reads, RXSTALL, ring exhaustion, preservation and us32 rollover |
| First dependent firmware decision | Actual driver records through production mapping and common selector into phase/frequency and first control decision |
| Fixed firmware build | Pinned Arduino-Pico 6.0.0, compiler 16.1.0, verified binary provenance and resource budget |
| Production operational rehearsal | All eight frozen boundaries passed; two progressive transactions, metadata hold/requalification, normal-writer backpressure, independent abort delivery, closure, analysis, seal and registration |
| Portable delivery | Fresh archive extraction, exact inventory/hashes, firmware, current host, spec, receipt and sealed-package validators passed |
| Lint delta | No introduced findings; existing main baseline 162, final 161 |

The actual rehearsal ended by its deliberate independent abort injection. Its
analysis passed with `interrupted_incomplete`, and capture integrity was
`complete`. That is the expected rehearsal result, not a scientific pass.
Historical compact fixture bytes were left unchanged; test-only projections
exercise the current vocabulary without promoting old evidence.

## Frozen identities

- Release checkout: `0f413d1665c56a18ef072848d09cdbe816d76306`.
- Firmware audit revision: `224a75c7188d239d77624e78e2f15d45e6135602`.
- Build session: `1f1f000020260919`.
- Source SHA-256: `56cc4d9dff72ec92b2539c575b365899377661d3a4e6db3ce600421edd663a95`.
- Configuration SHA-256: `584e841d933a0d7f0c68f8860807bc9dda8fbe5cb7e785b6199e4c472ecdc496`.
- UF2 SHA-256: `2facbef0a033f4b083736fc37c1c4f89499c279fa97819a27d878cf99e02874c` (487,424 bytes).
- Host toolset SHA-256: `04bf3ecc7406da61a1fd021559f27bf4ee955502c0e9e5a4bd15a1b5db6661b2`.
- Run specification SHA-256: `582227541a92e14952b815ab02ed7dca46aa8c15a640d9aab1da4663e5cb2b30`.
- Rehearsal receipt SHA-256: `003fe716060041b7e8d88b4c56919a33fb8b53277a78c8909482a2d9b8050510`.
- Sealed rehearsal package content: `0a55a89d23886ab07aeeb228af9e7e94b33e2340e16a9890ecd3ee8242f1a6ce`.

The final test-only commit and this documentation do not change the firmware
inputs or host toolset. The recorded build and rehearsal remain applicable.

Program storage is 226,072 bytes. Static RAM is 150,396 bytes, leaving 111,748
bytes versus the required 104,858-byte runtime reserve. The final ELF has a
96-byte IRQ handler and 608-byte FIFO service routine. Their observed own stack
frames are 16 and 304 bytes respectively; this is not a complete system stack
or interrupt-latency proof. No Serial formatting runs in this capture IRQ.

## Delivery and next decision

Delivery archive: `single-reference-owner-224a75c.tar.gz`, 2,672,641 bytes.
SHA-256: `13618e4e34bb474ad8eb9da744d0cdbe3d168ff94286f18b4a409346b0ed1d64`.
It contains 61 manifest-listed payloads plus `DELIVERY_MANIFEST.json`, including
firmware, the inert contingent-72-hour specification, rehearsal and verification
records, and separate preparation/physical-entry prompts in `BENCH_HANDOFF.md`.
The shared-storage copy must be independently verified on receipt; local
packaging is not evidence of cloud synchronization.

The next decision-bearing gate is one authorized physical contingent campaign
using that exact bundle and its existing pre-actuation eligibility checks.
No additional physical mini-campaign is introduced merely because the binary
hash changed. Real FIFO service timing, physical pin recognition and USB/device
behavior remain unexercised by the native stubs and PTY instrument. Broad timing
brackets may legitimately prevent qualification; do not widen the tolerance or
reinterpret an old held attempt to obtain a pass.

A successful run would establish behavior under its recorded conditions. It
would not prove an electrical D14 edge timestamp, capture-to-service latency,
or the original disturbance's electrical cause. A stopped or sufficiently slow
D8 can delay PIO recognition; that limitation is retained explicitly in the
[current design](../50_SOFTWARE/SINGLE_REFERENCE_OWNER_REPAIR.md).
