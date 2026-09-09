from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path

from host.otis_tools import adaptive_hybrid_supersede as supersede_module


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_offline_supersession_is_separate_idempotent_and_zero_authority(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source-run"
    source.mkdir()
    _write_json(
        source / "run_manifest.json",
        {"firmware": {"source_revision": "9" * 40}},
    )
    original_seal_path = source / "reports/adaptive_hybrid_physical_seal_v1.json"
    original_seal = {
        "status": "review_required",
        "primary_decision": "operator_review_required",
        "tool": "adaptive_hybrid_analyze_v1",
        "tool_sha256": "a" * 64,
        "seal_sha256": "b" * 64,
        "checks": {
            "D14_D8_measurement_replay_exact": False,
            "maintenance_replay_exact": False,
        },
    }
    _write_json(original_seal_path, original_seal)
    journal_path = tmp_path / "finalization.json"
    journal = {
        "expected_content_sha256": "c" * 64,
        "phases": {
            phase: {"completed_utc": "2026-09-09T00:00:00Z"}
            for phase in (
                "capture_closed",
                "completion",
                "snapshot",
                "analysis",
                "seal",
                "registration",
            )
        },
        "primary_failure": {"phase": "analysis", "error": "retained"},
        "secondary_failures": [],
    }
    _write_json(journal_path, journal)
    source_identity = {
        "content_sha256": "c" * 64,
        "file_count": 36,
        "total_bytes": 1234,
    }
    original_registration = {
        "content_sha256": "c" * 64,
        "attempt_classification": "diagnostic",
        "analyzer_identity": "a" * 64,
        "storage_locations": [str(source.resolve())],
    }
    monkeypatch.setattr(
        supersede_module, "package_identity", lambda path: dict(source_identity)
    )
    monkeypatch.setattr(
        supersede_module, "validate_index_location", lambda path: path.resolve()
    )
    monkeypatch.setattr(
        supersede_module,
        "load_index",
        lambda _path: {
            "index_id": "otis_evidence_index_v1",
            "packages": {"c" * 64: original_registration},
        },
    )
    monkeypatch.setattr(
        supersede_module, "journal_path_for", lambda _source: journal_path
    )
    monkeypatch.setattr(
        supersede_module,
        "validate_completed_diagnostic_journal",
        lambda *_args, **_kwargs: None,
    )
    tool_hashes = {
        "adaptive_hybrid_analyze": "d" * 64,
        "adaptive_hybrid_evidence": "e" * 64,
        "adaptive_hybrid_replay": "f" * 64,
        "adaptive_hybrid_supersede": "1" * 64,
    }
    monkeypatch.setattr(
        supersede_module, "_decision_tool_sha256", lambda: tool_hashes
    )
    monkeypatch.setattr(
        supersede_module,
        "_current_host_source",
        lambda: {"revision": "8" * 40, "source_state": "clean"},
    )
    analyze_calls: list[tuple[Path, Path, Path]] = []

    def analyze(source_path: Path, *, output_path: Path, prior_review_seal_path: Path):
        analyze_calls.append((source_path, output_path, prior_review_seal_path))
        corrected = {
            "status": "passed",
            "primary_decision": "inhibited_zero_write_complete",
            "tool": "adaptive_hybrid_analyze_v1",
            "tool_sha256": "d" * 64,
            "seal_sha256": "2" * 64,
            "source_sha256": {"raw/serial.log": "3" * 64},
        }
        _write_json(output_path, corrected)
        return output_path, corrected

    monkeypatch.setattr(supersede_module, "analyze", analyze)
    registrations: list[Path] = []

    def register(*, index_path: Path, addendum_path: Path):
        registrations.append(addendum_path)
        return {"content_sha256": "4" * 64}

    monkeypatch.setattr(
        supersede_module, "register_analysis_supersession", register
    )
    addendum = tmp_path / "addendum"
    index_path = tmp_path / "index.json"

    first = supersede_module.supersede_analysis(
        source_run_dir=source,
        evidence_index_path=index_path,
        addendum_dir=addendum,
    )
    report_path = addendum / supersede_module.REPORT_NAME
    first_report_bytes = report_path.read_bytes()
    second = supersede_module.supersede_analysis(
        source_run_dir=source,
        evidence_index_path=index_path,
        addendum_dir=addendum,
    )

    assert first == second
    assert len(analyze_calls) == 1
    assert len(registrations) == 2
    assert report_path.read_bytes() == first_report_bytes
    report = json.loads(first_report_bytes)
    assert report["source_package"]["content_sha256"] == "c" * 64
    assert report["source_package"]["firmware_source_revision"] == "9" * 40
    assert report["current_host_source"] == {
        "revision": "8" * 40,
        "source_state": "clean",
    }
    assert report["original_seal"]["tool_sha256"] == "a" * 64
    assert report["corrected_seal"]["tool_sha256"] == "d" * 64
    assert report["acceptance_criterion_unchanged"] is True
    assert report["actionable"] is False
    assert report["actuation_authorized"] is False
    assert report["physical_rerun"] is False
    assert report["device_or_actuator_io"] is False
    assert report["hardware_interaction"] is False
    assert report["new_control_or_terminal_authority"] is False
    unsigned = {
        key: value
        for key, value in report.items()
        if key != "supersession_sha256"
    }
    assert report["supersession_sha256"] == sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_supersession_import_closure_excludes_live_and_device_io_modules() -> None:
    package = Path(supersede_module.__file__).parent
    modules = {
        path.stem: path
        for path in package.glob("*.py")
        if path.name != "__init__.py"
    }

    def import_time_dependencies(name: str) -> set[str]:
        tree = ast.parse(modules[name].read_text(encoding="utf-8"))
        dependencies: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    dependency = node.module.split(".", 1)[0]
                    if dependency in modules:
                        dependencies.add(dependency)
                elif node.level:
                    dependencies.update(
                        alias.name.split(".", 1)[0]
                        for alias in node.names
                        if alias.name.split(".", 1)[0] in modules
                    )
                elif node.module and node.module.startswith("host.otis_tools."):
                    dependency = node.module.split(".")[2]
                    if dependency in modules:
                        dependencies.add(dependency)
            elif isinstance(node, ast.Import):
                dependencies.update(
                    alias.name.split(".")[2]
                    for alias in node.names
                    if alias.name.startswith("host.otis_tools.")
                    and alias.name.split(".")[2] in modules
                )
        return dependencies

    closure: set[str] = set()
    pending = ["adaptive_hybrid_supersede"]
    while pending:
        module = pending.pop()
        if module in closure:
            continue
        closure.add(module)
        pending.extend(import_time_dependencies(module) - closure)

    assert closure == set(supersede_module.ANALYSIS_SUPERSESSION_TOOL_MODULES)
    assert not closure & {
        "adaptive_hybrid_run",
        "capture_device",
        "capture_serial",
        "serial_commands",
        "abort_transport",
    }


def test_supersession_rejects_unsafe_destination_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "source/run"
    source.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    retained = unrelated / "user-data.txt"
    retained.write_text("retain\n", encoding="utf-8")

    for unsafe in (source, source / "child", source.parent, tmp_path):
        try:
            supersede_module._prepare_addendum_directory(source, unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe destination accepted: {unsafe}")
    try:
        supersede_module._prepare_addendum_directory(source, unrelated)
    except ValueError as error:
        assert "unexpected entries" in str(error)
    else:
        raise AssertionError("non-empty unrelated destination accepted")
    assert retained.read_text(encoding="utf-8") == "retain\n"
