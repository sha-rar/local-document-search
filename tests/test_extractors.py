import pytest
from local_document_search.extractors import ExtractionError, extract_text, is_supported
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def write_pdf(path, page_texts, user_password=None, owner_password=None):
    """Write a PDF whose pages each draw one line of Helvetica text (None = blank page)."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for text in page_texts:
        page = writer.add_blank_page(612, 792)
        if text is None:
            continue
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(content)
    if user_password is not None:
        writer.encrypt(user_password, owner_password, algorithm="RC4-128")
    with open(path, "wb") as fh:
        writer.write(fh)


@pytest.mark.parametrize("name", ["a.txt", "b.md", "C.TXT", "d.pdf", "E.PDF"])
def test_supported_extensions(tmp_path, name):
    assert is_supported(tmp_path / name)


def test_unsupported_extension_raises(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG")
    assert not is_supported(path)
    with pytest.raises(ExtractionError):
        extract_text(path)


@pytest.mark.parametrize(
    "data",
    [
        "café".encode("utf-8"),
        "café".encode("utf-8-sig"),
        "café".encode("utf-16"),
        "café".encode("cp1252"),
    ],
)
def test_decodes_common_encodings(tmp_path, data):
    path = tmp_path / "doc.txt"
    path.write_bytes(data)
    assert extract_text(path) == "café"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ExtractionError):
        extract_text(tmp_path / "gone.txt")


def test_pdf_text_from_every_page(tmp_path):
    path = tmp_path / "report.pdf"
    write_pdf(path, ["First page budget", "Second page forecast"])
    text = extract_text(path)
    assert "First page budget" in text
    assert "Second page forecast" in text


def test_pdf_without_text_layer_is_empty(tmp_path):
    path = tmp_path / "scan.pdf"
    write_pdf(path, [None])
    assert extract_text(path).strip() == ""


def test_pdf_with_empty_user_password_is_readable(tmp_path):
    path = tmp_path / "restricted.pdf"
    write_pdf(path, ["Owner locked"], user_password="", owner_password="owner")
    assert "Owner locked" in extract_text(path)


def test_password_protected_pdf_raises(tmp_path):
    path = tmp_path / "secret.pdf"
    write_pdf(path, ["Hidden"], user_password="secret")
    with pytest.raises(ExtractionError, match="password"):
        extract_text(path)


@pytest.mark.parametrize("data", [b"", b"not a pdf at all", b"%PDF-1.7\n%%EOF"])
def test_malformed_pdf_raises(tmp_path, data):
    path = tmp_path / "broken.pdf"
    path.write_bytes(data)
    with pytest.raises(ExtractionError):
        extract_text(path)
