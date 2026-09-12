# OTIS host architecture

The host has five responsibilities: capture, supervise, monitor, analyse, and
package. The instrument remains responsible for hardware timing, timestamp
semantics, reference acceptance, and bounded actuator behaviour.

## Live ownership

`live_run.run_experiment` is the foreground experiment owner. It launches one
`capture_device` worker and runs the supervisor in the foreground. Capture exclusively reserves the run directory before opening evidence files.
It owns serial, drains it continuously, retains the raw stream, and publishes
observations. Raw bytes are written immediately, including unterminated input;
queued host markers spill to disk instead of growing without bound. On an
interrupted partial record, an explicit host marker identifies the synthetic
line delimiter used to separate the retained tail from subsequent markers.
The supervisor consumes those observations and owns discovery, authority,
transactions, qualification, holds, and terminal decisions. It never opens serial.

`adaptive_hybrid_monitor.snapshot` is a read-only view. It creates no worker,
readiness receipt, command, hold-adoption handshake, or terminal. Monitor failure
cannot change the experiment. Published state identifies missing observations as
unknown, not healthy.

Capture has two bounded command inputs: normal commands and direct priority
abort. The latter remains available when normal commands are obstructed. Both inputs
are serviced by the capture worker: this does not promise delivery through a
blocked operating-system serial or storage call. Firmware fail-static behaviour
is the independent bound in that case. Abort
submission, capture transmission, and the subsequent firmware snapshot are
separate facts. The owner confirms delivery before capture closure. A local host
failure enters a review hold; it does not manufacture abort permission.

One acquisition retains one serial owner through its terminal. Offline work
starts after closure, so no transition spool, serial-owner transfer, or second
command path is required.

## One configuration

`run_spec.json` is inert and immutable. It binds the instrument image, host tool
contents, one campaign envelope, authoritative inputs, record contracts, policy,
and command limits. `run_manifest.json` is a small dynamic record: run identity,
start, device, execution kind, retained relative spec binding, and explicit entry
authorization where applicable. `run_loader` derives the shared scientific view
in memory. It does not persist another configuration copy.

There are no bundle, proposal, activation, or expanding global-index validators
in the acquisition path. Historical formats are read at their recorded revision.
A copied package can be validated and analysed without reconstructing the
original machine's directory layout.

Physical entry is an explicit engineering operation in `bench_entry`. It checks
the frozen spec, actual firmware/tool bytes, exact rehearsal receipt, operator
instruction, board identity, and absence of an existing serial owner. Upload is
optional and explicit; when requested it occurs once and retains full output.
Before physical I/O, entry retains the exact validated specification and
rehearsal receipt. A single diagnostic record records each entry phase and its
failure without retrying. Upload uses a hashed, run-local read-only copy of the
selected UF2, insulating it from changes to a build or cloud delivery path.
The runtime itself never flashes, resets, restores a DAC value, or guesses the
firmware's initial state.

Startup discovery accepts a complete coherent identity snapshot before reference
qualification. Independent ACTIVE and PPS publications need not be simultaneous. PPS fields
are staged between the existing firmware begin/end markers and replaced as one
cohort; omitted fields never inherit values from an older snapshot. The existing
producer-clock coherence bound prevents fresh ACTIVE traffic from refreshing
historical PPS evidence, including across the declared counter rollover.
SETUP, ARM, and scientific progress require the appropriate fresh causal evidence;
late or missing telemetry cannot grant authority. Qualification advances in the
declared exact accepted-aperture domain. Host service deadlines use monotonic
nanoseconds and cannot redefine instrument duration.

## Offline responsibilities

`adaptive_hybrid_analyze` independently reconstructs D14/D8 measurements,
accepted spans, phase-source associations, transactions, responses, and controller
history. Phase replay follows the producer's two-stage qualification: an exact
qualified RPH may feed an initializing PHE until the 600-point frequency support
exists, while an invalid RPH requires an invalid PHE. Raw D14/D8 replay is
independent of whether a controller or estimator produced a record. Selected
600-span estimates and overlapping 60-span diagnostic estimates have separate
replay scopes. Diagnostics are reported locally and never populate the selected
source map used by controller and transaction consumers. EST stream identity
and CSV integrity remain explicit checks; a diagnostic numeric mismatch is not
a failure of the selected estimator or canonical D14/D8 observations. Source
windows are looked up by capture session, acceptance epoch and ordinal, so dense
diagnostic output does not require a full APS scan for every estimate.
An inhibited attachment can have valid measurements and no
control decisions; emitted estimates and decisions still require exact source
bindings. D10 remains optional external-event evidence and cannot veto D14/D8
validity or control. Evidence integrity and scientific outcome are separate.

`offline.finish_run` runs analysis once, retains a diagnostic report if it fails,
and asks `evidence_package` to seal the closed acquisition. Packaging inventories
relative regular-file paths and hashes. `evidence_registry` optionally records
locations; registration failure cannot alter the package or scientific result.
CLI exit status distinguishes failed operations from scientific outcomes. A
review-required analysis or runtime failure returns nonzero with retained JSON;
verification of a valid diagnostic package and a completed scientific non-pass
can succeed.
A subsequent analysis of sealed evidence writes a separate report linked to its
source package. It never changes the old result or raw observations. Current
analysis v2 reports retain both the analyzer-file hash and the complete host
operational-toolset hash. Initial analysis requires the frozen toolset; a later
external corrected analysis records its actual new toolset and the immutable
source-package content hash.

## Engineering verification

`tools/rehearse_host.py` supplies a deterministic PTY instrument to the actual
live owner and capture worker. It exercises startup publication order, progressive
commands and acknowledgements, holds, obstruction, direct abort, closure, and
the offline path. Boundary results must come from retained observations; a
synthetic device makes no firmware cross-core or physical propagation claim.

Firmware building and independent reproduction are explicit engineering tasks.
Firmware identity follows actual firmware inputs and the pinned toolchain;
repository/host revision is separate provenance. Ordinary acquisition, monitoring,
analysis, and package validation never invoke a compiler.

See [HOST_REPLACEMENT](../10_REFERENCE_ARCHITECTURE/HOST_REPLACEMENT.md) for the
cutover scope. The replacement introduces no standalone firmware steering mode,
hardware port, D10 witness role, or change to the characterized DAC envelope.

## Configuration responses during status publication

Core 1 alone publishes the PPS and ACTIVE snapshot fields. Core 0 may insert
configuration, environment or other status records between complete queued
records, but cannot republish fields in those two namespaces. CONFIG requests
timing configuration from core 1. This removes ambiguous membership at the
producer instead of adding host nesting rules or accepting duplicate values.
The strict reducer remains unchanged.

The operational PTY rehearsal deliberately inserts a representative core-0
configuration response inside both PPS and ACTIVE cohorts. A retained physical
excerpt and a source-ownership regression cover the previously escaped duplicate
PPS emission and the first downstream zero-write decision. The fixture tests
record ordering and host consumption; it does not claim to execute the physical
cross-core scheduler or validate electrical timing.
