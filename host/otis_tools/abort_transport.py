"""Independent fail-static abort transport for current OTIS operations.

The abort path is deliberately separate from capture_device's serial-command
FIFO.  It accepts only the token ``ABORT`` and never writes a DAC command or an
automatic restore.  Operational supervisors import :class:`AbortFifo`; this module
also provides a no-write probe used before the first DAC command.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import errno
import json
import os
import stat
import tempfile
import time


ABORT_TOKEN = "ABORT"
TOOL_VERSION = "cx317_independent_abort_fifo_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class AbortFifo:
    """Non-blocking, fail-closed reader for one independent abort token."""

    def __init__(self, path: Path, max_line_bytes: int = 32) -> None:
        self.path = path
        self.max_line_bytes = max_line_bytes
        self.fd: int | None = None
        self.buffer = bytearray()

    def __enter__(self) -> "AbortFifo":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if not stat.S_ISFIFO(self.path.stat().st_mode):
                raise ValueError(f"abort path exists but is not a FIFO: {self.path}")
        else:
            os.mkfifo(self.path, 0o600)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _require_live_path(self) -> None:
        if self.fd is None:
            raise RuntimeError("abort FIFO reader is not open")
        try:
            mode = self.path.stat().st_mode
        except FileNotFoundError as exc:
            raise RuntimeError("independent abort FIFO path was lost") from exc
        if not stat.S_ISFIFO(mode):
            raise RuntimeError("independent abort path is no longer a FIFO")

    def poll(self) -> bool:
        self._require_live_path()
        assert self.fd is not None
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        if chunks:
            self.buffer.extend(b"".join(chunks))
        if len(self.buffer) > self.max_line_bytes:
            self.buffer.clear()
            raise ValueError("abort FIFO input exceeded the maximum line length")

        requested = False
        while True:
            try:
                newline = self.buffer.index(0x0A)
            except ValueError:
                break
            raw = bytes(self.buffer[:newline]).rstrip(b"\r")
            del self.buffer[: newline + 1]
            try:
                token = raw.decode("ascii").strip().upper()
            except UnicodeDecodeError as exc:
                raise ValueError("abort FIFO accepts ASCII ABORT only") from exc
            if token != ABORT_TOKEN:
                raise ValueError("abort FIFO accepts ABORT only")
            requested = True
        return requested


def send_abort(path: Path) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno == errno.ENXIO:
            raise RuntimeError(f"no independent abort reader is active for {path}") from exc
        raise
    try:
        os.write(fd, b"ABORT\n")
    finally:
        os.close(fd)


def probe_abort_path(path: Path, result_path: Path, timeout_s: float) -> Path:
    if timeout_s <= 0:
        raise ValueError("probe timeout must be positive")
    started_utc = _utc_now()
    started = time.monotonic()
    with AbortFifo(path) as abort:
        deadline = started + timeout_s
        while time.monotonic() < deadline:
            if abort.poll():
                elapsed = time.monotonic() - started
                result = {
                    "schema_version": 1,
                    "tool_version": TOOL_VERSION,
                    "abort_fifo": str(path),
                    "started_at_utc": started_utc,
                    "completed_at_utc": _utc_now(),
                    "probe_timeout_s": timeout_s,
                    "abort_observed": True,
                    "abort_observation_latency_s": elapsed,
                    "serial_commands_sent": 0,
                    "automatic_restore": False,
                    "fail_static": True,
                    "hardware_actuation": False,
                }
                result_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=result_path.parent,
                    prefix=f".{result_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    json.dump(result, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                    temporary = Path(handle.name)
                temporary.replace(result_path)
                return result_path
            time.sleep(0.01)
    raise TimeoutError(f"independent abort probe timed out after {timeout_s} s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe or trigger the independent CX317 fail-static abort FIFO.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    probe = subparsers.add_parser("probe", help="Open the abort reader and wait for one ABORT token without hardware action.")
    probe.add_argument("--fifo", type=Path, required=True)
    probe.add_argument("--result", type=Path, required=True)
    probe.add_argument("--timeout-s", type=float, default=30.0)
    trigger = subparsers.add_parser("send", help="Send one ABORT token to an already-active independent reader.")
    trigger.add_argument("--fifo", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "probe":
            print(probe_abort_path(args.fifo, args.result, args.timeout_s))
        else:
            send_abort(args.fifo)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
