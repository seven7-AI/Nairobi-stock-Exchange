"""Which extraction stages this box can run.

Detected at run time and recorded on every extraction row, so a fact's provenance
says which tools produced it and a later re-run on a better-equipped box is
distinguishable. Imports are lazy: an optional library that is absent yields a
``False`` flag, never an ImportError at import time.

    codegraph explore "detect_capabilities Capabilities"
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Capabilities:
    pymupdf: bool
    pdfplumber: bool
    camelot: bool
    pytesseract: bool
    ghostscript: bool
    tesseract: bool
    poppler: bool
    ocrmypdf: bool
    ocr_enabled: bool
    llm_cleanup: bool

    @property
    def tables_via_camelot(self) -> bool:
        return self.camelot and self.ghostscript

    @property
    def ocr(self) -> bool:
        return self.ocr_enabled and self.pytesseract and self.tesseract and self.poppler

    def stages(self) -> dict[str, tuple[bool, str]]:
        """Stage -> (available, why not)."""
        return {
            "pymupdf_text": (self.pymupdf, "" if self.pymupdf else "pymupdf not installed"),
            "pdfplumber": (self.pdfplumber, "" if self.pdfplumber else "pdfplumber not installed"),
            "camelot": (
                self.tables_via_camelot,
                ""
                if self.tables_via_camelot
                else _missing({"camelot-py": self.camelot, "ghostscript (gs)": self.ghostscript}),
            ),
            "ocr": (
                self.ocr,
                ""
                if self.ocr
                else (
                    "CORPORATE_OCR_ENABLED is false"
                    if not self.ocr_enabled
                    else _missing(
                        {
                            "pytesseract": self.pytesseract,
                            "tesseract": self.tesseract,
                            "poppler (pdftoppm)": self.poppler,
                        }
                    )
                ),
            ),
            "llm_cleanup": (
                self.llm_cleanup,
                "" if self.llm_cleanup else "gated off (needs AI layer enabled and a key)",
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _missing(flags: dict[str, bool]) -> str:
    absent = [name for name, present in flags.items() if not present]
    return "missing " + ", ".join(absent) if absent else ""


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def detect_capabilities(
    *, ocr_enabled: bool = False, llm_cleanup_enabled: bool = False
) -> Capabilities:
    """Probe libraries and binaries. Cheap; safe to call per run."""
    return Capabilities(
        pymupdf=_module_present("pymupdf") or _module_present("fitz"),
        pdfplumber=_module_present("pdfplumber"),
        camelot=_module_present("camelot"),
        pytesseract=_module_present("pytesseract"),
        ghostscript=shutil.which("gs") is not None,
        tesseract=shutil.which("tesseract") is not None,
        poppler=shutil.which("pdftoppm") is not None,
        ocrmypdf=shutil.which("ocrmypdf") is not None,
        ocr_enabled=ocr_enabled,
        llm_cleanup=llm_cleanup_enabled,
    )


__all__ = ["Capabilities", "detect_capabilities"]
