from host.otis_tools.service_latency import decode_reports


def rows(g=1, c=1, s=0, eligible=2):
    prefix = f"LAT,v=1,g={g},c={c},s={s},p="
    result = [prefix + f"0,e={eligible},m=0,a=0,x=0,d=1,t=1000,sat=0,hw=0",
              prefix + f"1,hv=1,b0=0,b1={eligible},b2=0,b3=0,b4=0,b5=0,b6=0,b7=0"]
    for p in range(2, 6):
        have = eligible >= (2 if p == 5 else 1)
        result.append(prefix + f"{p},have={int(have)},session=9,seq={p},"
                      f"start=4294967295,end=2,u=0,status={0 if have else 1},"
                      f"domain={1 if have else 0}")
    result.append(prefix + "6,have=0,session=0,seq=0,start=0,end=0,u=0,status=1,domain=0")
    return result


def test_complete_snapshot_retains_raw_endpoints_wrap_and_drop_evidence():
    source = rows()
    report, = decode_reports(["REF,unrelated", *source])
    assert report["status"] == "complete"
    assert report["raw_rows"] == source
    assert report["parts"]["2"]["start"] == 4294967295
    assert report["parts"]["0"]["d"] == 1
    assert not report["hardware_to_service_available"]


def test_missing_duplicate_and_reordered_rows_never_clean():
    source = rows()
    report, = decode_reports(source[:2] + source[3:])
    assert report["status"] == "missing" and report["missing_parts"] == [2]
    report, = decode_reports(source + [source[2]])
    assert report["status"] == "ambiguous" and len(report["raw_rows"]) == 8
    report, = decode_reports([source[1], source[0], *source[2:]])
    assert report["status"] == "ambiguous"


def test_generation_gap_rollover_and_identity_conflict():
    reports = decode_reports(rows(g=0xffffffff) + rows(g=0, c=2))
    assert [r["status"] for r in reports] == ["complete", "complete"]
    reports = decode_reports(rows(g=1) + rows(g=3, c=2))
    assert reports[1]["reason"] == "generation_gap"
    assert reports[1]["missing_generations"] == 1
    reports = decode_reports(rows(g=1) + rows(g=1, c=2))
    assert all(r["status"] == "ambiguous" for r in reports)


def test_unknown_malformed_and_contradictory_diagnostics_preserved():
    for malformed in ["LAT,v=2,g=1,c=1,s=0,p=0", "LAT,v=1,v=1", "LAT,g=-1"]:
        report, = decode_reports([malformed])
        assert report["status"] == "ambiguous"
        assert report["raw_rows"] == [malformed]
    source = rows()
    source[1] = source[1].replace("b1=2", "b1=1")
    assert decode_reports(source)[0]["status"] == "ambiguous"
    source = rows()
    source[2] = source[2].replace("end=2", "end=2147483647")
    assert decode_reports(source)[0]["status"] == "ambiguous"
    source = rows()
    source[2] = source[2].replace("u=0", "u=2")
    assert decode_reports(source)[0]["status"] == "ambiguous"


def test_empty_and_single_eligible_reports_have_explicit_absent_tail():
    for eligible in (0, 1):
        report, = decode_reports(rows(eligible=eligible))
        assert report["status"] == "complete"
        assert report["parts"]["5"]["have"] == 0


def test_noneligible_sample_retains_raw_ambiguous_coordinate():
    source = rows()
    source[0] = source[0].replace("a=0", "a=1")
    source[6] = source[6].replace("have=0", "have=1").replace("status=1", "status=2")
    report, = decode_reports(source)
    assert report["status"] == "complete"
    assert report["parts"]["6"]["status"] == 2


def test_malformed_latency_is_local_without_weakening_boot_contract(tmp_path):
    import csv
    import json
    import tempfile

    from host.otis_tools.capture_device import (
        CaptureDeviceConfig,
        CaptureDeviceRunner,
        RawEvidenceWriter,
    )
    from host.otis_tools.record_splitter import CsvRecordSplitter

    runner = CaptureDeviceRunner(CaptureDeviceConfig("/dev/never-open", 115200, tmp_path))
    errors = []
    splitter = CsvRecordSplitter({}, on_parser_error=runner._parser_error)

    class Frontier:
        def note_discrepancy(self, *args, **kwargs):
            errors.append((args, kwargs))

    # Real CSV error (field-size overflow), structural error, and malformed UTF-8.
    lines = [b"LAT," + b"x" * 100 + b"\n", b"LAT,v=9,g=1\n", b"LAT,\xff\n"]
    limit = csv.field_size_limit(64)
    try:
        with tempfile.TemporaryFile("w+b") as stream:
            raw = RawEvidenceWriter(stream)
            for line in lines:
                raw.write_device(line)
                runner._process_line(line, splitter, raw,
                                     acquisition_frontier_tracker=Frontier())
            raw.close()
            stream.seek(0)
            evidence = stream.read()
    finally:
        csv.field_size_limit(limit)
    assert runner.parser_errors == 0 and runner.malformed_utf8 == 0
    assert not errors
    for line in lines:
        assert line in evidence
    markers = [json.loads(line.removeprefix(b"# OTIS_HOST "))
               for line in evidence.splitlines() if line.startswith(b"# OTIS_HOST ")]
    assert len(markers) == 3
    assert all(m["disposition"] == "raw_only_diagnostic_invalid" for m in markers)
    assert all(m["diagnostic_errors"] for m in markers)
    splitter.process_line("BOOT_WARN,v=2,key=serial_absent,wait_ms=250")
    assert runner.parser_errors == 1 and splitter.last_disposition == "error"
