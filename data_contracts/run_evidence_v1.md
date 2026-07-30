# OTIS Run Evidence Snapshot v1

`evidence_manifest.json` is the immutable, machine-verifiable snapshot of the
primary evidence used to reproduce an OTIS run. Its machine-readable schema is
`schemas/run_evidence_v1.schema.json`.

## Repository storage policy

Evidence snapshots normally live inside local `runs/` directories. The
repository `.gitignore` is authoritative, `runs/` is intentionally ignored,
and neither a snapshot nor its source run may be force-added to Git. Snapshot
integrity and Git storage are separate concerns: sealing proves the retained
local bytes, while the ignore policy keeps bulky evidence out of repository
history.

Tracked artifacts promoted from a run must be compact, reviewed products stored
outside `runs/`, such as schemas, contracts, plant models, result summaries, or
purpose-built fixtures. Documentation references to `runs/...` identify local
provenance and need not resolve in a fresh clone.

## Scope

The snapshot covers:

- the selected run manifest;
- `config.env`, when present;
- an exact `selected_profile.yaml` copy of the manifest-selected repository
  profile, when a profile is declared;
- every regular file below `raw/`, plus legacy root-level raw serial logs;
- every existing file declared by the run manifest.

When the declared `health_v1` evidence contains the new-only
`build,provenance_format,otis_generated_build_v1` sentinel, the snapshot also
records the exact emitted Git commit,
clean/dirty source state, canonical build-input source hash, configuration hash,
profile, generated FQBN/board identity, Arduino core provider/version and
installed-byte hash, compiler/toolchain and installed-byte hash, Arduino CLI
version, and build invocation identity as `firmware_build_provenance`.
These values are derived from the sealed device output; a detached build-side
claim is not substituted for what the device reported. A partial new banner is
rejected. Historical identity-like rows without the sentinel remain legacy v1
evidence and do not acquire a new provenance interpretation. A run manifest
may require the complete banner with
`firmware.build_provenance_required: true`; new OTIS Phase 5 candidate
templates do so.

Reports, plots, and derived products are covered only when the run manifest
declares them. They are otherwise reproducible outputs, not primary evidence.
The `COMPLETE` marker and the snapshot file itself are deliberately excluded.

## Canonical form and digests

Every artifact entry records a normalized run-relative path, evidence role,
byte length, and lowercase SHA-256 digest. Entries are sorted bytewise by path.
`snapshot_digest` is SHA-256 over compact, UTF-8 JSON with sorted object keys
containing exactly the following base fields, plus
`firmware_build_provenance` when emitted by the device:

```text
schema_version, run_id, run_state, digest_algorithm, artifacts
```

The digest is independent of filesystem metadata, source directory, locale,
clock, and JSON indentation. Timestamps are intentionally absent.

## Lifecycle

Create a snapshot only after capture has stopped and the `COMPLETE` marker is
present:

```bash
python3 -m host.otis_tools.evidence path/to/run
python3 -m host.otis_tools.validate_run path/to/run
```

The command refuses an in-progress capture and refuses to overwrite an existing
snapshot. `--allow-incomplete` exists for deliberately preserving a partial
run; the canonical snapshot records `run_state: partial`, and it does not imply
scientific completeness.

Once sealed, do not edit evidence in place. Preserve the original run and make
a new run directory or explicitly versioned derived product. Validation fails
if snapshotted bytes change, a snapshotted artifact disappears, snapshot
metadata changes without a matching canonical digest, or new evidence-bearing
raw/config/profile/declared files are not covered.

## Compatibility

Historical runs without `evidence_manifest.json` remain loadable and valid.
The validator emits a warning so their weaker provenance is visible. Templates
do not require or accept evidence snapshots.
