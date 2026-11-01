"""Builders for test documents, so no binary fixtures are committed."""

import docx
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


def write_docx(path, paragraphs):
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)
