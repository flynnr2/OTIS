"""Small actual-wire regressions for offline unattended evidence accounting."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from host.otis_tools.firmware_host_contract import (
    RECORD_FIELDS,
    RECORD_TYPE_TO_CONTRACT,
)
from host.otis_tools.unattended import _analyze_raw, finalize

# Literal records were taken from the retained 2026-09-23 autonomous short gate.
# Sequence/tick mutations below isolate one causal defect at a time.
IWR = "IWR,2,15,1396544150034562714,1,2,2,43085,43085,1,2,144914083,0,2,rp2040_timer_us64"
IAP = "IAP,2,17,1396544150034562714,1,2,2,43085,43085,1,1,1,0,142915663,rp2040_timer_us64"
IRS = "IRS,2,46,1396544150034562714,1,1,4,-11,1,healthy_evidence_below_empirical_detection_floor,5101586929,1,4491,5091,rp2040_timer_us64"
ENV_A = "ENV,1,943,567545239,rp2040_monotonic_us32,sht4x,vcocxo_near,27.673,47.965,,0"
ENV_B = "ENV,1,945,568545331,rp2040_monotonic_us32,sht4x,vcocxo_near,27.665,47.973,,0"


def _field(line: str, name: str, value: str) -> str:
    cells = line.split(",")
    fields = RECORD_FIELDS[RECORD_TYPE_TO_CONTRACT[cells[0]]]
    cells[fields.index(name)] = value
    return ",".join(cells)


def _analyze(tmp_path: Path, *lines: str) -> dict:
    (tmp_path / "serial-0001.raw").write_bytes(
        ("\r\n".join(lines) + "\r\n").encode("ascii")
    )
    return _analyze_raw(tmp_path, {"segments": [{"path": "serial-0001.raw"}]})


def test_environment_uses_actual_env_seq_and_exposes_gap_and_reorder(tmp_path):
    result = _analyze(tmp_path, ENV_A, ENV_B, _field(ENV_A, "env_seq", "944"))
    coverage = result["source_sequence_coverage"]["ENV"]
    assert coverage["gaps"] == 1
    assert coverage["nonmonotonic_or_restart"] == 1
    assert result["environment_record_gaps_separate_from_control"] == 1
    assert result["observed_record_counts"]["ENV"] == 3


def test_exact_accepted_write_application_join_with_timer_domain(tmp_path):
    request = _field(IWR, "record_sequence", "1")
    application = _field(IAP, "record_sequence", "2")
    result = _analyze(tmp_path, request, application)
    joins = result["write_request_application_joins"]
    assert joins["matched_accepted"] == 1
    assert joins["matched_rejected"] == 0
    assert joins["contradictions"] == []
    assert joins["unmatched_requests"] == joins["unmatched_applications"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture_session", "2"),
        ("requested_code", "43086"),
        ("accepted", "0"),  # attempted/ok true contradict rejection
        ("timestamp_ticks", "144914084"),  # later than the IWR deadline
        ("timestamp_domain", "rp2040_monotonic_us32"),
    ],
)
def test_write_application_contradictions_are_never_counted_as_accepted(
    tmp_path, field, value
):
    request = _field(IWR, "record_sequence", "1")
    application = _field(_field(IAP, "record_sequence", "2"), field, value)
    result = _analyze(tmp_path, request, application)
    joins = result["write_request_application_joins"]
    assert joins["matched_accepted"] == 0
    assert len(joins["contradictions"]) + joins["unmatched_applications"] >= 1


def test_rejected_application_keeps_exact_request_identity(tmp_path):
    request = _field(_field(IWR, "record_sequence", "1"), "requested_code", "43086")
    application = _field(IAP, "record_sequence", "2")
    for name, value in (
        ("requested_code", "43086"), ("attempted", "0"), ("ok", "0"),
        ("accepted", "0"), ("rejection", "1"),
    ):
        application = _field(application, name, value)
    result = _analyze(tmp_path, request, application)
    joins = result["write_request_application_joins"]
    assert joins["matched_rejected"] == 1
    assert joins["matched_accepted"] == 0
    assert joins["contradictions"] == []


def test_rejected_application_after_request_deadline_is_not_a_matched_rejection(tmp_path):
    request = _field(IWR, "record_sequence", "1")
    application = _field(IAP, "record_sequence", "2")
    for name, value in (
        ("attempted", "0"), ("ok", "0"), ("accepted", "0"),
        ("rejection", "1"), ("timestamp_ticks", "144914083"),
    ):
        application = _field(application, name, value)
    joins = _analyze(tmp_path, request, application)["write_request_application_joins"]
    assert joins["matched_accepted"] == 0
    assert joins["matched_rejected"] == 0
    assert joins["contradictions"]


def test_irs_uses_numeric_classification_and_extended_timer_domain(tmp_path):
    response = _field(IRS, "record_sequence", "1")
    valid = _analyze(tmp_path, response)
    assert valid["response_classifications"] == {"1": 1}
    assert valid["instrument_domain_contradictions"] == 0
    wrong_domain = _field(response, "timestamp_domain", "rp2040_monotonic_us32")
    invalid = _analyze(tmp_path, wrong_domain)
    assert invalid["instrument_domain_contradictions"] == 1


def test_raw32_rollover_does_not_look_like_source_regression(tmp_path):
    ref1 = "REF,1,1,1,R,4294967290,rp2040_monotonic_us32,16"
    ref2 = "REF,1,2,1,R,7,rp2040_monotonic_us32,16"
    snp1 = "SNP,2,1,1,3347542582,1,4294967290,164,0,pio_wait_cumulative_snapshot_fifo_irq_v2"
    snp2 = "SNP,2,1,2,3337542582,2,7,164,0,pio_wait_cumulative_snapshot_fifo_irq_v2"
    cnt1 = "CNT,1,1,2,4294966200,4294967290,rp2040_monotonic_us32,10000000,R,h1_oscillator_10mhz,16"
    cnt2 = "CNT,1,2,2,4294967290,7,rp2040_monotonic_us32,10000000,R,h1_oscillator_10mhz,16"
    result = _analyze(tmp_path, ref1, snp1, cnt1, ref2, snp2, cnt2)
    for tag in ("REF", "SNP", "CNT"):
        coverage = result["source_sequence_coverage"][tag]
        assert coverage["gaps"] == 0
        assert coverage["nonmonotonic_or_restart"] == 0


@pytest.mark.parametrize("scope_case, coverage_finding", [
    ("valid", False), ("regression", True), ("malformed", True), ("gap", True), ("phase_gap", True),
])
def test_offline_reanalysis_of_relocated_closed_recording_keeps_frozen_inputs(
    tmp_path, scope_case, coverage_finding
):
    original = tmp_path / "bench-run"
    relocated = tmp_path / "extracted" / "bench-run"
    relocated.mkdir(parents=True)
    old_shared = tmp_path / "bench-shared"
    local_output = tmp_path / "local-output"
    plan = {
        "schema_version": 1,
        "device": "/dev/cu.example",
        "run_dir": str(original),
        "shared_output_dir": str(old_shared),
        "expected_session": 1,
        "expected_build_identity": "a" * 64 + ":" + "b" * 64,
        "expected_policy_sha256": "c" * 64,
        "keep_awake": False,
    }
    plan_bytes = (json.dumps(plan, sort_keys=True) + "\n").encode()
    (relocated / "unattended_plan.json").write_bytes(plan_bytes)
    scope_rows = [_source("APS", 99), _source("APS", 1, epoch=2)]
    if scope_case == "regression":
        scope_rows.append(_source("APS", 100, epoch=1))
    elif scope_case == "malformed":
        scope_rows.append(_field(_source("APS", 2, epoch=2), "acceptance_epoch", "bad"))
    elif scope_case == "gap":
        scope_rows.append(_source("APS", 3, epoch=2))
    elif scope_case == "phase_gap":
        scope_rows.extend([_source("RPH", 99), _source("RPH", 1, epoch=3)])
    raw = ("\r\n".join([ENV_A, ENV_B, *scope_rows]) + "\r\n").encode()
    (relocated / "serial-0001.raw").write_bytes(raw)
    (relocated / "recording_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "segments": [{"path": "serial-0001.raw", "bytes": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest()}],
        "bytes_recorded": len(raw), "recording_error": None,
    }))
    (relocated / "recorder_state.json").write_text(json.dumps({
        "instrument": {
            "session": 1, "mode": "OBSERVE_HOLD", "requested_mode": "OBSERVE_HOLD",
            "applied_code_known": True, "applied_code": 43085,
            "completed_command_sequence": 1, "last_command_sequence": 1,
            "dac_epoch": 1,
            "fields": {"write_state": "0", "fault": "none",
                       "instrument_ticks_domain": "rp2040_timer_us64",
                       "instrument_ticks": "101", "operating_end_ticks": "0"},
        }
    }))
    (relocated / "unattended_state.json").write_text(json.dumps({
        "phase": "closing", "auto_sequence": 1, "operating_end_ticks": 100,
    }))
    (relocated / "unattended-events.jsonl").write_text(
        '{"event":"firmware_timed_hold_endpoint"}\n'
    )
    (relocated / "monitor-events-0001.jsonl").write_text(
        '{"event":"capture_progress"}\n'
    )
    (relocated / "monitor.stdout.json").write_text('{"status":"completed"}\n')

    with pytest.raises(ValueError, match="relocated.*output_dir"):
        finalize(relocated)
    with pytest.raises(ValueError, match="output_dir|destination|inside"):
        finalize(relocated, output_dir=relocated / "packages")
    result = finalize(relocated, output_dir=local_output)
    assert result["status"] == "packaged"
    assert not old_shared.exists()
    assert (relocated / "unattended_plan.json").read_bytes() == plan_bytes
    assert (relocated / "serial-0001.raw").read_bytes() == raw
    with zipfile.ZipFile(result["zip"]) as archive:
        assert archive.testzip() is None
        assert archive.read("unattended_plan.json") == plan_bytes
        assert archive.read("serial-0001.raw") == raw
        assert "unattended_state_at_close.json" in archive.namelist()
        assert "unattended-events-frozen.jsonl" in archive.namelist()
        assert "unattended_state.json" not in archive.namelist()
        assert "unattended-events.jsonl" not in archive.namelist()
        archive.extractall(tmp_path / "archive-extract")
    summary = json.loads(Path(result["summary"]).read_text())
    assert ("canonical_source_sequence_coverage_gap" in summary["review_findings"]) == coverage_finding
    assert summary["original_run_dir"] == str(original)
    assert summary["analysis_run_dir"] == str(relocated)
    assert summary["scientific_qualification"] == "not_established_by_automatic_package"
    repeat = finalize(relocated, output_dir=local_output)
    assert repeat["status"] == "already_packaged"
    assert repeat["sha256"] == result["sha256"]

    replay_root = tmp_path / "archive-extract"
    replay = finalize(replay_root, output_dir=tmp_path / "replay-output")
    assert replay["status"] == "packaged"
    replay_summary = json.loads(Path(replay["summary"]).read_text())
    assert replay_summary["original_run_dir"] == str(original)
    assert replay_summary["analysis_run_dir"] == str(replay_root)
    assert (replay_root / "unattended_plan.json").read_bytes() == plan_bytes
    assert (replay_root / "serial-0001.raw").read_bytes() == raw


def _source(tag, sequence, epoch=1, capture=1, **overrides):
    fields = RECORD_FIELDS[RECORD_TYPE_TO_CONTRACT[tag]]
    values = dict.fromkeys(fields, "0")
    values.update(record_type=tag, schema_version="2" if tag in {"RPH", "PHE"} else "1",
                  capture_session=str(capture), acceptance_epoch=str(epoch),
                  phase_epoch=str(epoch), accepted_boundary_ordinal=str(sequence),
                  observation_sequence=str(sequence))
    values.update({key: str(value) for key, value in overrides.items()})
    return ",".join(values[name] for name in fields)


@pytest.mark.parametrize("tag", ["APS", "RPH", "PHE"])
def test_epoch_transition_restarts_local_sequence_without_losing_coverage(tmp_path, tag):
    first = 1 if tag == "APS" else 0
    rows = [_source(tag, 99), _source(tag, 100),
            _source(tag, first, epoch=2), _source(tag, first + 1, epoch=2)]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["gaps"] == coverage["nonmonotonic_or_restart"] == 0
    assert coverage["scope_regressions"] == coverage["malformed_records"] == 0
    assert coverage["observed_scopes"] == 2
    assert coverage["scope_transitions"] == 1


@pytest.mark.parametrize("tag", ["RPH", "PHE"])
def test_phase_epoch_may_begin_with_first_span_and_acceptance_cannot_mask_reset(tmp_path, tag):
    rows = [_source(tag, 99), _source(tag, 1, epoch=2),
            _source(tag, 2, epoch=2),
            _source(tag, 1, epoch=2, acceptance_epoch=3)]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["gaps"] == coverage["scope_regressions"] == 0
    assert coverage["scope_transitions"] == 1
    assert coverage["nonmonotonic_or_restart"] == 1


@pytest.mark.parametrize("tag", ["APS", "RPH", "PHE"])
def test_epoch_aware_coverage_retains_real_gaps_duplicates_and_resets(tmp_path, tag):
    rows = [_source(tag, 10), _source(tag, 12), _source(tag, 12),
            _source(tag, 1), _source(tag, 4, epoch=2)]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["gaps"] == 4  # one within epoch, three at observed next epoch
    assert coverage["nonmonotonic_or_restart"] == 2


@pytest.mark.parametrize("tag", ["APS", "RPH", "PHE"])
def test_old_or_backward_epoch_remains_a_review_finding(tmp_path, tag):
    rows = [_source(tag, 10, epoch=2), _source(tag, 1, epoch=4),
            _source(tag, 1, epoch=3), _source(tag, 11, epoch=2)]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["scope_regressions"] == 2


@pytest.mark.parametrize("tag", ["APS", "RPH", "PHE"])
@pytest.mark.parametrize("return_epoch", [1, 2])
def test_capture_session_is_part_of_epoch_identity_and_cannot_reenter(tmp_path, tag, return_epoch):
    rows = [_source(tag, 10), _source(tag, 1, capture=2),
            _source(tag, 11, capture=1, epoch=return_epoch)]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["observed_scopes"] == (2 if return_epoch == 1 else 3)
    assert coverage["scope_regressions"] == 1


@pytest.mark.parametrize("tag", ["APS", "RPH", "PHE"])
def test_malformed_scope_is_visible_not_silently_skipped(tmp_path, tag):
    epoch_field = "acceptance_epoch" if tag == "APS" else "phase_epoch"
    rows = [_source(tag, 10), _field(_source(tag, 11), epoch_field, "invalid")]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["malformed_records"] == 1


@pytest.mark.parametrize("tag, missing", [("APS", 0), ("RPH", 1), ("PHE", 1)])
def test_missing_whole_phase_epoch_is_loss_but_empty_acceptance_epoch_is_legal(tmp_path, tag, missing):
    rows = [_source(tag, 10), _source(tag, 1, epoch=3)]
    coverage = _analyze(tmp_path, *rows)["source_sequence_coverage"][tag]
    assert coverage["missing_phase_epochs"] == missing
