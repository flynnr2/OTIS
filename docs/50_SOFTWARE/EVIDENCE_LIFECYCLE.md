# Evidence Lifecycle

## Current policy

Current HEAD creates and reads only the `adaptive_hybrid_regulation` package
contract. Every non-template package requires canonical `run_manifest.json`,
`raw/serial.log`, and immutable `evidence_manifest.json`. Historical packages
remain immutable and are interpreted only with their recorded source revision;
current HEAD deliberately provides no compatibility reader.

Raw OTIS evidence remains outside Git. Each retained package is registered in
the external content-addressed `otis_evidence_index_v1` with its content hash,
per-file manifest, storage location, source revision, build identity, image
identity, attempt classification, result or failure reason, and analyzer
identity.

The default local index is:

```text
~/.local/share/otis/evidence_index_v1.json
```

`host.otis_tools.evidence_index` rejects an index path inside the repository.
It hashes regular files recursively in deterministic relative-path order and
rejects symlinks, so a recorded identity cannot depend on an unrecorded target.
Validation succeeds when at least one registered storage location still has
the exact recorded content identity. A moved exact copy may be added as a
second location by registering it with the same provenance.

## Attempt classification

Every package uses one explicit classification:

- `successful_rehearsal`
- `failed_rehearsal`
- `successful_qualification`
- `failed_qualification`
- `completed_campaign`
- `interrupted_campaign`
- `diagnostic`
- `historical`

Failure or interruption is evidence, not absence. The result field records the
concrete result or failure reason rather than implying that an unsealed attempt
passed.

Current physical seals and their registrations separately record
`evidence_integrity` (`passed` or `review_required`) and `scientific_outcome`:

| Scientific outcome | Meaning | Campaign registration |
| --- | --- | --- |
| `qualified_complete` | Exact healthy endpoint and all 259,200 frozen accepted apertures | `completed_campaign` or explicitly `successful_qualification` |
| `bounded_nonpass` | A defined finite scientific rejection | `completed_campaign` |
| `interrupted_incomplete` | Operator abort or right-censored incomplete attempt | `interrupted_campaign` |
| `diagnostic_complete` | Completed inhibited zero-write diagnostic | `diagnostic` |
| `undetermined` | Missing or contradictory evidence requires review | `diagnostic` |

`completed_campaign` describes a concluded scientific decision; only
`qualified_complete` is a qualification pass. The seal's `status` is the
integrity result, never shorthand for the scientific outcome. An exact,
well-preserved early operator abort can have passing integrity and remain
scientifically incomplete. Registration validates every claimed passing
integrity seal, including interrupted and diagnostic outcomes. Unsealed raw
inventory can still be retained without asserting passing integrity.

The analyzer derives the outcome from the frozen bench envelope, terminal
identity and exact integer accepted-aperture count. Registration independently
checks that derivation against the retained supervisor evidence; a success
label or a recent timestamp is insufficient. Direct registration and journal
recovery use the same rules. Old seals and index records are not rewritten or
silently upgraded by this change.

The success-bearing classifications `successful_rehearsal`,
`successful_qualification`, and `completed_campaign` are fail-closed. Direct
registration and crash recovery require the exact current run manifest, a
complete and valid immutable evidence snapshot, a passing content-hashed
analyzer seal, and agreement between the package's source, build, image,
analyzer, terminal, and primary-decision identities and the proposed index
metadata. The current repository has no operational-rehearsal producer or seal,
so `successful_rehearsal` cannot currently be registered.

Failed, interrupted, diagnostic, and historical classifications remain the
explicit raw-inventory path. They preserve content and supplied provenance but
do not by themselves claim that current package validation or analysis passed.
Any explicit passing-integrity claim also requires the seal-validation gate.

## Mothball gate

Mothballing keeps the raw package and its identity but removes it from active
investigation. It requires all of the following:

1. no active investigation, programme, or unresolved anomaly depends on it;
2. its decision-bearing result and lessons are captured in a reviewed tracked
   summary, test, contract, or limitation;
3. that reviewed summary exists and is content-hashed in the index; and
4. the operator or maintainer running the command explicitly confirms there is
   no active dependency.

Example:

```bash
.venv/bin/python -m host.otis_tools.evidence_index mothball CONTENT_SHA256 \
  --reviewed-summary docs/path/to/reviewed-summary.md \
  --reason "superseded by the reviewed result" \
  --confirm-no-active-dependency
```

Mothballing does not delete or rewrite raw files.

## Future deletion gate

No current repository command deletes indexed raw evidence. Deletion may be
introduced only after all of these prerequisites are met:

1. OTIS has reached an explicitly declared stable and mature milestone;
2. no active programme, investigation, accepted claim, reproducibility need,
   or unresolved anomaly depends on the package;
3. the package is already mothballed;
4. a reviewed compact summary and the full identity/provenance record remain;
5. at least one independent validation of the retained index has passed; and
6. the operator gives explicit approval for the named content identities.

Deletion must target exact content hashes, never a broad path, glob, workspace,
or unresolved environment variable. The operation and outcome must be logged,
and the tracked summary and content identity normally remain permanently.

## Registration example

```bash
.venv/bin/python -m host.otis_tools.evidence_index register /absolute/run/path \
  --source-revision GIT_REVISION \
  --build-identity FIRMWARE_MANIFEST_SHA256 \
  --image-identity adaptive_hybrid_regulation \
  --attempt-classification diagnostic \
  --result-or-failure-reason "retained diagnostic evidence" \
  --analyzer-identity PRODUCING_TOOL_SHA256
```

The external index is mutable stewardship metadata; each raw package remains
immutable scientific evidence. If a package changes, it has a new content
identity and must be registered as a new package.

An interrupted finalizer can exceptionally register a package immediately
before appending its final seal, then register the completed package at the same
location. Do not delete the earlier registration or pretend its bytes still
occupy that path. If the completed record proves that every predecessor file is
retained byte-for-byte and only new files were added, preserve the earlier
identity with an explicit append-only registration disposition:

```bash
.venv/bin/python -m host.otis_tools.evidence_index \
  --index /absolute/path/to/evidence_index_v1.json \
  supersede-append-only-registration PREDECESSOR_SHA256 SUCCESSOR_SHA256 \
  --reason "offline finalization appended the retained seal" \
  --confirm-all-predecessor-files-retained
```

This operation changes only index stewardship metadata. It records both
registration times, the shared in-place location, the exact added paths, and
explicit `evidence_preserved: true` / `data_deleted: false` assertions. Index
validation remains fail-closed: the successor must be present under its exact
standard record, the predecessor manifest must reconstruct its original
content identity, and every predecessor file entry must occur unchanged in the
successor. Changed or removed predecessor files cannot use this disposition.

## Crash-recoverable finalization

The current adaptive-regulation runner creates an external
`otis_evidence_finalization_v1` journal before finalization. It records the
ordered phases `capture_closed`, `completion`, `snapshot`, `analysis`, `seal`,
and `registration`, plus an immutable registration intent and expected sealed
package identity. Phase completion is idempotent. The first error remains the
`primary_failure`; cleanup and registration errors are retained separately and
cannot replace the acquisition or analyzer verdict.

The immutable evidence snapshot covers acquisition inputs and outputs. Analyzer
results are created only after that snapshot and are bound separately by the
seal; the final package identity covers the snapshot, analyzer results, report,
and seal together. This keeps the recorded phase order truthful while allowing
an analyzer repair to supersede a verdict without rewriting acquisition
evidence.

The evidence index uses an adjacent advisory lock for the complete
load-modify-fsync-replace transaction. The replacement file and parent
directory are fsynced. Parallel registrations therefore cannot overwrite one
another.

If registration is interrupted after a valid seal, recover without changing
the package:

```bash
.venv/bin/python -m host.otis_tools.evidence_finalization \
  /absolute/run-parent/.otis-finalization/RUN_NAME.json
```

Recovery requires `COMPLETE`, `evidence_manifest.json`, the declared seal, and
an exact match to the content identity recorded before the failed registration.
It then performs the same package, seal, metadata, and idempotent locked
registration validation as direct registration. A mutation or unsupported
success claim is rejected without being indexed as a successful package.

## Host-only reanalysis and supersession

New adaptive-hybrid acquisitions declare their recording-frontier policy in
the frozen manifest. The capture owner records the first reconstructable
opening pair live and retains its immutable identity plus live readiness state.
The initial incomplete prefix remains in full raw/CSV evidence. At closure,
the analyzer verifies that previously recorded selection and strictly replays
all required subsequent observations; it must not choose a later frontier or
invent one during analysis. An estimate received after attachment may still
have unretained source history and therefore remain unqualified. See
`data_contracts/acquisition_frontier_v1.md`. This prospective scope cannot be
applied retroactively to change an existing campaign's acceptance rules.

A failed analysis does not invalidate a complete raw acquisition when the
defect is demonstrably downstream of capture. Reanalysis may supersede the
earlier verdict without repeating hardware only when all of these conditions
hold:

1. the raw package is sealed or otherwise content-addressed and unchanged;
2. capture completeness, command history, acknowledgements, serial ownership,
   timing, segmentation, and terminal physical state are sufficient for the
   claim;
3. the repair is confined to a deterministic offline consumer and could not
   have changed acquisition, safety, firmware behavior, or the scientific
   result; and
4. the new result binds the raw content identity, old and new analyzer
   identities, original verdict, superseding verdict, reason, and review
   authority.

Reanalysis may correct the implementation of a criterion frozen before the
acquisition. It must not weaken, replace, or reinterpret an acceptance criterion
after examining the evidence merely to turn a non-pass into a pass.

Preserve the original report. Store a new provenance-linked result rather than
rewriting the acquisition package. The new product must record:

- source package content hash and each consumed source-file hash;
- original source revision, analyzer identity, and verdict;
- new source revision, analyzer identity, and verdict;
- superseded product identity, supersession reason, review authority, and UTC;
- `actionable: false`, `actuation_authorized: false`, and
  `hardware_interaction: false`.

For the current adaptive-hybrid programme, publish that separate addendum with
the offline-only supersession command:

```bash
.venv/bin/python -m host.otis_tools.adaptive_hybrid_supersede \
  /absolute/path/to/the/registered-diagnostic-run \
  --evidence-index /absolute/path/to/evidence_index_v1.json
```

The command requires the unchanged diagnostic package, its completed external
finalization journal, original review-required seal, and exact diagnostic index
record. It reruns only deterministic analyzer consumers, writes the corrected
seal and canonical supersession manifest to a separate content-addressed
addendum directory, and registers that addendum without changing or
reclassifying the original package. The addendum binds the original failure,
old and new analyzer/replay identities, frozen source-file identities, and the
explicit no-I/O/no-authority conditions. An exact retry is idempotent; a
conflicting second result for the same source seal is rejected.

If any condition is not met, repeat the
shortest affected operational gate: a short operational-path rehearsal for
live host orchestration changes, or physical qualification when firmware,
real-time I/O, plant behavior, or acquired evidence could change.
