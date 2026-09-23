"""The ordinary host CLI exposes recording and explicit mode requests only."""

import json

import pytest

from host.otis_tools.__main__ import main


def test_record_cli_forwards_capture_limits_without_opening_serial(monkeypatch, tmp_path, capsys):
    from host.otis_tools import instrument_recorder

    observed = []

    class Recorder:
        def __init__(self, config):
            observed.append(config)

        def run(self):
            return {"recording": "closed"}

    monkeypatch.setattr(instrument_recorder, "InstrumentRecorder", Recorder)
    assert main([
        "record", "--device", "/dev/not-opened", "--run-dir", str(tmp_path),
        "--duration-s", "12.5", "--rotate-bytes", "4096",
    ]) == 0
    assert observed[0].device == "/dev/not-opened"
    assert observed[0].run_dir == tmp_path
    assert observed[0].duration_s == 12.5
    assert observed[0].rotate_bytes == 4096
    assert json.loads(capsys.readouterr().out) == {"recording": "closed"}


def test_mode_cli_routes_exact_boot_session_and_request_without_serial_ownership(monkeypatch, tmp_path, capsys):
    from host.otis_tools import instrument_recorder

    observed = []
    monkeypatch.setattr(instrument_recorder, "request", lambda directory, body: (
        observed.append((directory, body)) or {"receipt": "accepted"}
    ))
    session = 2**63 + 23
    assert main([
        "mode", str(tmp_path), "--session", str(session), "--mode", "0", "--dwell-s", "120",
    ]) == 0
    assert observed == [(tmp_path, {
        "operation": "mode", "expected_session": session,
        "mode": 0, "code": 0, "dwell_s": 120,
    })]
    assert json.loads(capsys.readouterr().out) == {"receipt": "accepted"}


def test_verify_cli_reports_failed_recording_integrity(monkeypatch, tmp_path, capsys):
    from host.otis_tools import instrument_recorder

    monkeypatch.setattr(instrument_recorder, "verify_recording", lambda directory: {
        "error": f"incomplete recording at {directory}",
    })
    assert main(["verify", str(tmp_path)]) == 2
    assert "incomplete recording" in capsys.readouterr().out


@pytest.mark.parametrize("retired", ["compile", "run", "rehearse", "abort", "package", "analyse", "spec"])
def test_retired_supervisor_commands_are_not_ordinary_runtime_entrypoints(retired):
    with pytest.raises(SystemExit) as failure:
        main([retired])
    assert failure.value.code == 2
