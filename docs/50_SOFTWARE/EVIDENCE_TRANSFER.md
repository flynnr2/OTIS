# Closed evidence transfer between workstations

Use Git for source, reviewed summaries, contracts, and compact identities. Use
a delivery folder for immutable compressed evidence packages. iCloud is the
first proposed carrier; Google Drive or another file transport can carry the
same files without changing the evidence contract. No cloud SDK, synchronized
live capture, or shared mutable index is required.

Keep the bench original independently. Each receiving machine analyzes its own
fully downloaded, checksum-verified copy outside the cloud folder. A cloud
filename, placeholder, or matching reported size does not establish a complete
copy. SHA-256 verifies bytes relative to the sender's retained digest, not
authorship or scientific validity.

## Sender

Run on the bench machine after capture has closed and sealing is finished:

```bash
.venv/bin/python -m host.otis_tools.evidence_transfer inspect /absolute/sealed/run
.venv/bin/python -m host.otis_tools.evidence_transfer publish /absolute/sealed/run \
  --output-dir /absolute/local/delivery-staging
```

`inspect` reports the uncompressed bytes, file count and content identity.
`publish` creates `<content-sha256>.tar.gz` and
`<content-sha256>.transfer.json`. The receipt records the compressed size,
archive checksum, package checksum and every source-file identity. Archive
bytes are verified against the source before publication; the receipt appears
last. Existing delivery files are never overwritten. Keep a receipt copy with
the bench evidence and copy the two finished files to the chosen cloud folder.

The command requires closure, run manifest, evidence snapshot and physical seal
files and refuses an active-capture marker, links or unexpected special files.
After those closure checks, it permits only the runner's three retained FIFO
endpoints: `control/normal_commands.fifo`, `control/host_abort.fifo`, and
`control/emergency_abort.fifo`. It records them in `omitted_runtime_endpoints`
as objects with `relative_path` and `type: "fifo"`; it neither opens nor archives
them. The receipt preserves this inventory alongside the regular-file identity,
and publication checks that both remain unchanged. No other FIFO location or
special-file type is permitted. These are
transport prerequisites: it deliberately neither reinterprets historical
schemas nor claims that seal integrity or scientific acceptance passed. A
sealed interrupted or review-required attempt remains useful transferable
evidence.

## Receiver

Obtain the archive and its sender receipt. Use both sender checksums:

```bash
.venv/bin/python -m host.otis_tools.evidence_transfer receive /downloaded/package.tar.gz \
  --archive-sha256 ARCHIVE_SHA256_FROM_SENDER \
  --content-sha256 PACKAGE_SHA256_FROM_SENDER \
  --destination /absolute/local/evidence
```

The command validates the compressed archive before extracting regular files
into a temporary local directory. It rejects traversal, links, duplicate paths,
checksum disagreement and incomplete closure. Only a verified complete tree is
promoted to `/absolute/local/evidence/<content-sha256>`. An exact retry reuses
the identical copy; a conflicting existing copy is left unchanged and rejected.
The source package, archive and external evidence index are not rewritten.

The receiver must independently apply the appropriate source revision's
scientific reader. Register verified locations only with the corresponding
provenance and classification rules. Do not use a new registration to erase a
wrong original classification. Retain the original result and publish an
explicit provenance-linked correction.

## First transfer and companion metadata

The first received package is the closed 10–11 September 2026 attempt:
600,757,463 bytes / 55 regular files, delivered in a 67,278,492-byte gzip archive.
Its regular-file content hash matches the prior bench handover exactly. Its
identity, targeted review and qualification prefix are recorded in
`../60_EXPERIMENTS/CONTINGENT_72H_ATTEMPT1_REVIEW_2026_09_11.md`.

That first delivery used an ordinary enclosing-directory tar, including the
three runtime FIFO entries, rather than the canonical publisher format above.
A one-time checked import preserved every regular file, recorded the omitted
FIFO entries locally, and verified the independently supplied package hash.
It did not claim verification against an unavailable sender archive digest or
use the canonical receiver to accept a different archive format. Future
deliveries should use the publisher's files-only archive and sender receipt.

Also retain a frozen copy of the run's external finalization journal and its
exact original index record. They sit outside the package and are therefore
not in its archive; their hashes and locations must accompany the handover for
classification review. Do not synchronize or replace either machine's live
index. Review outstanding journals and stashes individually at their recorded
revisions; do not apply a blanket finalization or migration.

This first transfer tests delivery reliability and disk use. It does not
commit OTIS to iCloud as the long-term archive or sole backup.
