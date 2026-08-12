from __future__ import annotations

from pathlib import Path
import json
import threading
import time

import pytest

from host.otis_tools.abort_transport import AbortFifo, probe_abort_path, send_abort


def test_independent_abort_fifo_accepts_only_abort(tmp_path: Path) -> None:
    fifo = tmp_path / "abort.fifo"
    with AbortFifo(fifo) as reader:
        send_abort(fifo)
        assert reader.poll() is True
        assert reader.poll() is False


def test_abort_fifo_fails_closed_on_unknown_input(tmp_path: Path) -> None:
    fifo = tmp_path / "abort.fifo"
    with AbortFifo(fifo) as reader:
        fd = __import__("os").open(fifo, __import__("os").O_WRONLY | __import__("os").O_NONBLOCK)
        try:
            __import__("os").write(fd, b"CONTINUE\n")
        finally:
            __import__("os").close(fd)
        with pytest.raises(ValueError, match="ABORT only"):
            reader.poll()


def test_probe_records_fail_static_no_write_result(tmp_path: Path) -> None:
    fifo = tmp_path / "abort.fifo"
    result_path = tmp_path / "probe.json"
    errors: list[BaseException] = []

    def run_probe() -> None:
        try:
            probe_abort_path(fifo, result_path, 2.0)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread = threading.Thread(target=run_probe)
    thread.start()
    deadline = time.monotonic() + 1.0
    while not fifo.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    while True:
        try:
            send_abort(fifo)
            break
        except RuntimeError as exc:
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "independent abort reader did not become active"
                ) from exc
            time.sleep(0.005)
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert errors == []
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["abort_observed"] is True
    assert result["serial_commands_sent"] == 0
    assert result["automatic_restore"] is False
    assert result["fail_static"] is True
    assert result["hardware_actuation"] is False


def test_abort_reader_detects_lost_path(tmp_path: Path) -> None:
    fifo = tmp_path / "abort.fifo"
    with AbortFifo(fifo) as reader:
        fifo.unlink()
        with pytest.raises(RuntimeError, match="path was lost"):
            reader.poll()
