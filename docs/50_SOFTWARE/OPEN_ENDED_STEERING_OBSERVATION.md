# Open-ended active steering observation — 2 October 2026

The operator requested continued active steering data gathering and reports a
bench-Mac reboot after the last finite test. Use the exact firmware that passed
the 72-hour observation. Discover the powered rig rather than assuming the old
session, DAC code or mode survived the reboot. USB power loss may have restarted
firmware into AUTO; retained power may have left it in the prior timed HOLD.

This is an engineering observation with no scheduled actuator endpoint or
scientific pass/fail duration. Firmware remains the only steering owner, inside
`0xA800..0xAB00`, with unchanged policy, capture topology and qualification.
Record qualified frequency/relative-phase estimates, decisions, applications,
response classifications, reference/metadata holds, raw sequences and delivered
environmental observations for later analysis. Do not deliberately dither the
DAC, sweep it, alter acceptance tolerances, repair firmware or change wiring
during this observation. D10 remains optional external-event evidence.

## Entry and local supervision

Use one checksummed bundle containing this procedure, current host source,
the plan template, entry tool, exact firmware identities and verification.
The firmware input closure is unchanged from the physical 72-hour test; this
handoff requests no upload, reset or rebuild. Close a stale terminal after the
Mac reboot and check for other serial owners before discovery. Never replace
an active recording or take over an unrelated transaction.

Run the supplied entry tool once. It retains a 30-second passive discovery in a
new local `runs/` workspace, closes that discovery recorder, and binds a frozen
plan to its observed session, build and policy. The deliberate gap before the
new acquisition is unobserved; neither attachment reconstructs pre-attachment
history. The detached coordinator independently rechecks advancing REF/SNP/CNT,
fresh complete status, known in-envelope code, no fault and no unresolved write.

Fresh indefinite AUTO with no operating deadline is observed without a mode
command. Fresh HOLD admits one AUTO command with dwell zero; exact accepted ICM
and later matching completed status must prove indefinite AUTO and deadline zero
within the fixed 60-second command deadline. No AUTO retry, deadline renewal or
takeover of finite AUTO, fixed-code or characterization is authorized.
`written_unconfirmed`, a process identifier or an old status is insufficient.

The user authorizes durable local unattended supervision for this requested
open-ended observation. The coordinator, sole recorder and independent read-only
monitor survive invoking-terminal loss and require no model/API budget. Status
and capture progress are checked every second. Local files retain transitions,
hourly summaries, stale evidence and unresolved review findings. A monitor exit
is retained independently; coordinator evidence checks and recording continue.
The Mac prevents idle sleep for this process, without changing global settings.
Keep it connected to power and leave the lid open. This arrangement does not
survive host reboot, power loss, disk failure or destruction of the coordinator;
firmware can continue independently. A later host restart requires fresh discovery
and a new recording, with an explicit evidence gap, never blind command replay.

Known reference/metadata holds follow firmware's existing causal recovery rules.
Freeze the existing one-shot review policy: a demonstrated unknown decision-bearing
contradiction may submit one HOLD through fresh exact identity, retaining any
pending write. It never auto-resumes AUTO, resets, flashes, aborts or tears down
capture. Output loss or stale status alone is a coverage finding, without HOLD
authority. A fault-inhibited instrument remains a retained review case.

## Storage, observation and ending

Raw segments rotate at approximately 128 MiB; rotation never stops the serial
owner. The prior run retained about 305 MB/day of raw bytes. Reserve at least
5 GiB, preferably substantially more for weeks of recording and packaging.
Storage below the frozen reserve produces a retained warning, not automatic
HOLD or teardown. No automatic deletion or retention cap exists. Check actual
disk use and local status at least daily; local logs are the notification
destination and no remote alerts are promised.

From the frozen bundle's source directory, with the same interpreter:

```sh
python -m host.otis_tools.unattended status /absolute/local/runs/workspace/acquisition
python -m host.otis_tools.unattended end-recording /absolute/local/runs/workspace/acquisition
```

`end-recording` is explicit operator authority to close evidence. It records a
plan-bound request, and the coordinator asks its sole recorder to drain to a
complete row/status cohort within five seconds, then close and retain the actual
boundary result. This operation sends no serial command, requires no static
actuator endpoint and works with stale status or a pending application. It does
not establish that an in-flight write or response completed after the cutoff.
Retain incomplete joins and cutoff-censored evidence for review. A malformed or
mismatched request is retained as a review finding; it cannot close recording,
change instrument mode or terminate supervision. Offline finalization also
checks the request against the frozen plan.

The coordinator waits for recorder/monitor closure, verifies raw bytes, runs the
epoch-aware offline analyzer and creates a checksummed ZIP in
`~/Documents/OTIS_DATA/open-ended-steering-results/`. Confirm local ZIP identity
separately from arrival on the development Mac. If packaging fails, preserve the
closed recording and replay `unattended finalize` without new serial I/O.
Coordinator logs and chronology are frozen at closure so later launcher output
cannot change the identity of repeated offline packaging.

To stop steering as well, explicitly request OBSERVE_HOLD through the same
recorder, using its freshly observed session, and verify exact ICM/completed
status and write resolution before ending recording. Such a request becomes an
operator transition retained by the observer as a review case; it is not an
automatic timed endpoint or scientific failure. Do not issue it just to collect
data or obtain an archive.

## Evidence limits and verification

This continues data gathering with the existing image. The known clustered
reference qualification losses and optional ENV drops remain explicit; this
exercise does not repair them, establish uninterrupted qualified coverage or
qualify indefinite reliability. Count operational duration, qualified coverage,
steering activity and evidence gaps separately. An automatic package describes
retained evidence and operational outcomes, not scientific acceptance.

The real detached host CLI, single recorder, monitor, mode socket, terminal
detachment, Mac sleep inhibition, recording-only closure, analyzer and verified
ZIP are rehearsed over a synthetic PTY. Exercise HOLD-to-AUTO and existing
boot-AUTO entry, unanswered review with monitor loss, continued capture and
closure with stale status/pending write. The synthetic instrument and modem
adapter do not establish real USB power/reset behavior, RP2040 cross-core timing,
physical DAC response or D14/D8 metrology; reuse only the exact prior firmware's
physical claims, and retain the fresh bench entry observation.

## Repository integration — 6 October 2026

The observation host path and reviewed September evidence are retained in
the normal source repository. A repository update does not replace the source
of an already-running frozen recorder, coordinator or monitor. Preserve that
process topology and the current acquisition until an explicit operational
transition is requested. The separate alternation-policy update changes the next
firmware image; this host integration does not clear the current controller hold
or deploy that image. Historical evidence retains its original source, analysis
identity and acceptance contract.

Integration verification: 469 tests passed, with one default-installation-path
CDC check skipped. Its four assertions also passed against the verified isolated
RP2040 core 6.1.0. The detached PTY rehearsal exercised actual entry, recorder,
monitor, mode request, continued capture, recording-only closure, analysis and
verified packaging. Invalid cutoff tests retain supervision and reject both live
closure and offline endpoint attribution. Lint and Markdown table alignment
checks passed. The exact 154-file firmware input inventory and configuration
match the previously built alternation-policy image, so this host-only integration
requires no firmware rebuild or additional physical acquisition. Deploying the
revised steering policy remains a separate physical operation.
