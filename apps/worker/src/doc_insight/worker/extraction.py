"""File/PDF/OCR adapter; no file access or OCR occurs when importing this module."""

from contextlib import closing
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
from doc_insight.contracts.extraction import ExtractedDocument, MediaType, Page
from doc_insight.worker.settings import Settings, get_settings
from PIL import Image, ImageOps


class UnsupportedMediaType(ValueError):
    """The input does not start with a supported PDF or image signature."""


def media_type(data: bytes) -> MediaType:
    """Use content rather than a filename supplied by the caller."""
    signatures: tuple[tuple[bytes, MediaType], ...] = (
        (b"%PDF-", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"II*\x00", "image/tiff"),
        (b"MM\x00*", "image/tiff"),
    )
    for signature, kind in signatures:
        if data.startswith(signature):
            return kind
    raise UnsupportedMediaType("Expected PDF, PNG, JPEG or TIFF bytes")


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _ocr(image: Image.Image, settings: Settings) -> str:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    return _normalize(str(pytesseract.image_to_string(image, lang=settings.ocr_langs)))


def _pdf_page(page: pdfium.PdfPage, number: int, settings: Settings) -> Page:
    """Prefer a sufficient text layer; otherwise OCR the rendered page at configured DPI."""
    with closing(page.get_textpage()) as text_page:
        text = _normalize(str(text_page.get_text_bounded()))
    if len(text) >= settings.ocr_min_chars:
        return Page(number=number, text=text, source="text_layer")
    # PDF coordinates are points (72 per inch); OCR resolution is dots per inch.
    with (
        closing(page.render(scale=settings.ocr_dpi / 72)) as bitmap,
        bitmap.to_pil() as image,
    ):
        text = _ocr(image, settings)
    return Page(number=number, text=text, source="ocr")


def extract(path: Path) -> ExtractedDocument:
    """Extract ordered pages from one byte snapshot, also used for its digest.

    PDFium and pytesseract configuration are used sequentially in this CLI process.
    Images, including TIFF, intentionally yield only their first frame.
    """
    data = path.read_bytes()
    kind = media_type(data)
    settings = get_settings()
    if kind == "application/pdf":
        with pdfium.PdfDocument(data) as document:
            pages = []
            for index in range(len(document)):
                with closing(document[index]) as page:
                    pages.append(_pdf_page(page, index + 1, settings))
    else:
        with Image.open(BytesIO(data)) as image:
            # Scanners record rotation in EXIF rather than rotating the pixels.
            ImageOps.exif_transpose(image, in_place=True)
            pages = [Page(number=1, text=_ocr(image, settings), source="ocr")]
    return ExtractedDocument(
        sha256=sha256(data).hexdigest(), media_type=kind, pages=pages
    )
