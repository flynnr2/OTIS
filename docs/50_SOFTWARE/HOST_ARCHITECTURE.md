# OTIS host architecture

Firmware is the operating instrument. It acquires D14/D8 timing evidence,
qualifies the reference, selects the operating mode, makes controller decisions
and owns the DAC. A host may attach to observe and record. Attachment never
starts a campaign, resets the board, sets a DAC code or grants steering
authority. Firmware operation continues when the host closes or fails.

## One serial owner

`python3 -m host.otis_tools record --device DEVICE --run-dir DIRECTORY` runs
one recorder process. It constructs the serial port closed, sets DTR high for
TinyUSB CDC carrier and RTS low, then opens it with an exclusive descriptor
and bounded read/write timeouts. The 1200 baud reset rate is rejected. In the
pinned RP2040 core, serial output requires DTR and reset is triggered only by
1200 baud with DTR low. The board's actual behavior remains a physical
integration check. The process reads up to 4 KiB at a time and appends every
received byte to numbered `serial-*.raw` files. Unknown, malformed and partial
records stay in raw evidence. Parser memory is bounded; derived status may be
unavailable after a malformed record without altering the bytes.

The recorder rotates raw files at a configured approximate size boundary. It
closes and hashes each segment and writes `recording_manifest.json` on exit.
An exclusive `recorder.in_progress` reservation marks an active or interrupted
directory. A new attachment uses a new directory and begins a new evidence
segment; it never replays a past command. The recorder writes directly and has
no unbounded in-memory evidence queue. A disk/write error ends recording and
appears in `recorder_state.json` where storage remains writable. Operating
system storage calls do not have a hard latency bound, so recorder availability
and completeness are host evidence claims, not firmware safety premises.

`--duration-s` closes only the recorder. It sends no mode command. The USB
connection is an evidence and explicit command interface, never an internal
actuation dispatch or lease. Host process death or disk failure cannot by
itself change firmware mode.

## Status and explicit commands

`python3 -m host.otis_tools status DIRECTORY` reads the independent local
snapshot. It reports host recording and serial state, bytes, line counts,
observed record counts, last record age, status age, and the latest complete
instrument status. Counts describe records observed by this host, not records
the instrument generated. Missing, malformed or late status is unknown, never
inferred healthy from process existence. The status command recalculates
publication and instrument age from the saved monotonic coordinate, so a dead
writer's last fresh flag cannot remain fresh.

`python3 -m host.otis_tools monitor DIRECTORY` is a separate read-only local
process. It samples the atomic recorder state every five seconds, derives
D14/D8 capture freshness from advancing REF, SNP and CNT counts, and writes
material changes to rotated `monitor-events-*.jsonl` files. Mode, state,
qualification holds, faults, applications, responses, commands, record loss,
storage failure and stale status are material. Routine raw count and decision
increments appear in hourly summaries instead of producing an event per PPS.
The monitor stops after a closed recording manifest appears. Each event is
flushed and synced; failed local delivery is reported on stderr and, if storage
allows, in `monitor_delivery_failure.json`. An external notification channel
is not configured, so these reports do not promise remote alerts.

The recorder reduces only complete `adaptive_hybrid` STS cohorts bearing
`OTIS_INSTRUMENT_STATUS_V2`, bounded by matching
`snapshot_generation_begin` and `snapshot_generation_complete`. An incomplete
generation cannot update mode-command identity. Instrument session and command
sequence are read from this cohort. A changed session starts fresh command
identity. The recorder retains new ICM receipts as raw evidence and publishes
the latest understood receipt and pending request without treating host
submission as firmware acceptance or DAC application.

`python3 -m host.otis_tools mode DIRECTORY --session SESSION --mode MODE`
submits one operator-selected mode request through a local Unix socket to the
existing serial owner. `MODE` is 0 AUTO_DISCIPLINE, 1 OBSERVE_HOLD, 2
FIXED_CODE or 3 CHARACTERIZE. FIXED_CODE also requires `--code`; CHARACTERIZE
requires its bounded code and `--dwell-s`. AUTO may carry `--dwell-s` up to
604800 for a firmware-owned timed transition to OBSERVE_HOLD; zero means
indefinite AUTO. The caller supplies the expected
session from status. The owner requires a fresh complete matching cohort,
allocates the next sequence and emits
`ACTIVE MODE <session> <sequence> <mode> <code> <dwell_s>` with decimal
arguments. Its immediate result is `written_unconfirmed`; firmware ICM and
later status establish acceptance and completion. The owner does not resend
an ambiguous write. A pending request prevents another normal request; an
explicit OBSERVE_HOLD can supersede it through firmware's reserved path.

The local socket is addressed by a hash of the absolute recording directory
under the system temporary directory, avoiding the short Unix socket path
limit on macOS. It is accessible only to the local user. Clients never open a
second serial descriptor. There is no automatic arm, abort, lease, correction
acknowledgement or host scientific decision worker.

## Evidence and verification boundary

The raw segment hashes bind what this recorder retained. They do not assert
complete coverage of a period before attachment, while USB was obstructed,
or across a firmware reset. Firmware status includes its own bounded delivery
loss and current state summaries; these do not reconstruct discarded history.
The historical campaign analyser and package format cannot be applied to a
new instrument recording. Current numeric replay helpers remain available
for an instrument V2 offline reader built against its new schema.

The PTY recorder tests exercise byte retention, complete-status discovery,
session-bound command submission, storage failure, rotation and duration
closure. A simulated serial endpoint cannot establish actual Nano RP2040
serial-open reset behavior, firmware cross-core propagation or physical DAC
behavior. Those require the exact-profile firmware integration checks and a
separately authorized short bench gate.
