from __future__ import annotations

from dataclasses import dataclass
import argparse
import errno
import os
from pathlib import Path
import re
import stat
import time


KNOWN_SWEEP_PROFILES = frozenset(
    {
        "CENTER_ONLY",
        "TINY_PLUS_MINUS_1",
        "TINY_PLUS_MINUS_2",
        "SLOPE_CENTER_EDGE_300S",
        "SLOPE_REPEAT_300S",
    }
)
KNOWN_PSEUDO_PPS_PROFILES = frozenset(
    {
        "CLEAN_NOMINAL",
        "CLEAN_SOAK_10M",
        "ONE_SHORT",
        "ONE_LONG",
        "ONE_OMIT",
        "DOUBLE",
        "BOUNCE",
        "NARROW_GLITCH",
        "POSITIVE_PHASE_STEP",
        "NEGATIVE_PHASE_STEP",
        "SUSTAINED_POSITIVE_OFFSET",
        "SUSTAINED_NEGATIVE_OFFSET",
        "REPEATED_OMISSIONS",
        "MIXED_MALFORMED",
        "RETURN_CLEAN",
        "COMPOSITE",
    }
)
SIMPLE_COMMANDS = frozenset(
    {
        "HELP",
        "CONFIG?",
        "DUALCORE?",
        "DUALCORE INVALIDATE_GNSS",
        "DUALCORE RECOVER",
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
        "PPSGEN?",
        "PPSGEN PROFILES?",
        "PPSGEN START",
        "PPSGEN STOP",
        "ACTIVE?",
        "ACTIVE ABORT",
    }
)
TIMESTAMPED_COMMAND_PREFIX = "OTISQ1"


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

    if command.startswith("PPSGEN ARM "):
        profile = command[len("PPSGEN ARM ") :]
        if profile not in KNOWN_PSEUDO_PPS_PROFILES:
            raise ValueError(
                f"PPSGEN ARM profile must be one of {sorted(KNOWN_PSEUDO_PPS_PROFILES)}"
            )
        return SerialCommand(f"PPSGEN ARM {profile}")

    if command.startswith("ACTIVE LEASE "):
        value = command[len("ACTIVE LEASE ") :]
        if not re.fullmatch(r"[1-9][0-9]*", value) or int(value, 10) > 0xFFFFFFFF:
            raise ValueError("ACTIVE LEASE requires one non-zero uint32 sequence")
        return SerialCommand(f"ACTIVE LEASE {int(value, 10)}")

    if command.startswith("ACTIVE ARM "):
        fields = command[len("ACTIVE ARM ") :].split()
        if len(fields) != 3 or any(
            not re.fullmatch(r"[1-9][0-9]*", field) or int(field, 10) > 0xFFFFFFFF
            for field in fields
        ):
            raise ValueError("ACTIVE ARM requires three non-zero uint32 values")
        return SerialCommand("ACTIVE ARM " + " ".join(str(int(field, 10)) for field in fields))

    if command.startswith("ACTIVE EVIDENCE "):
        fields = command[len("ACTIVE EVIDENCE ") :].split()
        if len(fields) != 2 or any(
            not re.fullmatch(r"[1-9][0-9]*", field) or int(field, 10) > 0xFFFFFFFF
            for field in fields
        ):
            raise ValueError(
                "ACTIVE EVIDENCE requires non-zero request and phase sequences"
            )
        if int(fields[1], 10) not in {1, 2, 3, 4}:
            raise ValueError(
                "ACTIVE EVIDENCE phase sequence must be 1, 2, 3, or 4"
            )
        return SerialCommand(
            f"ACTIVE EVIDENCE {int(fields[0], 10)} {int(fields[1], 10)}"
        )

    raise ValueError("unknown or unsupported command")


def timestamped_command_line(
    command: str, *, created_monotonic_ns: int | None = None
) -> str:
    parsed = parse_serial_command(command)
    created = (
        time.monotonic_ns()
        if created_monotonic_ns is None
        else created_monotonic_ns
    )
    if created <= 0:
        raise ValueError("created_monotonic_ns must be positive")
    return f"{TIMESTAMPED_COMMAND_PREFIX} {created} {parsed.normalized}"


def parse_timestamped_command_line(
    line: str,
) -> tuple[SerialCommand, int | None]:
    normalized = " ".join(line.strip().split())
    prefix = TIMESTAMPED_COMMAND_PREFIX + " "
    if not normalized.startswith(prefix):
        return parse_serial_command(normalized), None
    fields = normalized.split(" ", 2)
    if len(fields) != 3 or not fields[1].isdigit():
        raise ValueError("invalid OTISQ1 command envelope")
    created = int(fields[1], 10)
    if created <= 0:
        raise ValueError("OTISQ1 monotonic timestamp must be positive")
    return parse_serial_command(fields[2]), created


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
        self.close()

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def poll(self, *, max_lines: int | None = None) -> list[str]:
        if self.fd is None:
            return []
        if max_lines is not None and max_lines <= 0:
            raise ValueError("max_lines must be positive when provided")
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
        if not self.buffer:
            return []

        lines: list[str] = []
        while True:
            if max_lines is not None and len(lines) >= max_lines:
                break
            try:
                newline_index = self.buffer.index(0x0A)
            except ValueError:
                break
            if newline_index > self.max_line_bytes:
                del self.buffer[: newline_index + 1]
                lines.append("")
                continue
            line = bytes(self.buffer[:newline_index]).rstrip(b"\r")
            del self.buffer[: newline_index + 1]
            lines.append(line.decode("utf-8", errors="replace"))
        if (
            (max_lines is None or len(lines) < max_lines)
            and b"\n" not in self.buffer
            and len(self.buffer) > self.max_line_bytes
        ):
            self.buffer.clear()
            lines.append("")
        return lines


def _write_fifo_payload(fifo: Path, payload: bytes) -> int:
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno == errno.ENXIO:
            raise SystemExit(f"no capture_device command reader is active for {fifo}") from exc
        raise
    try:
        bytes_written = os.write(fd, payload)
        if bytes_written != len(payload):
            raise OSError(
                f"short FIFO write: expected {len(payload)}, wrote {bytes_written}"
            )
    finally:
        os.close(fd)
    return 0


def send_command_to_fifo(fifo: Path, command: str) -> int:
    parsed = parse_serial_command(command)
    payload = (parsed.normalized + "\n").encode("ascii")
    return _write_fifo_payload(fifo, payload)


def send_timestamped_command_to_fifo(
    fifo: Path,
    command: str,
    *,
    created_monotonic_ns: int | None = None,
) -> int:
    line = timestamped_command_line(
        command, created_monotonic_ns=created_monotonic_ns
    )
    return _write_fifo_payload(fifo, (line + "\n").encode("ascii"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one validated OTIS command to a capture_device command FIFO.")
    parser.add_argument("--fifo", required=True, type=Path, help="Run-local command FIFO owned by capture_device.")
    parser.add_argument("command", help="Atomic OTIS command to send, for example 'DAC MID' or 'SWEEP START'.")
    args = parser.parse_args()
    raise SystemExit(send_command_to_fifo(args.fifo, args.command))


if __name__ == "__main__":
    main()
