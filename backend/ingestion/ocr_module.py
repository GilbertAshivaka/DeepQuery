"""
Deep Query — OCR Sub-module (Tesseract)

PURPOSE: Extract text from scanned pages ONLY for the BM25 sparse keyword
search index. This module is NOT used for embedding — Gemini Embedding 2
handles images natively.

Flow:
1. Receive a scanned page image (bytes)
2. Pre-process (deskew, binarise, denoise)
3. Run Tesseract OCR
4. Return extracted text + confidence score
"""

import io
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _resolve_tesseract_cmd() -> Optional[str]:
    """Find the Tesseract binary: explicit setting → PATH → common install dirs.
    Returns the path to use (or None to leave pytesseract's default)."""
    from core.config import settings

    if settings.tesseract_cmd and os.path.isfile(settings.tesseract_cmd):
        return settings.tesseract_cmd
    if shutil.which("tesseract"):
        return None  # on PATH — let pytesseract use its default
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass
class OCRResult:
    """Result of OCR processing on a single page/image."""

    text: str
    confidence: float  # 0.0 – 100.0
    is_usable: bool  # False if confidence is too low for BM25
    page_number: int = 0


class OCRModule:
    """Tesseract OCR wrapper for BM25 sparse index text extraction.

    Only used for scanned pages. OCR output is never sent to the embedding API.
    """

    # Minimum average confidence to consider OCR output usable for BM25
    MIN_CONFIDENCE_THRESHOLD = 40.0

    def __init__(self, lang: str = "eng"):
        self.lang = lang

    def process_image(
        self,
        image_bytes: bytes,
        page_number: int = 0,
    ) -> OCRResult:
        """Run OCR on an image and return text for the BM25 index.

        Args:
            image_bytes: Raw PNG/JPEG bytes of the scanned page.
            page_number: Source page number for metadata.

        Returns:
            OCRResult with extracted text and confidence score.
        """
        try:
            import pytesseract
        except ImportError:
            logger.error("pytesseract not installed. OCR disabled.")
            return OCRResult(text="", confidence=0.0, is_usable=False, page_number=page_number)

        resolved = _resolve_tesseract_cmd()
        if resolved:
            pytesseract.pytesseract.tesseract_cmd = resolved

        try:
            # Load image
            image = Image.open(io.BytesIO(image_bytes))

            # Pre-process for better OCR quality
            image = self._preprocess(image)

            # Run Tesseract with detailed output for confidence scores
            ocr_data = pytesseract.image_to_data(
                image, lang=self.lang, output_type=pytesseract.Output.DICT
            )

            # Extract text and compute average confidence
            words = []
            confidences = []
            for i, text in enumerate(ocr_data["text"]):
                conf = int(ocr_data["conf"][i])
                word = text.strip()
                if word and conf > 0:
                    words.append(word)
                    confidences.append(conf)

            extracted_text = " ".join(words)
            avg_confidence = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )

            is_usable = avg_confidence >= self.MIN_CONFIDENCE_THRESHOLD

            if not is_usable:
                logger.warning(
                    f"OCR confidence too low ({avg_confidence:.1f}%) for page {page_number}. "
                    f"Page will still be embedded as an image but won't participate in BM25."
                )

            return OCRResult(
                text=extracted_text,
                confidence=avg_confidence,
                is_usable=is_usable,
                page_number=page_number,
            )

        except Exception as e:
            logger.error(f"OCR failed for page {page_number}: {e}")
            return OCRResult(
                text="", confidence=0.0, is_usable=False, page_number=page_number
            )

    def _preprocess(self, image: Image.Image) -> Image.Image:
        """Pre-process image for better OCR quality.

        Steps: convert to grayscale → binarise → denoise.
        """
        try:
            import cv2

            # Convert PIL → numpy
            img_array = np.array(image)

            # Convert to grayscale if needed
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array

            # Adaptive thresholding (binarisation)
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )

            # Denoise
            denoised = cv2.fastNlMeansDenoising(binary, h=10)

            # Convert back to PIL
            return Image.fromarray(denoised)

        except ImportError:
            logger.warning("OpenCV not available. Skipping image pre-processing.")
            # Fallback: just convert to grayscale via PIL
            return image.convert("L")

    def process_batch(
        self, images: list[tuple[bytes, int]]
    ) -> list[OCRResult]:
        """Process multiple images. Each tuple is (image_bytes, page_number)."""
        return [self.process_image(img, page) for img, page in images]
