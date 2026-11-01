"""A rendered synthetic Word fixture must survive the package API byte for byte."""

from hashlib import sha256
from importlib import import_module
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"
EXPECTED_HASH = "73009626640400679d2b1a2031c565a964308073aa287067cf39088836176fcd"


def test_rendered_docx_preserves_every_part_and_original_archive():
    data = FIXTURE.read_bytes()
    assert sha256(data).hexdigest() == EXPECTED_HASH
    api = import_module("ara.docx_package")
    source = api.open_docx(data)
    assert source.main_part == "word/document.xml"
    assert source.sha256 == EXPECTED_HASH
    inventory = {item.name: item for item in source.entries}
    assert {
        "word/document.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/header1.xml",
        "word/footer1.xml",
        "word/media/image1.png",
    } <= set(inventory)
    with ZipFile(BytesIO(data)) as original:
        names = {entry.filename for entry in original.infolist() if not entry.is_dir()}
        assert set(inventory) == names
        for name in names:
            payload = original.read(name)
            assert inventory[name].sha256 == sha256(payload).hexdigest()
            assert inventory[name].size_bytes == len(payload)
    assert any(item.target_mode == "External" for item in source.relationships)
    exported = api.export_original(source)
    assert exported == data
    reopened = api.open_docx(exported)
    assert reopened.sha256 == source.sha256
    assert reopened.entries == source.entries
    assert reopened.relationships == source.relationships
