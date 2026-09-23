"""The OTIS recording host."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="otis", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Attach passively and record the instrument stream")
    record.add_argument("--device", required=True)
    record.add_argument("--run-dir", required=True, type=Path)
    record.add_argument("--baud", type=int, default=115200)
    record.add_argument("--duration-s", type=float, help="Close recording after this interval; instrument keeps operating")
    record.add_argument("--rotate-bytes", type=int, default=128 * 1024 * 1024)
    status = commands.add_parser("status", help="Read the independent local recorder and instrument snapshot")
    status.add_argument("run_dir", type=Path)
    monitor = commands.add_parser("monitor", help="Write independent local material-event and hourly observation reports")
    monitor.add_argument("run_dir", type=Path)
    monitor.add_argument("--poll-s", type=float, default=5.0)
    mode = commands.add_parser("mode", help="Submit one explicit mode request through the recorder")
    mode.add_argument("run_dir", type=Path)
    mode.add_argument("--session", type=int, required=True, help="Expected instrument session from status")
    mode.add_argument("--mode", type=int, required=True, choices=(0, 1, 2, 3))
    mode.add_argument("--code", type=int, default=0)
    mode.add_argument("--dwell-s", type=int, default=0,
                      help="Firmware-owned timed AUTO hold or characterization dwell")
    verify = commands.add_parser("verify", help="Check raw segment hashes and byte counts of a closed recording")
    verify.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "record":
        from .instrument_recorder import InstrumentRecorder, RecorderConfig
        result = InstrumentRecorder(RecorderConfig(
            device=args.device, run_dir=args.run_dir, baud=args.baud,
            duration_s=args.duration_s, rotate_bytes=args.rotate_bytes,
        )).run()
    elif args.command == "status":
        from .instrument_recorder import read_recorder_status
        result = read_recorder_status(args.run_dir)
    elif args.command == "monitor":
        from .instrument_monitor import RecordingMonitor
        result = RecordingMonitor(args.run_dir, poll_interval_s=args.poll_s).run()
    elif args.command == "mode":
        from .instrument_recorder import request
        result = request(args.run_dir, {
            "operation": "mode", "expected_session": args.session,
            "mode": args.mode, "code": args.code, "dwell_s": args.dwell_s,
        })
    elif args.command == "verify":
        from .instrument_recorder import verify_recording
        result = verify_recording(args.run_dir)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    if "error" in result or args.command == "record" and result.get("recording_error"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
