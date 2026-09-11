"""Transport exercises exact bytes, without claiming scientific validation."""

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tarfile

import pytest

from host.otis_tools.evidence import package_identity
from host.otis_tools.evidence_transfer import (
    INERT_RUNTIME_FIFO_PATHS, SEAL_PATH, inspect_package, publish_package,
    receive_package,
)


def _package(root: Path) -> Path:
    source = root / "sealed"
    for relative, value in {
        "COMPLETE": '{"result":"aborted"}',
        "run_manifest.json": '{"fixture":"transport only"}',
        "evidence_manifest.json": '{"fixture":"transport only"}',
        SEAL_PATH.as_posix(): '{"status":"review_required"}',
        "raw/serial.log": "raw evidence\n" * 1000,
        "csv/retained space.csv": "a,b\n1,2\n",
    }.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)
    return source


def _receive(root: Path, archive: Path, receipt: dict) -> Path:
    return receive_package(
        archive,
        archive_sha256=receipt["archive_sha256"],
        content_sha256=receipt["package"]["content_sha256"],
        destination=root / "local-evidence",
    )


def test_closed_interrupted_package_round_trip_preserves_every_byte(tmp_path):
    source = _package(tmp_path)
    before = package_identity(source)
    report = inspect_package(source)
    assert report["uncompressed_bytes"] == before["total_bytes"]
    assert report["omitted_runtime_endpoints"] == []
    assert report["scientific_validation_performed"] is False
    receipt = publish_package(source, tmp_path / "delivery")
    archive = tmp_path / "delivery" / receipt["archive_name"]
    retained_receipt = json.loads(next((tmp_path / "delivery").glob("*.json")).read_text())
    assert retained_receipt == receipt
    assert receipt["omitted_runtime_endpoints"] == []
    assert receipt["archive_bytes"] < before["total_bytes"]
    restored = _receive(tmp_path, archive, receipt)
    assert package_identity(restored) == before == package_identity(source)
    assert _receive(tmp_path, archive, receipt) == restored
    with pytest.raises(ValueError, match="already exists"):
        publish_package(source, tmp_path / "delivery")
    (restored / "raw/serial.log").write_text("changed")
    with pytest.raises(ValueError, match="refusing replacement"):
        _receive(tmp_path, archive, receipt)


def test_partial_cloud_download_is_rejected_before_local_publication(tmp_path):
    receipt = publish_package(_package(tmp_path), tmp_path / "delivery")
    archive = tmp_path / "delivery" / receipt["archive_name"]
    archive.write_bytes(archive.read_bytes()[:-10])
    with pytest.raises(ValueError, match="archive checksum"):
        _receive(tmp_path, archive, receipt)
    assert not (tmp_path / "local-evidence").exists()


def test_wrong_content_identity_does_not_publish_a_local_package(tmp_path):
    receipt = publish_package(_package(tmp_path), tmp_path / "delivery")
    archive = tmp_path / "delivery" / receipt["archive_name"]
    receipt["package"]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="identity differs"):
        _receive(tmp_path, archive, receipt)
    assert list((tmp_path / "local-evidence").iterdir()) == []


@pytest.mark.parametrize("member_name,kind", [
    ("../escape", "file"), ("/absolute", "file"),
    ("a/./b", "file"), ("link", "symlink"),
    ("hardlink", "hardlink"), ("duplicate", "duplicate"),
])
def test_archive_cannot_escape_or_replace_members(tmp_path, member_name, kind):
    archive = tmp_path / "invalid.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        item = tarfile.TarInfo(member_name)
        item.size = 1
        if kind in {"symlink", "hardlink"}:
            item.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            item.linkname = "../escape"
            item.size = 0
        stream.addfile(item, io.BytesIO(b"x"))
        if kind == "duplicate":
            stream.addfile(item, io.BytesIO(b"y"))
    with pytest.raises(ValueError, match="archive member"):
        receive_package(archive, archive_sha256=sha256(archive.read_bytes()).hexdigest(),
                        content_sha256="0" * 64, destination=tmp_path / "local")
    assert not (tmp_path / "escape").exists()
    assert list((tmp_path / "local").iterdir()) == []


def test_live_capture_and_nested_delivery_are_rejected(tmp_path):
    source = _package(tmp_path)
    active = source / "capture_in_progress.flag"
    active.touch()
    with pytest.raises(ValueError, match="active capture"):
        publish_package(source, tmp_path / "delivery")
    active.unlink()
    with pytest.raises(ValueError, match="outside the source"):
        publish_package(source, source / "delivery")


def test_closed_runner_fifos_are_reported_and_omitted_from_archive(tmp_path):
    source = _package(tmp_path)
    for relative in INERT_RUNTIME_FIFO_PATHS:
        endpoint = source / relative
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(endpoint)
    expected = [
        {"relative_path": relative, "type": "fifo"}
        for relative in sorted(INERT_RUNTIME_FIFO_PATHS)
    ]
    before = package_identity(source)
    assert inspect_package(source)["omitted_runtime_endpoints"] == expected

    receipt = publish_package(source, tmp_path / "delivery")
    assert receipt["package"] == before
    assert receipt["omitted_runtime_endpoints"] == expected
    archive = tmp_path / "delivery" / receipt["archive_name"]
    with tarfile.open(archive, "r:gz") as stream:
        assert all(member.isfile() for member in stream)
        assert not (set(stream.getnames()) & INERT_RUNTIME_FIFO_PATHS)

    restored = _receive(tmp_path, archive, receipt)
    assert package_identity(restored) == before
    assert inspect_package(restored)["omitted_runtime_endpoints"] == []


def test_runner_fifo_exception_requires_a_closed_package(tmp_path):
    source = _package(tmp_path)
    (source / "control").mkdir()
    os.mkfifo(source / "control/normal_commands.fifo")
    active = source / "capture_in_progress.flag"
    active.touch()
    with pytest.raises(ValueError, match="active capture"):
        inspect_package(source)
    active.unlink()
    (source / "COMPLETE").unlink()
    with pytest.raises(ValueError, match="closed package is missing COMPLETE"):
        inspect_package(source)


@pytest.mark.parametrize("kind", ["symlink", "fifo_elsewhere"])
def test_runner_fifo_exception_is_exact(tmp_path, kind):
    source = _package(tmp_path)
    if kind == "symlink":
        special = source / "control/normal_commands.fifo"
        special.parent.mkdir()
        special.symlink_to(source / "COMPLETE")
    else:
        special = source / "other/normal_commands.fifo"
        special.parent.mkdir()
        os.mkfifo(special)
    with pytest.raises(ValueError, match="link or special"):
        inspect_package(source)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_special_files_cannot_be_silently_omitted(tmp_path, kind):
    source = _package(tmp_path)
    special = source / "special"
    if kind == "symlink":
        special.symlink_to(source / "COMPLETE")
    else:
        os.mkfifo(special)
    with pytest.raises(ValueError, match="link or special"):
        publish_package(source, tmp_path / "delivery")


def test_mutating_source_is_not_published(tmp_path, monkeypatch):
    from host.otis_tools import evidence_transfer
    source = _package(tmp_path)
    original = evidence_transfer._archive_files

    def verify_then_mutate(*args):
        result = original(*args)
        (source / "raw/serial.log").write_text("late producer write")
        return result

    monkeypatch.setattr(evidence_transfer, "_archive_files", verify_then_mutate)
    with pytest.raises(ValueError, match="source changed"):
        publish_package(source, tmp_path / "delivery")
    assert list((tmp_path / "delivery").iterdir()) == []
