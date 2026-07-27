from __future__ import annotations

import json
from pathlib import Path
import struct
import zlib

from host.otis_tools.h1_characterize import analyze_run, characterize_run, render_report
from host.otis_tools.pps_diagnostics import classify_pps_interval


def _read_png_rgb(path: Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    data = path.read_bytes()
    offset = 8
    width = height = 0
    compressed = bytearray()
    while offset < len(data):
        chunk_length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + chunk_length]
        offset += 12 + chunk_length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", chunk_data[:8])
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    raw = zlib.decompress(bytes(compressed))
    pixels: list[tuple[int, int, int]] = []
    stride = width * 3
    cursor = 0
    for _ in range(height):
        assert raw[cursor] == 0
        cursor += 1
        row = raw[cursor : cursor + stride]
        cursor += stride
        for index in range(0, len(row), 3):
            pixels.append((row[index], row[index + 1], row[index + 2]))
    return width, height, pixels


def _non_white_pixels(
    pixels: list[tuple[int, int, int]],
    width: int,
    *,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> int:
    count = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pixels[y * width + x] != (255, 255, 255):
                count += 1
    return count


def _write_synthetic_run(
    run_dir: Path,
    *,
    include_voltage: bool = True,
    include_second_step: bool = True,
    include_environment: bool = False,
    include_ref: bool = False,
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
            *([{"path": "csv/ref.csv", "contract": "raw_events_v1"}] if include_ref else []),
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

    if include_ref:
        ref_rows = [
            "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
            "REF,1,1,1,R,0,rp2040_timer0,16",
            "REF,1,2,1,R,15999920,rp2040_timer0,16",
            "REF,1,3,1,R,31999840,rp2040_timer0,16",
            "REF,1,4,1,R,47999760,rp2040_timer0,16",
        ]
        (run_dir / "csv" / "ref.csv").write_text("\n".join(ref_rows) + "\n", encoding="utf-8")


def test_h1_characterize_ppm_and_voltage_slope(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1"
    _write_synthetic_run(run_dir)

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.points[0].median_hz == 10_000_005
    assert analysis.points[0].median_ppm == 0.5
    assert round(analysis.slopes[0].hz_per_v or 0, 6) == 1750.0
    assert round(analysis.slopes[0].ppm_per_v or 0, 6) == 175.0


def test_h1_characterize_missing_voltage_uses_code_slope(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_missing_voltage"
    _write_synthetic_run(run_dir, include_voltage=False)

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.slopes[0].hz_per_v is None
    assert analysis.slopes[0].ppm_per_v is None
    assert analysis.slopes[0].hz_per_code == 0.175
    assert analysis.slopes[0].ppm_per_code == 0.0175


def test_h1_characterize_missing_voltage_uses_manifest_voltage_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_manifest_voltage"
    _write_synthetic_run(run_dir, include_voltage=False)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dac"] = {
        "nominal_code": 32768,
        "measured_output_min_v": 0.9,
        "measured_output_mid_v": 1.0,
        "measured_output_max_v": 1.2,
    }
    manifest["safety_limits"].update(
        {
            "dac_min_code": 31768,
            "dac_max_code": 33768,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.points[0].voltage_v == 1.0
    assert analysis.points[1].voltage_v == 1.2
    assert round(analysis.slopes[0].hz_per_v or 0, 6) == 875.0
    assert "used manifest measured DAC voltage model" in analysis.warnings[0]


def test_h1_characterize_insufficient_settling_is_explicit(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_one_step"
    _write_synthetic_run(run_dir, include_second_step=False)

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.settling[0].response_90_s is None
    assert "insufficient data" in analysis.settling[0].note


def test_h1_characterize_writes_report_csv_and_supported_plots(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_outputs"
    _write_synthetic_run(run_dir)

    analysis, report_path, points_path, plots = characterize_run(run_dir, settling_discard_s=0)
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
    width, height, pixels = _read_png_rgb(run_dir / "plots" / "dac_code_vs_hz.png")
    assert _non_white_pixels(pixels, width, x0=250, y0=10, x1=650, y1=55) > 50
    assert _non_white_pixels(pixels, width, x0=360, y0=500, x1=540, y1=535) > 20
    assert _non_white_pixels(pixels, width, x0=5, y0=120, x1=55, y1=420) > 50
    assert _non_white_pixels(pixels, width, x0=650, y0=75, x1=870, y1=115) > 50
    assert height == 540


def test_h1_characterize_uses_pps_calibrated_gate_rate(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_pps_calibrated"
    _write_synthetic_run(run_dir, include_second_step=False, include_ref=True)
    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
        "CNT,1,1,2,0,15999920,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
        "CNT,1,2,2,15999920,31999840,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
    ]
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")

    analysis, report_path, _, _ = characterize_run(run_dir, settling_discard_s=0)
    report = report_path.read_text(encoding="utf-8")

    assert analysis.pps_clock is not None
    assert analysis.pps_clock.tick_rate_hz == 15_999_920
    assert analysis.count_windows[0].gate_seconds == 1
    assert analysis.count_windows[0].measured_hz == 10_000_000
    assert analysis.count_windows[0].ppm == 0
    assert "PPS-Calibrated Clock" in report
    assert "gate_ticks / pps_calibrated_tick_rate" in report


def test_h1_characterize_local_pps_removes_injected_timer_rate_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_local_pps_drift"
    _write_synthetic_run(run_dir, include_second_step=False, include_ref=True)
    ref_rows = [
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
        "REF,1,1,1,R,0,rp2040_timer0,16",
        "REF,1,2,1,R,16000000,rp2040_timer0,16",
        "REF,1,3,1,R,32000000,rp2040_timer0,16",
        "REF,1,4,1,R,48001000,rp2040_timer0,16",
    ]
    (run_dir / "csv" / "ref.csv").write_text("\n".join(ref_rows) + "\n", encoding="utf-8")
    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
        "CNT,1,1,2,0,32000000,rp2040_timer0,20000000,R,h1_ocxo_open_loop,16",
        "CNT,1,2,2,32000000,48001000,rp2040_timer0,10000000,R,h1_ocxo_open_loop,16",
    ]
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.count_windows[1].estimator_mode == "LOCAL_PPS_INTERPOLATED"
    assert analysis.count_windows[1].estimator_valid
    assert analysis.count_windows[1].local_pps_gate_seconds == 1
    assert analysis.count_windows[1].measured_hz == 10_000_000
    assert analysis.count_windows[1].legacy_frequency_hz != analysis.count_windows[1].local_pps_frequency_hz


def test_h1_characterize_local_pps_does_not_interpolate_across_rejected_short_pps(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_local_pps_reject_short"
    _write_synthetic_run(run_dir, include_second_step=False, include_ref=True)
    ref_rows = [
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
        "REF,1,1,1,R,0,rp2040_timer0,16",
        "REF,1,2,1,R,16000000,rp2040_timer0,16",
        "REF,1,3,1,R,30400000,rp2040_timer0,16",
        "REF,1,4,1,R,32000000,rp2040_timer0,16",
        "REF,1,5,1,R,48000000,rp2040_timer0,16",
    ]
    (run_dir / "csv" / "ref.csv").write_text("\n".join(ref_rows) + "\n", encoding="utf-8")
    count_rows = [
        "record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags",
        "CNT,1,1,2,16000000,48000000,rp2040_timer0,20000000,R,h1_ocxo_open_loop,16",
    ]
    (run_dir / "csv" / "cnt.csv").write_text("\n".join(count_rows) + "\n", encoding="utf-8")

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.pps_anomalies
    assert analysis.count_windows[0].estimator_mode == "RUN_WIDE_TICK_RATE"
    assert not analysis.count_windows[0].estimator_valid
    assert "gate_crosses_invalid_or_missing_pps_segment" in analysis.count_windows[0].estimator_quality_flags


def test_h1_characterize_reports_near_vcocxo_temperature(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_environment"
    _write_synthetic_run(run_dir, include_environment=True)

    analysis, report_path, points_path, plots = characterize_run(run_dir, settling_discard_s=0)
    report = report_path.read_text(encoding="utf-8")
    points_csv = points_path.read_text(encoding="utf-8")

    assert len(analysis.environment_samples) == 5
    assert round(analysis.points[0].env_temperature_delta_c or 0, 6) == 0.2
    assert "Near-VCOCXO Temperature" in report
    assert "source=sht4x role=vcocxo_near" in report
    assert "env_temperature_delta_c" in points_csv
    assert run_dir / "plots" / "vcocxo_temperature_vs_elapsed.png" in plots
    assert run_dir / "plots" / "vcocxo_temperature_vs_ppm.png" in plots


def test_h1_characterize_unwraps_environment_timer_for_temperature_plot(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_environment_wrap"
    _write_synthetic_run(run_dir, include_environment=True)
    wrap = (1 << 32) * 16
    env_rows = [
        "record_type,schema_version,env_seq,timestamp_ticks,observation_domain,source,role,temperature_c,relative_humidity_pct,pressure_pa,flags",
        f"ENV,1,1,{wrap - 32000000},rp2040_timer0,sht4x,vcocxo_near,25.000,45.000,,0",
        f"ENV,1,2,{wrap - 16000000},rp2040_timer0,sht4x,vcocxo_near,25.100,45.100,,0",
        "ENV,1,3,0,rp2040_timer0,sht4x,vcocxo_near,25.200,45.200,,0",
        "ENV,1,4,16000000,rp2040_timer0,sht4x,vcocxo_near,25.300,45.300,,0",
        "ENV,1,5,32000000,rp2040_timer0,sht4x,vcocxo_near,25.400,45.400,,0",
    ]
    (run_dir / "csv" / "environment.csv").write_text("\n".join(env_rows) + "\n", encoding="utf-8")

    analysis, _, _, plots = characterize_run(run_dir, settling_discard_s=0)
    sht = [
        sample
        for sample in analysis.environment_samples
        if sample.source == "sht4x" and sample.role == "vcocxo_near"
    ]

    assert [sample.elapsed_s for sample in sht] == [
        (wrap - 32000000) / 16_000_000,
        (wrap - 16000000) / 16_000_000,
        wrap / 16_000_000,
        (wrap + 16000000) / 16_000_000,
        (wrap + 32000000) / 16_000_000,
    ]
    assert run_dir / "plots" / "vcocxo_temperature_vs_elapsed.png" in plots
    assert (run_dir / "plots" / "vcocxo_temperature_vs_elapsed.png").read_bytes().startswith(b"\x89PNG")


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

    analysis, report_path, _, _ = characterize_run(run_dir, settling_discard_s=0)
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

    analysis = analyze_run(run_dir, settling_discard_s=0)

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

    analysis = analyze_run(run_dir, settling_discard_s=0)

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

    analysis = analyze_run(run_dir, settling_discard_s=0)
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

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.startup_control.first_post_inhibit_bad_elapsed_s == 625
    assert not analysis.startup_control.valid_for_control
    assert analysis.startup_control.note.startswith("not control-eligible")


def test_h1_fc0_bad_window_diagnostics_are_reported(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_bad_window_diagnostics"
    rows = [(seq, 100_000_000, 16) for seq in range(1, 68)]
    _write_startup_gate_run(run_dir, rows)
    sts_rows = [
        "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
        "STS,1,10,160000000,rp2040_timer0,fc0,window_invalid_reason,counted_edges_zero,WARN,528",
        "STS,1,11,160000010,rp2040_timer0,fc0,window_sample_count,1,WARN,528",
        "STS,1,12,160000020,rp2040_timer0,fc0,window_zero_sample_count,1,WARN,528",
        "STS,1,13,160000030,rp2040_timer0,fc0,window_valid_sample_count,0,WARN,528",
        "STS,1,14,160000040,rp2040_timer0,fc0,window_first_sample_khz,0,WARN,528",
        "STS,1,15,160000050,rp2040_timer0,fc0,window_last_sample_khz,0,WARN,528",
        "STS,1,16,160000060,rp2040_timer0,fc0,window_min_sample_khz,0,WARN,528",
        "STS,1,17,160000070,rp2040_timer0,fc0,window_max_sample_khz,0,WARN,528",
        "STS,1,18,160000080,rp2040_timer0,fc0,window_elapsed_us,300000003,WARN,528",
        "STS,1,19,160000090,rp2040_timer0,fc0,window_flags,528,WARN,528",
        "STS,1,20,160000100,rp2040_timer0,fc0,post_startup_invalid_window,true,WARN,528",
        "STS,1,21,160000110,rp2040_timer0,fc0,consecutive_bad_windows,1,WARN,528",
        "STS,1,22,160000120,rp2040_timer0,fc0,total_bad_windows,1,WARN,528",
        "STS,1,30,320000000,rp2040_timer0,fc0,window_invalid_reason,partial_zero_samples,WARN,48",
        "STS,1,31,320000010,rp2040_timer0,fc0,window_sample_count,2,WARN,48",
        "STS,1,32,320000020,rp2040_timer0,fc0,window_zero_sample_count,1,WARN,48",
        "STS,1,33,320000030,rp2040_timer0,fc0,window_valid_sample_count,1,WARN,48",
        "STS,1,34,320000040,rp2040_timer0,fc0,window_flags,48,WARN,48",
        "STS,1,35,320000050,rp2040_timer0,fc0,post_startup_invalid_window,false,WARN,48",
        "STS,1,36,320000060,rp2040_timer0,fc0,consecutive_bad_windows,2,WARN,48",
        "STS,1,37,320000070,rp2040_timer0,fc0,total_bad_windows,2,WARN,48",
    ]
    (run_dir / "csv" / "sts.csv").write_text("\n".join(sts_rows) + "\n", encoding="utf-8")

    analysis = analyze_run(run_dir, settling_discard_s=0)
    report = render_report(analysis)

    assert len(analysis.fc0_bad_windows) == 2
    assert analysis.fc0_bad_windows[0].reason == "counted_edges_zero"
    assert analysis.fc0_bad_windows[0].post_startup_invalid
    assert analysis.fc0_bad_windows[1].sample_count == 2
    assert "## FC0 Bad Window Diagnostics" in report
    assert "diagnostic_windows: 2" in report
    assert "counted_edges_zero=1" in report
    assert "partial_zero_samples=1" in report
    assert "post_startup_invalid: false=1, true=1" in report


def test_h1_startup_gate_requires_clean_windows_after_inhibit(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_no_clean_after_inhibit"
    rows = [(seq, 100_000_000, 16) for seq in range(1, 62)]
    _write_startup_gate_run(run_dir, rows)

    analysis = analyze_run(run_dir, settling_discard_s=0)

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

    analysis = analyze_run(run_dir, settling_discard_s=0)

    assert analysis.startup_control.startup_discarded_window_count == 0
    assert analysis.startup_control.first_control_eligible_elapsed_s == 3000
    assert analysis.startup_control.valid_for_control


def test_pps_interval_classifies_missed_pulses() -> None:
    two_seconds = classify_pps_interval(32_000_000, 16_000_000)
    five_seconds = classify_pps_interval(80_000_000, 16_000_000)

    assert two_seconds.classification == "likely_missed_1_pps"
    assert two_seconds.missed_pulse_count == 1
    assert five_seconds.classification == "likely_missed_n_pps"
    assert five_seconds.missed_pulse_count == 4


def test_h1_default_settling_discard_excludes_early_measurements(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_default_settling"
    _write_synthetic_run(run_dir, include_second_step=False)

    analysis = analyze_run(run_dir)

    assert analysis.settling_discard_s == 60
    assert analysis.points[0].sample_count == 0
    assert analysis.points[0].discarded_count == 7


def test_h1_configurable_settling_discard_excludes_only_early_windows(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_configurable_settling"
    _write_synthetic_run(run_dir, include_second_step=False)

    analysis = analyze_run(run_dir, settling_discard_s=3)

    assert analysis.points[0].sample_count == 5
    assert analysis.points[0].discarded_count == 2


def test_h1_pps_anomaly_marks_overlapping_dac_step_degraded(tmp_path: Path) -> None:
    run_dir = tmp_path / "h1_degraded_pps_step"
    _write_synthetic_run(run_dir, include_ref=True)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["validation_gates"] = {
        "pps_cadence": [
            {
                "domain": "rp2040_timer0",
                "classification": "likely_missed_1_pps",
                "count": 1,
                "root_cause": "unresolved",
                "control_eligibility": "not_control_eligible",
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    ref_rows = [
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
        "REF,1,1,1,R,0,rp2040_timer0,16",
        "REF,1,2,1,R,16000000,rp2040_timer0,16",
        "REF,1,3,1,R,32000000,rp2040_timer0,16",
        "REF,1,4,1,R,64000000,rp2040_timer0,16",
        "REF,1,5,1,R,80000000,rp2040_timer0,16",
        "REF,1,6,1,R,96000000,rp2040_timer0,16",
    ]
    (run_dir / "csv" / "ref.csv").write_text("\n".join(ref_rows) + "\n", encoding="utf-8")

    analysis, report_path, points_path, _ = characterize_run(run_dir, settling_discard_s=0)
    report = report_path.read_text(encoding="utf-8")
    points_csv = points_path.read_text(encoding="utf-8")

    assert analysis.pps_anomalies[0].classification.classification == "likely_missed_1_pps"
    assert analysis.points[0].quality == "degraded"
    assert analysis.points[0].pps_anomaly_count == 1
    assert "PPS Anomalies" in report
    assert "likely_missed_1_pps" in report
    assert "pps_cadence_anomaly_status: explicitly_gated" in report
    assert "quality" in points_csv
