# Offline capacity measurement — 12 September 2026

## Decision and scope

The actual offline analyzer and package sealer can process 259,200 synthetic
one-second D14/D8 apertures on the development Mac. This is an input-volume
measurement, not 72-hour physical qualification. Analysis starts after capture
closes and can run on the development machine; the older bench Mac need not
carry this memory load while owning serial.

Measurements used macOS 15.7.4 on arm64 and Python 3.14.6. They are not a
performance measurement of the older bench Mac.

The fixture extends a retained simulated, inhibited rehearsal with ideal
10 MHz observations and one frequency estimate per 600 apertures. It retains
an explicit synthetic declaration and an interrupted-incomplete lifecycle. It
does not exercise controller execution, DAC movement, real elapsed duration,
USB, or the physical reference. Its successful analysis must never be reported
as a completed steering campaign.

## Measurement-only baseline

The baseline used the merged five-job host at `c60164c`, before the subsequent
phase-source and analysis-provenance repairs:

| Quantity | Measured value |
| --- | --- |
| Accepted D14/D8 apertures | 259,200 |
| Frequency estimates | 432 |
| Phase and controller records | None |
| Analyzer wall duration | 44.246787875 seconds |
| Analyzer peak process RSS | 1,187,037,184 bytes |
| Analysis integrity | Passed, all checks true |
| Scientific outcome | `interrupted_incomplete` |
| Sealed package content SHA-256 | `e2b1e5607a3e2efd2329e706f3423ce6f09c15280b99dd8469a57e9b48dacab0` |
| Analysis report SHA-256 | `29f4810fb631cb0ffe7bec7dcfbe35b00a673ce13705aebd60d7d3784c81a760` |

RSS is macOS `resource.ru_maxrss` in bytes, measured in the analyzer process.
Fixture generation and sealing are outside this duration and memory reading.
The retained local fixture is `/private/tmp/otis-offline-capacity-259200`;
the adjacent `-analyze-metrics.json` and `-analyze.log` retain the measurement.
These paths identify local evidence, not durable cross-machine delivery.

This replaces extrapolation from the earlier 25,000-aperture core-only probe
for the measurement-only workload. It does not establish the cost of dense
phase history or unlimited D10 event traffic. No replay indexing or storage
framework is justified by this baseline alone.

## Dense phase history

The final repaired host also passed the actual public CLI analysis, packaging,
and verification path with one RPH and PHE per accepted aperture:

| Quantity | Measured value |
| --- | --- |
| D14/D8 apertures / EST rows | 259,200 / 432 |
| RPH rows / PHE rows | 259,200 / 259,200 |
| Primary CLI analysis wall duration | 65.24 seconds |
| Resource-measured CLI analysis wall duration | 65.613737667 seconds |
| Analyzer peak process RSS | 1,425,342,464 bytes |
| Sealed payload | 33 files, 568,205,781 bytes |
| Included analysis report | 100,313,095 bytes |
| Integrity / scientific outcome | Passed / `interrupted_incomplete` |
| Complete host-toolset SHA-256 | `c1e828b6399cb9c666205cf17ac023e241b74088f47aa63a087eac88cd9eda58` |
| Package content SHA-256 | `0dc3a510edfa34bf39b97cb0175283048bd01123d022530422840817d2b6fe8e` |
| Packaged analysis report SHA-256 | `225a3812bc34c343c455b56eb89be33e10cac86737fc9ad7f483a7530c718234` |

The second completed invocation measured the real public CLI in a child process,
with its inherited environment, file-drained stdout/stderr, and a 180-second
limit. It wrote an external report while the source was still unsealed. The
original report was then packaged and verified unchanged. No tests or rehearsals
were run concurrently with this timing measurement. Both analyses passed every
check. Generation, package validation, and sealing are outside the measured
analyzer duration and RSS.

The primary timing command could not obtain RSS because the sandbox denied its
clock-rate query. An attempted replacement measurement then waited on unfinished
terminal input: no analyzer child started. That setup was interrupted and
replaced by the explicit bounded child above. Neither setup issue was an
analyzer timeout or scientific failure. The successful analyzer was not repaired
or altered between the two completed measurements.

The sealed source remains at
`/private/tmp/otis-offline-capacity-phase-259200-v2`. Commands, stdout/stderr,
resource metrics, the external report, and package/verify results are retained
under `/private/tmp/otis-capacity-probe/` with the `dense-phase-` prefix.
These results close the synthetic 72-hour measurement-and-phase input-volume
check on this Mac. They do not establish older-Mac performance, arbitrary D10
traffic capacity, dense controller-transaction history, or physical qualification.
The measured cost does not justify adding streaming or indexing machinery now.

## Reproducing the input-volume experiment

`tools/generate_offline_capacity_fixture.py` builds a fresh disposable fixture
from explicitly selected sealed simulated donors. The starting donor supplies
the inhibited lifecycle and observation prefix; a separate estimate donor
supplies the current estimate shape. The generated specification binds the
current host toolset. Use a new destination whenever those tools change, and
preserve previous diagnostic packages unchanged.

Run the ordinary public analyzer and package path on that fixture. Measure the
analyzer in a separate process with a finite timeout, recording wall duration,
peak RSS, all-checks result, report identity, and package identity. Keep generated
raw data outside Git. Historical donors are input bytes, not a claim that an
old report has passed the current acceptance contract.

## Defects exposed before another physical acquisition

Adding phase history exposed a real producer/consumer mismatch. Firmware can
publish a qualified relative-phase observation while its frequency estimator is
still initializing. The host incorrectly required those two qualification states
to be equal. The repair follows the current firmware's relation and preserves
all existing exact source and raw-value checks. A native firmware formatter
regression now feeds its emitted rows through the host replay consumer; malformed
source values and contradictory qualification pairs still fail. Duplicate RPH
or PHE identities also fail. An RPH whose PHE is absent is counted explicitly
as incomplete pair coverage: the separately transmitted records need not both
be present at capture closure, and missing preview coverage has no scientific
terminal authority.

The analyzer also used to identify only its entry file. A replay-helper repair
could therefore produce a different result without changing the reported tool
hash. Analysis now records the existing complete host-toolset identity. First
analysis checks the frozen toolset; a subsequent external report records the
current toolset and links the immutable source package. These are offline
platform repairs. They do not change firmware, control authority, reference
acceptance, or the frozen scientific criterion.

## Verification of the repair

The full current suite passed: **673 tests in 86.91 seconds**. Focused tests
include native firmware phase emission through the actual source-association
consumer, duplicate identities, explicit missing-preview coverage, frozen-toolset
rejection, and corrected external reanalysis with unchanged sealed evidence.
Firmware source and build inputs are unchanged; the fixed image and its existing
independent reproduction remain applicable. Operational rehearsals for a new
candidate must bind this updated host toolset before physical entry.
