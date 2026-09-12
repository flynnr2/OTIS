"""The OTIS host: acquire, inspect, analyse, and preserve instrument evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="otis", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    monitor = commands.add_parser("monitor", help="Read the current capture and experiment state")
    monitor.add_argument("run_dir", type=Path)
    analyse = commands.add_parser("analyse", help="Independently analyse closed evidence")
    analyse.add_argument("run_dir", type=Path)
    analyse.add_argument("--output", type=Path)
    package = commands.add_parser("package", help="Analyse and seal a closed acquisition")
    package.add_argument("run_dir", type=Path)
    package.add_argument("--registry", type=Path)
    verify = commands.add_parser("verify", help="Check a portable package without replay or hardware")
    verify.add_argument("run_dir", type=Path)
    abort = commands.add_parser("abort", help="Explicitly request instrument abort through its serial owner")
    abort.add_argument("run_dir", type=Path)
    spec = commands.add_parser("spec", help="Freeze an inert experiment specification")
    spec.add_argument("firmware_manifest", type=Path)
    spec.add_argument("--purpose", required=True, choices=("inhibited_zero_write", "contingent_72_hour_hybrid_control"))
    spec.add_argument("--output", required=True, type=Path)
    rehearse = commands.add_parser("rehearse", help="Exercise the complete host path with a simulated device")
    rehearse.add_argument("spec", type=Path)
    rehearse.add_argument("--run-dir", required=True, type=Path)
    run = commands.add_parser("run", help="Enter one explicitly authorized physical experiment")
    run.add_argument("spec", type=Path)
    run.add_argument("--rehearsal", required=True, type=Path)
    run.add_argument("--run-dir", required=True, type=Path)
    run.add_argument("--device", required=True)
    run.add_argument("--operator-ref", required=True)
    run.add_argument("--reason", required=True)
    run.add_argument("--flash", action="store_true", help="Upload the frozen firmware once before attachment")
    run.add_argument("--arduino-cli", default="arduino-cli")
    run.add_argument("--rehearsal-package", type=Path, help="Verified rehearsal package at its delivered location")
    run.add_argument("--firmware-manifest", type=Path, help="Verified build manifest at its delivered location")
    args = parser.parse_args(argv)
    if args.command == "monitor":
        from .adaptive_hybrid_monitor import snapshot
        result = snapshot(args.run_dir)
    elif args.command == "analyse":
        from .adaptive_hybrid_analyze import analyze
        path, report = analyze(args.run_dir, output_path=args.output)
        result = {"report": str(path), "status": report["status"], "outcome": report["outcome"]}
    elif args.command == "package":
        from .offline import finish_run
        result = finish_run(args.run_dir, registry_path=args.registry)
    elif args.command == "verify":
        from .evidence_package import validate_package
        package = validate_package(args.run_dir)
        result = {key: package[key] for key in ("package_content_sha256", "capture", "analysis")}
    elif args.command == "abort":
        from .live_run import EMERGENCY_FIFO
        from .serial_commands import send_timestamped_command_to_fifo
        send_timestamped_command_to_fifo(args.run_dir / EMERGENCY_FIFO, "ACTIVE ABORT")
        result = {"abort": "submitted", "delivery": "await capture and firmware evidence"}
    elif args.command == "spec":
        from .run_spec import build_run_spec
        spec = build_run_spec(firmware_manifest_path=args.firmware_manifest, purpose=args.purpose, output_path=args.output)
        result = {"spec": str(spec.path), "sha256": spec.sha256, "hardware_authority": False}
    elif args.command == "rehearse":
        from tools.rehearse_host import rehearse
        result = rehearse(spec_path=args.spec, run_dir=args.run_dir)
    else:
        from .bench_entry import start
        result = start(spec_path=args.spec, rehearsal_path=args.rehearsal, run_dir=args.run_dir,
                       device=args.device, operator_instruction_ref=args.operator_ref,
                       attempt_reason=args.reason, flash=args.flash, arduino_cli=args.arduino_cli,
                       firmware_manifest_path=args.firmware_manifest,
                       rehearsal_package_path=args.rehearsal_package)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
