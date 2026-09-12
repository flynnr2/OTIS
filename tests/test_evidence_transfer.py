"""Portable evidence transfer tests."""

import io
import os
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools.evidence_package import seal_package, validate_package
from host.otis_tools.evidence_transfer import (
    inspect_package,
    publish_package,
    receive_package,
)
from tests.capture_fixtures import write_simulated_run


def _package(root: Path) -> Path:
    run = root / "sealed"
    write_simulated_run(run)
    for relative, text in {
        "raw/serial.log": "raw\n",
        "reports/capture_segment_closure_v1.json": "{}",
    }.items():
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    seal_package(
        run, analysis={"status": "review_required", "outcome": "interrupted_incomplete"}
    )
    return run


def test_round_trip_verifies_new_inventory(tmp_path):
    source = _package(tmp_path)
    receipt = publish_package(source, tmp_path / "delivery")
    archive = tmp_path / "delivery" / receipt["archive_name"]
    restored = receive_package(
        archive,
        archive_sha256=receipt["archive_sha256"],
        content_sha256=receipt["package_content_sha256"],
        destination=tmp_path / "local",
    )
    assert (
        validate_package(restored)["package_content_sha256"]
        == inspect_package(source)["package_content_sha256"]
    )


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", "file"),
        ("/absolute", "file"),
        ("link", "link"),
        ("duplicate", "duplicate"),
    ],
)
def test_unsafe_archive_members_are_rejected(tmp_path, name, kind):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        member = tarfile.TarInfo(name)
        member.size = 1
        if kind == "link":
            member.type, member.linkname, member.size = tarfile.SYMTYPE, "../escape", 0
        stream.addfile(member, io.BytesIO(b"x"))
        if kind == "duplicate":
            stream.addfile(member, io.BytesIO(b"y"))
    with pytest.raises(ValueError, match="archive member"):
        receive_package(
            archive,
            archive_sha256=sha256(archive.read_bytes()).hexdigest(),
            content_sha256="0" * 64,
            destination=tmp_path / "local",
        )


def test_round_trip_retains_declared_fifo_omissions_without_archiving_specials(
    tmp_path,
):
    run = tmp_path / "fifo-source"
    write_simulated_run(run)
    raw = run / "raw/serial.log"
    raw.parent.mkdir(parents=True)
    raw.write_text("raw\n")
    closure = run / "reports/capture_segment_closure_v1.json"
    closure.parent.mkdir(parents=True)
    closure.write_text("{}")
    for relative in (
        "control/normal_commands.fifo",
        "control/emergency_abort.fifo",
    ):
        endpoint = run / relative
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(endpoint)
    seal_package(
        run,
        analysis={"status": "review_required", "outcome": "interrupted_incomplete"},
    )
    receipt = publish_package(run, tmp_path / "delivery-fifo")
    archive = tmp_path / "delivery-fifo" / receipt["archive_name"]
    restored = receive_package(
        archive,
        archive_sha256=receipt["archive_sha256"],
        content_sha256=receipt["package_content_sha256"],
        destination=tmp_path / "restored-fifo",
    )
    package = validate_package(restored)
    assert package["omitted_runtime_endpoints"] == [
        {"path": "control/emergency_abort.fifo", "type": "fifo"},
        {"path": "control/normal_commands.fifo", "type": "fifo"},
    ]
    assert not (restored / "control/normal_commands.fifo").exists()
    assert not (restored / "control/emergency_abort.fifo").exists()
