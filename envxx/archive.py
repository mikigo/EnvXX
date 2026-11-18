from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path

from .errors import ArchiveError

_CHUNK = 1024 * 1024


def _fs(path: Path) -> str:
    """Filesystem path string; Windows long paths need the \\\\?\\ prefix.

    Node's npm tree nests deep enough to exceed MAX_PATH, so every write path
    goes through this helper.
    """
    text = str(path)
    if os.name != "nt":
        return text
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def _safe_target(dest: Path, member_name: str) -> Path:
    """Resolve an archive member against dest, rejecting escapes."""
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ArchiveError(f"absolute path in archive: {member_name}")

    root = os.path.normpath(str(dest))
    target = os.path.normpath(os.path.join(root, normalized))
    if target != root and not target.startswith(root + os.sep):
        raise ArchiveError(f"path escapes destination: {member_name}")
    return Path(target)


def _strip_top(name: str) -> str:
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) <= 1:
        return ""
    return "/".join(parts[1:])


def _extract_tar(archive: Path, dest: Path, strip_top: bool) -> None:
    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            name = _strip_top(member.name) if strip_top else member.name
            if not name:
                continue
            target = _safe_target(dest, name)

            if member.issym() or member.islnk():
                link_target_raw = member.linkname
                if os.path.isabs(link_target_raw):
                    raise ArchiveError(f"absolute symlink in archive: {member.name}")
                if member.issym():
                    _safe_target(dest, str((Path(name).parent / link_target_raw)))
                    os.makedirs(_fs(target.parent), exist_ok=True)
                    if os.path.lexists(_fs(target)):
                        os.unlink(_fs(target))
                    os.symlink(link_target_raw, _fs(target))
                else:
                    source = _safe_target(dest, link_target_raw)
                    if not os.path.exists(_fs(source)):
                        raise ArchiveError(f"hard link target missing: {member.name}")
                    os.makedirs(_fs(target.parent), exist_ok=True)
                    if os.path.lexists(_fs(target)):
                        os.unlink(_fs(target))
                    os.link(_fs(source), _fs(target))
                continue

            if member.isdir():
                os.makedirs(_fs(target), exist_ok=True)
                continue

            if not member.isfile():
                continue

            os.makedirs(_fs(target.parent), exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, open(_fs(target), "wb") as out:
                shutil.copyfileobj(source, out, _CHUNK)

            mode = member.mode
            if mode and os.name != "nt":
                os.chmod(_fs(target), mode & 0o777 or 0o644)


def _extract_zip(archive: Path, dest: Path, strip_top: bool) -> None:
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = _strip_top(info.filename) if strip_top else info.filename
            if not name:
                continue
            target = _safe_target(dest, name)
            if info.is_dir():
                os.makedirs(_fs(target), exist_ok=True)
                continue
            os.makedirs(_fs(target.parent), exist_ok=True)
            with zf.open(info) as source, open(_fs(target), "wb") as out:
                shutil.copyfileobj(source, out, _CHUNK)

            # zipfile does not preserve unix mode; recover it from external_attr
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if os.name != "nt":
                if unix_mode and stat.S_ISREG(unix_mode):
                    os.chmod(_fs(target), unix_mode & 0o777)
                else:
                    os.chmod(_fs(target), 0o755 if unix_mode & 0o111 else 0o644)


def extract(archive: Path, dest: Path, strip_top: bool = True) -> None:
    os.makedirs(_fs(dest), exist_ok=True)
    name = archive.name.lower()
    # a .vsix is a zip container, which is how VSCode extensions ship
    if name.endswith((".zip", ".vsix")):
        _extract_zip(archive, dest, strip_top)
    elif name.endswith((".tar.gz", ".tgz")):
        _extract_tar(archive, dest, strip_top)
    else:
        raise ArchiveError(f"unsupported archive format: {archive.name}")


def copy_single(src: Path, dest: Path, name: str | None = None) -> Path:
    """Install a single-file artifact (e.g. a standalone .exe) into dest.

    Release asset names carry the version ('CC-Switch-v4.0.31-Linux-x86_64.AppImage')
    while the entrypoint is version independent, so callers may rename.
    """
    os.makedirs(_fs(dest), exist_ok=True)
    target = dest / (name or src.name)
    shutil.copy2(src, _fs(target))
    if os.name != "nt":
        os.chmod(_fs(target), os.stat(_fs(target)).st_mode | 0o111)
    return target
