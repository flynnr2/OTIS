# Native reference-acceptance candidate assessment

## Decision and scope

The native candidate supports advancing to the complete firmware/host source
cutover. With the proposed ±1.25 ms policy it excludes the recorded extra
edge and reconstructs the intended accepted-to-accepted D8 span exactly.
It remains unwired and has no control authority. Frequency, phase, live
capture association, producer-frontier expiry and campaign qualification have
not been promoted to this policy.

The [prospective contract](../../data_contracts/reference_acceptance_v1.md)
states acquisition, tracking, exclusion, loss and requalification semantics.
The numerical window incorporates the operator's report of successful use
on another instrument with the same GPS breakout board. That other
implementation and its experimental evidence were not independently reviewed.

## Retained evidence and native result

The source is the unchanged package with content SHA-256
`43a596f175122b632bb40a410b33c3bd956923a89d6d09ef0114c178582d0739`.
This assessment reads only its REF/SNP/CNT CSV files and writes to a separate
new output directory. Source hashes are checked before and after execution.
The first retained CNT still lacks its opening snapshot and is explicitly
excluded from this mathematical raw-pair check; it is not repaired or sealed.

| Check | Result |
| --- | --- |
| Paired retained REF/SNP observations | 52,310 |
| Independently reconstructable adjacent raw pairs | 52,309 |
| Unproved leading CNT rows | 1 |
| Acquisition | One seed plus eight qualifying raw intervals |
| Subsequent accepted spans under the candidate | 52,300 |
| Excluded candidates | 1 |
| Acceptance epochs containing spans | 1 |
| Candidate qualification losses | 0 |

For the disturbance, the accepted span opens at raw SNP/D14 source ordinal
37,886 and closes at 37,888, excluding 37,887. Its local timestamps are
3,528,306,506 and 3,529,306,507 microsecond ticks. The unchanged cumulative D8
counter endpoints are 3,387,451,285 and 3,377,451,285. The candidate therefore
records 10,000,000 edges across 1,000,001 local ticks, with one excluded
candidate and no acceptance-epoch change. REF's emitted event ordinals are
independent of those SNP/D14 source ordinals.

The assessment uses the entire retained recording, including observations
after the historical review hold. Its 52,300 candidate spans are **not** the
original attempt's qualified-duration count. The original 35,480-aperture
prefix, closure, seal and incomplete scientific result remain unchanged.
No present-day criterion is applied retroactively to that campaign.

## Verification and reproduction

All 47 focused native and architectural checks passed in 2.14 seconds. The
source guard confirms that no current firmware consumer includes or calls
the candidate. This is a native-component result, not a fixed-image build,
full release gate or physical qualification.

The native regression cases exercise acquisition without retrospective
promotion, exact tolerance boundaries, repeated early candidates, the
exclusion limit, missing and late reference, reacquisition, session changes,
source/ordinal/counter rollover, flagged or missing evidence, zero-count short
fragments, 600-span endpoints, and stale/incomplete/contradictory expiry
frontiers. An in-band impostor case explicitly demonstrates the limitation of
timing-only admission rather than labelling the candidate genuine.

The assessment tool compiles the same integer-only C++ kernel used by those
tests and retains every per-input outcome. The summary binds the source files,
policy, kernel, harness, assessment tool, raw reconstruction helper, native
binary, commands and input/output traces by hash. To reproduce in a new local
directory:

```sh
.venv/bin/python tools/replay_reference_acceptance_candidate.py \
  --source runs/imported/43a596f175122b632bb40a410b33c3bd956923a89d6d09ef0114c178582d0739 \
  --output build/reference-acceptance/retained-attempt1-repeat
```

The original local result is
`build/reference-acceptance/retained-attempt1/summary.json` with full native
trace alongside it. Large traces and the source package remain local evidence,
outside Git. This report and the reproducible implementation are the reviewed
repository record.

This observation-driven replay does not exercise the expiry-frontier API;
deterministic native cases cover that API's stated assumptions. Those cases
cannot prove that real firmware can supply a truthful drained frontier.
The next integration must either prove that producer boundary or retain a
diagnostic control hold while pending observations could still resolve it.
Likewise, the native selector does not establish phase preservation or a
reconstructable control transaction until the real consumers use its accepted
span identities together.
