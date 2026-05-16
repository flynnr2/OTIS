from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

from host.otis_tools.capture_serial import capture_serial
from host.otis_tools.h1_dac_sweep import build_builtin_profile, validate_step
from host.otis_tools.report_run import build_summary, render_report
from host.otis_tools.run_loader import load_manifest
from host.otis_tools.validate_run import validate_run

EXAMPLE = Path("examples/h0_pps_tcxo_synthetic")
TEMPLATE_EXAMPLES = [
    Path("examples/h0_usb_synthetic"),
    Path("examples/h0_gpio_loopback"),
    Path("examples/h0_gps_pps"),
    Path("examples/h0_pps_tcxo_real"),
]
H1_TEMPLATE = Path("runs/h1_open_loop/dac_manual_sweep/_template")


def _copy_example(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    shutil.copytree(EXAMPLE, run_dir)
    return run_dir


def _rewrite_csv_cell(path: Path, row_index: int, field_name: str, value: str) -> None:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    assert fieldnames is not None
    rows[row_index][field_name] = value
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_manifest() -> None:
    manifest = load_manifest(EXAMPLE)
    assert manifest.run_id == "h0_pps_tcxo_synthetic_001"
    assert manifest.known_channels == frozenset({0, 1, 2})
    assert "rp2040_timer0" in manifest.known_domains
    assert manifest.stage == "SW1"
    assert manifest.h_phase == "H0"
    assert manifest.capture_mode == "synthetic_usb"
    assert manifest.firmware_version == "SW1"


def test_validate_example_run() -> None:
    assert validate_run(EXAMPLE) == 0


def test_validate_bringup_templates() -> None:
    for run_dir in TEMPLATE_EXAMPLES:
        assert validate_run(run_dir) == 0


def test_validate_h1_template() -> None:
    assert validate_run(H1_TEMPLATE) == 0


def test_validate_run_accepts_h1_count_source_domain(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1"
    shutil.copytree(H1_TEMPLATE, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "h1_count_test"
    manifest["template"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "manifest.json").unlink()
    (run_dir / "csv" / "cnt.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
                "CNT,1,1,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0


def test_validate_run_accepts_h1_rp2040_timer_wrap(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_wrap"
    shutil.copytree(H1_TEMPLATE, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "h1_wrap_test"
    manifest["template"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "manifest.json").unlink()
    wrap = (1 << 32) * 16
    (run_dir / "csv" / "ref.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
                f"REF,1,1000,1,R,{wrap - 16_000_000},rp2040_timer0,16",
                "REF,1,1001,1,R,0,rp2040_timer0,16",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "csv" / "cnt.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
                f"CNT,1,1,2,{wrap - 2_000_000},{wrap - 1_000_000},rp2040_timer0,625000,R,h1_ocxo_open_loop,16",
                "CNT,1,2,2,1000000,2000000,rp2040_timer0,625000,R,h1_ocxo_open_loop,16",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0
    summary = build_summary(run_dir)
    assert summary["reference_pps_summary"]["domains"]["rp2040_timer0"]["timestamp_wrap_count"] == 1


def test_h1_dac_sweep_profiles_are_conservative() -> None:
    steps = build_builtin_profile("tiny_plus_minus_2", 0x7000, 0x9000, dwell_ms=5000)

    assert [step.code for step in steps] == [
        0x8000,
        0x8400,
        0x8000,
        0x7C00,
        0x8000,
        0x8800,
        0x8000,
        0x7800,
        0x8000,
    ]
    assert all(0x7000 <= step.code <= 0x9000 for step in steps)
    assert all(step.dwell_ms == 5000 for step in steps)


def test_h1_dac_sweep_profile_rejects_missing_or_narrow_clamps() -> None:
    for min_code, max_code in ((0x0000, 0xFFFF), (0x8000, 0x8001)):
        try:
            build_builtin_profile("tiny_plus_minus_2", min_code, max_code)
        except ValueError as exc:
            assert "clamps" in str(exc)
        else:
            raise AssertionError("unsafe H1 DAC sweep profile was accepted")

    assert validate_step(0x8000, 0x7000, 0x9000)
    assert not validate_step(0x6FFF, 0x7000, 0x9000)


def test_validate_run_accepts_gps_pps_bringup_records(tmp_path: Path) -> None:
    run_dir = tmp_path / "gps_pps"
    shutil.copytree(Path("examples/h0_gps_pps"), run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "gps_pps_test"
    manifest["template"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "raw_events.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
                "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "health.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
                "STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0


def test_validate_run_accepts_sw1_5a_pio_capture_mode(tmp_path: Path) -> None:
    run_dir = tmp_path / "gps_pps_pio"
    shutil.copytree(Path("examples/h0_gps_pps"), run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "gps_pps_pio_test"
    manifest["template"] = False
    manifest["capture_mode"] = "pio_fifo_cpu_timestamped"
    manifest["known_limitations"] = [
        "PIO detects rising edges; firmware attaches timestamps while draining the FIFO.",
        "DMA is intentionally deferred to SW1.5b.",
    ]
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "raw_events.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
                "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "health.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
                "STS,1,1,1,rp2040_timer0,capture,mode,pio_fifo_cpu_timestamped,INFO,32768",
                "STS,1,2,2,rp2040_timer0,build,capture_backend,pio_fifo,INFO,32768",
                "STS,1,3,3,rp2040_timer0,capture,pio_init,ok,INFO,32768",
                "STS,1,4,4,rp2040_timer0,capture,pio_gpio,26,INFO,32768",
                "STS,1,5,5,rp2040_timer0,capture,pio_fifo_drained_event_count,2,INFO,0",
                "STS,1,6,6,rp2040_timer0,capture,pio_fifo_overflow_drop_count,0,INFO,0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0

    summary = build_summary(run_dir)
    report = render_report(run_dir)
    assert summary["run_identity"]["capture_mode"] == "pio_fifo_cpu_timestamped"
    assert summary["health_status_summary"]["latest_capture_status"]["pio_init"] == "ok"
    assert "SW1.5a capture mode: pio_fifo_cpu_timestamped" in report
    assert "latest_capture_status" in report


def test_capture_serial_splits_records(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "captured"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "\n".join(
                [
                    "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
                    "STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768",
                    "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                    "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                    "",
                ]
            )
        ),
    )

    assert capture_serial(run_dir, Path("examples/h0_gps_pps"), "captured_gps_pps") == 0
    assert validate_run(run_dir) == 0
    assert not (run_dir / "capture_in_progress.flag").exists()


def test_capture_serial_splits_h1_evt_and_ref_files(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "captured_h1"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "\n".join(
                [
                    "EVT,1,1000,0,R,16000000,rp2040_timer0,0",
                    "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                    "CNT,1,1,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
                    "STS,1,1,1,rp2040_timer0,system,mode,H1_OCXO_OBSERVE_OPEN_LOOP,INFO,32768",
                    "DAC,1,1,1000,-1,32768,32768,0,,,5000,start,0",
                    "DAC,1,2,2000,0,32768,32768,0,,,5000,fc0_window,16",
                    "",
                ]
            )
        ),
    )

    assert capture_serial(run_dir, H1_TEMPLATE, "captured_h1") == 0
    assert "EVT,1,1000" in (run_dir / "csv" / "evt.csv").read_text(encoding="utf-8")
    assert "REF,1,1001" in (run_dir / "csv" / "ref.csv").read_text(encoding="utf-8")
    assert "EVT,1,1000" not in (run_dir / "csv" / "ref.csv").read_text(encoding="utf-8")
    dac_steps = (run_dir / "csv" / "dac_steps.csv").read_text(encoding="utf-8")
    assert "DAC,1,1,1000,-1,32768,32768,0,,,5000,start,0" in dac_steps
    assert "DAC,1,2,2000,0,32768,32768,0,,,5000,fc0_window,16" in dac_steps
    assert validate_run(run_dir) == 0


def test_validate_run_accepts_h1_dac_safety_rejection(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_sweep_reject"
    shutil.copytree(H1_TEMPLATE, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "h1_sweep_reject"
    manifest["template"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "manifest.json").unlink()
    (run_dir / "csv" / "dac_steps.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,dac_code_applied,dac_code_clamped,dac_voltage_measured_v,ocxo_tune_voltage_measured_v,dwell_ms,event,flags",
                "DAC,1,1,1000,-1,65535,36864,1,,,5000,safety_reject,32768",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0


def test_verify_h1_manual_log_command(tmp_path: Path) -> None:
    raw_log = tmp_path / "h1.log"
    run_dir = tmp_path / "h1_run"
    raw_log.write_text(
        "\n".join(
            [
                "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
                "STS,1,1,1,rp2040_timer0,system,mode,H1_OCXO_OBSERVE_OPEN_LOOP,INFO,32768",
                "STS,1,2,2,rp2040_timer0,system,h1_open_loop,true,WARN,32768",
                "STS,1,3,3,rp2040_timer0,control,gpsdo_steering,not_implemented,INFO,32768",
                "STS,1,4,4,rp2040_timer0,build,enable_dac_ad5693r,1,INFO,32768",
                "STS,1,5,5,rp2040_timer0,dac,enabled,true,INFO,32768",
                "STS,1,6,6,rp2040_timer0,dac,initialized,true,INFO,0",
                "STS,1,7,7,rp2040_timer0,dac,init,ok,INFO,0",
                "STS,1,8,8,rp2040_timer0,capture,tcxo_counter_backend,rp2040_fc0_gpin0,INFO,32768",
                "STS,1,9,9,rp2040_timer0,command,h1_help,DAC?_DAC_SET_code_DAC_MID_DAC_ZERO_DAC_LIMITS?_FC0?_HELP,INFO,0",
                "STS,1,10,10,rp2040_timer0,dac,min_code,0x7000,INFO,32768",
                "STS,1,11,11,rp2040_timer0,dac,max_code,0x9000,INFO,32768",
                "STS,1,12,12,rp2040_timer0,dac,accepted_code,0x8000,INFO,0",
                "STS,1,13,13,rp2040_timer0,dac,accepted_code,0x7000,INFO,0",
                "STS,1,14,14,rp2040_timer0,dac,rejected_code,0x0000,WARN,32768",
                "STS,1,15,15,rp2040_timer0,dac,rejected_code,0xFFFF,WARN,32768",
                "STS,1,16,16,rp2040_timer0,dac,set,rejected_outside_clamps,WARN,32768",
                "STS,1,17,17,rp2040_timer0,fc0,valid,true,INFO,0",
                "CNT,1,1,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
                "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host.otis_tools.verify_h1_manual_log",
            str(raw_log),
            "--run-dir",
            str(run_dir),
        ],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "OK H1 manual command checks" in result.stdout
    assert "CNT,1,1,2" in (run_dir / "csv" / "cnt.csv").read_text(encoding="utf-8")


def test_verify_h1_manual_log_skips_initial_two_second_pps(tmp_path: Path) -> None:
    raw_log = tmp_path / "h1_first_pps_2s.log"
    run_dir = tmp_path / "h1_first_pps_2s_run"
    raw_log.write_text(
        "\n".join(
            [
                "STS,1,1,1,rp2040_timer0,system,mode,H1_OCXO_OBSERVE_OPEN_LOOP,INFO,32768",
                "STS,1,2,2,rp2040_timer0,system,h1_open_loop,true,WARN,32768",
                "STS,1,3,3,rp2040_timer0,control,gpsdo_steering,not_implemented,INFO,32768",
                "STS,1,4,4,rp2040_timer0,build,enable_dac_ad5693r,1,INFO,32768",
                "STS,1,5,5,rp2040_timer0,dac,enabled,true,INFO,32768",
                "STS,1,6,6,rp2040_timer0,dac,initialized,true,INFO,0",
                "STS,1,7,7,rp2040_timer0,dac,init,ok,INFO,0",
                "STS,1,8,8,rp2040_timer0,capture,tcxo_counter_backend,rp2040_fc0_gpin0,INFO,32768",
                "STS,1,9,9,rp2040_timer0,command,h1_help,DAC?_DAC_SET_code_DAC_MID_DAC_ZERO_DAC_LIMITS?_FC0?_HELP,INFO,0",
                "STS,1,10,10,rp2040_timer0,dac,min_code,0x7000,INFO,32768",
                "STS,1,11,11,rp2040_timer0,dac,max_code,0x9000,INFO,32768",
                "STS,1,12,12,rp2040_timer0,dac,accepted_code,0x8000,INFO,0",
                "STS,1,13,13,rp2040_timer0,dac,accepted_code,0x7000,INFO,0",
                "STS,1,14,14,rp2040_timer0,dac,rejected_code,0x0000,WARN,32768",
                "STS,1,15,15,rp2040_timer0,dac,rejected_code,0xFFFF,WARN,32768",
                "STS,1,16,16,rp2040_timer0,dac,set,rejected_outside_clamps,WARN,32768",
                "STS,1,17,17,rp2040_timer0,fc0,valid,true,INFO,0",
                "CNT,1,1,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
                "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                "REF,1,1001,1,R,48000000,rp2040_timer0,16",
                "REF,1,1002,1,R,64000000,rp2040_timer0,16",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host.otis_tools.verify_h1_manual_log",
            str(raw_log),
            "--run-dir",
            str(run_dir),
        ],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "INFO skipped initial PPS intervals ticks: [32000000]" in result.stdout


def test_verify_h1_manual_log_allows_missing_dac(tmp_path: Path) -> None:
    raw_log = tmp_path / "h1_no_dac.log"
    run_dir = tmp_path / "h1_no_dac_run"
    raw_log.write_text(
        "\n".join(
            [
                "STS,1,1,1,rp2040_timer0,system,mode,H1_OCXO_OBSERVE_OPEN_LOOP,INFO,32768",
                "STS,1,2,2,rp2040_timer0,system,h1_open_loop,true,WARN,32768",
                "STS,1,3,3,rp2040_timer0,control,gpsdo_steering,not_implemented,INFO,32768",
                "STS,1,4,4,rp2040_timer0,build,enable_dac_ad5693r,1,INFO,32768",
                "STS,1,5,5,rp2040_timer0,dac,enabled,true,INFO,32768",
                "STS,1,6,6,rp2040_timer0,dac,initialized,false,WARN,0",
                "STS,1,7,7,rp2040_timer0,dac,init,failed,ERROR,32",
                "STS,1,8,8,rp2040_timer0,capture,tcxo_counter_backend,rp2040_fc0_gpin0,INFO,32768",
                "STS,1,9,9,rp2040_timer0,command,h1_help,DAC?_DAC_SET_code_DAC_MID_DAC_ZERO_DAC_LIMITS?_FC0?_HELP,INFO,0",
                "STS,1,10,10,rp2040_timer0,dac,min_code,0x7000,INFO,32768",
                "STS,1,11,11,rp2040_timer0,dac,max_code,0x9000,INFO,32768",
                "STS,1,12,12,rp2040_timer0,dac,requested_code,0x8000,INFO,0",
                "STS,1,13,13,rp2040_timer0,dac,requested_code,0x7000,INFO,0",
                "STS,1,14,14,rp2040_timer0,dac,requested_code,0x0000,INFO,0",
                "STS,1,15,15,rp2040_timer0,dac,requested_code,0xFFFF,INFO,0",
                "STS,1,16,16,rp2040_timer0,dac,set,rejected_not_initialized,WARN,32",
                "STS,1,17,17,rp2040_timer0,fc0,valid,true,INFO,0",
                "CNT,1,1,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host.otis_tools.verify_h1_manual_log",
            str(raw_log),
            "--run-dir",
            str(run_dir),
            "--allow-dac-init-fail",
        ],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "OK H1 manual command checks" in result.stdout


def test_render_report_mentions_contracts() -> None:
    report = render_report(EXAMPLE)
    assert "raw_events_v1" in report
    assert "count_observations_v1" in report
    assert "health_v1" in report
    assert "# OTIS Run Report" in report
    assert "stage: SW1" in report
    assert "capture_mode: synthetic_usb" in report
    assert "SW1 capture mode: irq_reconstructed" in report
    assert "## Validation Findings" in report
    assert "## Validation Warnings" in report
    assert "## Development Usefulness" in report


def test_render_report_handles_missing_optional_count_file() -> None:
    report = render_report(Path("examples/h0_gps_pps"))

    assert "## Count Observation Summary" in report
    assert "- not present" in report
    assert "keep_as_fixture: True" in report


def test_validate_run_warns_for_in_progress_and_missing_complete(tmp_path: Path, capsys) -> None:
    run_dir = _copy_example(tmp_path)
    (run_dir / "capture_in_progress.flag").touch()

    assert validate_run(run_dir) == 0
    captured = capsys.readouterr()

    assert "capture_in_progress.flag exists" in captured.err
    assert "COMPLETE marker is missing" in captured.err


def test_validate_run_accepts_complete_marker_without_warning(tmp_path: Path, capsys) -> None:
    run_dir = _copy_example(tmp_path)
    (run_dir / "COMPLETE").touch()

    assert validate_run(run_dir) == 0
    captured = capsys.readouterr()

    assert "COMPLETE marker is missing" not in captured.err


def test_validate_run_warns_for_missing_optional_artifact(tmp_path: Path, capsys) -> None:
    run_dir = _copy_example(tmp_path)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["files"].append({"path": "reports/extra.json", "contract": "health_v1", "optional": True})
    manifest["expected_artifacts"].append("reports/extra.json")
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert validate_run(run_dir) == 0
    captured = capsys.readouterr()

    assert "optional expected artifact is missing" in captured.err


def test_validate_run_reports_missing_manifest(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "no_manifest"
    run_dir.mkdir()

    assert validate_run(run_dir) == 1
    captured = capsys.readouterr()

    assert "missing manifest" in captured.err


def test_report_run_reports_malformed_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "bad_manifest"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("{not json}\n", encoding="utf-8")

    report = render_report(run_dir)

    assert "manifest_loaded: False" in report
    assert "manifest_error:" in report
    assert "not fixture-ready: manifest could not be loaded" in report


def test_validate_run_warns_for_empty_csv(tmp_path: Path, capsys) -> None:
    run_dir = _copy_example(tmp_path)
    (run_dir / "raw_events.csv").write_text(
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags\n",
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0
    captured = capsys.readouterr()

    assert "CSV has headers but no data rows" in captured.err


def test_render_report_summarizes_monotonicity_failure(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 1, "timestamp_ticks", "1")

    summary = build_summary(run_dir)
    report = render_report(run_dir)

    assert summary["raw_event_summary"]["timestamp_monotonic"] is False
    assert "timestamp_ticks are not monotonic" in report
    assert "keep_as_fixture: False" in report


def test_report_command_handles_malformed_csv_without_fatal_exit(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    with (run_dir / "raw_events.csv").open("a", encoding="utf-8") as handle:
        handle.write("EVT,1,1004,0,R,1632000100,rp2040_timer0,0,extra\n")

    result = subprocess.run(
        [sys.executable, "-m", "host.otis_tools.report_run", str(run_dir)],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "malformed row has too many columns" in result.stdout
    assert "row 5 has too many columns" in result.stdout


def test_report_command_writes_markdown_and_json(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    report_path = tmp_path / "summary.md"
    json_path = tmp_path / "summary.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "host.otis_tools.report_run",
            str(run_dir),
            "--output",
            str(report_path),
            "--json",
            str(json_path),
        ],
        check=False,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "# OTIS Run Report" in report_path.read_text(encoding="utf-8")
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert summary["row_counts"]["raw_events_v1"] == 4


def test_validate_run_rejects_bad_channel(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "channel_id", "99")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_non_monotonic_raw_timestamps(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 1, "timestamp_ticks", "1")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_malformed_rows(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    with (run_dir / "raw_events.csv").open("a", encoding="utf-8") as handle:
        handle.write("EVT,1,1004,0,R,1632000100,rp2040_timer0,0,extra\n")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_bad_pps_cadence(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 3, "timestamp_ticks", "1700000000")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_zero_count_without_flag(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "count_observations.csv", 0, "counted_edges", "0")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_reserved_flags(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "health.csv", 0, "flags", str(1 << 16))

    assert validate_run(run_dir) == 1


def test_validate_run_accepts_contract_edge_enums(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "edge", "B")
    _rewrite_csv_cell(run_dir / "count_observations.csv", 0, "source_edge", "B")

    assert validate_run(run_dir) == 0


def test_validate_run_rejects_invalid_edge(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "edge", "X")

    assert validate_run(run_dir) == 1


def test_validate_run_accepts_contract_health_severities(tmp_path: Path) -> None:
    for severity in ("INFO", "WARN", "ERROR", "FATAL"):
        run_dir = tmp_path / severity.lower()
        shutil.copytree(EXAMPLE, run_dir)
        _rewrite_csv_cell(run_dir / "health.csv", 0, "severity", severity)

        assert validate_run(run_dir) == 0


def test_validate_run_rejects_invalid_health_severity(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "health.csv", 0, "severity", "CRITICAL")

    assert validate_run(run_dir) == 1


def test_load_manifest_requires_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"schema_version": 1, "run_id": "empty", "files": []}),
        encoding="utf-8",
    )

    try:
        load_manifest(run_dir)
    except ValueError as exc:
        assert "at least one data file" in str(exc)
    else:
        raise AssertionError("load_manifest accepted an empty file list")
