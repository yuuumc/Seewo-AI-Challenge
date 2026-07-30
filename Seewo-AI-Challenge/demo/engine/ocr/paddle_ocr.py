"""PaddleOCR engine — handwritten answer-sheet recognition with mock fallback.

Design:
    * ``PaddleOCREngine`` wraps ``paddleocr.PaddleOCR`` (v3.x API).
      On first use it lazily initialises the model (heavy import).
    * ``MockOCREngine`` returns deterministic placeholder text so tests
      and dev environments without paddlepaddle still work.
    * ``get_ocr_engine()`` auto-selects: PaddleOCR if importable and
      initialised, else MockOCREngine — no crash.
    * ``extract_text(image_bytes, question_type)`` is the single public
      entry point used by the Celery task and the Flask route.

The returned dict shape is:
    {
        "text": "recognized text or empty string",
        "confidence": float,        # 0.0–1.0
        "provider": "paddleocr" | "mock",
        "lines": [str, ...],        # per-line recognized text
        "question_type": str,       # echo-back
    }
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import os
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# ── Environment flags ─────────────────────────────────────────────────
# OCR_FORCE_MOCK=1 → always use mock (useful for CI and fast tests)
_FORCE_MOCK = os.environ.get("OCR_FORCE_MOCK", "") == "1"


def _try_import_paddleocr() -> Optional[Any]:
    """Attempt to import PaddleOCR; return None if unavailable."""
    try:
        from paddleocr import PaddleOCR  # type: ignore
        return PaddleOCR
    except Exception:
        return None


class MockOCREngine:
    """Deterministic mock OCR — no external dependencies.

    Returns a fixed placeholder string so downstream grading logic
    can be tested end-to-end without a real OCR engine.
    """

    @property
    def name(self) -> str:
        return "mock"

    def extract(
        self,
        image: Union[bytes, str],
        question_type: str = "long_answer",
    ) -> Dict[str, Any]:
        """Return a mock recognition result."""
        # If the caller passed a known image filename, try to return
        # a subject-appropriate placeholder.
        mock_text = self._mock_text_for_type(question_type)
        return {
            "text": mock_text,
            "confidence": 0.0,
            "provider": "mock",
            "lines": [mock_text] if mock_text else [],
            "question_type": question_type,
        }

    @staticmethod
    def _mock_text_for_type(question_type: str) -> str:
        """Return a plausible-looking answer string for the question type."""
        if question_type in ("choice", "fill_blank"):
            return "A"
        # long_answer / essay — a short derivation placeholder
        return "f'(x) = 3x² - 3, 令 f'(x)=0 得 x=±1, 函数在(-∞,-1)递增, (1,+∞)递增"


class PaddleOCREngine:
    """Real PaddleOCR wrapper with lazy initialisation.

    The PaddleOCR model is loaded on first ``extract()`` call to keep
    module import fast. If model loading fails (e.g. missing .pdmodel
    files, GPU mis-config), the engine degrades to MockOCREngine
    transparently.
    """

    def __init__(self) -> None:
        self._ocr: Optional[Any] = None
        self._init_error: Optional[str] = None
        self._mock_fallback = MockOCREngine()

    @property
    def name(self) -> str:
        return "paddleocr"

    def _ensure_model(self) -> bool:
        """Lazily initialise the PaddleOCR model. Returns True on success."""
        if self._ocr is not None:
            return True
        if self._init_error is not None:
            return False  # don't retry after first failure

        PaddleOCR = _try_import_paddleocr()
        if PaddleOCR is None:
            self._init_error = "paddleocr not installed"
            logger.warning("PaddleOCR not available, falling back to mock")
            return False

        try:
            # PaddleOCR v3.x API — use angle classification + Chinese OCR
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang="ch",
                show_log=False,
            )
            logger.info("PaddleOCR model initialised successfully")
            return True
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning("PaddleOCR init failed: %s — falling back to mock", exc)
            return False

    def extract(
        self,
        image: Union[bytes, str],
        question_type: str = "long_answer",
    ) -> Dict[str, Any]:
        """Run OCR on an image, return structured text.

        Parameters
        ----------
        image:
            Either raw image bytes, a base64-encoded string, or a file path.
        question_type:
            Echoed back in the result for downstream routing.
        """
        if not self._ensure_model():
            return self._mock_fallback.extract(image, question_type)

        # Normalise input to a file path or numpy array
        img_for_ocr = self._prepare_image(image)
        if img_for_ocr is None:
            return self._mock_fallback.extract(image, question_type)

        try:
            result = self._ocr.ocr(img_for_ocr, cls=True)
            lines, confidences = self._parse_paddle_result(result)
            avg_conf = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )
            full_text = "\n".join(lines)
            return {
                "text": full_text,
                "confidence": round(avg_conf, 4),
                "provider": "paddleocr",
                "lines": lines,
                "question_type": question_type,
            }
        except Exception as exc:
            logger.warning("PaddleOCR inference failed: %s — falling back to mock", exc)
            return self._mock_fallback.extract(image, question_type)

    @staticmethod
    def _prepare_image(image: Union[bytes, str]) -> Optional[Any]:
        """Convert image input to a form PaddleOCR accepts (numpy array or path).

        Returns None if the input cannot be converted.
        """
        # File path
        if isinstance(image, str) and not image.startswith("data:"):
            # Check if it's a base64 string (no slashes/backslashes typical of paths)
            try:
                # Try treating as file path first
                if os.path.isfile(image):
                    return image
            except (OSError, ValueError):
                pass
            # Try base64 decode
            try:
                raw = base64.b64decode(image, validate=True)
                return PaddleOCREngine._bytes_to_numpy(raw)
            except (binascii.Error, ValueError):
                return None

        # Raw bytes
        if isinstance(image, bytes):
            return PaddleOCREngine._bytes_to_numpy(image)

        # Data URI: data:image/png;base64,....
        if isinstance(image, str) and image.startswith("data:"):
            try:
                header, b64 = image.split(",", 1)
                raw = base64.b64decode(b64)
                return PaddleOCREngine._bytes_to_numpy(raw)
            except (ValueError, binascii.Error):
                return None

        return None

    @staticmethod
    def _bytes_to_numpy(raw: bytes) -> Optional[Any]:
        """Decode image bytes to a numpy array via PIL."""
        try:
            import numpy as np
            from PIL import Image
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            return np.array(img)
        except Exception:
            return None

    @staticmethod
    def _parse_paddle_result(result: Any) -> tuple[List[str], List[float]]:
        """Parse PaddleOCR output into (lines, confidences).

        PaddleOCR v3 returns a list of pages; each page is a list of
        [bbox, (text, confidence)] entries.
        """
        lines: List[str] = []
        confidences: List[float] = []

        if not result:
            return lines, confidences

        for page in result:
            if not page:
                continue
            for line in page:
                try:
                    # PaddleOCR v3 format: [bbox, (text, conf)]
                    text_conf = line[1]
                    text = text_conf[0]
                    conf = float(text_conf[1])
                    lines.append(text)
                    confidences.append(conf)
                except (IndexError, TypeError, ValueError):
                    continue

        return lines, confidences


# ── Module-level singleton ────────────────────────────────────────────
_engine_instance: Optional[Union[PaddleOCREngine, MockOCREngine]] = None


def get_ocr_engine() -> Union[PaddleOCREngine, MockOCREngine]:
    """Return the best available OCR engine (singleton).

    Selection order:
        1. OCR_FORCE_MOCK=1 → MockOCREngine
        2. PaddleOCR importable → PaddleOCREngine (degrades to mock
           internally if model init fails)
        3. Fallback → MockOCREngine
    """
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    if _FORCE_MOCK:
        _engine_instance = MockOCREngine()
        return _engine_instance

    if _try_import_paddleocr() is not None:
        _engine_instance = PaddleOCREngine()
    else:
        _engine_instance = MockOCREngine()

    return _engine_instance


def is_ocr_available() -> bool:
    """Check whether a real (non-mock) OCR engine is available."""
    if _FORCE_MOCK:
        return False
    return _try_import_paddleocr() is not None


def extract_text(
    image: Union[bytes, str],
    question_type: str = "long_answer",
) -> Dict[str, Any]:
    """Public convenience function — single entry point for OCR.

    Parameters
    ----------
    image:
        Image bytes, base64 string, data URI, or file path.
    question_type:
        Used for mock text generation and downstream routing.

    Returns
    -------
    dict with keys: text, confidence, provider, lines, question_type
    """
    engine = get_ocr_engine()
    return engine.extract(image, question_type)
