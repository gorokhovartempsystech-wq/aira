"""Allow only known inert template metadata; preserve visibility refusal."""

from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from ara.docx_analysis.visible_main import build_visible_snapshot
from ara.docx_package.creation import NewParagraph, create_docx


def read(data):
    return build_visible_snapshot(
        data, document_id=uuid4(), storage_revision=1, source_sha256=sha256(data).hexdigest()
    )


def test_own_body_and_heading_template_is_readable():
    data = create_docx((NewParagraph("Заголовок", "heading1"), NewParagraph("Текст требований")))
    before = sha256(data).hexdigest()
    result = read(data)
    assert result.complete
    assert [f.text for f in result.fragments] == ["Заголовок", "Текст требований"]
    assert sha256(data).hexdigest() == before


def test_unknown_settings_are_not_whitelisted():
    data = create_docx((NewParagraph("Текст требований"),))
    target = BytesIO()
    with ZipFile(BytesIO(data)) as src, ZipFile(target, "w") as out:
        for name in src.namelist():
            value = src.read(name)
            if name == "word/settings.xml":
                value = value.replace(b"</w:settings>", b"<w:trackRevisions/></w:settings>")
            out.writestr(name, value)
    assert not read(target.getvalue()).complete


def test_numbered_list_remains_blocked_until_supported():
    assert not read(create_docx((NewParagraph("Текст требований", "numbered"),))).complete
