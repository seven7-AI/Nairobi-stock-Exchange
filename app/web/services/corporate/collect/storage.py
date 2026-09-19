"""Where collected files live: ``<documents_dir>/<ticker|regulator>/<sha256>.<ext>``.

Content-addressed, written atomically, never deleted: a new version of a document
is a new file; an unchanged file at a new identity is the same file referenced twice.

    codegraph explore "store_document StoredFile"
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    sha256: str
    size: int
    is_pdf: bool
    already_present: bool


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def is_pdf(content: bytes) -> bool:
    return content[:5] == _PDF_MAGIC


def store_document(documents_dir: Path, folder: str, content: bytes) -> StoredFile:
    digest = sha256_of(content)
    pdf = is_pdf(content)
    extension = "pdf" if pdf else "bin"
    relative = Path(folder) / f"{digest}.{extension}"
    target = documents_dir / relative
    if target.exists():
        return StoredFile(str(relative), digest, len(content), pdf, True)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(content)
    partial.replace(target)
    return StoredFile(str(relative), digest, len(content), pdf, False)


__all__ = ["StoredFile", "is_pdf", "sha256_of", "store_document"]
