from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from host.otis_tools import gnss_baud_envelope_bundle as bundle


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "profiles/qualification/otis_gnss_baud_envelope_characterization_continuation_v1.json"
)
SOURCE_RUN = (
    Path(__file__).resolve().parents[1]
    / "runs/otis_gnss_baud_envelope_characterization_v1/live_20260826T223754Z"
)
REQUIRED_SOURCE_FILES = (
    "evidence_manifest.json",
    "run_manifest.json",
    "reports/activated_contract_v1.json",
    "reports/activated_firmware_build_manifest_v1.json",
    "reports/gnss_baud_envelope_supervisor_events_v1.jsonl",
    "reports/gnss_baud_envelope_supervisor_state_v1.json",
    "reports/gnss_baud_envelope_analysis_v1.json",
)


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _copy_required_source(tmp_path: Path) -> Path:
    target = (
        tmp_path
        / "runs/otis_gnss_baud_envelope_characterization_v1/live_20260826T223754Z"
    )
    for relative in REQUIRED_SOURCE_FILES:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_RUN / relative, destination)
    return target


def test_prefix_validator_replays_exact_original_gates_with_source_tags() -> None:
    result = bundle._validate_historical_continuation_source(_contract())

    assert result["status"] == "validated_against_original_manifest_and_contract"
    assert result["historical_terminal_reused_as_programme_success"] is False
    assert result["counter_deltas_cross_source_artifacts"] is False
    assert result["firmware_identity_stratification_required"] is True
    assert [
        (entry["segment_id"], entry["phase_id"])
        for entry in result["reused_phase_sources"]
    ] == [
        ("S01", "ordinary"),
        ("S02", "ordinary"),
        ("S03", "ordinary"),
        ("S04", "ordinary"),
        ("S05", "ordinary"),
        ("S06", "ordinary_entry"),
    ]
    for entry in result["reused_phase_sources"]:
        assert set(
            (
                "source_run_id",
                "source_artifact_sha256",
                "source_contract_sha256",
                "source_firmware_sha256",
                "source_counter_baseline_id",
            )
        ) <= set(entry)
        assert entry["source_run_id"] == "live_20260826T223754Z"
    assert result["reused_phase_sources"][-1][
        "phase_completed_event_sequence"
    ] == 29


@pytest.mark.parametrize(
    "field",
    ("supervisor_events_sha256", "original_contract_file_sha256"),
)
def test_prefix_validator_rejects_changed_original_identity(field: str) -> None:
    contract = deepcopy(_contract())
    contract["prefix_validation"][field] = "0" * 64

    with pytest.raises(ValueError, match="continuation provenance/scope contract differs"):
        bundle._validate_historical_continuation_source(contract)


def test_prefix_validator_rejects_changed_s06_event_29(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _copy_required_source(tmp_path)
    events_path = target / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl"
    events = events_path.read_text(encoding="utf-8").splitlines()
    event_29 = json.loads(events[28])
    assert event_29["event_sequence"] == 29
    event_29["phase_id"] = "tampered"
    events[28] = json.dumps(event_29, sort_keys=True)
    events_path.write_text("\n".join(events) + "\n", encoding="utf-8")
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    monkeypatch.setattr(
        bundle,
        "LIVE_RUN_ROOT",
        tmp_path / "runs/otis_gnss_baud_envelope_characterization_v1",
    )

    with pytest.raises(ValueError, match="historical artifact identity differs"):
        bundle._validate_historical_continuation_source(_contract())


def test_continuation_mapping_cannot_reissue_historical_logical_segments() -> None:
    contract = deepcopy(_contract())
    contract["continuation"]["local_to_logical_segment_map"][0][
        "logical_segment_id"
    ] = "S01"

    with pytest.raises(ValueError, match="continuation provenance/scope contract differs"):
        bundle._validate_historical_continuation_source(contract)


def test_composite_counter_and_firmware_rules_are_frozen() -> None:
    for field in ("counter_delta_rule", "firmware_compatibility_rule"):
        contract = deepcopy(_contract())
        contract["composite_analysis"][field] = "weakened"
        with pytest.raises(
            ValueError, match="continuation provenance/scope contract differs"
        ):
            bundle._validate_historical_continuation_source(contract)
