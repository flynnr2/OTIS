# Host Architecture

OTIS host services preserve and analyze timing evidence; hardware capture is
timing truth. Host scheduling, logging, networking, and storage must never
define or modify a timestamp.

## Current boundary

Current HEAD supports one operating path, `adaptive_hybrid_regulation`. The
host package is a closed, acyclic dependency graph. It contains no readers,
aliases, programme registries, compatibility branches, or command-line tools
for retired campaigns. Historical reproduction uses the exact recorded Git
revision.

Responsibilities are grouped as follows:

- `capture_device`, `capture_serial`, `serial_commands`, and
  `adaptive_hybrid_transport` own the bounded serial and command paths;
- `adaptive_hybrid_contract`, `adaptive_hybrid_policy`,
  `adaptive_hybrid_transactions`, and `adaptive_hybrid_supervisor` implement
  the current decision-bearing controller and transaction state;
- `adaptive_hybrid_bundle`, `adaptive_hybrid_proposal`,
  `adaptive_hybrid_structural_preflight`, `adaptive_hybrid_activation`, and
  `adaptive_hybrid_run` form the frozen operational path;
- `authoritative_inputs` freezes the exact five-profile transitive closure and
  all seven current schemas as content-addressed bytes, while
  `firmware_binary` independently reconstructs and inspects the UF2 payload;
- `adaptive_hybrid_replay`, `adaptive_hybrid_analyze`, and
  `adaptive_hybrid_monitor` provide deterministic replay, analysis, and
  retained-state monitoring;
- `adaptive_hybrid_evidence`, `evidence`, `evidence_finalization`, and
  `evidence_index` preserve provenance, sealing, and registration; and
- `time_domains`, `contracts`, `run_loader`, and `run_paths` provide shared
  current-only kernels.

## Timing and channel authority

D14/channel 1 reference records and D8 count observations are the only inputs
to regulation validity and authority. D10/channel 0 `EVT` records are optional
external-event evidence. D10 absence, noise, invalidity, or overflow changes
only D10-local evidence and can never change eligibility, requested/applied DAC
codes, or a run terminal. D6 is likewise diagnostic-only. GNSS serial metadata
can place regulation into a bounded static hold but cannot replace D14 timing
authority.

Host validation rejects a role/record mismatch: `EVT` belongs to D10/channel 0
and `REF` belongs to D14/channel 1.

## Operational path

```text
fixed firmware + policy + tools
              |
            bundle
              |
           proposal
              |
          rehearsal
              |
          activation
              |
         run manifest
              |
   capture + supervisor + monitor
              |
      analysis + sealed evidence
```

The bundle embeds and content-addresses every decision-bearing component,
including the exact profile/schema bytes used by later supervision, replay,
and analysis. Those consumers do not substitute files from the live checkout.
The retained `adaptive_hybrid_structural_preflight` tool is a deterministic
structural preflight: it exercises current controller, exact-timing, evidence,
and D10-isolation semantics without device or process I/O, and cannot authorize
activation.

Current activation is intentionally fail-closed because current HEAD does not
yet contain a genuine process-level rehearsal producer for the separate
capture, supervisor, monitor, FIFO, obstruction, abort, analysis, sealing, and
registration path. Restoring live readiness requires that exact current-only
path; a producer acknowledgement must then be followed through the first
dependent consumer rather than being treated as proof of downstream
application by itself.

## Canonical package

A current package contains a canonical run manifest, append-only raw serial
capture, manifest-declared CSV products, retained reports, and an immutable
evidence manifest. Derived products never overwrite raw observations. Offline
analysis may supersede a failed deterministic consumer only when it binds the
unchanged raw evidence and both tool identities.

## Authority

Repository code and offline verification do not authorize hardware work. Live
operation requires an exact frozen bundle and explicit operator authority.
Normal and abort transport remain separate, serial ownership remains singular,
and an identity, health, timeout, or evidence discontinuity holds or fails
static according to the fixed current contract.
