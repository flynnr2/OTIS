# Causal wait ownership after the older Mac rehearsal cutoff

## Evidence and diagnosis

The production-bundle PTY rehearsal at merged revision
`7b499a684a36ae74db33ce4384194203a972e9f8` passed build, startup and worker
readiness, then hit the coordinator's 90-second transaction-sequence timer.
No hardware was accessed. This is a platform defect caught in rehearsal.

The received archive is 976,970 bytes, SHA-256
`42ab2939d81101edf8877492926143c0b3e030a708b9fddd586cdf05f5899517`.
All 53 delivery-manifest entries were verified. The original 43 regular files
exactly match the indexed 8,653,033-byte package, content SHA-256
`9a7aa5f79bfbbab40fcca73d904558af2e9bf5e5bd5743f8d43d22d9b60280e6`.
Three FIFO nodes were deliberately omitted from the local analysis copy; no
original regular file or embedded binding was altered. The outer stdout/stderr
is missing; the separately supplied command is explicitly reconstructed.

The decisive sequence, in UTC on September 11:

- 21:11:34.501479: complete snapshot generation 32 / query 658895324 reports
  request 2, application pending, DAC code 43085 and epoch 3.
- 21:11:35.511: capture writes `ACTIVE EVIDENCE 2 3` after retaining application
  record 8 and its capsule.
- 21:11:35.556: capture writes the corresponding query 658895325.
- 21:11:45.202: the coordinator terminates capture, only 9.646 seconds after
  that query write. No generation 33 or row carrying that nonce was retained.
- 21:11:46.242834: the finalization journal records the original aggregate
  timeout; diagnostic registration succeeds.

Capture remained fresh and clean before shutdown: zero parser, UTF-8,
reconnect or command-rejection faults, no host hold or terminal, and no abort.
The simulator was still emitting the response horizon; retained accepted
ordinal 7459 was 344 intervals short of the response target 7803. The only
partial-line warning follows shutdown and is cleanup damage, not its cause.
The evidence proves writes at the capture boundary; it does not prove when
the simulator internally read those final commands or that acknowledgement
would ultimately have succeeded. It does prove that the parent stopped the
attempt before the query's own allowed observation interval expired.

## Shared defects and finite replacement

The parent 90-second timer and separate 120-second capture/supervisor timers
had different origins and no consistent budget for the legal transaction,
abort, rotation and closure sequence. Increasing the first timer alone would
move the escape to the next one.

The pre-acknowledgement wait also issued an initial query plus up to four
further queries, discarded the fifth response, and restarted a 30-second
wait on each query. Its comment incorrectly claimed all queries fit within
30 seconds. Snapshot and incomplete-health waits could block the outer abort
and lease-service loop. These source defects affect the shared physical path,
but their causal role in this particular cutoff is not asserted.

The replacement keeps the existing supervisor and command interfaces. A
causal operation owns one monotonic deadline, consumed by nested command,
snapshot and incomplete-health waits. Retries and unrelated snapshots do not
refresh it. Wait slices service explicit abort; lease renewal is limited to
already-owned authority and cannot insert a second normal command while the
first command's exact write acknowledgement is unresolved. An unknown prior
process's persisted monotonic deadline cannot authorize continuation.

The private PTY coordinator owns managed process lifetime. Its frozen timing
declaration gives each exact progress stage one deadline and reserves the
later abort/rotation/closure phases. A fixed, finite set of one-shot transitions
bounds total duration without a competing aggregate stopwatch. Progress counts
one-shot census, setup, exact acknowledged-record prefixes and metadata
requalification; heartbeats, newer snapshots and repeated observation of a
written ACK do not extend a stalled operation. The two abort waits consume one
delivery deadline. No independent 120-second child expiry remains.

This is removable campaign machinery, not a future standalone runtime or a
new async framework. Firmware safety expiry and scientific counter-domain
qualification remain separate and unchanged. The historical failure remains
failed diagnostic evidence; successor tests do not retrospectively promote it.

## Whole-host simplification

The review expanded beyond the triggering timer defect. The physical runner
also assigned separate capture and supervisor lifetimes; these are removed.
The unused base supervisor loop is removed, including contradictory automatic
abort behaviour. Startup identity queries now run inside the guarded census
cycle; a failed query retains the no-authority hold and abort ingress.
Unsupported restart adoption is observational, not a second recovery protocol.

The monitor no longer replays full growing EST/ACT/AHY/AHM histories on every
poll. It checks bounded complete tails, reports total counts as unknown, and
labels the observation scope. Full history validation remains with its actual
consumers. Valid header-only evidence is an explicit no-observations-yet
state; missing/malformed evidence remains a review finding. Session monitoring
consumes findings and stale receipts through the existing review hold. The
PTY path exercises the same consumer.

Abort verification previously rescanned the complete raw log every poll and
had a separate live-state shortcut. It now uses one post-send raw path: capture
records its open-file device/inode and search offset; the verifier reads
forward in bounded chunks, observes the actual marker, and accepts only a
subsequent complete snapshot. It retains the highest begun generation and
rejects contradictory markers, file replacement and truncation. A 512 MiB
sparse-history test exercises the producer-to-consumer path with a deferred
marker and partial final status row. This changes no firmware abort semantics.

The physical partial-snapshot implementation is replaced by the canonical
inventory/writer. Rehearsal's private registration sequence is replaced by the
existing intent-first recovery operation. This fixes demonstrated journal
shape drift and prevents an index write preceding durable registration intent.
Tests interrupt the real index-write/journal boundary and recover twice without
changing package content or adding a second index entry.

The monitor seal predicate now checks observation of the fixture's completed
transaction frontier, rather than asking a current-state observer to claim a
full-history row total. Independent raw replay and complete transaction/history
analysis remain required. Historical failed packages and criteria are unchanged.

## Remaining simplification boundary

One pure manifest projection should eventually replace repeated declaration
inventories in producer and validator, and the existing immutable configuration
should be carried through more preparation calls. These are identified follow-up
reductions, not a new framework or grounds to remove independent firmware
binary, raw-source or acknowledgement checks. Autonomous firmware operation,
compact serial output, D10 capture and true latch-to-service latency remain
separate product work. No hardware portability programme is introduced.

## Verification

The final current release sweep passed **715 tests** excluding the two full
process cases. Both full process cases passed: normal command effects and a
four-second device-side delay on every evidence acknowledgement. The delayed
case completed in 112.23 seconds, including shared analysis, sealing and
registration. Each successful package was registered through shared recovery
twice without a content change. This is 717 current tests across the release
and focused process runs, not 717 hardware tests.

The full-path checks exposed and repaired implementation integration errors:
a duplicate Python method shadowed the current query nonce, a seal consumer
still expected the monitor's retired row total, the seal-check inventory was
not shared, and monitor startup inferred event arrival from host flags. Direct
nonce, duplicate-definition, shared check-inventory and full monitor startup
regressions now cover these boundaries before another process rehearsal.

The publication verification record binds the exact committed firmware build,
independent deterministic reproduction and production-bundle PTY result. The
firmware, profile, schema, protocol and build-tool inputs are unchanged by this
host tranche; the prior 7,936-case PIO instruction proof is reusable on that
basis. The new image still needs its real USB/firmware/plant gate. No original
experimental evidence was changed and no hardware was accessed here.

The next bench task is actual hardware entry using the frozen candidate and
its existing finite authorization envelope. Full host software simulation stays
on the development Mac. Compact standalone operation and the remaining pure
manifest/configuration consolidation remain separate work, not claims made by
this rehearsal.
