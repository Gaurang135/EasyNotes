"""Optional image OCR for diagram-heavy slides and scanned PDFs.

Opt-in (OCR_ENABLED=1) and kept out of the default install to keep the core lean.
Uses RapidOCR on ONNX Runtime — pip-installable, no Tesseract/system dependency,
and reuses the onnxruntime we already ship. Degrades to a no-op if the extra isn't
installed, so parsing never breaks.
"""
from __future__ import annotations
import os
import logging

log = logging.getLogger("easynotes.ocr")
_engine = None
_tried = False


def ocr_enabled() -> bool:
    return os.environ.get("OCR_ENABLED", "").lower() in ("1", "true", "yes")


def _get_engine():
    global _engine, _tried
    if _tried:
        return _engine
    _tried = True
    if not ocr_enabled():
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
        log.info("OCR engine loaded (RapidOCR)")
    except Exception as e:  # extra not installed / load failure
        log.warning("OCR_ENABLED but RapidOCR unavailable (pip install rapidocr-onnxruntime): %s", e)
        _engine = None
    return _engine


def ocr_image(data: bytes) -> str:
    """Return recognized text from image bytes, or '' if OCR is off/unavailable/empty."""
    eng = _get_engine()
    if eng is None or not data:
        return ""
    try:
        import numpy as np
        import cv2
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return ""
        result, _ = eng(img)
        if not result:
            return ""
        return "\n".join(line[1] for line in result).strip()
    except Exception as e:
        log.warning("OCR failed on an image: %s", e)
        return ""
