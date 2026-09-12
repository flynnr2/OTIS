"""Physical boundary ordering and upload failure retention without hardware."""
import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from host.otis_tools import bench_entry
from host.otis_tools.run_spec import ConsumedEntry
from tests.run_spec_fixtures import build_synthetic_spec


def _entry(monkeypatch, tmp_path):
    spec = build_synthetic_spec(monkeypatch, tmp_path, purpose="inhibited_zero_write")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"receipt_sha256": "b" * 64}))
    return {"spec_path": spec.path, "rehearsal_path": receipt, "run_dir": tmp_path / "attempt",
            "device": "/dev/never-open", "operator_instruction_ref": "operator-message",
            "attempt_reason": "zero-write physical entry"}, spec


def test_invalid_entry_never_queries_board_or_creates_attempt(monkeypatch, tmp_path):
    kwargs, _ = _entry(monkeypatch, tmp_path)
    monkeypatch.setattr(bench_entry, "authorize_entry", lambda *a, **kw: (_ for _ in ()).throw(ValueError("receipt rejected")))
    monkeypatch.setattr(bench_entry, "read_board_identity", lambda *a, **kw: pytest.fail("board queried"))
    with pytest.raises(ValueError, match="receipt rejected"):
        bench_entry.start(**kwargs)
    assert not kwargs["run_dir"].exists()


def test_entry_evidence_precedes_board_io_and_failed_board_is_not_retried(monkeypatch, tmp_path):
    kwargs, spec = _entry(monkeypatch, tmp_path)
    calls = []
    def consume(identity):
        assert identity == spec.sha256
        calls.append("consume")
        return ConsumedEntry(spec_sha256=identity, authorization={})
    monkeypatch.setattr(bench_entry, "authorize_entry", lambda *a, **kw: SimpleNamespace(consume=consume))
    def board(*a, **kw):
        retained = json.loads((kwargs["run_dir"] / "reports/physical_entry.json").read_text())
        assert retained["run_spec_sha256"] == spec.sha256
        assert (kwargs["run_dir"] / "run_spec.json").read_bytes() == spec.path.read_bytes()
        assert calls == ["consume"]
        calls.append("board")
        raise ValueError("different board")
    monkeypatch.setattr(bench_entry, "read_board_identity", board)
    with pytest.raises(ValueError, match="different board"):
        bench_entry.start(**kwargs)
    assert calls == ["consume", "board"]
    assert not (kwargs["run_dir"] / "run_manifest.json").exists()


def test_relocated_authorized_artifact_is_uploaded(monkeypatch, tmp_path):
    kwargs, _spec = _entry(monkeypatch, tmp_path)
    moved_manifest = tmp_path / "delivered/build.json"
    moved_artifact = {"uf2": {"path": str(tmp_path / "delivered/image.uf2")}}
    authorization = {"rehearsal_receipt_sha256": "b" * 64,
                     "operator_instruction_ref": kwargs["operator_instruction_ref"],
                     "attempt_reason": kwargs["attempt_reason"]}
    def authorize(*a, **kw):
        assert kw["firmware_manifest_path"] == moved_manifest
        return SimpleNamespace(consume=lambda identity: ConsumedEntry(spec_sha256=identity, authorization=authorization),
                               firmware_artifact=SimpleNamespace(document=lambda: moved_artifact))
    monkeypatch.setattr(bench_entry, "authorize_entry", authorize)
    monkeypatch.setattr(bench_entry, "read_board_identity", lambda *a, **kw: {})
    monkeypatch.setattr(bench_entry, "_serial_owner_pids", lambda device: [])
    def upload(**kw):
        assert kw["firmware"] == moved_artifact
        return "/dev/cu.usbmodem-test-never-open"
    monkeypatch.setattr(bench_entry, "_upload_once", upload)
    def run(**kw):
        record = json.loads(kw["manifest_path"].read_text())
        assert record["execution_kind"] == "physical"
        assert kw["device"] == "/dev/cu.usbmodem-test-never-open"
        return {"status": "terminal"}
    monkeypatch.setattr(bench_entry, "run_experiment", run)
    monkeypatch.setattr(bench_entry, "finish_run", lambda path: {"status": "sealed"})
    result = bench_entry.start(**kwargs, flash=True, firmware_manifest_path=moved_manifest)
    assert result["evidence"] == {"status": "sealed"}


def test_failed_upload_once_retains_complete_output(monkeypatch, tmp_path):
    (tmp_path / "reports").mkdir()
    image = tmp_path / "image.uf2"
    image.write_bytes(b"frozen image")
    firmware = {"uf2": {"path": str(image), "size_bytes": image.stat().st_size,
                          "sha256": sha256(image.read_bytes()).hexdigest()}, "fqbn": "test"}
    monkeypatch.setattr(bench_entry, "read_board_identity", lambda *a, **kw: {"serial": "exact"})
    monkeypatch.setattr(bench_entry, "_serial_owner_pids", lambda device: [])
    calls = []
    def upload(command, **kw):
        calls.append(command)
        kw["stdout"].write("complete upload failure details\n")
        assert kw["timeout"] == 120
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(bench_entry.subprocess, "run", upload)
    with pytest.raises(RuntimeError, match="exit 7"):
        bench_entry._upload_once(firmware=firmware, device="/dev/never-open", bench=None,
                                run_dir=tmp_path, arduino_cli="never-execute")
    assert len(calls) == 1
    assert (tmp_path / "reports/firmware_upload.log").read_text() == "complete upload failure details\n"
    retained = json.loads((tmp_path / "reports/firmware_entry.json").read_text())
    assert retained["status"] == "failed" and retained["exit_code"] == 7
    assert retained["flash_count"] == 1
