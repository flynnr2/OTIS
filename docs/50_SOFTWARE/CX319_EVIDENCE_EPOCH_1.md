# CX319 Evidence Epoch 1 Compatibility Floor

## Decision

Current HEAD supports one operational and evidence epoch:
`CX319_EVIDENCE_EPOCH_1`.

A current run package uses `run_manifest.json`, `raw/serial.log`, the canonical
`csv/` and `reports/` directories, and an immutable `evidence_manifest.json`
for every non-template package. It carries complete firmware/build provenance
and current CX319 profile, policy, authority, analyzer, plant-model, and
evidence identities. `cx319_tight_lower` and `cx319_tight_upper` are the only
supported build profiles.

The exact deployed firmware wire vocabulary still contains `cx317_*` and one
owner-handoff transition contains the deployed
`CX318_STAGE5_TRANSITION_SPOOL` identity. Those strings remain because changing
them would reinterpret current observations. They are wire provenance, not
support for CX317/CX318 campaign tooling. Existing sealed CX319 packages may
also contain an inert `h_phase: H1` field; the loader accepts it only when the
manifest has an exact current CX319 stage and supported CX319 profile identity.
New manifests declare the compatibility floor explicitly and omit `h_phase`.

## Fail-closed boundary

Current readers reject:

- `manifest.json` instead of `run_manifest.json`;
- root-level `serial_raw.log` or `raw_serial.log`;
- a non-template package without `evidence_manifest.json`;
- H0, H1, SW1, Phase 4/5, CX317, and non-transition CX318 manifests;
- retired plant-model identities, PPS qualification v1, `estimates_v1`, and
  retired replay/policy variants.

The error directs the operator to the recorded Git revision or archival
checkout. Current code never silently migrates or grants authority to a
historical package.

## Historical reproduction

1. Read the package manifest, immutable bundle, evidence index entry, or
   reviewed report to obtain the exact source revision and tool identities.
2. Create a separate checkout at that revision: `git worktree add PATH REVISION`.
3. Verify artifact hashes against that revision's manifest and matrix.
4. Run that revision's documented analyzer or verification command.

No archival tags existed when this floor was established; recorded commits are
therefore the exact reproduction mechanism. Historical reports under
`docs/60_EXPERIMENTS/` remain authoritative records and are not rewritten.

## Reanalysis and supersession

Current analysis of historical raw evidence creates a new derived product; it
never edits the source package. The product must record the source package
content hash and source-file hashes, original revision and analyzer identity,
new revision and analyzer identity, original and superseding verdicts, reason,
review authority, and the identity of the superseded product. The original
report remains intact. A reanalysis grants no operational authority.

If the change could affect capture completeness, commands, acknowledgement,
serial ownership, timing, segmentation, safety, firmware behavior, or the
scientific observation, repeat the shortest affected operational or physical
gate instead of using host-only supersession.
