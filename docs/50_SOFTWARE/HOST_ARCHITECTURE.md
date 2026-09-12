# Host Architecture

OTIS host services preserve and analyze timing evidence; hardware capture is
timing truth. Host scheduling, logging, networking, and storage must never
define or modify a timestamp.

## Explainable responsibilities

The host has five jobs. Capture owns the serial connection and preserves raw
instrument output. Supervision discovers state and manages the explicitly
authorized experiment. Monitoring reports current progress and problems.
Analysis validates and interprets retained evidence. Packaging binds what ran
to what its evidence supports. Configuration binds those jobs once per process;
a small session owner launches them and manages authorized closure.

Monitoring does not replay entire growing CSV histories at every observation.
It reads bounded complete tails and labels their scope, leaving total row
counts unknown. Full validation belongs to the supervisor's decision-bearing
checks and the offline analyzer. A monitor finding requests review through the
runner and existing supervisor hold; it cannot abort, close capture or declare
a scientific failure. Stale monitor receipts are also review findings.

`reports/capture_device_state.json` publishes `emergency_abort_raw_frontier`
when capture sends an emergency abort. The object binds `run_directory`,
`search_offset_bytes`, `device` and `inode` to capture's open raw file. It is
host-local observation provenance, not a firmware timing coordinate. A forward-only bounded observer finds the retained
send marker and a subsequent complete firmware snapshot. A producer receipt
alone does not prove the deferred raw marker or firmware consumption. Neither
the verifier nor ordinary monitoring rescans multi-day history to stop a run.

Complete and partial evidence snapshots use one inventory. Partial snapshots
remain explicitly partial and retain diagnostic/carrier/provenance evidence;
missing or malformed required evidence cannot produce a successful seal.
Rehearsal and physical finalization persist registration intent before using
the same idempotent registration operation.
Entry validates the index location before authority reservation or capture.
After sealing, interrupted rehearsal registration and authorization-report
publication can be completed offline at the recorded tool revision. Recovery
retains destination corrections and tool identity in the external journal;
the sealed package stays unchanged.

## Current boundary

The current ownership ledger and standalone design boundary are recorded in
[Instrument ownership](INSTRUMENT_OWNERSHIP.md). Firmware operating policy and
serial evidence detail are separate concerns. The current campaign protocol
still requires host leases and progressive evidence acknowledgements;
autonomous startup and compact serial output are not implemented.

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
- `authoritative_inputs` freezes the exact five-profile transitive closure,
  all seven current schemas, and the reference-acceptance policy as
  content-addressed bytes, while
  `firmware_binary` independently reconstructs and inspects the UF2 payload;
- `adaptive_hybrid_replay`, `adaptive_hybrid_analyze`, and
  `adaptive_hybrid_monitor` provide deterministic replay, analysis, and
  retained-state monitoring;
- `accepted_span_replay` reconstructs accepted PPS spans from unchanged raw
  REF/SNP/CNT evidence; `acquisition_frontier` binds authority to an immutable
  retained opening and an exact same-epoch 600-span estimate;
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
`ValidatedAuthoritativeInputs` owns a detached, immutable snapshot after byte,
closure, binding and instance validation at the raw-input boundary. Consumers
read fresh document copies and exact bindings from that snapshot. The supervisor
prepares one `AdaptiveHybridRuntimeContext` for its lifetime; spec derivation and
construction consume it instead of recursively validating the same dictionaries.
Supplying a context for different embedded bytes is an error. A bounded cache of
successful schema-syntax checks avoids repeating schema self-validation across
independent input boundaries; it caches neither mutable documents nor authority.
Fresh census, retained source proofs and exact command acknowledgements remain
independent dynamic checks and cannot be satisfied by static configuration.

An accepted boundary ordinal is a wrapping 32-bit coordinate within a
nonzero acceptance epoch. It is distinct from a raw capture sequence, phase
epoch, and DAC epoch. A rejected early edge does not advance it or create a
new accepted opening. Qualification cannot add progress across epochs.

Before ARM, the host binds the selected EST to its 600 APS records and their
raw sources at retained canonical CSV positions. A recent observer state alone
does not prove source identity or completeness. Partial late-attachment evidence
stays unqualified; a fully retained opening can anchor later complete spans
without pretending the recorder observed the original acquisition sequence.

The retained `adaptive_hybrid_structural_preflight` tool is a deterministic
structural preflight: it exercises current controller, exact-timing, evidence,
and D10-isolation semantics without device or process I/O, and cannot authorize
activation.

The current process-level rehearsal exercises the separate capture, supervisor,
monitor, FIFO, obstruction, abort, handoff, analysis, sealing, and registration
path. Activation validates and binds one exact successful sealed rehearsal;
neither the structural preflight nor an unverified rehearsal claim can
authorize live entry. Producer acknowledgement is followed through the first
dependent consumer rather than being treated as proof of downstream
application by itself.

`AdaptiveHybridSession` owns the concrete capture/supervisor/monitor lifecycle
in both physical execution and the PTY rehearsal. Hardware preparation and
simulated stimulus remain explicit adapters. Both paths launch the same monitor
loop and require receipts bound to the launched PID, run, manifest bytes and
monotonic launch boundary. Supervisor initialization includes its independent
abort ingress; monitor initialization includes its first retained observation.
These receipts prove service readiness only. The supervisor still discovers
firmware state before admitting lease or control authority.

Startup phase records explain progress and failure location. A topology error
retains its primary diagnostic and attempts diagnostic registration after safe
closure; it cannot invent successful acquisition or a seal. Shared cleanup
refuses to stop a live capture owner. Bounded simulated cleanup independently
requires a PTY and a nonphysical session. Physical host discrepancies preserve
capture and enter the existing review-hold path; after the owner actually exits,
diagnostic finalization remains reachable. Abort delivery must still precede
any capture closure authorized by an aborting terminal.

A causal acknowledgement phase owns one process-bound host-monotonic deadline
from preparation through write acknowledgement and confirming snapshot.
Nested observations, retries and periodic service consume that same bound;
newer generations do not refresh it. Bounded waits service explicit operator
abort. Lease renewal is allowed only for established ownership and never while
a normal command's exact capture-write acknowledgement is unresolved.

A retained pending acknowledgement from a different supervisor process remains
observational and requires review. Its old monotonic deadline cannot be reused
or silently refreshed. The current host does not adopt that transaction on
restart. This removes an unsafe recovery assumption rather than adding another
recovery protocol.

The private rehearsal has one coordinator-owned progress deadline for a finite
set of exact transitions. Managed capture and supervisor processes have no independent lifetime
expiry in either physical execution or rehearsal. The supervisor owns the
scientific endpoint; the session watchdog can request review without closing
healthy capture. Heartbeats and repeated snapshots are not progress. Abort submission
and delivery share one remaining budget. The frozen manifest, session record,
process evidence and seal bind this timing declaration and completed frontier.
These are host verification semantics; they do not redefine firmware safety
expiry or scientific duration. See the [causal-wait repair record](../60_EXPERIMENTS/CAUSAL_WAIT_REPAIR_2026_09_11.md).

The sole authority-bearing physical purpose is
`contingent_72_hour_hybrid_control`. Its 72-hour accepted-aperture endpoint and
78-hour wall limit are one finite run, not a sequence of setup, one-application,
or short-duration campaigns. Retained host discrepancies create a review hold:
they inhibit new authority while capture and the sole serial owner continue,
and have no automatic abort, teardown, or scientific-terminal authority.

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
