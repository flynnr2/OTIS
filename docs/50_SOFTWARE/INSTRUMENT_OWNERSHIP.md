# Instrument ownership and standalone direction

## Scope and decision

This review follows accepted-PPS integration PR #176, merged as
`c175f5a0610a9ca92d625bc87065bdf555c5542d`. It distinguishes current owners,
demonstrated cleanup, and the operator's intended standalone instrument.
It does not enable a new operating mode or authorize a hardware action.

The bench instance's read-only handover was reviewed again for this work
(supplied text SHA-256
`d6841c2e28ddf7cb38c196b18025d321b77d2a99754ca8f216ffc4194eb5022f`).
Its recurring failure pattern is the review criterion: an acknowledgement
without its first consumer, one transaction without the next, a synthetic
snapshot without the production serializer, a simulated launch without the
real OS permission context, or an integrity seal without scientific completion
does not establish the complete boundary. Previously repaired failures remain
covered by the current regressions; historical sources and journals are not
migrated or rewritten by this review.

The intended instrument starts, qualifies its reference, disciplines its
oscillator, and provides D9 output without requiring a host control loop.
A host may later request compact measurement evidence, full replay, or an
explicit characterization operation. That is consistent with the existing
instrument boundary; it does not require a hardware port or general framework.

Operating policy and output detail are separate. One firmware controller owns
the oscillator in every supported policy. A host observes current state and
requests declared transitions; opening serial is not a reset, a known DAC
initial condition, a controller takeover, or a fresh campaign.

## Current owners

| Responsibility | Authoritative owner | Other participants and limits |
| --- | --- | --- |
| D8 count at the D14 boundary | PIO cumulative-counter snapshot | DMA transports the word; foreground reconstructs differences without defining the boundary. |
| Local D14 reference observation | GPIO IRQ and its bounded record | The timestamp is read by the ISR in the RP2040 timer domain; it is not a PIO hardware timestamp. |
| Association and accepted-reference selection | Core 1 timing service | One selection outcome feeds both phase and frequency. Raw observations remain unchanged. |
| Receiver and physical DAC service state | Core 0 GNSS and DAC drivers | Bounded immutable messages publish receiver qualification and applied-state facts to Core 1, independently of USB presence. |
| Controller policy and transaction proposal | Core 1 selected adaptive controller | Host admission and durable-evidence checks constrain the current supervised campaign; they do not calculate the physical measurement. |
| Physical DAC write | Core 0 DAC executor | Its exact cross-core request/expiry guard protects execution; Core 1 owns the proposal and consumes the correlated result. |
| USB framing and outbound queues | Core 0, sole queue consumer | Before attachment, bounded discard preserves internal service. Current transport faults retain the campaign's fail-static semantics. |
| Host serial descriptor and recorded frontier | Capture process | Supervisor, monitor, and runner use retained evidence and command channels; they do not open competing serial descriptors. |
| Campaign admission and acknowledgement | Host supervisor | Requires exact retained sources and frozen campaign authority. Host discrepancy is a review hold, not independent abort authority. |
| Process lifecycle | Shared `AdaptiveHybridSession` | Physical and PTY adapters launch the same capture/support lifecycle and monitor loop; initialized-worker receipts precede service readiness. Delivered abort still precedes authorized capture closure. |
| Acquisition evidence, analysis, seal, registration | Separate recorder and offline stages | An analyzer result cannot rewrite physical acquisition; sealing and registration retain distinct outcomes. |

Core 0 and Core 1 actuator guards are not duplicate control owners. One binds
the proposal and its downstream result; the other guards the exact hardware
execution. Likewise, independent host replay is useful verification and must
not be removed merely because firmware already calculated an estimate.

The current host module graph is acyclic but remains campaign-oriented. Having
one serial owner does not establish that generic attachment, campaign entry,
and authority transfer have been cleanly separated.

## Demonstrated cleanup in this tranche

Core 0 serviced GNSS while detached but returned before its regular receiver
and DAC metadata publication. A pending serial frame also bypassed that
publication. The publisher now runs before those transport branches, retaining
its existing cadence, queue-space checks, and no-actuation behavior. Its
regression executes the actual sketch loop against bounded service doubles
and the real transport-liveness state machine. Physical UART and I2C timing
remain bench claims.

The live controller dispatcher also retained an older decision path after an
unconditional call and return into the selected adaptive implementation. Its
unreachable controller state and code are removed while preserving the
decision representation used by current telemetry. This removes a false
second implementation to maintain; it does not move control to another owner.

Host startup previously renewed the capture lease before consuming its first
solicited current ACTIVE snapshot. Fresh flashing hid that ordering assumption
in the current campaign runner. Startup discovery now precedes lease and
control admission: a durable census distinguishes a fresh disarmed instrument,
an unsupported retained continuation, an unowned active or in-flight state, and a
faulted or incoherent state. A host may observe any of these. Observation alone
cannot authorize lease renewal, SETUP, ARM, or acknowledgement of another
transaction. Unsupported continuation retains capture in a review hold;
explicit operator abort remains a separate authority.

Retained continuation requires an explicitly successful setup-authority
validation. A validator returning early because the leading manual-start row
is absent or has not been observed is not success. The focused regression uses
the actual hashed setup-authority file and validator, then removes the manual
row, removes its observed identity, or alters the authority. Its ACT schema
and transaction-history validators are doubled; this is a discriminating
authority-boundary regression, not a complete restarted-process rehearsal.

The runner's retained orchestration hold previously had no supervisor
consumer. Reporting `new_controller_authority=false` therefore did not itself
inhibit a still-running supervisor. The hold must cross that boundary before
new SETUP/ARM admission, using a run-bound retained record and the same
supervisor hold semantics as a local verification discrepancy. Established
ownership may continue its lease and an independently verified already-issued
transaction phase; an unadmitted observer cannot. Failure to publish or consume
the hold must be surfaced as failed propagation, never described as a
successfully inhibited controller.

The runner separately records marker publication and a supervisor receipt
bound to the exact marker hash and run. The request itself is not proof that
inhibition took effect. Malformed or contradictory retained markers still
cause diagnostic hold; they cannot authorize continued control or teardown.

Repeated terminal checks in the supervisor, runner, analyzer and registrar
remain intentional. They respectively decide live campaign progression,
admit capture closure, reconstruct the scientific outcome, and independently
validate the sealed claim. Collapsing them would merge different authorities.

## What standalone operation still requires

The existing firmware can acquire and drain capture without a host, and D9
already forwards D8 through hardware at integer divisor one. It cannot yet
perform the proposed autonomous steering: current SETUP/ARM admission needs
a capture lease, solicited status identity, and exact evidence acknowledgements.
The pre-carrier discard path also consumes critical outbound requests rather
than executing them. Simply ignoring host acknowledgements would remove an
existing commit boundary without replacing it.

A finite standalone implementation therefore needs these coupled decisions:

1. Define boot configuration and initial DAC provenance. The current driver
   deliberately leaves the applied code unknown until an explicit successful
   write. Reference acquisition precedes qualified steering; D9 is initially
   only a forwarded oscillator output, not proof of discipline.
2. Define firmware-owned qualification, request, application, requalification,
   hold and integrity-fault transitions, including finite actuator limits.
   Replace supervised durability releases with an explicit autonomous commit
   rule. Retained state and incomplete evidence must be reported truthfully.
3. Separate internal actuator dispatch from optional serial delivery. No host
   or slow reader must not stall capture or autonomous control. Bounded output
   discard and exact loss/coverage records are required; autonomous continuity
   does not imply complete replay evidence.
4. Make ordinary host attachment observational first. Discover firmware/build,
   session, controller state, applied-code provenance, pending transaction,
   output policy, and evidence frontier. Observation does not grant authority
   over an in-flight action or repair missing historical evidence.
5. Exercise hostless acquisition and repeated corrections, then attach and
   detach a reader without changing the DAC, session, or control state merely
   because the connection changed. Test stalled output and ambiguous discovery
   deterministically before a sustained physical qualification.

The present physical campaign runner intentionally performs an authorized
firmware upload and establishes a new campaign start. Its fresh-image
preconditions belong to that explicit operation. They must not become the
default behavior of a generic instrument connection. Supported arbitrary-state
discovery and arbitrary-state campaign continuation are different capabilities;
the latter additionally needs the original authority and sufficient evidence.

The real macOS launch and removable-volume permission boundary remains a bench
gate. The runner binds the board, permits one firmware upload, rejects reused
attempt directories, and owns its process lifecycle; a fixture cannot prove
that the older Mac's actual launch context can access a mounted bootloader
volume. Rehearse the same one-shot launch context used for the physical run,
without keep-alive restarts. Do not add general recovery machinery to conceal
an untested platform permission boundary.

## Output contracts and D10

A compact stream should retain explicit sessions and domains, D14 reference
observations, cumulative D8 counts or bounded interval counts, relevant
qualification/configuration changes, and bounded external-event evidence.
Publishing every 10 MHz D8 edge over serial is not a useful encoding. Full
replay adds the selected-estimator, controller, transaction and diagnostic
sources required to independently reconstruct decisions. Each profile must
state its coverage, maximum event/byte rate, and loss behavior; compact output
must not claim the completeness of full replay.

D10 is a clean future implementation boundary. Its existing scaffolding,
fixtures, and prospective EVT representation may be replaced completely,
without compatibility aliases. Only the intended external-event input role
and isolation from D14/D8 are architectural requirements. The current fixed
firmware has no qualified D10 capture backend. New hardware capture must
preserve event polarity, an explicit D8-related measurement coordinate, and
overflow/ambiguity evidence without allowing D10 load to veto PPS or steering.
Historical recordings remain unchanged and use their recorded tools.

Future characterization selects an explicit stimulus/measurement policy under
the same owners. Future D9 integer division belongs to the output owner, with
declared source, ratio, edge/duty-cycle behavior, configuration transitions,
resource binding and electrical qualification. It must not redefine D8 count
authority or introduce fractional-divider jitter by accident.

## Service-latency diagnostics

The sibling `Arduino.Pendulum.Timer` implementation is a useful example, not an
OTIS timing implementation to copy. In
`Nano.Every/src/PendulumCapture.cpp`, `latency16 = cnt - ccmp` subtracts a
hardware capture latch from a later read of the same 16-bit timer, with the
timer's rollover and sampling separation explicitly considered. Its
`Docs/PPS_Swing_Latency_Investigation.md` traced a long service-delay tail to a
large copy under global interrupt masking. Those measurements describe that
board and workload, not RP2040 latency or capture completeness.

The reviewed sibling working tree was not clean. The read source identities,
rather than its HEAD alone, bind the example: `PendulumCapture.cpp` SHA-256
`28574517d5a668795f2861529ea98c1af8d9fdc197e8828a4ae497b20cf9155a`,
and investigation document SHA-256
`44e94a5d37aa1d4f8439e9fb58b858484260c2633fed616f51261cb24dbe1ffb`.
No sibling source or hardware was changed.

Current OTIS endpoints differ:

- The D14 IRQ reads the RP2040 microsecond timer after interrupt dispatch.
- The PIO boundary snapshots the D8 cumulative count, not that timer.
- DMA transfers count words and foreground polls their availability; there is
  no existing paired hardware latch timestamp and service timestamp.

The available same-clock diagnostic is therefore **D14 ISR timestamp to
foreground boundary service**, using the existing bounded low-word projection.
It excludes physical-edge-to-IRQ dispatch latency. It includes residence and
association delay after the ISR timestamp. It must not be named PIO-latch-to-ISR
latency or oscillator-domain event timing.

An eventual diagnostic can report bounded sample counts, extrema, a small
histogram and threshold events keyed to source identities. Sampling/wrap
ambiguity and dropped diagnostics remain explicit and diagnostic-local.
Formatting, serial writes, allocation and histogram traversal do not belong
in the capture hot path. True hardware-latch-to-service latency needs an
additional observable marker in a declared common domain, a hardware resource
and overhead budget, and a calibrated pipeline interpretation. It is not
implemented by this ownership cleanup.

## Verification boundaries

All **634 current tests passed** on the frozen implementation. The release
run covered 633 tests in 83.50 seconds; the separately run full-process
operational rehearsal passed in 106.11 seconds. Separating that test avoided
running the same process experiment twice. Independent review also checked
startup admission and the runner-to-supervisor hold boundary before freezing.

The process rehearsal establishes fresh discovery, lease and setup, two
corrections with exact acknowledgements and dependent decisions, recoverable
metadata hold, command obstruction, independent abort delivery, capture
closure, analysis, sealing and registration. It uses real host processes and
PTY transport with synthetic firmware and plant evidence. The runner review
marker is separately exercised through its real producer and supervisor
consumer using controlled scheduling; it is not an additional physical or
subprocess-failure qualification.

The registered fixture package is retained outside Git at
`runs/rehearsals/ownership-simplification-2026-09-11/package`: 51 files,
9,375,154 bytes, content SHA-256
`b09928820805321817f9817cbedc47dced4a79969aa4aee775aa11ebf5ac4b90`.
The external rehearsal report's declared SHA-256 is
`3a352e3498e0e1d08777b69f3f176ec338364d2da252c870ece6ede27926136e`.
Observed startup ordering was the three read-only identity queries, ACTIVE
snapshot nonce `3291500901`, completed generation 1/session 1 with lease false,
fresh-start census admission, then `ACTIVE LEASE 1`.

The test deliberately mutates `physical_actions_performed` after successful
registration to verify tamper rejection. The retained copy restores only that
field to its original zero and reproduces the complete registered package
hash; the original post-test directory is unchanged. An external provenance
note records that operation. Synthetic bundle inputs are retained alongside
the package. The test's `_frozen_inputs` substitutes firmware-build validation;
production validation correctly rejects those synthetic inputs outside that
fixture context. This package is evidence of the process test, not a reusable
real-firmware campaign bundle or bench authorization.

The review caught a retained setup-validation early return and an inaccurate
pre-lease fixture state before bench entry. These are platform defects caught
in review/rehearsal preparation, not scientific rejections or new campaign
failures. The passing gates close the finite ownership tranche; they do not
prove every possible host restart or remove the remaining campaign-oriented
structure from the host.

The fixed firmware was built from clean commit
`cef4fe36a9981a2ba9278787b7c89e6ad46c9a5f`. Its 131 declared build inputs
remain byte-identical after the host work; the later host and documentation
commit does not claim to be the embedded build revision.

| Firmware evidence | Result |
| --- | --- |
| Source SHA-256 | `9b52d002d57a2bf21d76c9c7e63f6260c0d86554a23f40d582cf9358eed5ad36` |
| Build manifest SHA-256 | `b94f476bdb9cc8498376244ac8ed919a7857c2b4c349615e1bf82812e4fe189a` |
| UF2 SHA-256 | `58d690f2bcad782b4e3b26162107c9e68dadde1a5666d368f7c82bb762114073` |
| UF2 size | 481,280 bytes |
| Program storage | 223,020 bytes |
| Static RAM / remaining runtime RAM | 154,140 / 108,004 bytes; existing resource limits pass |
| PIO instruction proof | 7,936 cases and 55,552 intervals; tested digital boundary error remains within ±1 oscillator edge |

The build manifest is retained locally at
`build/ownership-simplification/firmware/artifacts/firmware_build_manifest.json`.
The instruction proof uses the installed 133 MHz system-clock profile and
its declared continuously drained FIFO model. It does not establish analog
edge quality or an unconditional physical error bound.

Physical qualification still requires the exact frozen firmware/host bundle,
the real bench launch context, and its operational-path rehearsal. This tranche
does not flash, reset, open a device, change a DAC code, or revise the sealed
physical attempt.

## Superstructure simplification brought forward

The first bench-entry rehearsal at merged PR #177 failed before supervisor
readiness. Reviewing that escape also found that the earlier ownership table
overstated the physical runner: it launched capture and supervision, while only
the rehearsal launched a separate monitor loop. The table above describes the
successor shared implementation, not a capability established by PR #177.

At the operator's direction, broader host simplification now precedes bench
qualification. The finite scope is an immutable validated runtime configuration,
one concrete process lifecycle and monitor loop, explicit initialized-worker
readiness, and reachable diagnostic closure. Independent raw-source replay,
fresh census and exact transaction guards remain. This is not an autonomous
instrument implementation or a generalized campaign framework.

The [superstructure work record](../60_EXPERIMENTS/STARTUP_VALIDATION_REPAIR_2026_09_11.md)
records the escaped failure, implementation and verification boundary.

## Instrument services versus disposable campaign machinery

The intended normal experience is power on, acquire and discipline, then use
D9; optionally attach a host to record or inspect. This is the product direction,
not a claim that standalone startup is implemented today. Users must not need
campaign manifests, qualification runners, sealing or engineering process
knowledge to operate the finished instrument.

The operator's intended live instrument must not inherit the qualification
runner as a mandatory runtime. Durable instrument responsibilities are hardware
capture, accepted-reference measurement, bounded firmware actuation, explicit
state and protocol, and sufficient raw provenance. Host recording and offline
reconstruction remain useful independent consumers; attaching them does not
make them the timing owner.

`AdaptiveHybridSession`, private PTY stimulus, frozen campaign activation,
qualification deadlines and campaign-specific finalization are removable host
campaign machinery. Sharing their current process implementation prevents
rehearsal drift; it does not promote them into the instrument architecture.
They add no firmware dependency. The runtime context belongs to today's
supervised campaign, not to a compulsory future standalone service.

Retain a regression where it protects a demonstrated invariant. Retire obsolete
campaign adapters and fixtures when their decision is complete; preserve their
source revision and evidence rather than current compatibility branches. Future
standalone operation should consume the explicit instrument state/protocol,
not reproduce this campaign's activation, manifest or process topology.

## Causal waiting and restart ownership

The September 11 causal-wait repair supersedes the earlier narrowly retained
ACK restart path above. Exact retained records are necessary but cannot make
an old process's monotonic deadline valid in a new process. Such attachment
now retains a review hold without resuming the pending acknowledgement.
Within one admitted process, the phase owns its complete observation budget,
including nested queries, retries and confirmation; explicit abort remains
serviced throughout. An unresolved capture-write acknowledgement prevents a
lease or second normal command from contaminating its exact command counter.

The private rehearsal coordinator owns managed child lifetime and a finite
causal-progress deadline. It no longer races healthy capture against unrelated
90/120-second stopwatches. This correction is host verification work, not a
claim that the physical firmware or plant is qualified. Evidence and final
validation are recorded in the [repair report](../60_EXPERIMENTS/CAUSAL_WAIT_REPAIR_2026_09_11.md).
