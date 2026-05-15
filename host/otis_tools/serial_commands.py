from __future__ import annotations

from dataclasses import dataclass
import argparse
import errno
import os
from pathlib import Path
import re
import stat


KNOWN_SWEEP_PROFILES = frozenset({"CENTER_ONLY", "TINY_PLUS_MINUS_1", "TINY_PLUS_MINUS_2"})
SIMPLE_COMMANDS = frozenset(
    {
        "HELP",
        "DAC?",
        "DAC LIMITS?",
        "DAC MID",
        "DAC ZERO",
        "FC0?",
        "SWEEP?",
        "SWEEP START",
        "SWEEP STOP",
        "SWEEP STEP",
        "SWEEP CLEAR",
    }
)


@dataclass(frozen=True)
class SerialCommand:
    normalized: str


def _collapse_spaces(text: str) -> str:
    return " ".join(text.strip().split())


def _normalize_code(text: str) -> str | None:
    if not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", text):
        return None
    value = int(text, 0)
    if not 0 <= value <= 0xFFFF:
        return None
    if text.lower().startswith("0x"):
        return f"0x{value:04X}"
    return str(value)


def parse_serial_command(text: str) -> SerialCommand:
    command = _collapse_spaces(text).upper()
    if not command:
        raise ValueError("empty command")
    if command in SIMPLE_COMMANDS:
        return SerialCommand(command)

    if command.startswith("DAC SET "):
        code = _normalize_code(command[len("DAC SET ") :])
        if code is None:
            raise ValueError("DAC SET requires a 16-bit decimal or hex code")
        return SerialCommand(f"DAC SET {code}")

    if command.startswith("SWEEP LOAD "):
        profile = command[len("SWEEP LOAD ") :]
        if profile not in KNOWN_SWEEP_PROFILES:
            raise ValueError(f"SWEEP LOAD profile must be one of {sorted(KNOWN_SWEEP_PROFILES)}")
        return SerialCommand(f"SWEEP LOAD {profile}")

    if command.startswith("SWEEP ADD"):
        raise ValueError("SWEEP ADD is intentionally unsupported by host command ingress")

    raise ValueError("unknown or unsupported command")


class CommandFifo:
    def __init__(self, path: Path, max_line_bytes: int = 256) -> None:
        self.path = path
        self.max_line_bytes = max_line_bytes
        self.fd: int | None = None
        self.buffer = bytearray()

    def __enter__(self) -> CommandFifo:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            mode = self.path.stat().st_mode
            if not stat.S_ISFIFO(mode):
                raise ValueError(f"command path exists but is not a FIFO: {self.path}")
        else:
            os.mkfifo(self.path, 0o600)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def poll(self) -> list[str]:
        if self.fd is None:
            return []
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        if not chunks:
            return []

        self.buffer.extend(b"".join(chunks))
        lines: list[str] = []
        while True:
            try:
                newline_index = self.buffer.index(0x0A)
            except ValueError:
                break
            line = bytes(self.buffer[:newline_index]).rstrip(b"\r")
            del self.buffer[: newline_index + 1]
            lines.append(line.decode("utf-8", errors="replace"))
        if len(self.buffer) > self.max_line_bytes:
            self.buffer.clear()
            lines.append("")
        return lines


def send_command_to_fifo(fifo: Path, command: str) -> int:
    parsed = parse_serial_command(command)
    payload = (parsed.normalized + "\n").encode("ascii")
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno == errno.ENXIO:
            raise SystemExit(f"no capture_device command reader is active for {fifo}") from exc
        raise
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one validated OTIS command to a capture_device command FIFO.")
    parser.add_argument("--fifo", required=True, type=Path, help="Run-local command FIFO owned by capture_device.")
    parser.add_argument("command", help="Atomic OTIS command to send, for example 'DAC MID' or 'SWEEP START'.")
    args = parser.parse_args()
    raise SystemExit(send_command_to_fifo(args.fifo, args.command))


if __name__ == "__main__":
    main()
