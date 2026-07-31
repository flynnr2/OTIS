# PPS Backend No-Hardware Validation — 2026-07-31

## Disposition

No-hardware validation passes for the implemented candidate. Hardware
qualification remains pending; control remains blocked.

| Identity | Value |
|---|---|
| Repository base commit | `47fddb8e3c857f2312a7cf242735885cb906c383` |
| Branch during validation | `main` |
| Working tree | dirty programme-of-works tree; no commit or staging performed |
| Boundary owner | `pio_state_machine` |
| Aperture backend | `pio_wait_cumulative_snapshot_dma_v1` |
| System/PIO clock | `133000000 Hz`, divider `1.0` |
| Qualification | `backend_qualified=false` |

The generated build provenance hashes the dirty source inputs used for each
matrix profile. Formal bench evidence must use a deliberately reviewed clean
commit, not this uncommitted validation state.

## Work packages completed

- Prompt 20: single-state-machine oscillator-edge-driven WAIT backend, raw
  cumulative snapshot transport, independent REF observer, and fail-closed
  association/reacquisition.
- Prompt 25: annotated assembled listing, cycle proof, edge ownership, wrap and
  reset semantics, FIFO/DMA ownership, timing-envelope proof, and explicit
  external counter/CPLD fallback rule.
- Prompt 30: bounded ISR event preservation, foreground interval policy, and
  independent physical/snapshot/drain/measurement/telemetry/control progress.
- Prompt 40: command-armed D3 pseudo-PPS PIO/DMA generator, immutable profiles,
  PGT truth contract, safety guards, and fault-scoring support.
- Prompt 50: raw SNP contract and capture split, central wrap-safe
  reconstruction, qualification SNP/CNT parity, official versus diagnostic
  estimator separation, fixtures, scoring, and tests.
- Prompt 60: profile/resource integration, authoritative documentation,
  structural checks, full tests, positive/negative builds, wire fixtures, and
  example run validation/reporting.
- Prompt 70: executable staged bench handoff with clean, fault, quiet/load,
  phase-sweep, extended, overnight, and troubleshooting gates.

## Exact validation commands and results

PIO assembly and instruction-level proof:

```bash
python3 tools/verify_pio_snapshot.py \
  --pioasm /Users/richardflynn/Library/Arduino15/packages/rp2040/tools/pqt-pioasm/5.0.0-9576866/pioasm
```

Result:

```text
15 assembled words
7,936 phase/duty cases
55,552 reconstructed intervals
boundary error histogram: -1=17,508; 0=21,130; +1=16,914
maximum completed WAIT to opposite WAIT: 4 PIO clocks
stopped-oscillator finite tail: at most 6 clocks and 1 snapshot
128-word DMA ring exact capacity/wrap/overwrite checks: pass
repository installation assertions: pass
```

Python syntax compilation used an in-sandbox bytecode cache:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/otis-pycache \
  /private/tmp/otis-remediation-venv/bin/python -m compileall -q \
  host tools firmware/arduino/validation/scripts
```

Result: pass.

The integrated runner was executed using the same dependency-complete Python
interpreter. The user-owned local generated profile header was temporarily
relocated and restored unchanged because the provenance builder intentionally
rejects reusable generated headers:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/otis-pycache \
  /private/tmp/otis-remediation-venv/bin/python \
  firmware/arduino/validation/scripts/run_no_hardware_checks.py
```

Results:

- pytest: **363 passed, 2 skipped** in 14.08 s;
- firmware matrix: **12 expected-pass profiles compiled and verified**;
- negative matrix: **4 expected-fail guards failed with their exact expected
  diagnostic and were verified**;
- all 16 matrix results: `all_verified=true`;
- synthetic, GPIO-loopback, and GPIN0 wire fixtures: pass;
- example run contract validation: pass with expected unsealed/example
  provenance warnings;
- example report generation: pass.

The matrix includes the required `phase5_qualification` and
`pseudo_pps_loopback` binaries. It also verifies invalid PPS-backend/capture,
pseudo-PPS resource-sharing, actuator-mode, and sweep-without-actuator
combinations.

Final source hygiene commands:

```bash
git diff --check
test -e firmware/arduino/otis_nano_rp2040_connect/otis_build_profile.generated.h
```

The diff check passed and the pre-existing user-owned generated header was
confirmed restored. It remains intentionally untracked and is not part of the
programme output.

## Integrated self-review

1. No CPU instruction can move a physical count boundary; PIO alone decrements
   X and executes `IN X, 32`.
2. D14 and D10 ISRs preserve timestamp/level/sequence events only; interval
   classification and policy run in foreground.
3. Foreground backlog cannot mark physical PPS missing; only physical-producer
   progress updates that state.
4. One continuous outage produces one transition; reminders are separate.
5. Malformed PPS and any snapshot/association/transport fault fail closed.
6. Normal builds do not claim D3; the loopback build is explicit, isolated,
   command-armed, and high impedance when inactive or faulted.
7. Counter, snapshot sequence, reference sequence, and timer wrap behavior is
   explicitly tested.
8. Continuity loss starts reacquisition and requires two fresh snapshots.
9. `official_raw_frequency` is authoritative; timer-normalised output is
   explicitly diagnostic and cannot override failure.
10. Every shipped matrix profile keeps
    `OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=0`; actuation remains false.

## Hardware-only questions and limitations

No software proof establishes the actual D8 pad duty, threshold crossings,
ringing, synchronizer phase margin, board-level propagation distortion, or
temperature/voltage behavior. The required bench campaign must measure the
conditioned 16 MHz waveform, sweep PPS through a complete oscillator period,
exercise 35–65% duty stress where possible, run pseudo-PPS faults, and compare
quiet/load official counts before extended and overnight evidence.

The edge-driven programme blocks when the oscillator stops. D14 continues to
report physical REF events; association is immediately invalidated, late words
are discarded, resumption starts a new session, and two fresh snapshots are
required. This is intentional fail-closed behavior.

If the phase/duty bench proof fails, stop and recommend the external
counter/capture latch or CPLD fallback. Do not substitute ISR, DMA, or a second
PIO state machine as aperture owner.

**Qualification remains pending explicit hardware evidence and review.**
