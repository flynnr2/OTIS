# Reference association discontinuity — 13 September 2026

## Disposition

The contingent attempt at frozen revision
`41de81da3f35c8fc9ce818db5c010bfbe4bf4b49` encountered a real recorded
association/acceptance discontinuity after its one successful SETUP. The host
hold preserves evidence and withholds further authority as required. Recovery
into a new capture session and acceptance epoch cannot satisfy the attempt's
frozen uninterrupted qualification. Operator-authorized closure was in progress
when this offline investigation began; this report does not claim final closure.

This is a capture-association limitation exposed by an irregular D14 observation.
The evidence does not establish an electrical root cause or justify changing the
host verifier, guessing an association, or clearing the hold. The firmware/capture path is the working hypothesis by operator direction.
No oscilloscope is available. Reference tolerance, association acceptance and
actuation policy remain unchanged; the bounded diagnostic change below does
not establish or repair the underlying cause.

## Verified retained evidence

The active-run diagnostic archive
`contingent-72h-41de81d-held-diagnostic-20260913T080254Z.tar.gz` is
2,295,611 bytes, SHA-256
`e2a019d9422738029eb4aa9a7c6c96d76a59ec0733168b64fc4d15803f81fcb7`.
All 40 manifest entries and their sizes/hashes were verified locally. The
archive has 41 regular files including its sampling manifest. Sampling covered
08:05:11.858999Z through 08:06:03.374423Z. It is a non-atomic diagnostic of an
active run, not a sealed acquisition. Raw files remain unchanged.

The authoritative excerpt is raw serial lines 35159–35182, with corresponding
REF/SNP/CNT/APS and association-loss CSV records. REF event-emission sequence
and D14 source sequence differ by 1000 in this excerpt; they are not the same
identity.

| Observation | D14 source sequence | REF event sequence | RP2040 us32 ticks |
| --- | ---: | ---: | ---: |
| Previous paired reference | 813 | 1813 | 815250387 |
| Additional reference | 814 | 1814 | 816152754 |
| Following reference | 815 | 1815 | 816250369 |

The recorded adjacent differences are 902,367 and 97,615 microseconds. The
first-to-third difference is 999,982 microseconds. These are differences of
interrupt-observed reference coordinates, not electrical pulse-width
measurements or hardware-latched D14 timestamps.

Last paired SNP: session 1, sequence 813, cumulative down-counter 455011508.
The preceding two complete CNT rows each contain exactly 10,000,000 D8 edges.
The affected interval has no paired SNP/CNT; the count before/after the event
cannot prove continuous D8 operation through that missing interval.

ASL decision 0 at 816250605 ticks records:

- reason `ref_without_snapshot`, classification
  `unread_snapshot_present_when_decision_made`;
- pending D14 source 814, another source 815 waiting;
- snapshot session 1, producer ordinal 815, consumer ordinal 814, backlog 1;
- initialized/running backend with no latched fault, DMA error/stop, PIO RX stall,
  overwrite or snapshot-continuity loss.

The retained pending age is 97,824 ticks. It was sampled before the ASL decision
coordinate; it must not be forced equal to a subtraction using that later
coordinate.

Firmware invalidates acceptance, records association loss, rearms the backend
and clears pending references. The next paired SNP has capture session 2.
PPS status reports acceptance epoch 2. ACTIVE `session_id` remains the original
transaction's expected binding (1); it is not evidence of a firmware reboot.
The host first reports its hold at 07:54:03Z. Later tracking recovery does not
restore the old transaction/capture identity or uninterrupted epoch.

## Two misleading interpretations excluded

`pps_gate.pps_interval_anomaly_count == 0` is not proof of a clean raw D14
stream. The affected observations fail association before ordinary count-window
assessment. The independent raw diagnostic `pps_d14.rejected_short_count`
changes from 0 (status sequence 28418) to 1 (status sequence 28999).

The ASL Core 1 breadcrumb at 816018269 ticks is not proof of a 232 ms stall.
`loop1()` records progress at four trace samples per second; this is deliberately
sampled telemetry, not a timestamp for every loop or every service operation.

## Local reproduction and interpretation

The actual `otis_pps_snapshot_association_decide` header was compiled into a
small native probe with session 1, next snapshot 814, a word available and a
second reference waiting. It returns AssociationLoss with either possible
prior deferral state. A clean session-2 word follows the normal defer/pair
recovery. The rejection does not depend on SETUP, frequency error, DAC code,
wall time, or a guessed age threshold.

The existing regression already covers this ambiguity and the first dependent
measurement consumers. Focused verification passed **55 tests in 20.04 s**:
`test_pps_count_boundary`, `test_pps_snapshot_backend_architecture`,
`test_reference_acceptance`, `test_reference_acceptance_live`,
`test_association_loss_decisions`, and `test_frequency_regulation_pre_setup`.
No duplicate regression or new campaign framework was added.

The retained state proves two REF observations competing with one currently
available word. It does not identify which REF owns that word, nor establish
all earlier DMA visibility states. ASL records queue metadata but not the
unread counter value; rearm discards the word. Pairing it with either reference,
or dropping just the early CPU REF, would infer provenance that is absent.

The existing PIO instruction model also demonstrates a possible mechanism:
D14 is sampled by JMP PIN instructions interleaved with D8 counting, whereas
the CPU reference uses a separate GPIO interrupt path. With the real PIO words,
133 MHz system clock, a modeled 10 MHz 50% oscillator and two-stage input
synchronizers, an injected narrow pulse can escape PIO recognition. Across
40 integer-cycle pulse-start phases (100 through 139), widths of 1/2/3/4/6
system cycles were missed in 34/28/22/16/4 cases. Widths 8/12/16/24/32 cycles
were detected in all those tested phases; a later 100-cycle pulse was always
detected. This is a bounded synthetic mechanism test, not a guaranteed minimum
pulse width, a model of GPIO interrupt recognition, or reconstruction of the
bench waveform. It does not prove that the actual extra observation was a
narrow electrical pulse.

## Next decision

Preserve the closed attempt and do not launch another unchanged 72-hour attempt
merely hoping this event does not recur. Do not weaken the fail-closed
association guard or filter only CPU REF before the independent PIO stream.

The immediate firmware change preserves the unread DMA front word and its
post-stop queue identity in ASL schema 2 before rearm. It remains explicitly
unassociated evidence. Pre-stop decision statistics are retained separately;
DMA arrivals between those frontiers are legal. No word is assigned to a REF
by timing plausibility, ordinal coincidence, or count plausibility. Only the
front word is retained, with a presence flag and actual ring/FIFO depths;
this is not a full hardware trace or a claim to recover missing observations.

Deterministic verification must exercise empty/front/overwritten/faulted
backend states, unchanged consumer identity, recovery, and the actual firmware
formatter through the host splitter/validator. The existing ambiguity guard
must still reject the observed two-REF/one-word ordering. This closes an
evidence-loss gap; it does not make another 72-hour restart the next decision.

A robust association redesign ultimately needs a common hardware event
identity or an equally explicit causal guarantee. Another retry, foreground
delay or host status comparison cannot supply it. Use the preserved evidence
and bounded firmware models to select that change; do not promise electrical
root-cause attribution without evidence capable of making the distinction.

## Implemented diagnostic change and validation

Implementation revision `80ace6d2c765e4646e8f67e3cfcb02fae1887fb4` preserves the
unassociated front as specified above. The native backend fixture exercises the
actual backend, including DMA completion during abort, write-one-to-clear PIO
status, overflow, fault suppression and new-session recovery. The native
firmware formatter feeds the real host splitter and validator, including a
present zero word and a later DMA frontier. Contradictory presence, capture
identity, queue depth and backward frontiers are rejected.

- Full current suite: **715 passed in 96.80 s**.
- Pinned fixed `adaptive_hybrid_regulation` firmware build: passed from a clean
  implementation checkout; session `202609130a510003`.
- Program storage: 223,260 bytes. Static RAM: 154,140 bytes, unchanged;
  available runtime memory: 108,004 bytes.
- Development UF2: 481,792 bytes, SHA-256
  `40c4524f42fb75c8daedf8d0123163e186d4db7ff38f52fbf85cb5c1ecf760ea`.

This validation covers software behavior and the fixed-profile build. No
hardware operation, physical qualification, or operational-path rehearsal of a
new exact campaign bundle occurred. The result is not bench-entry authority
and does not establish that the reference-association defect is repaired.
