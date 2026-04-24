"""File copy/move helpers that preserve macOS Finder \"Created\" (APFS birth time)."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import sys
from pathlib import Path

# /usr/include/copyfile.h
_COPYFILE_ACL = 1 << 0
_COPYFILE_STAT = 1 << 1
_COPYFILE_XATTR = 1 << 2
_COPYFILE_DATA = 1 << 3
_COPYFILE_SECURITY = _COPYFILE_STAT | _COPYFILE_ACL
_COPYFILE_METADATA = _COPYFILE_SECURITY | _COPYFILE_XATTR
COPYFILE_ALL = _COPYFILE_METADATA | _COPYFILE_DATA
COPYFILE_CLONE = 1 << 24


def copy_preserve_metadata(src: Path, dst: Path) -> None:
    """
    Copy a file. On macOS, use copyfile(3) with metadata + clone so st_birthtime
    matches the source (Finder \"Date Created\"). Else fall back to shutil.copy2.
    """
    src = src.resolve()
    dst = dst.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform != "darwin":
        shutil.copy2(src, dst)
        return

    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    cf = libc.copyfile
    cf.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint32]
    cf.restype = ctypes.c_int

    sb = str(src).encode()
    db = str(dst).encode()
    if cf(sb, db, None, COPYFILE_ALL | COPYFILE_CLONE) == 0:
        return
    if cf(sb, db, None, COPYFILE_ALL) == 0:
        return
    shutil.copy2(src, dst)


def move_preserving_metadata(src: Path, dst: Path) -> None:
    """Rename on same volume (keeps inode); otherwise copy preserving metadata then unlink."""
    src = src.resolve()
    dst = dst.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError:
        copy_preserve_metadata(src, dst)
        src.unlink()
