from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.h1_characterize import analyze_run, characterize_run, render_report


def _write_synthetic_run(
    run_dir: Path,
    *,
    include_voltage: bool = True,
    include_second_step: bool = True,
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
    assert "measured_hz = counted_edges / gate_seconds" in report
    assert render_report(analysis)
    assert run_dir / "plots" / "dac_code_vs_hz.png" in plots
    assert run_dir / "plots" / "dac_voltage_vs_ppm.png" in plots
    assert (run_dir / "plots" / "dac_code_vs_hz.png").read_bytes().startswith(b"\x89PNG")


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
    assert any("flagged zero-count" in warning for warning in analysis.warnings)
    assert any("using the final segment" in warning for warning in analysis.warnings)
