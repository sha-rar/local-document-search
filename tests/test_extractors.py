import pytest
from local_document_search.extractors import ExtractionError, extract_text, is_supported


@pytest.mark.parametrize("name", ["a.txt", "b.md", "C.TXT"])
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
