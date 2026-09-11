from __future__ import annotations

from dataclasses import asdict
import ast
import json
from pathlib import Path
from types import SimpleNamespace

from test_raw_measurement_replay import raw_measurement_rows

from host.otis_tools import adaptive_hybrid_replay as replay_module
from host.otis_tools.adaptive_hybrid_analyze import (
    _authoritative_csvs_exact,
    _d10_isolated,
    _validate_manifest_csvs,
)
from host.otis_tools.adaptive_hybrid_policy import (
    AdaptiveHybridObservation,
    AdaptiveHybridPhasePriorityController,
    load_policy,
)
from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CsvValidationContext, validate_csv


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
RAW_HEADER = (
    "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,"
    "capture_domain,flags"
)


def test_raw_event_contract_binds_evt_to_d10_and_ref_to_d14(tmp_path: Path) -> None:
    output = tmp_path / "raw_events.csv"
    parser_errors: list[str] = []
    with CsvRecordSplitter(
        {"raw_events_v1": output}, on_parser_error=parser_errors.append
    ) as splitter:
        assert splitter.process_line("EVT,1,1,0,R,1000000,rp2040_monotonic_us32,0")
        assert splitter.process_line("REF,1,2,1,R,1000000,rp2040_monotonic_us32,0")
        assert splitter.process_line("EVT,1,3,1,R,1000001,rp2040_monotonic_us32,0") is None
        assert splitter.process_line("REF,1,4,0,R,2000000,rp2040_monotonic_us32,0") is None
    assert parser_errors == [
        "EVT must use channel_id=0; got 1",
        "REF must use channel_id=1; got 0",
    ]

    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        RAW_HEADER
        + "\nEVT,1,1,1,R,1000000,rp2040_monotonic_us32,0"
        + "\nREF,1,2,0,R,2000000,rp2040_monotonic_us32,0\n",
        encoding="utf-8",
    )
    result = validate_csv(
        invalid,
        CsvValidationContext(
            contract="raw_events_v1",
            known_channels=frozenset({0, 1}),
            known_domains=frozenset({"rp2040_monotonic_us32"}),
        ),
    )
    assert any("EVT must be D10/CH0" in error for error in result.errors)
    assert any("REF must be D14/CH1" in error for error in result.errors)


def _controller_replay(event_rows: list[str], tmp_path: Path) -> list[dict]:
    events = tmp_path / (str(abs(hash(tuple(event_rows)))) + ".csv")
    events.write_text(RAW_HEADER + "\n" + "\n".join(event_rows) + "\n", encoding="utf-8")
    validation = validate_csv(
        events,
        CsvValidationContext(
            contract="raw_events_v1",
            known_channels=frozenset({0, 1}),
            known_domains=frozenset({"rp2040_monotonic_us32"}),
        ),
    )
    assert validation.ok, validation.errors

    controller = AdaptiveHybridPhasePriorityController(load_policy())
    decisions = []
    for timestamp_s, opening, closing in ((600, 0, 600), (1200, 600, 1200)):
        decisions.append(
            asdict(
                controller.decide(
                    AdaptiveHybridObservation(
                        timestamp_s=timestamp_s,
                        timestamp_ticks=timestamp_s * 1_000_000,
                        capture_session=1,
                        source_first_sequence=opening,
                        source_last_sequence=closing,
                        dac_epoch=controller.dac_epoch,
                        applied_code=controller.applied_code,
                        accumulated_edge_error_counts=-1,
                        tight_state="TIGHT_INSIDE",
                        phase_epoch=1,
                        relative_phase_cycles=-4,
                        frequency_estimator_id=(
                            "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"
                        ),
                    )
                )
            )
        )
    return decisions


def test_d10_absence_noise_and_overflow_cannot_change_control(tmp_path: Path) -> None:
    variants = (
        [],
        ["EVT,1,1,0,R,1000000,rp2040_monotonic_us32,0"],
        [
            "EVT,1,1,0,R,1000000,rp2040_monotonic_us32,0",
            "EVT,1,2,0,F,1000001,rp2040_monotonic_us32,0",
            "EVT,1,3,0,R,1000002,rp2040_monotonic_us32,32",
        ],
    )
    decisions = [_controller_replay(rows, tmp_path) for rows in variants]
    assert decisions[1:] == decisions[:-1]


def test_invalid_d10_is_diagnostic_only_in_actual_measurement_replay(
    monkeypatch,
) -> None:
    files = [
        {"contract": "count_observations_v1", "path": "counts.csv"},
        {"contract": "pps_snapshots_v1", "path": "snapshots.csv"},
        {"contract": "raw_events_v1", "record_type": "REF", "path": "ref.csv"},
        {"contract": "raw_events_v1", "record_type": "EVT", "path": "evt.csv"},
        {"contract": "estimates_v2", "path": "estimates.csv"},
    ]
    rows = raw_measurement_rows()
    rows["evt.csv"] = [{"record_type": "EVT", "channel_id": "99"}]
    monkeypatch.setattr(
        replay_module, "_read_csv", lambda path: rows[path.name]
    )
    exact, report, _ = replay_module._measurement_replay(
        SimpleNamespace(root=Path("/unused"), files=files),
        {"transaction_identities": {"estimator_sha256": "a" * 64}},
    )
    assert exact is True
    assert report["D10"] == {
        "row_count": 1,
        "channel_exact": False,
        "local_error": None,
        "authority": "evidence_only",
        "enters_D14_D8_replay": False,
    }

    def unreadable_d10(path: Path):
        if path.name == "evt.csv":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return rows[path.name]

    monkeypatch.setattr(replay_module, "_read_csv", unreadable_d10)
    exact, report, _ = replay_module._measurement_replay(
        SimpleNamespace(root=Path("/unused"), files=files),
        {"transaction_identities": {"estimator_sha256": "a" * 64}},
    )
    assert exact is True
    assert report["D10"]["channel_exact"] is False
    assert report["D10"]["local_error"].startswith("UnicodeDecodeError:")


def test_measurement_replay_uses_firmware_binary64_projection_before_serialization(
    monkeypatch,
) -> None:
    files = [
        {"contract": "count_observations_v1", "path": "counts.csv"},
        {"contract": "pps_snapshots_v1", "path": "snapshots.csv"},
        {"contract": "raw_events_v1", "record_type": "REF", "path": "ref.csv"},
        {"contract": "raw_events_v1", "record_type": "EVT", "path": "evt.csv"},
        {"contract": "estimates_v2", "path": "estimates.csv"},
    ]
    rows = raw_measurement_rows([9_999_999] + [10_000_000] * 599)
    monkeypatch.setattr(replay_module, "_read_csv", lambda path: rows[path.name])
    manifest = SimpleNamespace(root=Path("/unused"), files=files)
    identity = {"transaction_identities": {"estimator_sha256": "a" * 64}}

    exact, report, _ = replay_module._measurement_replay(manifest, identity)

    assert exact is True
    assert report["calculation_domain"] == (
        "firmware_ieee754_binary64_then_fixed_12_decimal"
    )
    assert report["comparisons"][0]["pass"] is True

    rows = raw_measurement_rows([10_000_001] + [10_000_000] * 599)
    rows["estimates.csv"][0]["frequency_estimate_hz"] = "10000000.001666666940"
    rows["estimates.csv"][0]["frequency_error_hz"] = "0.001666666940"
    exact, report, _ = replay_module._measurement_replay(manifest, identity)
    assert exact is True
    assert report["comparisons"][0]["pass"] is True

    rows = raw_measurement_rows([9_999_999] + [10_000_000] * 599)
    rows["estimates.csv"][0]["frequency_estimate_hz"] = "9999999.998333333333"
    rows["estimates.csv"][0]["frequency_error_hz"] = "-0.001666666667"
    exact, report, _ = replay_module._measurement_replay(manifest, identity)
    assert exact is False
    assert report["comparisons"][0]["pass"] is False


def test_invalid_d10_csv_cannot_fail_authoritative_analyzer_gate(
    tmp_path: Path,
) -> None:
    ref = tmp_path / "ref.csv"
    evt = tmp_path / "evt.csv"
    ref.write_text(
        RAW_HEADER + "\nREF,1,1,1,R,1000000,rp2040_monotonic_us32,0\n",
        encoding="utf-8",
    )
    evt.write_bytes(b"\xffinvalid D10 evidence")
    results = _validate_manifest_csvs(
        SimpleNamespace(
            root=tmp_path,
            files=[
                {"contract": "raw_events_v1", "record_type": "REF", "path": ref.name},
                {"contract": "raw_events_v1", "record_type": "EVT", "path": evt.name},
            ],
            known_channels=frozenset({0, 1}),
            known_domains=frozenset({"rp2040_monotonic_us32"}),
        )
    )
    assert results["raw_events_v1:REF"]["exact"] is True
    assert results["raw_events_v1:EVT"]["exact"] is False
    assert results["raw_events_v1:EVT"]["authority"] == "fail_local"
    assert _authoritative_csvs_exact(results) is True


def test_absent_d10_does_not_claim_entry_into_d14_d8_replay() -> None:
    section = {
        "external_event_input": {
            "pin": "D10",
            "authority": "evidence_only",
            "control_eligible": False,
            "terminal_eligible": False,
        }
    }
    report = {
        "D10": {"row_count": 0, "channel_exact": True, "local_error": None}
    }
    assert _d10_isolated(section, report) is True


def test_control_interfaces_have_no_external_event_authority_fields() -> None:
    for relative in (
        "host/otis_tools/adaptive_hybrid_policy.py",
        "host/otis_tools/adaptive_hybrid_transactions.py",
        "host/otis_tools/adaptive_hybrid_supervisor.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        identifiers = {
            node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        identifiers.update(
            node.arg.lower() for node in ast.walk(tree) if isinstance(node, ast.arg)
        )
        assert not {
            name
            for name in identifiers
            if "d10" in name or "external_event" in name or name.startswith("evt")
        }, relative


def test_fixed_firmware_preserves_d10_seam_without_claiming_a_backend() -> None:
    board = (FIRMWARE / "otis_board.h").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(encoding="utf-8")
    capture_irq = (FIRMWARE / "otis_capture_irq.cpp").read_text(encoding="utf-8")
    reference_init = sketch[
        sketch.index("void boot_phase_pps_input_init(void)") :
        sketch.index("void boot_phase_peripherals_init(void)")
    ]
    assert "OTIS_PIN_EXTERNAL_EVENT = D10" in board
    assert "OTIS_PIN_PPS_REFERENCE = D14" in board
    assert "otis_capture_irq_begin_d14_reference" in reference_init
    assert "OTIS_CHANNEL_PPS_REFERENCE" in capture_irq
    assert "OTIS_PIN_PPS_REFERENCE" in capture_irq
    capture_init = sketch[
        sketch.index("void boot_phase_capture_init(void)") :
        sketch.index("void boot_phase_timer_init(void)")
    ]
    assert "OTIS_PIN_EXTERNAL_EVENT" not in capture_init

    manifest = json.loads(
        (ROOT / "firmware/arduino/firmware_build_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    capability = manifest["capabilities"]["external_event_capture"]
    assert capability == {
        "pin": "D10",
        "channel": "CH0",
        "status": "not_implemented",
        "isolation_claimed": False,
        "control_authority": False,
        "terminal_authority": False,
    }
