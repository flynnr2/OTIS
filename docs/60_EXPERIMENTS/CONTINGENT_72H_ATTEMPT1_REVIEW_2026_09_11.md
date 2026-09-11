# Contingent 72-hour attempt 1: retained-evidence review

Reviewed locally on 11 September 2026. This note records a classification
clarification and targeted independent checks. It does not replace the source
package, rerun its complete historical analyzer, or change its frozen acceptance
criteria. Historical interpretation belongs to source revision
`f6c72624f6fed29f6be86ae252247ef075d44e2d`.

## Evidence identity and transfer

- Package content SHA-256:
  `43a596f175122b632bb40a410b33c3bd956923a89d6d09ef0114c178582d0739`.
- Regular files: 55; uncompressed bytes: 600,757,463.
- Received gzip archive: 67,278,492 bytes; observed archive SHA-256:
  `60d0bc5d54e7ef8926f17b15c0c299c937ed4a7d57d3f3ac3620b6dce0622086`.
- Original seal semantic SHA-256, independently recomputed:
  `dcb2c6b7b2838ef8e056163e2af707a24104ead33d2c310ab489303d26fcbf7d`.
- All 17 CSV content hashes recorded by that seal match the received files.

The extracted regular-file tree exactly matches the package identity supplied
by the bench before transfer. No separate sender archive digest was supplied.
The ordinary tar contains three command FIFO entries, which are recorded in a
local receipt and were not recreated. They contain no package file bytes. The
source archive and all 55 regular files remain unchanged. The local evidence
copy and receipt are under ignored `runs/imported/`; no raw campaign data is
added to Git. The external bench index and journal were not included.

## Classification clarification

The scientific outcome is **interrupted incomplete**, with 35,480 of 259,200
required qualified apertures retained: 9 hours, 51 minutes, 20 seconds. It is
not an uninterrupted 72-hour qualification pass.

The original seal reports `status=passed` alongside
`terminal_result=aborted` and
`primary_decision=adaptive_hybrid_operator_abort`. Its status describes the
original tool's integrity checks; it cannot establish completion of the
scientific duration. The handover's reported `completed_campaign` registration
therefore needs a provenance-linked correction in the external registry.
That registry has not been modified or independently inspected here.

The retained supervisor state records four responses, four corrections,
17 cumulative DAC movement codes, final code 43078 (`0xA846`), and DAC epoch 5.
Review hold began at 07:34:59 UTC; the explicit operator abort was recorded at
11:35:25 UTC. Physical serial closure followed at 11:35:27 UTC and `COMPLETE`
at 11:35:28 UTC. The closure record reports one emergency abort sent, zero
parser errors, rejected commands, malformed UTF-8 records, or reconnects.
These are retained component reports, not a new physical observation.

## Targeted raw-evidence checks

Independent examination of 52,309 adjacent retained SNP pairs reproduces their
CNT counts and endpoints and the associated REF timestamps, including 121
D8 down-counter wraps. The 52,310 retained reference occurrences span 12 native
32-bit microsecond timer wraps. Their independently ordered source and emitted
sequences have no gaps in this package; all retained SNP statuses are zero.

The first retained CNT lacks its opening SNP because recording begins after
the producer has started. Its raw arithmetic cannot be independently proved
from this package. This limitation does not authorize inventing an anchor or
claiming complete capture before the retained frontier.

At the reported disturbance, two adjacent D8 counts are 2,462,937 and
7,537,063, summing exactly to 10,000,000. Their D14 intervals are 246,294 and
753,707 native microsecond ticks. This supports the reported extra reference
edge and continuous D8 counting over the split aperture. It does not identify
whether the receiver output, electrical path, or capture input caused the
extra observation. The frozen uninterrupted-attempt rule remains unchanged.

## Consequence for current development

Using the real package exposed a defect in the new raw replay implementation
before bench entry. `REF.event_seq` is the foreground event counter, whereas
`SNP.reference_sequence` is the physical D14 source counter. This package has
an offset of 1000; firmware does not guarantee that offset because external
events can also advance the foreground counter.

Replay must preserve each counter's own semantics and bind ordered D14
occurrences by immutable timestamps in the declared domain. It must not require
counter equality, use D10 evidence as a validity veto, or confuse repeated low
32-bit timestamps across rollover. This is a current offline-verifier defect,
not evidence that the historical physical observations failed. Regression and
integration verification of that repair are recorded in the consolidation
programme.
