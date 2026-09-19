"""The compile entry point reproduces a frozen image without bench entry."""
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from host.otis_tools.__main__ import main


@pytest.fixture
def frozen_compile(monkeypatch, tmp_path):
    from host.otis_tools import bench_entry, firmware_artifact, run_spec

    retained = {
        "source_sha256": "a" * 64,
        "source_revision": "b" * 40,
        "configuration_sha256": "c" * 64,
        "firmware_inputs": {"set_sha256": "d" * 64},
        "build_session_id": "frozen-session",
        "provenance": {"frozen": "identity"},
        "uf2": {"sha256": "e" * 64},
    }
    reproduced = copy.deepcopy(retained)
    reproduced["build_manifest"] = {"path": str(tmp_path / "build.json")}
    artifact = SimpleNamespace(document=lambda: retained, sha256="f" * 64)
    loaded = []
    validated = []
    compiled = []
    manifest = object()
    def load_spec(path):
        loaded.append(path)
        return SimpleNamespace(document=lambda: {"firmware": {"artifact": retained}})
    def validate_artifact(document):
        validated.append(document)
        assert document is retained
        return artifact
    def compile_image(actual_manifest, output_dir, **kwargs):
        assert actual_manifest is manifest
        compiled.append((output_dir, kwargs))
        return {"build_manifest": str(tmp_path / "build.json")}
    def no_bench(**kwargs):
        pytest.fail("compile must not enter a physical experiment")
    monkeypatch.setattr(run_spec, "load_run_spec", load_spec)
    monkeypatch.setattr(firmware_artifact, "validate_frozen_firmware_artifact", validate_artifact)
    monkeypatch.setattr(firmware_artifact.build_firmware, "load_manifest", lambda: manifest)
    monkeypatch.setattr(firmware_artifact.build_firmware, "capture_source_state", lambda value: {
        "source_state": "clean", "source_sha256": retained["source_sha256"],
        "firmware_audit_revision": retained["source_revision"],
        "config_sha256": retained["configuration_sha256"],
        "firmware_inputs": retained["firmware_inputs"],
    })
    monkeypatch.setattr(firmware_artifact.build_firmware, "build_firmware", compile_image)
    monkeypatch.setattr(firmware_artifact, "load_firmware_artifact",
                        lambda path: SimpleNamespace(document=lambda: reproduced))
    monkeypatch.setattr(bench_entry, "start", no_bench)
    return SimpleNamespace(module=firmware_artifact, retained=retained, reproduced=reproduced,
                           loaded=loaded, validated=validated, compiled=compiled)


@pytest.mark.parametrize("cli", [None, "/custom/arduino-cli"])
def test_compile_binds_frozen_artifact_and_prints_verified_receipt(frozen_compile, tmp_path, capsys, cli):
    arguments = ["compile", "prepared-spec.json", "--output-dir", str(tmp_path / "output")]
    if cli is not None:
        arguments += ["--arduino-cli", cli]
    assert main(arguments) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "verified"
    assert receipt["firmware_artifact_sha256"] == "f" * 64
    assert receipt["uf2_sha256"] == "e" * 64
    assert receipt["build_session_id"] == "frozen-session"
    assert len(receipt["receipt_sha256"]) == 64
    assert frozen_compile.loaded == [Path("prepared-spec.json")]
    assert frozen_compile.validated == [frozen_compile.retained]
    assert frozen_compile.compiled == [(tmp_path / "output", {
        "arduino_cli": cli or "arduino-cli", "build_session_id": "frozen-session"})]


def test_compile_propagates_compiler_failure_without_receipt(frozen_compile, monkeypatch, tmp_path, capsys):
    failure = subprocess.CalledProcessError(1, ["compiler"])
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(frozen_compile.module.build_firmware, "build_firmware", fail)
    with pytest.raises(subprocess.CalledProcessError) as error:
        main(["compile", "spec.json", "--output-dir", str(tmp_path)])
    assert error.value is failure
    assert capsys.readouterr().out == ""


def test_compile_propagates_binary_mismatch_without_receipt(frozen_compile, tmp_path, capsys):
    frozen_compile.reproduced["uf2"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="reproduced firmware binary differs"):
        main(["compile", "spec.json", "--output-dir", str(tmp_path)])
    assert len(frozen_compile.compiled) == 1
    assert capsys.readouterr().out == ""


def test_compile_rejects_invalid_spec_before_compiler(frozen_compile, monkeypatch, tmp_path, capsys):
    from host.otis_tools import run_spec
    def fail(path):
        raise ValueError("invalid frozen specification")
    monkeypatch.setattr(run_spec, "load_run_spec", fail)
    with pytest.raises(ValueError, match="invalid frozen specification"):
        main(["compile", "spec.json", "--output-dir", str(tmp_path)])
    assert not frozen_compile.compiled and not frozen_compile.validated
    assert capsys.readouterr().out == ""
