"""Extract text from supported document formats.

Each extractor takes a file path and returns its text. Register new formats in
``EXTRACTORS`` keyed by lower-case file extension.
"""

from collections.abc import Callable
from pathlib import Path

from pypdf import PdfReader

Extractor = Callable[[Path], str]


class ExtractionError(Exception):
    """Raised when a supported file cannot be read or decoded."""


def decode_text(data: bytes) -> str:
    """Decode bytes predictably: BOM-marked UTF-8/UTF-16, then UTF-8, then cp1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Legacy Windows text files are usually cp1252; replace undefined bytes.
        return data.decode("cp1252", errors="replace")


def extract_plain_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ExtractionError(f"cannot read file: {exc.strerror or exc}") from exc
    try:
        return decode_text(data)
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"cannot decode text: {exc.reason}") from exc


def extract_pdf_text(path: Path) -> str:
    """Extract the text layer of a PDF; scanned pages without one yield no text."""
    try:
        reader = PdfReader(path)
        # Many encrypted PDFs only restrict editing and open with an empty password.
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("PDF is password-protected")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ExtractionError:
        raise
    except OSError as exc:
        raise ExtractionError(f"cannot read file: {exc.strerror or exc}") from exc
    except Exception as exc:
        # pypdf raises many exception types for malformed files; one bad PDF must not stop a scan.
        raise ExtractionError(f"cannot parse PDF: {exc}") from exc
    return "\n\n".join(pages)


EXTRACTORS: dict[str, Extractor] = {
    ".txt": extract_plain_text,
    ".md": extract_plain_text,
    ".pdf": extract_pdf_text,
}


def get_extractor(path: Path) -> Extractor | None:
    return EXTRACTORS.get(path.suffix.lower())


def is_supported(path: Path) -> bool:
    return get_extractor(path) is not None


def extract_text(path: Path) -> str:
    extractor = get_extractor(path)
    if extractor is None:
        raise ExtractionError(f"unsupported file type: {path.suffix or '(none)'}")
    return extractor(path)
