from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from envxx.archive import extract
from envxx.errors import ArchiveError


def test_zip_strips_top_directory(tmp_path: Path):
    archive = tmp_path / "node-v22-x64.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("node-v22-x64/node.exe", b"binary")
        zf.writestr("node-v22-x64/npm.cmd", b"@echo off")

    dest = tmp_path / "out"
    extract(archive, dest, strip_top=True)

    assert (dest / "node.exe").read_bytes() == b"binary"
    assert (dest / "npm.cmd").exists()
    assert not (dest / "node-v22-x64").exists()


def test_zip_keeps_top_directory_when_disabled(tmp_path: Path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("top/file.txt", b"x")

    dest = tmp_path / "out"
    extract(archive, dest, strip_top=False)
    assert (dest / "top" / "file.txt").exists()


def _make_tar(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))


def test_tar_strips_top_directory(tmp_path: Path):
    archive = tmp_path / "python.tar.gz"
    _make_tar(
        archive,
        [
            ("python/bin/python3", b"py"),
            ("python/lib/os.py", b"os"),
        ],
    )
    dest = tmp_path / "out"
    extract(archive, dest, strip_top=True)
    assert (dest / "bin" / "python3").exists()
    assert (dest / "lib" / "os.py").exists()
    assert not (dest / "python").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_tar_symlink_preserved(tmp_path: Path):
    archive = tmp_path / "py.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        data = b"py"
        info = tarfile.TarInfo("python/bin/python3.11")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

        link = tarfile.TarInfo("python/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3.11"
        tar.addfile(link)

    dest = tmp_path / "out"
    extract(archive, dest, strip_top=True)
    assert (dest / "bin" / "python3").is_symlink()


def test_zip_rejects_path_escape(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("top/../../escape.txt", b"nope")

    with pytest.raises(ArchiveError):
        extract(archive, tmp_path / "out", strip_top=True)


def test_tar_rejects_path_escape(tmp_path: Path):
    archive = tmp_path / "evil.tar.gz"
    _make_tar(archive, [("top/../../escape.txt", b"nope")])

    with pytest.raises(ArchiveError):
        extract(archive, tmp_path / "out", strip_top=True)


def test_unsupported_format(tmp_path: Path):
    archive = tmp_path / "weird.tar.zst"
    archive.write_bytes(b"x")
    with pytest.raises(ArchiveError):
        extract(archive, tmp_path / "out")
