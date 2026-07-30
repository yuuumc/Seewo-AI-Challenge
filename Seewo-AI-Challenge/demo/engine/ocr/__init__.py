"""OCR engine sub-package — handwritten answer-sheet recognition.

Public API:
    get_ocr_engine()  → PaddleOCREngine | MockOCREngine
    is_ocr_available() → bool
    extract_text(image_bytes, question_type) → dict
"""
from __future__ import annotations

from engine.ocr.paddle_ocr import (
    PaddleOCREngine,
    MockOCREngine,
    get_ocr_engine,
    is_ocr_available,
    extract_text,
)

__all__ = [
    "PaddleOCREngine",
    "MockOCREngine",
    "get_ocr_engine",
    "is_ocr_available",
    "extract_text",
]
