# Conditional Fine Map and Frequency Traversal Plan

## Decision served

This campaign closes CX319 Part A at the measured deadband transitions and,
only if that evidence passes, executes Part B as three fresh frequency-only
legs: lower acquisition, upper acquisition and lower reacquisition. Phase and
hybrid actuation remain outside the authority envelope throughout.

The executable contract is
`profiles/qualification/cx319_conditional_range_campaign_v2.json`. It binds the
complete survey result, plant model, estimators and policy by SHA-256. Exact
firmware builds, host tools, command bounds and stop rules are subsequently
frozen in the physical bundles.

## Survey-informed focusing

The completed 30-point survey is locally linear over the transition region:

- fitted response: `0.107803` accumulated 600-second counts per DAC code;
- equivalent response: `0.000179672 Hz/code`;
- RMS residual: `0.264` count;
- maximum residual: `0.517` count;
- predicted lower count-boundary crossing: approximately `0xA81B`;
- predicted upper count-boundary crossing: approximately `0xA84A..0xA84B`.

Accordingly, the fine map does not repeat the established plant curve. It uses
three two-code-spaced samples around each predicted crossing in both
directions:

- lower: `0xA819`, `0xA81B`, `0xA81D`;
- upper: `0xA849`, `0xA84B`, `0xA84D`.

The turnaround code is reapplied to open a distinct DAC epoch before each
return traversal. Three `0xA830` references distinguish boundary movement from
run-level drift, and opening/final `0xA800` observations provide closure. This
is a 17-point programme rather than the initial 35-point exhaustive proposal.

## Adaptive observations

Opening and closure points require two fresh selected 600-second observations.
References require four. Every boundary point requires four and permits six.
The host extends a boundary point from four to six observations only when the
first four include both tight-entry evidence (`abs(count) <= 2`) and outside
evidence (`abs(count) >= 3`). The analyzer independently recomputes this rule
from retained TDB records; it does not trust the runner's declared decision.

At the frozen worst-case timing, Part A takes 63,900 seconds with no adaptive
extensions and 78,300 seconds if every boundary point extends. These are
17 hours 45 minutes and 21 hours 45 minutes respectively, before small
flash/prewrite/finalization allowances.

## End-to-end propagation and promotion

Every point must preserve this exact chain:

1. the sole serial owner sends the timestamped `DAC SET` command;
2. firmware records exact requested and applied code equality;
3. Core 0 advances a new DAC epoch, including for same-code reapplication;
4. the selected estimator binds its output to that epoch and source identity;
5. the tight-deadband consumer retains the required adaptive observations;
6. the hybrid-preview consumer sees the same code and epoch while all its
   authority flags remain false;
7. the analyzer reconstructs point order, epoch order, estimator identity,
   zero authority and the adaptive count;
8. the promotion tool derives four directional transition intervals and emits
   one content-addressed pass/nonpass record.

Promotion requires complete and healthy capture, no active transactions,
correct inside/outside guards, a single contiguous transition or honest mixed
code in every direction, clear brackets no wider than two codes, directional
displacement no greater than four codes, stable centre references, endpoint
closure and a Part B movement budget that covers the observed transitions.
Failure seals Part A and stops before any active firmware flash.

## Part B boundary

Part B is not a continuation of Part A state. Each leg uses a fresh exact
active firmware entry and its own immutable evidence package:

1. `0xA800`, positive-only automatic correction;
2. `0xA890`, negative-only automatic correction;
3. `0xA800`, positive-only reacquisition.

Each leg is limited to nine corrections, 21 codes per step, 189 cumulative
codes, the characterized `0xA800..0xAB00` range and a minimum 1,800-second
applied cadence. There is one outstanding request at most, no automatic retry
and no automatic restore. The next leg consumes the exact predecessor terminal
and sealed evidence; an acknowledgement alone cannot promote it.

The Part A image retains the historical `p21600_cap1_v2` hybrid candidate so
the frozen acquisition bundle remains exact. Each Part B image instead carries
the non-actionable `p21600_cap1_epoch_reseed_v3` observation candidate. At
every externally applied DAC epoch it reseeds the actual and shadow code,
candidate start code, correction count, cumulative path, direction history,
terminal-fault lifetime, frequency support and decision cadence. Host/firmware
parity tests cover that transition, and the live analyzer independently
requires the candidate/configuration identity and zeroed first record for every
physically applied DAC epoch.

This revision improves what Part B can teach about hybrid-preview lifetime
semantics without broadening authority: hybrid state cannot affect frequency
eligibility, requested delta, the live frequency budget or physical actuation.

## Monitoring

The authoritative supervisor state and retained evidence freshness are checked
continuously. After prewrite and the first complete point establish stable
operation, unchanged state may be sampled every five minutes. Updates are
issued for regional boundaries, promotion, each automatic correction, every
leg terminal and any fault or stale-evidence condition. Process existence or a
quiet terminal is never treated as progress evidence.
