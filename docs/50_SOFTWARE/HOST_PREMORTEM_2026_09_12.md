# Host replacement pre-mortem — 12 September 2026

## Verdict and scope

The five-job replacement removes a substantial amount of orchestration, but
simplicity alone is not evidence of correctness. Adversarial review found real
escapes at capture closure, physical entry, rehearsal admission, and operator
abort. These are host/platform defects; none is evidence against D14/D8 timing or
the oscillator. They were repaired in the same integrated replacement, before issuing another
bench candidate.

The review covered the actual owner, capture worker, startup and command paths,
PTY simulator, offline analysis, portable evidence, and physical-entry wrapper.
It used deliberate malformed input, exceptions, delayed observations, duplicate
owners, changed files, and producer-to-consumer tests. It did not operate the
bench Mac. That Mac's held physical attempt remains a separate live acquisition;
source replacement cannot dispose of it.

## Concrete escapes and remedies

| Priority | Failure imagined or reproduced | Consequence | Remedy and evidence |
| --- | --- | --- | --- |
| P1 | Capture raises during startup, writing, disconnect, or serial close, yet its cleanup publishes clean closure. | An incomplete acquisition can be labelled complete. | Publish closure only after a graceful record boundary and successful serial/evidence closure. Abnormal paths retain the exclusive reservation and original error. Inject startup, write, disconnect, immediate-stop, and close failures. |
| P1 | Unterminated serial input grows a hidden raw buffer; shutdown discards it. | Memory exhaustion and loss of canonical observations. | Retain raw bytes immediately. Bound memory for deferred markers with disk spooling; explicitly mark the synthetic delimiter after an interrupted partial record. Exercise a 1 MiB unterminated stream and 2,000 deferred markers. |
| P1 | A second worker opens evidence before discovering serial is already owned. | Existing evidence can change despite acquisition rejection. | Exclusively reserve the run directory before opening evidence. Verify duplicate startup changes no existing file bytes. This is a local ownership guard, not a distributed filesystem lock. |
| P1 | A receipt points to the seal file where the consumer expects its directory; relocation overrides hide the error in tests. | A successful rehearsal cannot authorize ordinary entry. | Use explicit directory/manifest result names. Validate every produced receipt through the default entry consumer before publication. Test the real producer without overrides, then relocation separately. |
| P1 | Self-consistent minimal JSON claims a passing analysis or a physical package claims to be a rehearsal. | Preflight admits insufficient evidence. | Require the actual analyzer contract, identities, digest, checks, and source hashes matching sealed inventory. Rehearsal requires a simulated run without physical authority. Store boundary claims once, in the sealed report. |
| P1 | Ctrl-C abort submission raises, or fresh capture state never arrives after submission. | Foreground supervision can unwind or wait indefinitely while capture remains alive. | Retain ownership and the submission failure; distinguish submission, delivery, and response. Bound the delivery observation from submission, independently of state freshness. Exercise the actual review-hold path. |
| P1 | A PPS block arrives with begin/end but missing middle fields; the reducer merges new fields with an old healthy tail. | Fresh ACTIVE traffic can present historical PPS counters and health as current, including at the zero-write endpoint. | Stage the existing firmware PPS snapshot cohort and replace its fields atomically; never inherit missing fields from its predecessor. Use the existing producer-domain coherence bound, with no new timer or firmware protocol. Exercise the reducer through the first supervisor decision. |
| P1 | A cloud/build process replaces the UF2 between verification and upload. | Uploaded bytes differ from the reviewed image. | Copy and hash the selected bytes into a read-only run-local image before upload, then verify after upload. Inject source replacement during board discovery. Record full upload output and one attempted upload. |
| P2 | Entry fails before the run record exists, or the external receipt disappears later. | The failed physical boundary or entry authorization cannot be reconstructed. | Retain exact spec and receipt before I/O; record entry phases and the primary failure. Failure to write a secondary diagnostic must not replace the primary exception. |
| P2 | The simulator's startup reason differs from firmware; tests patch the expected value. | A self-consistent simulation hides real startup incompatibility. | Align the simulator with the firmware declaration and bind it with a source check. Exercise healthy zero-write completion through the actual worker, supervisor, closure, analysis, and package. |
| P2 | CLI prints a failed-operation diagnostic but exits successfully. | An outer script advances despite review-required analysis or failed runtime. | Return nonzero for failed operations while preserving JSON; verifying a valid diagnostic package and completing a scientifically useful non-pass remain successful operations. |
| P2 | A tiny closure object claims completeness, or a symlink substitutes for the package seal. | Structural validation overstates retained evidence. | Validate the current closure contract and final capture marker; require regular package files. Preserve partial diagnostic evidence without promoting it to complete. |

These checks protect instrument outcomes rather than creating another campaign
framework. A producer acknowledgement is evidence at that boundary only; tests
must reach its first decision-bearing consumer.

## What can still go wrong

### Operating-system stalls are outside the priority FIFO guarantee

A separate priority FIFO defeats normal command backpressure. It does not bypass
a capture thread stuck inside serial open/read or synchronous filesystem I/O.
User-space deadlines cannot cancel an arbitrary blocked kernel call. Firmware's
independent fail-static behaviour remains essential. A dead or stuck capture
owner is not proof of continued recording, even if its process exists.

Short physical entry must check actual driver response, capture freshness, and
bounded firmware behaviour. No new thread/process/watchdog hierarchy is proposed
merely to claim an impossible universal host deadline. Storage exhaustion must
produce an incomplete acquisition, never a forged clean closure.

### Rehearsal is only as good as the exercised producer

The PTY path uses the real host processes and protocol consumers, but a synthetic
device. It cannot establish firmware cross-core propagation, USB reset and
re-enumeration behaviour, real serial congestion, or D14 electrical immunity.
Source checks catch omitted fields and simple simulator drift; they cannot prove
all firmware semantics. The next physical gate remains necessary and must use the
exact reviewed image and host specification.

Freshness also differs from causal sufficiency. The PPS cohort repair uses the
existing firmware framing; independent ACTIVE and PPS ordinals are not required
to be simultaneous. The startup/transaction checks must retain their explicit
session, epoch, ordinal, and source frontiers. Missing component publication is a
separate failure case from an entirely stale stream. Host snapshot freshness is
not itself proof of fresh hardware observations.

### Frozen files are an operational premise

Entry validates the toolset, but Python modules already imported by the parent
and those later imported by a child can differ if the checkout changes during
execution. Run the candidate from a clean, isolated checkout and leave it alone
until capture closes. A retained hash does not make hot-editing an active process
safe. Avoid adding a second deployment/archive framework solely to support it.

Likewise, checksums establish content consistency, not authenticity against an
actor deliberately rewriting every report and hash. This is a trusted local
scientific workflow, not an adversarial signing service.

### Duration and data volume need their own evidence

A short rehearsal proves transaction and lifecycle behaviour, not 72-hour
capacity. The current analyzer loads CNT/SNP/REF/APS/EST/EVT into memory,
retains raw interval/association/index structures, and reloads APS for phase
joins. It validates the CSVs and hashes source files in additional passes.
At 259,200 apertures and the firmware's 600-second estimate cadence, selecting
sources scans approximately 111,974,400 span candidates for 432 estimates.

A bounded current-schema probe replayed 25,000 apertures and 41 estimates exactly
in 0.570 seconds, with 150,487,040 bytes peak process RSS (a repeated
measurement; the original probe used 141,344,768 bytes). Linear scaling of that
in-memory core alone is roughly 1.5 GiB; that is an extrapolation, not a full
analyzer measurement, and excludes CSV parsing and additional indexes. The
largest existing raw replay test covers 49,752 rows, not the full 72-hour
CSV/analyzer/report path. Full-artifact capacity remains an explicit open gate
before a long campaign, especially on the older bench Mac. It does not block the
short inhibited entry. The retained probe source, invocation and measured output accompany the delivery
under `capacity-probe/`. The likely remedies are indexed source selection and
streaming reconstruction; choose them against a measured budget, not guesswork. A capacity
failure after successful capture should be repaired by replaying the unchanged
evidence; it must not force another physical acquisition.

Power loss can also leave recently buffered data or an active reservation. File
flush and a content seal are not an all-files atomic durability guarantee. Do
not delete a reservation merely to make finalization proceed; establish worker
death and preserve the interrupted state for review.

## Verification retained

The integrated current suite passed: **662 tests in 90.54 seconds**, including
native firmware/source checks, actual PTY lifecycle tests, and the adversarial
producer-to-consumer regressions above. The affected fixed firmware profile
compiled and independently reproduced with byte-identical UF2/BIN/header and
matching semantic provenance/resources. The host-only red-team changes did not
change those firmware inputs. Build logs and the full release-test log accompany
the engineering delivery. ELF/map debug-path bytes are not claimed identical.

This is evidence for the enumerated software boundaries. It is not physical
qualification, a universal blocked-I/O guarantee, or a full-duration capacity
measurement.

## Entry decision

Before a new physical attempt: finish the grouped regressions and release checks,
run both actual firmware-bound public CLI rehearsals, verify their default entry
receipts, and verify the delivered bytes after relocation. A successful inhibited
physical entry is the next integration decision. It is not permission to assert
72-hour qualification or enable a campaign the operator has not selected.

The already-running bench attempt requires explicit operator disposition first.
No local test, review finding, or replacement implementation has abort authority
over that acquisition.
