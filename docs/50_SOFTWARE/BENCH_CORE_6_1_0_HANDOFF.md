# Prepared Nano 6.1.0 bench entry

The development Mac owns source changes, release checks, the fixed image/resource
review, no-I/O preflight, frozen specification and operational-path rehearsals.
The bench Mac reproduces that exact image, flashes once and runs it. Installing
the pinned local build dependencies and the entry point's automatic identity
checks are part of compilation/entry, not a second engineering campaign.

Do not repeat source engineering, the release suite, specification creation or
rehearsal on the bench. Return a concrete pre-upload identity/build mismatch to
the development Mac without editing the frozen inputs. Use a local Python 3.10+
environment with the repository dependencies installed.

Use Arduino-Pico **6.1.0**, Arduino CLI **1.4.1**, and the compiler package and
Nano 133 MHz FQBN pinned in `firmware/arduino/firmware_build_manifest.json`.
The prepared Intel image uses the approved x86_64 macOS compiler. It was built
on Apple Silicon through Rosetta. The bench must reproduce the selected
compiler identity, build session, input set, provenance and UF2 bytes; approval
of both native compiler packages does not make their images interchangeable.

## Frozen observation

`inhibited_zero_write` now freezes **300 seconds** in the host monotonic clock,
starting at supervisor construction after the sole capture process is ready.
Compilation, upload and earlier manifest creation do not consume that window.
UTC changes and repeated status queries cannot move its deadline. A retained
supervisor state rejects re-entry before serial acquisition; an interrupted
attempt cannot restart its five-minute clock. This is a
five-minute observation window, not a claim of 300 qualified D14/D8 intervals;
closure follows the first eligible supervisor poll at or after the deadline.

Ordinary completion is `healthy_stop / inhibited_zero_write_complete` and
requires the existing healthy static-state evidence. No SETUP, ARM, DAC write,
or `ACTIVE ABORT` is needed. If that evidence is unavailable, retain the existing
diagnostic hold and serial owner for operator review; the deadline does not
authorize an invented success or automatic abort. The separate contingent
72-hour control purpose retains its existing timing semantics.

D14 remains the sole reference, D8 the sole oscillator input. D10 capture is
unimplemented. Service-latency diagnostics remain software-stage observations,
not electrical-edge latency or a new control/terminal gate.

## Bench commands

Deliver the prepared bundle separately from Git; raw rehearsal packages belong
outside repository history. Check out the exact revision identified in its
`HANDOFF.json`, with clean operational sources. The bundle contains the inert
`run_spec.json`, `rehearsal-receipt.json`, and sealed `rehearsal/` package.

From that checkout, compile using the retained specification:

```sh
python3 -m host.otis_tools compile /path/to/bundle/run_spec.json \
  --output-dir build/bench-core610
```

This uses the existing firmware reproduction verifier. A mismatch is a
pre-upload hold; do not regenerate the specification, edit hashes or substitute
another image. The compilation result identifies the reproduced build manifest.
Use that manifest with the delivered rehearsal and exact detected board port:

```sh
python3 -m host.otis_tools run /path/to/bundle/run_spec.json \
  --rehearsal /path/to/bundle/rehearsal-receipt.json \
  --rehearsal-package /path/to/bundle/rehearsal \
  --firmware-manifest build/bench-core610/artifacts/firmware_build_manifest.json \
  --run-dir runs/bench-core610-five-minute \
  --device /dev/cu.usbmodemACTUAL \
  --operator-ref 'operator-authorized Nano 6.1.0 five-minute inhibited baseline' \
  --reason 'observe current service-latency baseline with zero actuator writes' \
  --flash
```

The runner validates the delivered receipt, current host toolset, image and board
identity before upload, retains upload output, discovers re-enumeration, acquires
one serial owner, runs, closes normally, analyzes and seals. Do not separately
open a serial monitor. Use a fresh run directory; failed entry does not authorize
an automatic second flash or retry.

Keep the controlling Codex turn active and inspect `python3 -m host.otis_tools
monitor RUN_DIR` every two seconds. Report meaningful transitions, stale evidence
or a review-required hold. Process liveness alone is insufficient. Do not end
the turn while physical acquisition remains active. Preserve raw evidence,
terminal status and upload/build identities. A healthy no-write result may have
an unknown DAC code; no movement is authorized to discover or establish it.

## Scope of the offline evidence

The retained operational rehearsal runs real host capture and supervisor
processes over a pseudo-terminal with a deterministic device producer. It checks
identity/census, obstruction, independent priority abort, ordered closure,
analysis, sealing and registration. The graceful-endpoint integration check
exercises normal closure without abort; exact nanosecond boundary tests cover
the 300-second deadline. These establish host behavior, not real firmware
interrupt service, USB delivery, receiver state or physical timing quality.
The finite bench observation provides that remaining physical evidence.

## Development-Mac verification — 2026-09-19

- Release suite: 737 passed. Final timing-provenance/compile checks: 45 passed;
  restart-preservation/runtime checks after review: 51 passed.
- Approved Intel compiler through Rosetta: fixed image and resource audit
  passed; the public `compile` command reproduced identical provenance and UF2
  bytes from the frozen specification in a second build directory.
- Unchanged PIO proof: 7,936 cases, 55,552 intervals, -1/0/+1 edge boundary
  errors, four-clock longest opposite-WAIT path.
- Unaccelerated simulated normal completion: 300,023,068,875 host monotonic
  nanoseconds, `healthy_stop`, no SETUP/ARM/ABORT, complete capture and passing
  `diagnostic_complete` analysis. This preceded the restart-rejection guard;
  its original specification and evidence remain preserved. A post-closure
  helper used the wrong terminal field name; the corrected offline lookup
  finalized the unchanged evidence without repeating acquisition.
- After the guard, a fresh exact specification and real-process obstruction /
  independent-abort / closure / analysis / seal / registration rehearsal passed.
  The normal closure path was repeated with only its deadline accelerated after
  census and raw-origin admission; retained coordinates expose that acceleration.
  The guard's rejected-restart regression proves no new capture launch, no state
  rewrite and no deadline renewal. The earlier full-duration timing evidence
  was not relabeled as belonging to the refreshed host toolset.

The delivered bundle retains the build, reproduction receipt, current rehearsal
receipt/package, current accelerated closure evidence, earlier full-duration
package, verification logs and exact identities. Its `HANDOFF.json` records the
checkout revision. A no-I/O entry validation also verifies relocated artifacts;
this is preflight, separately from the actual process rehearsals above.
