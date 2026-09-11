# Shared host superstructure and cold-start failure

## Observed failure and evidence

The older bench Mac built clean merged revision
`e891476005504f198073053b64b99aaafcfa5190` successfully. Its production frozen
bundle and deterministic firmware reproduction passed. Its subsequent PTY
rehearsal timed out waiting for supervisor/monitor/abort-ingress readiness at
the unchanged ten-second boundary. No supervisor state or commands appeared.
This is a platform defect caught in rehearsal, not a scientific rejection or
a physical instrument failure. The rig was not accessed.

The received diagnostic package has 26 files, 1,034,814 bytes and content hash
`dc6def2af52439a449ba1f5969a603e2c7bc8f8db8636b676c1c94df4eb7526a`.
Its index and finalization journal were separately checksum-verified. The
supplementary archive has 199,922 bytes and SHA-256
`4fe305019abea680c691841066d55734e2a3ca3f81e441a84a5e8e9da7c49d25`;
all 11 manifest-listed payloads and the manifest were verified locally.
These originals remain unchanged in local `Documents/OTIS_DATA/rehearsals`.

The bench transcript reports import 0.277 s, private-manifest validation
5.858 s, and another spec validation 2.905 s: 9.041 s total. That measurement
excluded the rest of supervisor construction. Its invocation and output were
reconstructed from the coordinator transcript; Python 3.14.5 was inspected
later, not recorded at execution. No child phase trace establishes the exact
last instruction of the failed attempt. Startup exhaustion is strongly
supported, but the evidence does not establish it as the exclusive cause.

## Discriminating check and repair

On the development Mac, a fresh process loaded copies of the actual retained
manifest/bundle/build and ran private-manifest validation plus the complete
supervisor factory, stopping before `run()` or any serial operation. Profiling
found 29 full authoritative-input validations and 348 JSON-schema syntax
checks. Schema syntax checks consumed 5.735 of the 5.820 profiled seconds.

The first discriminating repair reused successful schema syntax checks by
complete canonical schema content, with a bounded 32-entry process-local cache. It neither caches
an authority decision nor trusts a supplied hash. At that intermediate step,
each consuming call still checked embedded bytes, set identity, profile
closure, bindings and profile instances. Invalid syntax is not cached; callers receive freshly
parsed documents, so mutation cannot poison a cached result.

A fresh local process after that narrow repair took 0.199 profiled seconds for the
same validation/construction path: 29 authority validations remained, while
syntax validation required seven checks and 341 cache hits. This diagnostic
used explicitly rebound copies for changed host-tool bytes and retained the
real build input. It is not a frozen live-bundle rehearsal and does not predict
the older Mac's runtime. That narrow experiment retained the old readiness
predicate and ten-second deadline. The broader implementation below replaces the readiness predicate
with actual initialized-worker receipts.

The rehearsal worker now records startup phases and the parent includes the
last observed phase and child status in a startup failure. The record is
diagnostic; it cannot replace actual readiness. Topology exceptions retain
their original failure and attempt diagnostic registration without inventing
acquisition completion or a successful seal. Secondary recording failures
remain separate from the primary error.

## Broader simplification before bench entry

The operator explicitly rejected postponing simplification until qualification
passes. This tranche therefore replaces duplicated ownership before the next
bench attempt:

- An immutable validated input snapshot separates raw configuration admission
  from repeated document access. One supervisor runtime context supplies policy,
  identities and spec without rebuilding the same static envelope.
- One concrete session owner launches capture, supervisor and monitor for both
  physical and PTY execution. The old physical path did not actually launch its
  monitor, despite the earlier ownership description.
- Both adapters use the same monitor loop and initialized-worker receipts,
  bound to run, manifest bytes, PID and monotonic launch boundary. A supervisor
  receipt is not a successful device census or control authorization.
- Shared cleanup cannot tear down a live physical capture on a host diagnostic.
  PTY cleanup is separately bounded and gated. Diagnostic closure retains the
  original failure and remains reachable after a held physical owner exits.

These are removable current-campaign host components, not permanent instrument
services or a new general framework. No firmware dependency is added.
Fresh device census, exact pending-phase acknowledgement, retained raw-source
replay and command guards remain decision-bearing. D14/D8 timing semantics,
firmware control ownership and prospective standalone features are unchanged.

## Integration verification

The current 656-test set is covered by 654 passing release checks, the newly
added partial-launch/closure regression in a 19-test affected-boundary rerun,
and the full process test. The full process test passed in 91.76 seconds after
one directly observed simulator startup repair. The first attempt hit a PTY
write `EIO` before capture opened the slave; cleanup then closed capture and
the supervisor reported that secondary transport closure. The old topology
also emitted before ownership readiness. The adapter now waits for the shared
capture-ready boundary before starting the synthetic stream, and the process
test asserts this exact ordering.

The process test uses synthetic build metadata. A separate normal production
bundle and PTY gate using the real fixed build also passed; the two claims
remain distinct. Both exercise real host child processes and
PTY I/O, not physical firmware execution.

The fixed firmware build passed at clean operational source revision
`ed47d362954b05464fc9e1380159064cb06e6ec1`. Firmware input hash remains
`9b52d002d57a2bf21d76c9c7e63f6260c0d86554a23f40d582cf9358eed5ad36`;
all firmware/configuration inputs are unchanged from the prior verified image.
The current build uses configuration hash
`1c81c04d069abe64caa1aaae2b6efc105e9d8fc1767ebde8e32f21d3e3ddffde`,
build session `4f13deb9451626db`, and UF2 SHA-256
`2055a85935bdbb3e9ee5de39ace7697381184324bc69f685a8bd964fd5cdfe26`.
Program storage is 223,020 bytes, static memory 154,140 bytes and runtime
headroom 108,004 bytes. The previous 7,936-case PIO proof is reused because
its firmware and configuration inputs are unchanged; it was not rerun to
qualify host-only changes.

The host bytes frozen into the production bundle include the subsequent PTY
startup-ordering repair; their individual hashes are in the bundle. The
embedded firmware revision identifies its build inputs, not a claim that the
later host files existed in that firmware commit.

No hardware was accessed. A successor merged bundle must still pass on the
older Mac before bench entry. The original failed attempt remains diagnostic
evidence and cannot be promoted by a successful successor run.

The production gate used normal bundle creation, proposal creation and the
public operational-rehearsal entry point, including independent deterministic
firmware reproduction. No synthetic build validation or private authority
bypass was substituted. All eight required operational boundaries passed and
the package was sealed and registered as `successful_rehearsal` with no
registration error. Its 55 files total 9,115,744 bytes; content SHA-256 is
`faf09d3fbae7ed2c21952cb4c3fad4937c9ca2e2c427528828268c38294b9bd5`.
The semantic seal SHA-256 is
`ca7efe3730a13b0b626c1c6d736333644bb858a96534fd874d6830ee8c5578c9`.
The package, report and index are retained under
`runs/rehearsals/shared-host-session-2026-09-11/`, outside Git. This completes
Stage 5b's finite local integration gate, not physical qualification or the
older Mac's launch-context rehearsal.
