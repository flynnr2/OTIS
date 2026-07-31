from __future__ import annotations

from pathlib import Path
import csv
import io
import subprocess

from host.otis_tools.diagnostics import (
    DEFAULT_DIAGNOSTIC_CONFIG_HASH,
    DEFAULT_DIAGNOSTIC_SPECS,
    DiagnosticEngine,
    DiagnosticSpec,
    diagnostic_config_hash,
)


SPEC = DiagnosticSpec(
    "diag.fixture",
    "reference",
    "WARN",
    "fixture_bad",
    "fixture_requalified",
    reference_effect="invalidate",
    raise_after=2,
    clear_after=2,
    update_interval=2,
)


def test_raise_update_clear_hysteresis_and_evidence_ranges() -> None:
    engine = DiagnosticEngine((SPEC,))
    assert engine.observe(
        "diag.fixture",
        active=True,
        ticks=10,
        time_domain="fixture",
        evidence_refs="ref:1",
        evidence_token="1",
    ) is None
    raised = engine.observe(
        "diag.fixture",
        active=True,
        ticks=20,
        time_domain="fixture",
        evidence_refs="ref:2",
        evidence_token="2",
    )
    assert raised is not None
    assert raised["transition"] == "raised"
    assert raised["first_evidence_refs"] == "ref:2"

    updated = engine.observe(
        "diag.fixture",
        active=True,
        ticks=30,
        time_domain="fixture",
        evidence_refs="ref:3",
        evidence_token="3",
    )
    assert updated is not None
    assert updated["transition"] == "updated"
    assert updated["first_evidence_refs"] == "ref:2"
    assert updated["latest_evidence_refs"] == "ref:3"

    assert engine.observe(
        "diag.fixture",
        active=False,
        ticks=40,
        time_domain="fixture",
        evidence_refs="ref:4",
        evidence_token="4",
    ) is None
    cleared = engine.observe(
        "diag.fixture",
        active=False,
        ticks=50,
        time_domain="fixture",
        evidence_refs="ref:5",
        evidence_token="5",
    )
    assert cleared is not None
    assert cleared["transition"] == "cleared"
    assert cleared["clear_reason_code"] == "fixture_requalified"


def test_duplicate_evidence_is_idempotent() -> None:
    engine = DiagnosticEngine((SPEC,))
    engine.observe(
        "diag.fixture",
        active=True,
        ticks=10,
        time_domain="fixture",
        evidence_refs="ref:1",
        evidence_token="same",
    )
    assert engine.observe(
        "diag.fixture",
        active=True,
        ticks=10,
        time_domain="fixture",
        evidence_refs="ref:1",
        evidence_token="same",
    ) is None


def test_missing_source_evidence_is_explicit_not_fabricated() -> None:
    engine = DiagnosticEngine((SPEC,))
    assert engine.observe(
        "diag.fixture",
        active=True,
        ticks=10,
        time_domain="fixture",
        evidence_refs="unavailable:fixture:REF;fixture:CNT:1",
        evidence_token="1",
    ) is None
    raised = engine.observe(
        "diag.fixture",
        active=True,
        ticks=20,
        time_domain="fixture",
        evidence_refs="unavailable:fixture:REF;fixture:CNT:2",
        evidence_token="2",
    )
    assert raised is not None
    assert raised["first_evidence_refs"].startswith("unavailable:")


def test_host_and_firmware_reducers_have_transition_parity(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    firmware = (
        root
        / "firmware"
        / "arduino"
        / "otis_nano_rp2040_connect"
    )
    executable = tmp_path / "diagnostic_engine_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(root / "tests" / "cpp" / "diagnostic_engine_harness.cpp"),
            str(firmware / "otis_diagnostic_engine.cpp"),
            "-I",
            str(firmware),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=root,
    )
    live = subprocess.run(
        [str(executable)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        cwd=root,
    ).stdout.splitlines()

    engine = DiagnosticEngine((SPEC,))
    host: list[str] = []
    for index, active in enumerate((True, True, True, False, False), start=1):
        row = engine.observe(
            "diag.fixture",
            active=active,
            ticks=index * 10,
            time_domain="fixture",
            evidence_refs=f"ref:{index}",
            evidence_token=str(index),
        )
        if row is not None:
            host.append(
                ",".join(
                    (
                        row["transition"],
                        row["episode_id"].rsplit(":", 1)[-1],
                        row["occurrence_count"],
                        row["first_seen_ticks"],
                        row["last_seen_ticks"],
                    )
                )
            )
    assert live == host


def test_default_configuration_hash_binds_the_rule_table() -> None:
    assert DEFAULT_DIAGNOSTIC_CONFIG_HASH == diagnostic_config_hash(
        DEFAULT_DIAGNOSTIC_SPECS
    )
    assert len(DEFAULT_DIAGNOSTIC_CONFIG_HASH) == 64


def test_sealed_catalog_evidence_has_full_live_replay_parity(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    firmware = (
        root
        / "firmware"
        / "arduino"
        / "otis_nano_rp2040_connect"
    )
    executable = tmp_path / "diagnostic_catalog_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(root / "tests" / "cpp" / "diagnostic_catalog_harness.cpp"),
            str(firmware / "otis_diagnostic_engine.cpp"),
            str(firmware / "otis_diagnostic_catalog.cpp"),
            "-I",
            str(firmware),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=root,
    )
    fields = (
        "diagnostic_seq",
        "diagnostic_id",
        "episode",
        "subsystem",
        "severity",
        "state",
        "transition",
        "diagnostic_confidence",
        "reason_code",
        "clear_reason_code",
        "first_seen_ticks",
        "last_seen_ticks",
        "occurrence_count",
        "first_evidence_refs",
        "latest_evidence_refs",
        "algorithm_version",
        "config_hash",
        "observation_effect",
        "reference_effect",
        "model_effect",
        "control_effect",
    )
    live_text = subprocess.run(
        [str(executable)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        cwd=root,
    ).stdout
    live = list(csv.DictReader(io.StringIO(live_text), fieldnames=fields))

    active_sets = (
        {
            "diag.reference.authority",
            "diag.aperture.unqualified",
            "diag.plant.inapplicable",
        },
        {
            "diag.reference.authority",
            "diag.aperture.unqualified",
            "diag.plant.inapplicable",
        },
        {"diag.aperture.unqualified"},
        {
            "diag.aperture.unqualified",
            "diag.sequence.discontinuity",
            "diag.count.window",
        },
        {"diag.aperture.unqualified"},
        {"diag.aperture.unqualified"},
        {"diag.aperture.unqualified"},
        set(),
    )
    engine = DiagnosticEngine(DEFAULT_DIAGNOSTIC_SPECS)
    replay: list[dict[str, str]] = []
    for event, active_ids in enumerate(active_sets, start=1):
        refs = (
            f"fixture:REF:{event};fixture:CNT:{event};"
            "unavailable:fixture:STS"
        )
        for spec in DEFAULT_DIAGNOSTIC_SPECS:
            row = engine.observe(
                spec.diagnostic_id,
                active=spec.diagnostic_id in active_ids,
                ticks=event * 100,
                time_domain="fixture",
                evidence_refs=refs,
                evidence_token=str(event),
            )
            if row is None:
                continue
            replay.append(
                {
                    **{field: row[field] for field in fields if field in row},
                    "episode": row["episode_id"].rsplit(":", 1)[-1],
                }
            )
    assert live == replay
