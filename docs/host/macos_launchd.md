# macOS launchd Host Ingest

This note covers running `host.otis_tools.capture_device` as the single owner of
the OTIS USB serial device on a headless, AC-powered MacBook Pro A1707.

## Ownership Rule

Only the ingest daemon opens `/dev/cu.usbmodem*`.

Validation, reporting, replay, and ad-hoc analysis must read files emitted by
the daemon:

```text
USB serial device
  -> capture_device daemon
  -> raw/serial.log
  -> csv/*.csv
  -> validate_run / report_run
```

Do not run `screen`, Arduino Serial Monitor, `cat`, or another capture tool
against the same serial device while the daemon is active. Multiple readers make
the run non-forensic.

## Run Command

Use an explicit device path for unattended service operation:

```bash
cd /Users/richardflynn/Documents/GitHub/OTIS
python3 -m host.otis_tools.capture_device \
  --device /dev/cu.usbmodem101 \
  --baud 115200 \
  --run-dir runs/2026-05-13_h0_pps_tcxo_001
```

`--auto-detect` is available only for bench use when exactly one
`/dev/cu.usbmodem*` device exists. A launchd service should use a fixed device
path or a wrapper that chooses one deterministically and logs the choice.

## Example plist

Save as `~/Library/LaunchAgents/org.otis.capture-device.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>org.otis.capture-device</string>

  <key>WorkingDirectory</key>
  <string>/Users/richardflynn/Documents/GitHub/OTIS</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>host.otis_tools.capture_device</string>
    <string>--device</string>
    <string>/dev/cu.usbmodem101</string>
    <string>--baud</string>
    <string>115200</string>
    <string>--run-dir</string>
    <string>/Users/richardflynn/Documents/GitHub/OTIS/runs/2026-05-13_h0_pps_tcxo_001</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/Users/richardflynn/Documents/GitHub/OTIS/runs/2026-05-13_h0_pps_tcxo_001/reports/capture_device.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/richardflynn/Documents/GitHub/OTIS/runs/2026-05-13_h0_pps_tcxo_001/reports/capture_device.stderr.log</string>

  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
```

Load and inspect it over SSH:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.otis.capture-device.plist
launchctl print gui/$(id -u)/org.otis.capture-device
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/org.otis.capture-device.plist
```

## Logging

The daemon writes:

- append-only raw serial bytes plus explicit host markers to `raw/serial.log`;
- parsed CSV rows to `csv/raw_events.csv`, `csv/count_observations.csv`, and
  `csv/health.csv`;
- human-readable structured process logs to launchd stdout/stderr paths.

Keep launchd stdout/stderr under the run `reports/` directory so service
restarts, parser warnings, reconnects, byte counts, malformed UTF-8, and clean
shutdowns remain attached to the run.

## Headless Operation

For lid-closed operation, keep the A1707 on AC power and verify the machine does
not sleep during capture. Recommended checks:

```bash
pmset -g
pmset -g assertions
```

Use `caffeinate` or a persistent `pmset` policy appropriate for the dedicated
host. A simple SSH-managed wrapper can run:

```bash
caffeinate -dimsu python3 -m host.otis_tools.capture_device ...
```

Do not rely on terminal sessions staying open. launchd should own the daemon,
and the daemon should own only the serial device.

## Recovery Semantics

USB disconnects and RP2040 resets are expected failure modes. The daemon keeps
the raw log open in append mode, drops any incomplete line at disconnect with an
explicit marker, backs off before reconnecting, and continues writing to the
same run. Existing raw logs are never truncated.
