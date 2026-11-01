"""Extract text from supported document formats.

Each extractor takes a file path, plus the file's bytes when the caller has already read
them, and returns its text. Register new formats in ``EXTRACTORS`` keyed by lower-case
file extension.
"""

import io
from collections.abc import Callable
from pathlib import Path

import docx
from docx.table import Table
from pypdf import PdfReader

Extractor = Callable[[Path, bytes | None], str]


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


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ExtractionError(f"cannot read file: {exc.strerror or exc}") from exc


def extract_plain_text(path: Path, data: bytes | None = None) -> str:
    if data is None:
        data = _read(path)
    try:
        return decode_text(data)
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"cannot decode text: {exc.reason}") from exc


def extract_pdf_text(path: Path, data: bytes | None = None) -> str:
    """Extract the text layer of a PDF; scanned pages without one yield no text."""
    try:
        reader = PdfReader(path if data is None else io.BytesIO(data))
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


# Password-protected Office files are OLE compound files rather than ZIP packages.
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells = []
        seen = set()
        for cell in row.cells:
            # Merged cells repeat the same underlying cell; keep its text once.
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            cells.append(cell.text)
        lines.append("\t".join(cells))
    return lines


def extract_docx_text(path: Path, data: bytes | None = None) -> str:
    """Extract body paragraphs and table text from a Word document, in document order."""
    try:
        if data is None:
            data = _read(path)
        if data.startswith(OLE_SIGNATURE):
            raise ExtractionError("DOCX is password-protected")
        document = docx.Document(io.BytesIO(data))
        lines = []
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                lines.extend(_table_lines(block))
            else:
                lines.append(block.text)
    except ExtractionError:
        raise
    except OSError as exc:
        raise ExtractionError(f"cannot read file: {exc.strerror or exc}") from exc
    except Exception as exc:
        # python-docx raises ZIP, XML and package errors for malformed files.
        raise ExtractionError(f"cannot parse DOCX: {exc}") from exc
    return "\n".join(lines)


EXTRACTORS: dict[str, Extractor] = {
    ".txt": extract_plain_text,
    ".md": extract_plain_text,
    ".pdf": extract_pdf_text,
    ".docx": extract_docx_text,
}


def get_extractor(path: Path) -> Extractor | None:
    return EXTRACTORS.get(path.suffix.lower())


def is_supported(path: Path) -> bool:
    return get_extractor(path) is not None


def extract_text(path: Path, data: bytes | None = None) -> str:
    """Extract ``path``'s text, using ``data`` instead of reading the file when given."""
    extractor = get_extractor(path)
    if extractor is None:
        raise ExtractionError(f"unsupported file type: {path.suffix or '(none)'}")
    return extractor(path, data)
