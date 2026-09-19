# Accepted-PPS firmware and host integration

## Decision and scope

The coupled production cutover has passed the current release verification
and complete simulated operational path. It is ready for review and merge,
then an exact-bundle rehearsal on the rig. No firmware was flashed, no physical
control action was performed, and the original sealed 72-hour attempt remains
unchanged and incomplete.

One post-association selector now supplies the same accepted-span outcome to
frequency and relative-phase consumers. After eight qualifying acquisition
intervals, it admits subsequent D14 boundaries within the inclusive
1,000,000 ± 1,250 local microsecond-tick window. An excluded early candidate
does not replace the accepted anchor or erase valid measurement history.
Missing, late, excessive, or integrity-invalid candidates require a new
acceptance epoch and acquisition. D14 remains the timing authority, D8 the
oscillator count input, and D10 optional external-event evidence.

The integrated policy SHA-256 is
`ccbac9f756a0ff2932a3f1c160c464af06eaaa1713d8bbc0ceba73762f80fad3`.
Its policy artifact has no independent control authority. Actual steering
still requires the instrument's qualification, exact source, command, and
acknowledgement gates. See the
[acceptance contract](../../data_contracts/reference_acceptance_v2.md).

## Complete producer-to-consumer boundary

Raw REF/SNP/CNT observations retain their existing schemas and meanings.
APS v1 records accepted endpoints and their complete raw count sources.
EST v3, RPH/PHE v2, AHY/ACT v3, AHM v2, and ACTIVE snapshot v2 carry the
corresponding capture session, acceptance epoch, and accepted-boundary identity.
Superseded current readers are removed; Git history retains historical tools.

The selected frequency estimate requires exactly 600 accepted spans in one
acceptance epoch. That identity reaches the request, acknowledgement, Core 0
execution gate, downstream measurement consumer, response, and metadata
requalification. Modular accepted ordinal zero is legal; qualification never
adds durations from different acceptance epochs. DAC settling starts from the
actual accepted opening. Healthy raw relative-phase history survives a DAC
change and an excluded candidate.

Before host ARM readiness, the recorder reopens the exact canonical CSV
occurrences and reconstructs the full selected APS/raw source and EST
arithmetic. Mutable readiness metadata alone cannot grant authority. A newer
pending estimate retires the older ready proof. Separate firmware queues may
deliver derived evidence before its raw source; bounded pending handling
withholds authority until the exact source arrives, including across a session
transition. Contradictory evidence causes a retained diagnostic review hold.

CPU observation latency does not establish a missing physical PPS. An
unresolved deadline therefore inhibits control without fabricating a physical
discontinuity. The status snapshot retains the latest acceptance-loss cause
through recovery, including source-coordinate ambiguity. It is a latest-cause
diagnostic, not an exhaustive history of every burst transition.

## Verification actually completed

| Gate | Result and scope |
| --- | --- |
| Complete current repository suite | 609 passed in 172.31 s |
| Full operational process rehearsal | Passed twice with the final host implementation; actual PTY capture, supervisor, monitor, command and acknowledgement processes, analyzer, seal, and registration |
| Production measurement consumers | Native frequency/phase tests include the recorded split, selected windows, DAC settling, phase retention, association loss, and reacquisition |
| Authority and transport ordering | Exact Core 0 source predicate; canonical 600-span readiness; delayed raw evidence; session changes; contradictory sources; retained history beyond a microsecond-counter wrap |
| SPSC rollover | Native non-power-of-two queue regression verifies slot order across the 32-bit producer/consumer counter rollover |
| PIO instruction proof | 7,936 cases and 55,552 intervals; existing −1/0/+1-edge digital count-error bound preserved |
| Fixed current firmware profile | Build, binary contract, and resource audit passed; all 131 operational firmware input files still match the verified build |

The fixed build was made from clean integration commit
`065ae346a6a8e15f6d6c6f455d9bc13ef268d553`, using Arduino CLI 1.4.1 and
RP2040 core 6.0.0. Later changes in this tranche affect host source handling,
tests, and reporting, with identical firmware build inputs.

- Firmware source SHA-256:
  `bf57e1b914fc9b7b63ea8b5f1ee059f35ac5afe14d9d0772e2262eb030e4fb7b`.
- Configuration SHA-256:
  `30bc945d43b76c639b7b0c00e86ecfd6c90766b4eac7bf03d09c7704e4342c0f`.
- UF2 SHA-256:
  `a716f74ffb84353b2401f150e1cc940fce92b6899a2c3542ae0af88b0495b44c`.
- Static RAM: 154,248 bytes. Runtime memory available: 107,896 bytes.
  Existing limits remain unchanged; headroom to the static ceiling is
  3,038 bytes. This is not a claim that runtime memory is only 3,038 bytes.

Local build artifacts are under
`build/accepted-span-integration/final-firmware/artifacts/`.

## Rehearsal evidence and defects caught

The retained final-host rehearsal contains 7,803 accepted spans and 7,804 raw
count records, including an extra D14 edge that splits one raw aperture.
Both correction transactions, all eight progressive acknowledgements,
metadata hold and requalification, normal-command obstruction, independent
priority abort delivery, serial-owner-preserving rotation, analysis, sealing,
and registration completed. Scientific duration is accelerated; firmware and
plant identities in this fixture are explicitly synthetic.

The registered package contains 51 files and 9,084,964 bytes, with content
SHA-256 `33c82f21264ae01fedd4e9ef6cb081d07bbc0c4f8805759ad4118f9050b78946`.
The report SHA-256 is
`f0be70a35efae63de230122b7c1ca61ed56f9f72d257379ee415d0e0ce1712f2`.
It is retained locally under
`runs/rehearsals/accepted-span-integration-2026-09-11/` and remains outside Git.
The test deliberately mutates one process-evidence field after validating
registration to prove tamper rejection. The retained copy restores only that
known mutation and reproduces the registered package hash exactly; the
post-test source remains unchanged and the copy provenance is recorded outside
the package in `retention_provenance.json`.

This integration caught platform defects in deterministic tests or rehearsal:
an unrelated orphan raw prefix poisoned readiness; source selection included
the count closing at its opening anchor; separate queue delivery caused false
source errors; timestamp-only selection aliased older records after timer
wrap; and final registration retained obsolete schema requirements. Each was
repaired at the affected boundary and the complete final path passed. Earlier
rehearsal outcomes remain diagnostic evidence, not successful final bundles.
The final full-suite run independently registered a second successful rehearsal
under `a1e9643a1e201e5e76f2f351d38eb0420196509585e26444d8b62814f1004b93`.

## Remaining physical gate

The fixture proves the host process path, not real cross-core scheduling,
USB transport, receiver electrical behavior, or physical steering response.
The native and fixed-build checks cover firmware logic and compiled feature
presence without establishing those physical claims. Timing-only admission
also cannot distinguish a genuine PPS from an impostor inside the window.

After merge, the rig host must build and identify the exact merged revision,
freeze the operational bundle and prospective acceptance criteria, and rehearse
that bundle before the authorized finite live qualification. A changed binary
identity requires exact rebinding; unrelated physical evidence need not be
discarded. The earlier interrupted 72-hour attempt cannot become a pass under
this new policy.
