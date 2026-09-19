"""Deterministic extraction of corporate facts from collected documents.

The ladder is PyMuPDF text -> pdfplumber tables -> Camelot (needs ghostscript) ->
OCR (needs tesseract + poppler) -> LLM clean-up (gated). Each stage runs only when
its capability is present; a missing stage is recorded, never faked.
"""
