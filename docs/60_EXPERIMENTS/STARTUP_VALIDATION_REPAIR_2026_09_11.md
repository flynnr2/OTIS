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

The first discriminating repair reused successful schema syntax checks by the complete canonical
schema content, with a bounded 32-entry process-local cache. It neither caches
an authority decision nor trusts a supplied hash. Each consuming call still
checks current embedded bytes, set identity, profile closure, bindings and
profile instances. Invalid syntax is not cached; callers receive freshly
parsed documents, so mutation cannot poison a cached result.

A fresh local process after that narrow repair took 0.199 profiled seconds for the
same validation/construction path: 29 authority validations remained, while
syntax validation required seven checks and 341 cache hits. This diagnostic
used explicitly rebound copies for changed host-tool bytes and retained the
real build input. It is not a frozen live-bundle rehearsal and does not predict
the older Mac's runtime. That narrow experiment retained the old readiness predicate and ten-second
deadline. The broader implementation below replaces the readiness predicate
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

## Verification boundary

Integration verification is pending. The 61 focused immutable-input, raw-replay
and frontier tests passed after consumer migration. The final gate must exercise
the common lifecycle, repeated transactions, holds, obstruction, abort delivery,
closure and actual analysis/sealing/registration, plus current release checks.
A subsequent frozen production bundle must pass on the older Mac before any
hardware entry. The original failed attempt remains diagnostic evidence and
cannot be promoted by a successful successor run.
