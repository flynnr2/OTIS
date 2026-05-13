# SW1 Hardening Before PIO/DMA

SW1 is the first H0 capture firmware stage. It proves that the Arduino Nano
RP2040 Connect firmware can emit parseable OTIS telemetry, that the host can
split and validate run artifacts, and that GPS PPS / TCXO observe runs can be
summarized repeatably.

SW1 does not prove final timestamp metrology, PIO capture, DMA transport, DAC
steering, oscillator discipline, GPSDO lock behavior, or Allan deviation.

SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench
validation and protocol bring-up, not final PIO/DMA metrology.

## Firmware Metadata

SW1 firmware emits `STS` rows during boot for protocol/schema version, firmware
name, firmware version, optional firmware git commit, board target, Arduino core,
bring-up mode, capture mode, nominal capture clock, nominal PPS/TCXO frequencies,
pin mapping, and relevant compile-time feature flags.

`OTIS_FIRMWARE_GIT_COMMIT` defaults to `unknown`. Scripted builds may pass a
git hash with a compiler define, but Arduino IDE builds do not require git
integration.

## Capture Lifecycle

Use explicit markers around captured runs:

```bash
touch capture_in_progress.flag
# capture raw serial and parse artifacts
python3 -m host.otis_tools.validate_run <run_dir>
python3 -m host.otis_tools.report_run <run_dir> > <run_dir>/reports/summary.md
rm capture_in_progress.flag
touch COMPLETE
```

`capture_in_progress.flag` means the run may be partial. `COMPLETE` means the
operator has finished capture, parsing, validation, and report generation.
Missing `COMPLETE` is a warning for non-template runs, not a fatal validation
error.

## Manifest Expectations

SW1 manifests should retain backward-compatible fields and include:

- `h_phase`
- `stage`
- `capture_mode`
- `board`
- `firmware_git_commit`
- `host_git_commit`
- `firmware_version`
- `host_tool_version`
- `expected_artifacts`
- `nominal_frequencies_hz`
- `pin_mapping`
- `known_limitations`

Expected artifacts listed in the manifest should be present before committing a
representative run. Optional artifacts may be marked with `"optional": true`.

## Validation And Reporting

Run both tools before treating a run as a fixture:

```bash
python3 -m host.otis_tools.validate_run <run_dir>
python3 -m host.otis_tools.report_run <run_dir> --output <run_dir>/reports/summary.md
```

The validator and report call out missing or malformed manifests, missing
artifacts, empty CSVs, unknown CSV headers, malformed rows, non-monotonic
timestamps, sequence gaps, suspect PPS intervals, count sanity issues, increasing
drop/error counters, in-progress captures, and missing completion markers.

Commit representative data only when the run has clear provenance, parseable
artifacts, a generated report, no unexplained validation errors, and a `COMPLETE`
marker.

Move to SW1.5a PIO after H0/SW1 representative GPS PPS and TCXO observe runs
validate cleanly and A0 reporting can summarize them repeatably.
