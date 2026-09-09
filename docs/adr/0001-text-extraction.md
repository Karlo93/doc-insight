# ADR-0001: Text extraction with pypdfium2 and Tesseract

Status: accepted for M1. Date: 2026-09-09.

## Context

Inputs include PDFs with searchable text, scanned PDFs and standalone images,
including Croatian text. Processing must run locally on Windows and Linux,
and tests must exercise OCR without network access or cloud credentials.

## Decision

Use pypdfium2 for PDF text and rendering, Pillow for images, and pytesseract
as the adapter to an installed Tesseract binary with `eng+hrv` language data.
Detect PDF/PNG/JPEG/TIFF signatures from bytes; filenames cannot select a parser.
OCR a PDF page only when stripped text has fewer than 20 characters by default.
Render at 200 DPI by default: a practical initial cost/readability trade-off,
configurable through the same settings object as the threshold and languages.

Keep this I/O in the worker extraction adapter; share only Pydantic results in
contracts. Normalize newlines before future stages calculate character offsets.
Use bounded text extraction to retain Unicode beyond the basic multilingual plane.
Close native handles in context managers, including on OCR failures.

## Consequences

Text PDFs avoid unnecessary OCR. Scans require a separately installed binary;
CI installs it and exercises the committed image and mixed PDF fixtures.
OCR is approximate, so tests check names/places rather than exact transcripts.
The threshold cannot detect a large image beside an otherwise sufficient text
layer; region-level OCR remains outside M1. Images yield their first frame only.
PDFium is not thread-safe, so this CLI processes pages sequentially.

## Alternatives

- **PyMuPDF:** technically capable, but its AGPL/commercial licensing requires a
  different licensing choice; this slice uses pypdfium2's permissive distribution.
- **pdfplumber:** useful for detailed text/table layouts, but has no OCR engine;
  scans would still require rendering plus OCR, so it adds no benefit here.
- **Cloud OCR:** potentially stronger layout recognition, but sends document data
  to another provider and adds credentials, network dependence and cost.
- **OCR every page:** wastes work and can replace exact text with recognition errors.

References: [pypdfium2 API and handle lifecycle](https://pypdfium2.readthedocs.io/en/stable/python_api.html),
[pytesseract usage](https://github.com/madmaze/pytesseract),
[PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html).
