# GNSS baud-envelope starting-facts audit

Audit basis: repository revision
`3fbc62c5ca2acd3e59648f671579ebcf85c10333`, inspected before the
characterization implementation and before any bench access. Retained run
packages remain unchanged.

## Confirmed implementation facts

1. **Collector and parser behaviour is as stated.**
   `otis_gnss_receiver.h` fixes the canonical metadata collector at 96 bytes
   and the discovery collector at 256 bytes. `otis_gnss_receiver.cpp` starts a
   collector only at `$`, ignores CR, delivers a line only at LF, and counts a
   new `$` during a partial metadata line as a truncation/parser fault before
   resynchronizing. Complete lines require a terminal checksum and bounded
   field parsing.

2. **The live receive path is a 32-byte poll.**
   Baseline `otis_gnss_receiver_service()` loops while UART0 is readable under
   `OTIS_GNSS_SERVICE_BYTE_BUDGET`; the baseline configuration fixes that
   budget at 32 bytes. There is no interrupt-backed raw observation layer in
   the baseline.

3. **Core 0 has deliberate service opportunities but no measured worst-case
   receive-service interval.**
   In the dual-core Core 0 loop, GNSS service runs before ordinary USB/service
   work. `otis_status_emit.cpp` also invokes it after every complete synchronous
   `STS` record. The baseline snapshot and emitted status contain neither a
   maximum raw-drain/consumer gap nor UART DR overrun, break, parity, or framing
   counters, so those service opportunities do not classify the observed
   corruption.

4. **Discovery and target selection have different envelopes.**
   Baseline discovery enumerates `9600, 115200, 57600, 38400, 19200, 14400,
   4800` (target first), matching the local PMTK251 source. The compile-time
   target and emitted PMTK251 packet can be only 9600 or 115200. There is no
   progressive runtime target request for the five characterization rates.

5. **The retained baud-correlated corruption is real but layer-unclassified.**
   The terminal `health.csv` snapshots contain:

   | Run | Confirmed baud | Valid | Checksum failures | Truncations | Oversize | Parser drops |
   |---|---:|---:|---:|---:|---:|---:|
   | targeted Attempt 3 | 115200 | 2,662 | 28 | 42 | 1 | 71 |
   | targeted Attempt 4 | 115200 | 18,343 | 60 | 9 | 3 | 72 |
   | targeted Attempt 6 | 9600 | 137,028 | 0 | 0 | 0 | 0 |

   All three terminal snapshots record zero GNSS transmit failures and zero
   link losses. Because those firmware artifacts did not expose UART hardware,
   raw-acquisition, or ring evidence, checksum/truncation counts alone cannot
   identify receiver/electrical corruption, FIFO starvation, or consumer
   backlog.

6. **Attempt 6 physically emitted two GSA frames per nominal fix interval.**
   Its terminal metadata counters are exactly 34,257 RMC, 34,257 GGA, and
   68,514 GSA frames. Their sum is the retained 137,028 checksum-valid total,
   giving the observed `1:1:2` cadence. Wording that describes PMTK314's GSA
   field as one physical GSA line per second is therefore not an adequate
   runtime cadence contract for this receiver.

7. **The receiver contract has a stale eligibility clause.**
   `CX317_RX_ONLY_GNSS_RECEIVER_CONTRACT.md` correctly records 9600 as the
   frozen operational baud and records Attempt 6's clean confirmed-9600
   terminal, but its eligibility section still requires
   `confirmed_baud=115200`. That clause contradicts the same document and the
   current 9600 target. The characterization profile needs baud-epoch-local
   metadata qualification; ordinary production eligibility must follow its
   selected profile target rather than a stale hard-coded 115200 value.

## Primary-document check

The two local PA1616S datasheets identify the solution as MT3339 and the module
default as 9600 bps. Their SHA-256 identities are respectively
`1edf78b565231f887164a52e3ed0e6b001e9c6246cddc21dda7e64291ff8a8f2` and
`f041c26af4d3f244a33f8f0c6f6d5286e239173a9ea510346dc9c8c7cd3814c4`.
The local GlobalTop PMTK command document, SHA-256
`88318174825c78e27c4f24eb9b205875e5336f1352e5fa2801a724dad6ce1160`,
defines PMTK251 as a set-only NMEA-port baud command and lists
`4800,9600,14400,19200,38400,57600,115200`. Independent XOR calculation
reproduces the five frozen packets and checksums in the V1 contract.

## Evidence locations

- Attempt 3:
  `runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt3_20260825T155902Z/live_attempt3_20260825T160252Z/csv/health.csv`
- Attempt 4:
  `runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt4_20260825T164928Z/live_attempt4_20260825T165938Z/csv/health.csv`
- Attempt 6:
  `runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt6_20260826T061717Z/live_attempt6_20260826T062115Z/csv/health.csv`

The historical records and terminals are evidence inputs only; this audit does
not rewrite or relabel them.
