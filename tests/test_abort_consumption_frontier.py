"""Abort observation cost and causality do not depend on capture history size."""
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import capture_device as capture
from host.otis_tools.live_run import _AbortDeliveryObserver
from host.otis_tools.contracts import HEALTH_FIELDS
from test_adaptive_hybrid_status_contract import _snapshot


def _frontier(raw, offset=0):
    identity = raw.stat()
    return {"run_directory": str(raw.parent.parent), "search_offset_bytes": offset,
            "device": identity.st_dev, "inode": identity.st_ino}


def _wire(generation=1):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=HEALTH_FIELDS, lineterminator="\n")
    for sequence, row in enumerate(_snapshot(generation), 1):
        row = {**dict.fromkeys(HEALTH_FIELDS, "0"), **row}
        writer.writerow(row)
    return output.getvalue().encode()


def test_capture_frontier_to_post_abort_snapshot_skips_large_history_and_partial_line(tmp_path, monkeypatch):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    (tmp_path / "reports").mkdir()
    runner = capture.CaptureDeviceRunner(capture.CaptureDeviceConfig("/dev/unused", 115200, tmp_path))
    runner.capture_active = runner.serial_open = True
    sent = []
    monkeypatch.setattr(runner, "_send_command", lambda command, *_args, **_kwargs: sent.append(command))
    fifo = SimpleNamespace(poll=lambda **_: ["ACTIVE ABORT"])
    # A sparse prefix makes any read from byte zero both expensive and invalid.
    origin = 512 * 1024 * 1024
    with raw.open("w+b") as handle:
        handle.seek(origin - 1)
        handle.write(b"\n")
        handle.flush()
        writer = capture.RawEvidenceWriter(handle)
        writer.write_device(b"unrelated partial device line")
        runner._poll_emergency_command(fifo, None, object(), writer)
        assert sent == ["ACTIVE ABORT"]
        state = json.loads((tmp_path / capture.CAPTURE_STATE).read_text())
        assert state["emergency_abort_raw_frontier"]["search_offset_bytes"] == origin
        observer = _AbortDeliveryObserver(tmp_path)
        assert observer.observe(state) is None  # receipt does not prove queued marker delivery
        assert observer.offset == origin
        wire = _wire()
        writer.write_device(b"\n" + wire[:-5])
        assert observer.observe(state) is None  # incomplete complete-generation record
        writer.write_device(wire[-5:])
        health = observer.observe(state)
        assert health[("adaptive_hybrid", "snapshot_generation_complete")] == "1"
        assert observer.offset - origin < observer.READ_BYTES
        previous = observer.offset
        assert observer.observe(state) == health
        assert observer.offset == previous
        # A newer incomplete burst withdraws the old complete observation.
        writer.write_device(_wire(2).split(b"\n", 1)[0] + b"\n")
        assert observer.observe(state) is None


def test_complete_snapshot_before_send_marker_is_never_abort_evidence(tmp_path):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_bytes(_wire())
    state = {"emergency_abort_raw_frontier": _frontier(raw)}
    observer = _AbortDeliveryObserver(tmp_path)
    assert observer.observe(state) is None
    with raw.open("ab") as output:
        output.write(b'# OTIS_HOST {"event":"emergency_abort_sent"}\n')
    assert observer.observe(state) is None
    with raw.open("ab") as output:
        output.write(_wire(2))
    assert observer.observe(state)[("adaptive_hybrid", "snapshot_generation_complete")] == "2"


@pytest.mark.parametrize("mutation", ["other_run", "negative", "changed", "truncate", "replace"])
def test_abort_cursor_rejects_unknown_or_changed_raw_frontier(tmp_path, mutation):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_bytes(b"ignored\n")
    frontier = _frontier(raw)
    state = {"emergency_abort_raw_frontier": frontier}
    observer = _AbortDeliveryObserver(tmp_path)
    assert observer.observe(state) is None
    if mutation == "other_run": frontier["run_directory"] = str(tmp_path / "other")
    elif mutation == "negative": frontier["search_offset_bytes"] = -1
    elif mutation == "changed": frontier["search_offset_bytes"] = 1
    elif mutation == "truncate": raw.write_bytes(b"")
    else:
        replacement = raw.with_suffix(".replacement")
        replacement.write_bytes(b"ignored\n")
        replacement.replace(raw)
    with pytest.raises(ValueError):
        observer.observe(state)


def test_each_poll_has_bounded_input_and_oversized_line_is_rejected(tmp_path):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_bytes(b"X" * (_AbortDeliveryObserver.READ_BYTES * 3))
    state = {"emergency_abort_raw_frontier": _frontier(raw)}
    observer = _AbortDeliveryObserver(tmp_path)
    assert observer.observe(state) is None
    assert observer.offset == observer.READ_BYTES
    with pytest.raises(ValueError, match="line exceeds"):
        observer.observe(state)
    assert observer.offset == observer.READ_BYTES * 2


@pytest.mark.parametrize("payload", [b"null", b"[]", b"7", b'{"event":"emergency_abort_sent"}'])
def test_malformed_or_duplicate_send_marker_cannot_replace_retained_evidence(tmp_path, payload):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_bytes(b'# OTIS_HOST {"event":"emergency_abort_sent"}\n# OTIS_HOST ' + payload + b"\n")
    observer = _AbortDeliveryObserver(tmp_path)
    state = {"emergency_abort_raw_frontier": _frontier(raw)}
    with pytest.raises(ValueError):
        observer.observe(state)


def test_newer_incomplete_generation_cannot_be_erased_by_older_complete_snapshot(tmp_path):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_bytes(b'# OTIS_HOST {"event":"emergency_abort_sent"}\n'
                    + _wire(20).split(b"\n", 1)[0] + b"\n" + _wire(19))
    state = {"emergency_abort_raw_frontier": _frontier(raw)}
    observer = _AbortDeliveryObserver(tmp_path)
    assert observer.observe(state) is None
    with raw.open("ab") as handle:
        handle.write(_wire(21))
    assert observer.observe(state)[("adaptive_hybrid", "snapshot_generation_complete")] == "21"


def test_replacement_before_first_observation_cannot_impersonate_capture_file(tmp_path):
    raw = tmp_path / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_bytes(b'# OTIS_HOST {"event":"emergency_abort_sent"}\n' + _wire())
    state = {"emergency_abort_raw_frontier": _frontier(raw)}
    replacement = raw.with_suffix(".replacement")
    replacement.write_bytes(raw.read_bytes())
    replacement.replace(raw)
    with pytest.raises(ValueError, match="capture's raw file"):
        _AbortDeliveryObserver(tmp_path).observe(state)
