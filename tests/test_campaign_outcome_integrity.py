from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import adaptive_hybrid_activation
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    envelope_for_purpose,
)
from host.otis_tools.evidence import create_evidence_snapshot
from host.otis_tools.evidence_finalization import (
    PHASES,
    advance_phase,
    begin_finalization,
    recover_registration,
    set_registration_intent,
)
from host.otis_tools.evidence_index import (
    CURRENT_SEAL_PATH,
    load_index,
    package_identity,
    register_package,
    save_index,
    validate_index,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _seal_sha256(seal: dict[str, object]) -> str:
    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    return sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _terminal(
    *, result: str, reason: str, primary_decision: str | None = None
) -> dict[str, object]:
    terminal: dict[str, object] = {
        "result": result,
        "reason": reason,
        "last_confirmed_code": 0xA84D,
        "utc": "2026-09-11T00:00:00Z",
    }
    if result == "healthy_stop":
        terminal["preliminary_decision"] = "pending_offline_scientific_analysis"
    else:
        terminal["primary_decision"] = primary_decision
    return terminal


def _package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    terminal: dict[str, object],
    apertures: object,
    evidence_integrity: str,
    scientific_outcome: object = "qualified_complete",
) -> tuple[Path, dict[str, str]]:
    """Build the smallest sealed physical package at the recovery boundary."""

    run = tmp_path / "run"
    raw = run / "raw/serial.log"
    raw.parent.mkdir(parents=True)
    raw.write_text("retained serial evidence\n", encoding="utf-8")
    supervisor = run / "reports/adaptive_hybrid_supervisor_state.json"
    _write_json(
        supervisor,
        {
            "terminal": terminal,
            "qualified_d14_accepted_apertures": apertures,
        },
    )
    analyzer_identity = "a" * 64
    source_revision = "1" * 40
    build_identity = "source:configuration"
    manifest = {
        "schema_version": 1,
        "evidence_epoch": "OTIS_ADAPTIVE_HYBRID_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run.name,
        "stage": "OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE",
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "adaptive_hybrid": {"profile_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id},
        "firmware": {
            "source_revision": source_revision,
            "build_identity": build_identity,
        },
        "policy": {"policy_id": ADAPTIVE_HYBRID_PROGRAMME.policy_id},
        "host": {
            "tool_bindings": {
                "adaptive_hybrid_analyze": {"sha256": analyzer_identity}
            }
        },
        "bench_attempt": envelope_for_purpose(
            CONTINGENT_72_HOUR_HYBRID_CONTROL
        ).as_dict(),
        "files": [
            {"path": "raw/serial.log"},
            {"path": "reports/adaptive_hybrid_supervisor_state.json"},
        ],
    }
    _write_json(run / "run_manifest.json", manifest)
    _write_json(
        run / "COMPLETE",
        {
            "completion": "adaptive_hybrid_finite_physical_campaign",
            "terminal": terminal,
            "orchestration_error": None,
        },
    )
    _write_json(run / "reports/step_0001/record_0001.json", {"decision": "retained"})
    _write_json(
        run / "carrier/responses/response_0001.json", {"acknowledgement": "retained"}
    )
    snapshot_path = create_evidence_snapshot(run)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    primary_decision = terminal.get("primary_decision") or terminal["reason"]
    seal: dict[str, object] = {
        "schema_version": 1,
        "seal_type": "adaptive_hybrid_physical_seal_v1",
        "tool": "adaptive_hybrid_analyze_v1",
        "tool_sha256": analyzer_identity,
        "created_utc": "2026-09-11T00:00:00Z",
        "run_id": run.name,
        "run_identity": manifest["run_identity"],
        "build_identity": build_identity,
        "image_identity": manifest["image_identity"],
        "programme_id": manifest["programme_id"],
        "policy_id": manifest["policy"]["policy_id"],
        "status": evidence_integrity,
        "evidence_integrity": evidence_integrity,
        "scientific_outcome": scientific_outcome,
        "primary_decision": primary_decision,
        "terminal_result": terminal["result"],
        "terminal_reason": terminal["reason"],
        "host_review_resolution": None,
        "checks": {"all_current_checks": evidence_integrity == "passed"},
        "csv_validation": {},
        "exact_lifecycle_records": {},
        "maintenance_replay": {},
        "measurement_replay": {},
        "response_replay": {},
        "transaction_capsule_sha256": {},
        "evidence_snapshot": {
            "path": "evidence_manifest.json",
            "failures": [],
            "warnings": [],
        },
        "source_sha256": {
            "raw/serial.log": sha256(raw.read_bytes()).hexdigest(),
            "reports/adaptive_hybrid_supervisor_state.json": sha256(
                supervisor.read_bytes()
            ).hexdigest(),
        },
        "D10_semantics": {},
        "host_discrepancy_authority": {
            "review_required": evidence_integrity != "passed",
            "new_setup": False,
            "new_arm": False,
            "automatic_abort": False,
            "automatic_teardown": False,
            "failed_campaign": False,
            "raw_evidence_preserved": True,
        },
        "limitations": [],
    }
    seal["seal_sha256"] = _seal_sha256(seal)
    _write_json(run / CURRENT_SEAL_PATH, seal)

    # The fixture deliberately covers generic evidence preservation and the
    # finalization/index boundary.  The activation bundle itself is irrelevant
    # to these outcome classifications and has its own exact validator.
    monkeypatch.setattr(
        adaptive_hybrid_activation,
        "validate_frozen_run_manifest",
        lambda _path: manifest,
    )
    registration = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "image_identity": manifest["image_identity"],
        "attempt_classification": "completed_campaign",
        "result_or_failure_reason": f"ADAPTIVE_HYBRID outcome: {primary_decision}",
        "analyzer_identity": analyzer_identity,
        "evidence_integrity": evidence_integrity,
        "scientific_outcome": scientific_outcome,
    }
    return run, registration


def _recover(
    *, run: Path, registration: dict[str, str], index_path: Path
) -> dict[str, object]:
    journal = begin_finalization(
        run_dir=run,
        index_path=index_path,
        registration=registration,
        required_seal=CURRENT_SEAL_PATH,
    )
    for phase in PHASES[:-1]:
        advance_phase(journal, phase, {})
    set_registration_intent(
        journal,
        registration=registration,
        expected_content_sha256=package_identity(run)["content_sha256"],
    )
    return recover_registration(journal)


def test_exact_full_aperture_completion_registers_completed_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = _terminal(
        result="healthy_stop",
        reason=ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
    )
    run, registration = _package(
        tmp_path,
        monkeypatch,
        terminal=terminal,
        apertures=ADAPTIVE_HYBRID_PROGRAMME.qualified_d14_aperture_count,
        evidence_integrity="passed",
        scientific_outcome="qualified_complete",
    )

    record = _recover(
        run=run, registration=registration, index_path=tmp_path / "external/index.json"
    )

    assert record["attempt_classification"] == "completed_campaign"
    assert record["scientific_outcome"] == "qualified_complete"
    assert record["evidence_integrity"] == "passed"


@pytest.mark.parametrize(
    ("terminal", "apertures", "claimed_outcome"),
    [
        (
            _terminal(
                result="healthy_stop",
                reason=ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
            ),
            ADAPTIVE_HYBRID_PROGRAMME.qualified_d14_aperture_count - 1,
            "qualified_complete",
        ),
        (
            _terminal(
                result="aborted",
                reason="independent_host_abort_fifo",
                primary_decision="adaptive_hybrid_operator_abort",
            ),
            35_480,
            "qualified_complete",
        ),
    ],
)
def test_forged_completed_outcome_cannot_cross_recovery_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: dict[str, object],
    apertures: int,
    claimed_outcome: str,
) -> None:
    run, registration = _package(
        tmp_path,
        monkeypatch,
        terminal=terminal,
        apertures=apertures,
        evidence_integrity="passed",
        scientific_outcome=claimed_outcome,
    )
    index = tmp_path / "external/index.json"

    with pytest.raises(ValueError, match="scientific outcome|outcome|completed"):
        _recover(run=run, registration=registration, index_path=index)
    assert not index.exists()


def test_early_operator_abort_retains_integrity_but_registers_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, registration = _package(
        tmp_path,
        monkeypatch,
        terminal=_terminal(
            result="aborted",
            reason="independent_host_abort_fifo",
            primary_decision="adaptive_hybrid_operator_abort",
        ),
        apertures=35_480,
        evidence_integrity="passed",
        scientific_outcome="interrupted_incomplete",
    )
    registration["attempt_classification"] = "interrupted_campaign"

    record = _recover(
        run=run, registration=registration, index_path=tmp_path / "external/index.json"
    )

    assert record["attempt_classification"] == "interrupted_campaign"
    assert record["evidence_integrity"] == "passed"
    assert record["scientific_outcome"] == "interrupted_incomplete"


def test_bounded_nonpass_remains_completed_evidence_with_nonpass_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, registration = _package(
        tmp_path,
        monkeypatch,
        terminal=_terminal(
            result="nonpass",
            reason="authority_not_sustained",
            primary_decision="adaptive_hybrid_authority_not_sustained",
        ),
        apertures=35_480,
        evidence_integrity="passed",
        scientific_outcome="bounded_nonpass",
    )

    record = _recover(
        run=run, registration=registration, index_path=tmp_path / "external/index.json"
    )

    assert record["attempt_classification"] == "completed_campaign"
    assert record["scientific_outcome"] == "bounded_nonpass"
    assert record["evidence_integrity"] == "passed"


def test_review_hold_remains_diagnostic_and_does_not_claim_scientific_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, registration = _package(
        tmp_path,
        monkeypatch,
        terminal=_terminal(
            result="aborted",
            reason="independent_host_abort_fifo",
            primary_decision="adaptive_hybrid_operator_abort",
        ),
        apertures=35_480,
        evidence_integrity="review_required",
        scientific_outcome="undetermined",
    )
    registration["attempt_classification"] = "diagnostic"

    record = _recover(
        run=run, registration=registration, index_path=tmp_path / "external/index.json"
    )

    assert record["attempt_classification"] == "diagnostic"
    assert record["evidence_integrity"] == "review_required"
    assert record["scientific_outcome"] == "undetermined"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scientific_outcome", None),
        ("evidence_integrity", "review_required"),
    ],
)
def test_missing_or_contradictory_seal_outcome_is_rejected_at_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    terminal = _terminal(
        result="healthy_stop",
        reason=ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
    )
    run, registration = _package(
        tmp_path,
        monkeypatch,
        terminal=terminal,
        apertures=ADAPTIVE_HYBRID_PROGRAMME.qualified_d14_aperture_count,
        evidence_integrity="passed",
        scientific_outcome="qualified_complete",
    )
    seal_path = run / CURRENT_SEAL_PATH
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if value is None:
        del seal[field]
    else:
        seal[field] = value
    seal["seal_sha256"] = _seal_sha256(seal)
    _write_json(seal_path, seal)
    if field == "evidence_integrity":
        registration[field] = str(value)
    index = tmp_path / "external/index.json"

    with pytest.raises(ValueError, match="integrity|outcome|seal"):
        _recover(run=run, registration=registration, index_path=index)
    assert not index.exists()


@pytest.mark.parametrize(
    ("scientific_outcome", "attempt_classification"),
    [
        ("interrupted_incomplete", "interrupted_campaign"),
        ("diagnostic_complete", "diagnostic"),
    ],
)
def test_passed_outcome_claims_cannot_register_an_arbitrary_raw_directory(
    tmp_path: Path,
    scientific_outcome: str,
    attempt_classification: str,
) -> None:
    package = tmp_path / "unsealed"
    package.mkdir()
    (package / "raw.txt").write_text("retained but unvalidated\n", encoding="utf-8")
    index = tmp_path / "external/index.json"

    with pytest.raises(ValueError, match="requires|validated|package"):
        register_package(
            index_path=index,
            package_path=package,
            source_revision="1" * 40,
            build_identity="source:configuration",
            image_identity=ADAPTIVE_HYBRID_PROGRAMME.profile_id,
            attempt_classification=attempt_classification,
            result_or_failure_reason=f"untrusted {scientific_outcome}",
            analyzer_identity="a" * 64,
            evidence_integrity="passed",
            scientific_outcome=scientific_outcome,
        )
    assert not index.exists()


def test_index_reports_malformed_outcome_metadata_without_raising(
    tmp_path: Path,
) -> None:
    package = tmp_path / "diagnostic"
    package.mkdir()
    (package / "raw.txt").write_text("retained diagnostic evidence\n", encoding="utf-8")
    index_path = tmp_path / "external/index.json"
    record = register_package(
        index_path=index_path,
        package_path=package,
        source_revision="1" * 40,
        build_identity="source:configuration",
        image_identity=ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        attempt_classification="diagnostic",
        result_or_failure_reason="retained diagnostic evidence",
        analyzer_identity="a" * 64,
    )
    index = load_index(index_path)
    index["packages"][record["content_sha256"]].update(
        {
            "evidence_integrity": ["passed"],
            "scientific_outcome": "interrupted_incomplete",
        }
    )
    save_index(index_path, index)

    validation = validate_index(index_path)

    assert validation["valid"] is False
    assert validation["packages"] == [
        {
            "content_sha256": record["content_sha256"],
            "valid": False,
            "locations": [
                {
                    "location": str(package.resolve()),
                    "status": "mismatch",
                    "observed_content_sha256": record["content_sha256"],
                }
            ],
        }
    ]


@pytest.mark.parametrize("classification", ["historical", "failed_qualification"])
def test_inventory_classification_cannot_hide_invalid_outcome_fields(
    tmp_path: Path, classification: str,
) -> None:
    package = tmp_path / "inventory"
    package.mkdir()
    (package / "raw.txt").write_text("retained")
    index = tmp_path / "external/index.json"
    with pytest.raises(ValueError, match="contradicts"):
        register_package(
            index_path=index, package_path=package,
            source_revision="1" * 40, build_identity="source:configuration",
            image_identity=ADAPTIVE_HYBRID_PROGRAMME.profile_id,
            attempt_classification=classification,
            result_or_failure_reason="inventory only", analyzer_identity="a" * 64,
            evidence_integrity="unknown", scientific_outcome="unknown",
        )
    assert not index.exists()
