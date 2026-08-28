from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.gnss_baud_envelope_bundle import (
    ACTIVATION_KEYS,
    ACTIVATION_TYPE,
    GNSS_BAUD_ENVELOPE_PROFILE_ID,
    LIVE_RUN_ROOT,
    ORIGINAL_ACTIVATION_KEYS,
    ORIGINAL_CONTRACT_SHA256,
    _validated_binary_contract,
    canonical_sha256,
    validate_activation,
)


def _write_candidate(path: Path) -> dict[str, object]:
    candidate: dict[str, object] = {
        "bundle_id": "bundle-identity",
        "firmware": {"profile_id": GNSS_BAUD_ENVELOPE_PROFILE_ID},
        "expected_device": {"usb_serial": "503533748A919118"},
        "registration_index_path": str(path.parent / "evidence_index_v1.json"),
    }
    path.write_text(json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8")
    return candidate


def _activation(candidate_path: Path, candidate: dict[str, object]) -> dict[str, object]:
    run_id = "live_20990101T000000Z"
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "schema_version": 1,
        "activation_type": ACTIVATION_TYPE,
        "bundle_id": candidate["bundle_id"],
        "bundle_sha256": sha256(candidate_path.read_bytes()).hexdigest(),
        "effective": True,
        "physical_authority": True,
        "activated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "operator": "test operator",
        "authority_source": "test fixture",
        "run_id": run_id,
        "run_dir": str((LIVE_RUN_ROOT / run_id).resolve()),
        "device": "/dev/cu.test-otis",
        "expected_device_identity": "503533748A919118",
        "wall_deadline_utc": (
            now + timedelta(hours=15)
        ).isoformat().replace("+00:00", "Z"),
        "abort_deadline_ms": 2000,
        "flash_limit": 1,
        "live_run_limit": 1,
        "dac_writes_permitted": 0,
        "control_arm_permitted": False,
        "registration_index_path": candidate["registration_index_path"],
    }
    assert set(payload) == ORIGINAL_ACTIVATION_KEYS - {"activation_id"}
    return {**payload, "activation_id": canonical_sha256(payload)}


def test_exact_binary_contract_is_bound_for_candidate_revalidation() -> None:
    build_manifest = {
        "gnss_binary_contract": {
            "status": "verified",
            "campaign_contract": {"sha256": ORIGINAL_CONTRACT_SHA256},
            "startup_discovery": None,
            "continuation": None,
            "marker": "retained",
        }
    }

    assert _validated_binary_contract(
        build_manifest, GNSS_BAUD_ENVELOPE_PROFILE_ID
    )["marker"] == "retained"

    build_manifest["gnss_binary_contract"]["campaign_contract"]["sha256"] = (
        "0" * 64
    )
    with pytest.raises(ValueError, match="exact GNSS binary contract"):
        _validated_binary_contract(build_manifest, GNSS_BAUD_ENVELOPE_PROFILE_ID)


def test_activation_binds_candidate_and_external_registration_index(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate = _write_candidate(candidate_path)
    activation = _activation(candidate_path, candidate)

    validated = validate_activation(candidate_path, candidate, activation)

    assert validated == activation


def test_activation_rejects_candidate_file_changed_after_authorization(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate = _write_candidate(candidate_path)
    activation = _activation(candidate_path, candidate)
    candidate_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="authority or bundle binding"):
        validate_activation(candidate_path, candidate, activation)


def test_activation_rejects_registration_index_substitution(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate = _write_candidate(candidate_path)
    activation = _activation(candidate_path, candidate)
    activation["registration_index_path"] = str(tmp_path / "different.json")
    unsigned = {
        key: value for key, value in activation.items() if key != "activation_id"
    }
    activation["activation_id"] = canonical_sha256(unsigned)

    with pytest.raises(ValueError, match="authority or bundle binding"):
        validate_activation(candidate_path, candidate, activation)


def test_activation_rejects_unknown_fields(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate = _write_candidate(candidate_path)
    activation = _activation(candidate_path, candidate)
    activation["unexpected"] = True

    with pytest.raises(ValueError, match="field set differs"):
        validate_activation(candidate_path, candidate, activation)


def test_activation_rejects_empty_operator_even_with_recomputed_identity(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate = _write_candidate(candidate_path)
    activation = _activation(candidate_path, candidate)
    activation["operator"] = ""
    activation["activation_id"] = canonical_sha256(
        {key: value for key, value in activation.items() if key != "activation_id"}
    )

    with pytest.raises(ValueError, match="authority or bundle binding"):
        validate_activation(candidate_path, candidate, activation)


def test_activation_rejects_unbounded_wall_horizon(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate = _write_candidate(candidate_path)
    activation = _activation(candidate_path, candidate)
    activated_at = datetime.fromisoformat(
        str(activation["activated_at_utc"]).replace("Z", "+00:00")
    )
    activation["wall_deadline_utc"] = (
        activated_at + timedelta(days=365)
    ).isoformat().replace("+00:00", "Z")
    activation["activation_id"] = canonical_sha256(
        {key: value for key, value in activation.items() if key != "activation_id"}
    )

    with pytest.raises(ValueError, match="wall horizon differs"):
        validate_activation(candidate_path, candidate, activation)
