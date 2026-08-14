# Host Architecture

OTIS host services preserve and analyze timing evidence; hardware capture is
timing truth. Host scheduling, logging, networking, and storage must not define
or modify timestamps.

## Current boundary

Current HEAD implements only `CX319_EVIDENCE_EPOCH_1`; see
`docs/50_SOFTWARE/CX319_EVIDENCE_EPOCH_1.md`. The range-spanning additions are
summarized in
`docs/50_SOFTWARE/CX319_RANGE_SPANNING_CONTRACT_AND_AUTHORITY.md`. Reusable code
is organized by responsibility:

- `capture_device`, `capture_segment_rotation`, and `capture_owner_handoff`
  preserve one known serial owner and complete-record boundaries;
- `capture_runtime_checks` holds sole-owner, live-capture, and bounded
  obstruction/priority-abort checks;
- `active_transactions`, `active_control_policy`, and
  `active_control_supervisor` preserve the current transaction and fail-static
  authority mechanics without retired campaign state modes;
- `measurement_replay`, `frequency_control_replay`,
  `control_evidence_replay`, and `tight_deadband_policy` provide deterministic
  current replay;
- `time_domains` provides the canonical domain-selected rollover and
  progression semantics used by validation, estimation, supervision, replay,
  and analysis;
- `range_spanning_programme`, `range_spanning_bundle`,
  `range_spanning_rehearsal`, `range_spanning_run`, and
  `range_spanning_analyze` provide the exact non-automatic CX319 Part A path;
- `campaign_finalization`, `evidence`, `evidence_finalization`, and
  `evidence_index` preserve acquisition, sealing, recovery, and registration.

Deployed `cx317_*` strings in wire rows, firmware APIs, hashes, and profile
paths remain exact provenance. They do not imply that CX317 campaign CLIs or
formats are supported.

## Capture topology

```text
hardware timing fabric
        ↓
firmware telemetry
        ↓
capture_device (sole USB serial owner)
        ├── raw/serial.log (canonical immutable observations)
        ├── csv/ (interpreted products)
        └── reports/ (state and audit records)
```

Other host processes use bounded run-local FIFOs. The normal FIFO accepts only
the closed command vocabulary for the current operation. The independent
emergency FIFO accepts only `ACTIVE ABORT` and remains usable when normal
command ingress is obstructed. `host_written` proves only that the carrier sent
bytes; firmware telemetry proves receipt, authorization, application, failure,
and resulting state.

Logical segment rotation waits for a complete device record, closes the source
segment, and opens the target under the same PID and serial handle. The current
owner-handoff transition retains its deployed CX318 wire identity because that
identity is present in current sealed CX319 evidence; it has no command or
actuation authority.

## Canonical package

A current package contains:

```text
run_manifest.json
raw/serial.log
csv/
reports/
evidence_manifest.json
COMPLETE
```

The manifest is authoritative for declared artifacts and contracts. Raw
observations are append-only during capture and never overwritten by derived
values. A non-template package without the immutable evidence snapshot is
invalid. Root-level raw-log aliases and `manifest.json` are rejected.

## Replay and analysis

Analysis reads manifest-declared evidence and creates new derived products. It
must preserve raw source hashes, clock domains, estimator/policy/model identity,
and actionability. Reanalysis and supersession follow
`docs/50_SOFTWARE/EVIDENCE_LIFECYCLE.md`; no analyzer may silently make a
historical package current or grant operational authority.

## Authority

Repository code and offline verification do not authorize hardware work.
Operational tools must bind an exact operation-specific authority and frozen
bundle, keep the serial and abort invariants, and fail static on an identity,
health, timeout, or evidence discontinuity. Legacy CX319 operations use
`profiles/programme_status_v2.json`; the range-spanning successor additionally
binds `profiles/qualification/cx319_range_spanning_programme_v1.json`.
