# Evidence lifecycle

A run directory holds one immutable specification, its small run record, raw
serial bytes, derived observation files, owner state/events, and capture closure.
Large experiment data belongs outside Git. Commit small fixtures, contracts,
reviewed findings, and source instead.

While `capture_in_progress.flag` exists, analysis and sealing refuse the run.
The worker creates this reservation exclusively before opening evidence files.
Only the acquisition owner closes capture after the appropriate terminal and
command-delivery evidence. Clean closure is published after serial and evidence
streams have closed successfully. Startup exceptions, write/close failures,
unexpected disconnect, and immediate termination retain the reservation and
cannot report complete capture. A retained reservation after worker death is
a recovery/review condition; offline tools must not simply delete it. An offline tool cannot stop a live instrument.

After closure, `otis package RUN_DIR` performs analysis and seals the retained
payload. It preserves an analyzer failure as `review_required` with an
`undetermined` scientific outcome. A package containing useful partial evidence
is not an uninterrupted qualification pass. Capture completeness requires a
validated current closure record bound to the exact run record and a closed
serial connection. A passing analysis requires its full current report, matching
source hashes, frozen analyzer identity, and successful checks; a small JSON
object claiming success is insufficient. A physical entry retains the exact
rehearsal receipt, including package and sealed boundary-report identities.

The immutable `evidence_package_v1.json` lists each relative regular-file path,
size, and SHA-256 hash. Its content identity also binds the run record, capture
closure disposition, and analysis status. FIFO nodes and transient lock files are
not payload. Symlinks and escaping archive paths are rejected. Historical
absolute paths inside observations remain opaque provenance; validation does not
follow them.

`otis verify RUN_DIR` verifies that inventory and every payload byte. It does not
compile firmware, contact hardware, reinterpret the experiment, or consult a
historical global index. The package remains valid after relocation. A checksum
confirmed on one machine does not prove cloud delivery; the receiving machine
must independently verify the archive and extracted package.

Optional registration records the content identity and local locations in an
external registry. It is idempotent and cannot change the seal. Missing or stale
locations for another experiment cannot block current work. Retry registration
against the existing package instead of repeating capture or analysis.

For a deterministic analyzer repair, preserve the old package, run
`otis analyse RUN_DIR --output EXTERNAL_REPORT.json`, and retain the new report's
source-package and tool identities. The source remains unchanged. A corrected
implementation may apply the original acceptance criterion; it may not redefine
that criterion to fit observed evidence.

Old evidence packages use the tools at their recorded source revision. Current
HEAD deliberately contains no compatibility readers, old campaign CLIs, special
review-resolution seals, or per-failure supersession framework.
