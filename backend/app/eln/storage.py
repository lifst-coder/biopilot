"""Content-addressed blob store for attachment binaries (ELN-4).

Files live at ``<root>/<sha[:2]>/<sha256>``; writing the same bytes twice is a no-op,
so identical re-uploads never duplicate storage. There is deliberately no delete.
The root comes from ``BIOPILOT_ELN_STORAGE_DIR`` (default ``./eln_storage``) and gets a
``.gitignore`` so blobs are never committed by accident.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

DEFAULT_STORAGE_DIR = "eln_storage"
#: Maximum accepted attachment size in bytes.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def storage_root() -> Path:
    """Resolve (and create) the storage root."""
    root = Path(os.environ.get("BIOPILOT_ELN_STORAGE_DIR", DEFAULT_STORAGE_DIR))
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    return root


def blob_path(sha256: str) -> Path:
    """Path of the blob for a digest (may not exist)."""
    return storage_root() / sha256[:2] / sha256


def put_blob(data: bytes) -> tuple[str, bool]:
    """Store bytes; returns ``(sha256, newly_written)``."""
    digest = hashlib.sha256(data).hexdigest()
    path = blob_path(digest)
    if path.exists():
        return digest, False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return digest, True


def read_blob(sha256: str) -> bytes:
    """Read a stored blob; raises ``FileNotFoundError`` if missing."""
    return blob_path(sha256).read_bytes()
