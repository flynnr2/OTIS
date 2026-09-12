# Host replacement: five responsibilities

This change replaces the operational host as a whole. Intermediate commits are
review checkpoints, not successive bench candidates. Firmware timing and
actuation semantics remain unchanged.

1. **Capture** owns serial, continuously drains it, preserves raw bytes,
   publishes observations, and delivers bounded commands. A dedicated worker
   isolates drainage from experiment decisions and analysis.
2. **Supervise** owns experiment state, startup discovery, authority, command
   progress, qualification, holds, and terminal decisions. One foreground owner
   manages that lifecycle. Missing observations remain pending within a declared
   bound; contradictory evidence never becomes authority.
3. **Monitor** presents owner state and capture health. It has no command,
   authority, readiness-handshake, terminal, or lifecycle responsibilities.
4. **Analyse** independently reconstructs measurement and controller behaviour
   from closed evidence. Scientific outcome and evidence integrity are separate
   results. Analysis never changes captured observations.
5. **Package** inventories and seals closed evidence for portable validation.
   An optional registry records locations; unrelated historical locations cannot
   prevent acquisition, analysis, or packaging.

One immutable run specification binds firmware, host tools, policy, command
limits, duration, stop conditions, and evidence contracts. One small run record
adds actual run identity, start, and device. Consumers derive their common
configuration in memory; there is no bundle/proposal/activation/manifest copy
chain. Creating a specification grants no permission to operate hardware.
Explicit physical entry requires the operator instruction and a verified receipt
from the complete rehearsal of that specification.

Capture has a direct priority abort path. Operator abort submission, delivery,
and firmware observation are separate facts. A host discrepancy holds new
authority and keeps capture alive; it cannot invent permission to abort or close
a live instrument. Firmware retains independent bounded fail-static behaviour.
Host deadlines use host monotonic time; scientific elapsed duration uses the
declared exact firmware counter domain.

Build and rehearsal are engineering operations. Ordinary capture and analysis
never compile firmware, flash a board, validate a global historical registry, or
regenerate configuration. Rehearsal uses the real owner and capture worker with
a deterministic simulated device. Its receipt identifies exercised boundaries
and sealed evidence; it makes no physical propagation claim.

Acquisition retains its serial owner until its terminal and required delivery
are established. Offline analysis starts after capture closure, so it requires
no serial handoff, transition spool, or ownership transfer protocol.

The cutover removes superseded orchestration and artifact APIs rather than
retaining compatibility wrappers. Historical experiments use the source
revision recorded with their evidence. The held physical attempt on the bench
Mac is untouched and requires separate explicit operator disposition.
