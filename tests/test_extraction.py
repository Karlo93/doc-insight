from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
import pytest
from doc_insight.contracts.extraction import ExtractedDocument, Page
from doc_insight.worker.extraction import UnsupportedMediaType, extract, media_type
from doc_insight.worker.settings import get_settings
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "OCR_MIN_CHARS": "20",
        "OCR_DPI": "200",
        "OCR_LANGS": "eng+hrv",
    }.items():
        monkeypatch.setenv(f"DI_{key}", value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("filename", "words"),
    [
        ("text_en.pdf", ["Alice Johnson", "London"]),
        ("text_hr.pdf", ["Marić", "Zagrebu", "Škola"]),
    ],
)
def test_text_layers_preserve_words_and_unicode(
    filename: str, words: list[str]
) -> None:
    # Text-layer extraction must preserve Unicode and word boundaries without invoking OCR.
    result = extract(FIXTURES / filename)
    assert result.media_type == "application/pdf"
    assert result.page_count == 1
    assert result.pages[0].source == "text_layer"
    assert all(word in result.pages[0].text for word in words)
    assert "\r" not in result.pages[0].text


def test_image_uses_real_ocr() -> None:
    result = extract(FIXTURES / "scanned.png")
    assert result.media_type == "image/png"
    assert result.page_count == 1
    assert result.pages[0].source == "ocr"
    assert "Alice" in result.pages[0].text
    assert "London" in result.pages[0].text


def test_mixed_pdf_selects_ocr_per_page() -> None:
    result = extract(FIXTURES / "mixed.pdf")
    assert [page.source for page in result.pages] == ["text_layer", "ocr"]
    assert [page.number for page in result.pages] == [1, 2]
    assert all("Alice" in page.text for page in result.pages)


def test_long_fixture_has_six_pages_and_twelve_topics() -> None:
    result = extract(FIXTURES / "text_long.pdf")
    assert result.page_count == 6
    assert [page.number for page in result.pages] == list(range(1, 7))
    topics = [
        "Saturn",
        "sourdough",
        "coral",
        "railway",
        "vaccines",
        "orchard",
        "turbines",
        "tapestry",
        "chess",
        "ceramics",
        "newspapers",
        "rescue",
    ]
    for index, topic in enumerate(topics):
        assert topic in result.pages[index // 2].text
    assert all(page.source == "text_layer" for page in result.pages)


@pytest.mark.parametrize(
    "data", [b"", b"random unsupported bytes", b"GIF89a", b"PK\x03\x04"]
)
def test_unsupported_bytes_raise_a_typed_error(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "document.pdf"
    path.write_bytes(data)
    with pytest.raises(UnsupportedMediaType):
        extract(path)


def test_hash_describes_exact_bytes_and_is_stable() -> None:
    path = FIXTURES / "text_en.pdf"
    assert (
        extract(path).sha256
        == extract(path).sha256
        == sha256(path.read_bytes()).hexdigest()
    )


def test_png_with_pdf_extension_is_still_png(tmp_path: Path) -> None:
    path = tmp_path / "pretend.pdf"
    path.write_bytes((FIXTURES / "scanned.png").read_bytes())
    result = extract(path)
    assert result.media_type == "image/png"
    assert result.pages[0].source == "ocr"
    assert "London" in result.pages[0].text


@pytest.mark.parametrize(
    ("format_name", "expected"), [("JPEG", "image/jpeg"), ("TIFF", "image/tiff")]
)
def test_other_image_formats(tmp_path: Path, format_name: str, expected: str) -> None:
    path = tmp_path / "image.data"
    with Image.open(FIXTURES / "scanned.png") as image:
        image.save(path, format=format_name)
    result = extract(path)
    assert result.media_type == expected
    assert result.page_count == 1
    assert "Alice" in result.pages[0].text


def test_sideways_scan_is_uprighted_by_its_exif_tag(tmp_path: Path) -> None:
    """Cameras and scanners store rotation in EXIF instead of moving pixels."""
    path = tmp_path / "sideways.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: viewer must rotate 90 degrees clockwise.
    with Image.open(FIXTURES / "scanned.png") as image:
        image.rotate(90, expand=True).save(path, format="JPEG", exif=exif)
    result = extract(path)
    assert result.media_type == "image/jpeg"
    assert "Alice" in result.pages[0].text
    assert "London" in result.pages[0].text


@pytest.mark.parametrize("signature", [b"II*\x00", b"MM\x00*"])
def test_both_tiff_byte_orders(signature: bytes) -> None:
    assert media_type(signature) == "image/tiff"


def test_short_text_layer_triggers_configured_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_length = extract(FIXTURES / "text_en.pdf").pages[0].char_count
    monkeypatch.setenv("DI_OCR_MIN_CHARS", str(text_length + 1))
    get_settings.cache_clear()
    assert extract(FIXTURES / "text_en.pdf").pages[0].source == "ocr"
    monkeypatch.setenv("DI_OCR_MIN_CHARS", str(text_length))
    get_settings.cache_clear()
    assert extract(FIXTURES / "text_en.pdf").pages[0].source == "text_layer"


def test_missing_ocr_command_fails_without_silent_empty_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DI_TESSERACT_CMD", str(tmp_path / "missing-tesseract"))
    with pytest.raises(pytesseract.TesseractNotFoundError):
        extract(FIXTURES / "scanned.png")


def test_corrupt_pdf_is_not_reported_as_unsupported_type(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nbroken")
    with pytest.raises(pdfium.PdfiumError):
        extract(path)


def test_missing_file_propagates(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract(tmp_path / "missing.pdf")


def test_counts_are_derived_and_included_in_json() -> None:
    page = Page(number=1, text="čćđšž", source="text_layer")
    document = ExtractedDocument(
        sha256="a" * 64, media_type="application/pdf", pages=[page]
    )
    assert document.model_dump()["pages"][0]["char_count"] == 5
    assert document.model_dump()["page_count"] == 1
    page.text = "new text"
    assert page.char_count == 8


def test_settings_load_once_and_validate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert get_settings() is get_settings()
    monkeypatch.setenv("DI_OCR_DPI", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="ocr_dpi"):
        get_settings()


def test_fixture_budget() -> None:
    assert sum(path.stat().st_size for path in FIXTURES.iterdir()) <= 300_000
