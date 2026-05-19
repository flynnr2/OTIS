from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.h1_characterize import analyze_run, characterize_run, render_report


def _write_synthetic_run(
    run_dir: Path,
    *,
    include_voltage: bool = True,
    include_second_step: bool = True,
    include_environment: bool = False,
) -> None:
    (run_dir / "csv").mkdir(parents=True)
    (run_dir / "reports").mkdir()
    (run_dir / "plots").mkdir()
    manifest = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "stage": "OPEN_LOOP",
        "h_phase": "H1",
        "capture_type": "dac_manual_sweep",
        "oscillator": {"nominal_frequency_hz": 10_000_000},
        "safety_limits": {
            "control_voltage_min_v": 0.5,
            "control_voltage_max_v": 2.5,
        },
        "channels": [{"channel_id": 2, "role": "ocxo_observation"}],
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_ocxo_open_loop", "nominal_hz": 10_000_000},
        ],
        "files": [
            {"path": "csv/cnt.csv", "contract": "count_observations_v1"},
            {"path": "csv/dac_steps.csv", "contract": "dac_steps_v1"},
            *([{"path": "csv/environment.csv", "contract": "environment_v1"}] if include_environment else []),
        ],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
    ]
    seq = 1
    for second, count in [
        (1, 10_000_000),
        (2, 10_000_010),
        (3, 10_000_020),
        (4, 10_000_100),
        (5, 10_000_180),
        (6, 10_000_200),
        (7, 10_000_200),
    ]:
        open_ticks = second * 16_000_000
        close_ticks = (second + 1) * 16_000_000
        count_rows.append(
            f"CNT,1,{seq},2,{open_ticks},{close_ticks},rp2040_timer0,{count},R,h1_ocxo_open_loop,16"
        )
        seq += 1
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")

    voltage_1 = "1.0" if include_voltage else ""
    voltage_2 = "1.1" if include_voltage else ""
    dac_rows = [
        "record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,dac_code_applied,dac_code_clamped,dac_voltage_measured_v,ocxo_tune_voltage_measured_v,dwell_ms,event,flags",
        f"DAC,1,1,0,0,32768,32768,0,{voltage_1},{voltage_1},3000,start,0",
    ]
    if include_second_step:
        dac_rows.append(f"DAC,1,2,3500,1,33768,33768,0,{voltage_2},{voltage_2},3000,set,0")
    (run_dir / "csv" / "dac_steps.csv").write_text("\n".join(dac_rows) + "\n", encoding="utf-8")

    if include_environment:
        env_rows = [
            "record_type,schema_version,env_seq,timestamp_ticks,observation_domain,source,role,temperature_c,relative_humidity_pct,pressure_pa,flags",
            "ENV,1,1,0,rp2040_timer0,sht4x,vcocxo_near,30.000,45.000,,0",
            "ENV,1,2,32000000,rp2040_timer0,sht4x,vcocxo_near,30.200,45.100,,0",
            "ENV,1,3,64000000,rp2040_timer0,sht4x,vcocxo_near,30.500,45.200,,0",
            "ENV,1,4,96000000,rp2040_timer0,sht4x,vcocxo_near,30.800,45.300,,0",
            "ENV,1,5,112000000,rp2040_timer0,bmp280,pressure_reference,31.200,,100800.000,0",
        ]
        (run_dir / "csv" / "environment.csv").write_text("\n".join(env_rows) + "\n", encoding="utf-8")


def test_h1_characterize_ppm_and_voltage_slope(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1"
    _write_synthetic_run(run_dir)

    analysis = analyze_run(run_dir)

    assert analysis.points[0].median_hz == 10_000_005
    assert analysis.points[0].median_ppm == 0.5
    assert round(analysis.slopes[0].hz_per_v or 0, 6) == 1750.0
    assert round(analysis.slopes[0].ppm_per_v or 0, 6) == 175.0


def test_h1_characterize_missing_voltage_uses_code_slope(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_missing_voltage"
    _write_synthetic_run(run_dir, include_voltage=False)

    analysis = analyze_run(run_dir)

    assert analysis.slopes[0].hz_per_v is None
    assert analysis.slopes[0].ppm_per_v is None
    assert analysis.slopes[0].hz_per_code == 0.175
    assert analysis.slopes[0].ppm_per_code == 0.0175


def test_h1_characterize_insufficient_settling_is_explicit(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_one_step"
    _write_synthetic_run(run_dir, include_second_step=False)

    analysis = analyze_run(run_dir)

    assert analysis.settling[0].response_90_s is None
    assert "insufficient data" in analysis.settling[0].note


def test_h1_characterize_writes_report_csv_and_supported_plots(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_outputs"
    _write_synthetic_run(run_dir)

    analysis, report_path, points_path, plots = characterize_run(run_dir)
    report = report_path.read_text(encoding="utf-8")

    assert report_path.exists()
    assert points_path.exists()
    assert "SW2 Readiness" in report
    assert "open_loop_slope_known: true" in report
    assert "Center-Bracketed Slopes" in report
    assert "measured_hz = counted_edges / gate_seconds" in report
    assert render_report(analysis)
    assert run_dir / "plots" / "dac_code_vs_hz.png" in plots
    assert run_dir / "plots" / "dac_voltage_vs_ppm.png" in plots
    assert (run_dir / "plots" / "dac_code_vs_hz.png").read_bytes().startswith(b"\x89PNG")
    assert (run_dir / "csv" / "h1_center_bracketed_slopes.csv").exists()


def test_h1_characterize_reports_near_vcocxo_temperature(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_environment"
    _write_synthetic_run(run_dir, include_environment=True)

    analysis, report_path, points_path, plots = characterize_run(run_dir)
    report = report_path.read_text(encoding="utf-8")
    points_csv = points_path.read_text(encoding="utf-8")

    assert len(analysis.environment_samples) == 5
    assert round(analysis.points[0].env_temperature_delta_c or 0, 6) == 0.2
    assert "Near-VCOCXO Temperature" in report
    assert "source=sht4x role=vcocxo_near" in report
    assert "env_temperature_delta_c" in points_csv
    assert run_dir / "plots" / "vcocxo_temperature_vs_elapsed.png" in plots
    assert run_dir / "plots" / "vcocxo_temperature_vs_ppm.png" in plots


def test_h1_characterize_reports_center_bracketed_slope(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_center_bracketed"
    _write_synthetic_run(run_dir, include_second_step=False)
    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
        "CNT,1,1,2,0,16000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
        "CNT,1,2,2,16000000,32000000,rp2040_timer0,10000002,R,h1_ocxo_open_loop,16",
        "CNT,1,3,2,64000000,80000000,rp2040_timer0,10000200,R,h1_ocxo_open_loop,16",
        "CNT,1,4,2,80000000,96000000,rp2040_timer0,10000202,R,h1_ocxo_open_loop,16",
        "CNT,1,5,2,112000000,128000000,rp2040_timer0,10000010,R,h1_ocxo_open_loop,16",
    ]
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")
    dac_rows = [
        "record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,dac_code_applied,dac_code_clamped,dac_voltage_measured_v,ocxo_tune_voltage_measured_v,dwell_ms,event,flags",
        "DAC,1,1,0,0,32768,32768,0,1.0,1.0,3000,dwell_start,0",
        "DAC,1,2,3000,1,33768,33768,0,1.1,1.1,3000,dwell_start,0",
        "DAC,1,3,6000,2,32768,32768,0,1.0,1.0,3000,dwell_start,0",
    ]
    (run_dir / "csv" / "dac_steps.csv").write_text("\n".join(dac_rows) + "\n", encoding="utf-8")

    analysis, report_path, _, _ = characterize_run(run_dir)
    report = report_path.read_text(encoding="utf-8")
    csv_text = (run_dir / "csv" / "h1_center_bracketed_slopes.csv").read_text(encoding="utf-8")

    assert len(analysis.center_bracketed_slopes) == 1
    estimate = analysis.center_bracketed_slopes[0]
    assert estimate.center_code == 32768
    assert estimate.target_code == 33768
    assert estimate.center_drift_hz == 9
    assert estimate.target_delta_hz == 195.5
    assert estimate.hz_per_code == 0.1955
    assert "target_delta_hz=195.5" in report
    assert "h1_center_bracketed_slopes.csv" in report
    assert "0.1955" in csv_text


def test_h1_characterize_uses_final_segment_and_skips_flagged_zero_counts(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_long"
    _write_synthetic_run(run_dir, include_second_step=False)
    wrap = (1 << 32) * 16
    rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
        "CNT,1,10,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
        "CNT,1,1,2,16000000,32000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
        "CNT,1,2,2,32000000,48000000,rp2040_timer0,0,R,h1_ocxo_open_loop,32784",
        f"CNT,1,3,2,{wrap - 16_000_000},{wrap},rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
        "CNT,1,4,2,0,16000000,rp2040_timer0,10000010,R,h1_ocxo_open_loop,16",
    ]
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    analysis = analyze_run(run_dir)

    assert len(analysis.count_windows) == 3
    assert analysis.count_windows[0].seq == 1
    assert analysis.count_windows[-1].elapsed_s > analysis.count_windows[0].elapsed_s
    assert any("invalid or startup-suspect" in warning for warning in analysis.warnings)
    assert any("using the final segment" in warning for warning in analysis.warnings)


def test_h1_characterize_handles_count_window_crossing_timer_wrap(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_wrap_crossing"
    _write_synthetic_run(run_dir, include_second_step=False)
    wrap = (1 << 32) * 16
    rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
        f"CNT,1,1,2,{wrap - 8_000_000},8000000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
        "CNT,1,2,2,8000000,24000000,rp2040_timer0,10000020,R,h1_ocxo_open_loop,16",
    ]
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    analysis = analyze_run(run_dir)

    assert len(analysis.count_windows) == 2
    assert analysis.count_windows[0].gate_seconds == 1
    assert analysis.count_windows[1].elapsed_s > analysis.count_windows[0].elapsed_s


def _write_startup_gate_run(run_dir: Path, rows: list[tuple[int, int, int]]) -> None:
    _write_synthetic_run(run_dir, include_second_step=False)
    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
    ]
    for seq, counted_edges, flags in rows:
        open_ticks = (seq - 1) * 160_000_000
        close_ticks = seq * 160_000_000
        count_rows.append(
            f"CNT,1,{seq},2,{open_ticks},{close_ticks},rp2040_timer0,{counted_edges},R,h1_ocxo_open_loop,{flags}"
        )
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")


def test_h1_startup_gate_accepts_startup_local_bad_windows(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_startup_local"
    rows = [(seq, 0, 528) for seq in range(1, 21)]
    rows.extend((seq, 100_000_000, 16) for seq in range(21, 66))
    _write_startup_gate_run(run_dir, rows)

    analysis = analyze_run(run_dir)
    report = render_report(analysis)

    assert analysis.startup_control.invalid_window_count == 20
    assert analysis.startup_control.first_control_eligible_elapsed_s == 625
    assert analysis.startup_control.valid_for_control
    assert "fc0_valid_for_control: true" in report
    assert "startup_discarded_windows: 60" in report
    assert len(analysis.count_windows) == 45


def test_h1_startup_gate_flags_post_inhibit_bad_window(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_post_inhibit_bad"
    rows = [(seq, 100_000_000, 16) for seq in range(1, 63)]
    rows.append((63, 0, 528))
    rows.extend((seq, 100_000_000, 16) for seq in range(64, 68))
    _write_startup_gate_run(run_dir, rows)

    analysis = analyze_run(run_dir)

    assert analysis.startup_control.first_post_inhibit_bad_elapsed_s == 625
    assert not analysis.startup_control.valid_for_control
    assert analysis.startup_control.note.startswith("not control-eligible")


def test_h1_startup_gate_requires_clean_windows_after_inhibit(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_no_clean_after_inhibit"
    rows = [(seq, 100_000_000, 16) for seq in range(1, 62)]
    _write_startup_gate_run(run_dir, rows)

    analysis = analyze_run(run_dir)

    assert analysis.startup_control.first_control_eligible_elapsed_s is None
    assert not analysis.startup_control.valid_for_control


def test_h1_startup_gate_allows_zero_startup_discard_for_long_clean_windows(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_zero_startup_discard"
    _write_synthetic_run(run_dir, include_second_step=False)
    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
    ]
    for seq in range(1, 4):
        open_ticks = (seq - 1) * 19_200_000_000
        close_ticks = seq * 19_200_000_000
        count_rows.append(
            f"CNT,1,{seq},2,{open_ticks},{close_ticks},rp2040_timer0,12000000000,R,h1_ocxo_open_loop,16"
        )
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")

    analysis = analyze_run(run_dir)

    assert analysis.startup_control.startup_discarded_window_count == 0
    assert analysis.startup_control.first_control_eligible_elapsed_s == 3000
    assert analysis.startup_control.valid_for_control
