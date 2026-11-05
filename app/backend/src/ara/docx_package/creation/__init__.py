"""Create new DOCX bytes with AIRA's basic template, entirely in memory.

This API does not restyle imported documents, save files, or create UI/storage
records. Lists are single-level; each record is one paragraph, not Markdown.
"""

from dataclasses import dataclass, field, fields
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .. import DocxError, DocxLimits
from ..projection import ProjectionError, ProjectionLimits, project_docx

__all__ = ["NewParagraph", "CreationLimits", "CreationError", "create_docx"]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_STYLES = {
    "body": "Normal",
    "title": "Title",
    "heading1": "Heading1",
    "heading2": "Heading2",
    "heading3": "Heading3",
    "bullet": "ListBullet",
    "numbered": "ListNumber",
}


class CreationError(ValueError):
    """Content-free diagnostics for invalid input or generation bounds."""

    _MESSAGES = {
        "invalid_input": "Invalid new DOCX input or limits.",
        "generation_limit_exceeded": "New DOCX exceeds a technical generation limit.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class NewParagraph:
    text: str = field(default="", repr=False)
    style: str = "body"

    def __post_init__(self) -> None:
        text, style = getattr(self, "text", None), getattr(self, "style", None)
        if type(text) is not str or type(style) is not str or style not in _STYLES:
            raise CreationError("invalid_input")


@dataclass(frozen=True, slots=True)
class CreationLimits:
    max_paragraphs: int = 1000
    max_text_chars: int = 1000000

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or value <= 0:
                raise CreationError("invalid_input")


def _text(text: str) -> str:
    # LF and TAB are Word elements, never literal XML whitespace that Word
    # might collapse. Emit empty segments too, including an editable blank.
    result = []
    for index, line in enumerate(text.split("\n")):
        if index:
            result.append("<w:br/>")
        for position, piece in enumerate(line.split("\t")):
            if position:
                result.append("<w:tab/>")
            escaped = piece.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            result.append('<w:t xml:space="preserve">' + escaped + "</w:t>")
    return "".join(result)


def _document(paragraphs: tuple[NewParagraph, ...]) -> tuple[str, int]:
    output = []
    last_style, number_id = None, 1
    for paragraph in paragraphs:
        props = f'<w:pStyle w:val="{_STYLES[paragraph.style]}"/>'
        if paragraph.style in ("bullet", "numbered"):
            if paragraph.style == "numbered" and last_style != "numbered":
                number_id += 1
            current_id = 1 if paragraph.style == "bullet" else number_id
            props += f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{current_id}"/></w:numPr>'
        output.append(f"<w:p><w:pPr>{props}</w:pPr><w:r>{_text(paragraph.text)}</w:r></w:p>")
        last_style = paragraph.style
    section = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
    )
    return (
        f'<w:document xmlns:w="{_W}"><w:body>{"".join(output)}{section}</w:body></w:document>',
        number_id,
    )


def _styles() -> str:
    font = '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/>'
    normal_run = (
        f'{font}<w:color w:val="000000"/><w:sz w:val="22"/><w:szCs w:val="22"/>'
        '<w:lang w:val="ru-RU" w:eastAsia="ru-RU" w:bidi="ru-RU"/>'
    )
    spacing = '<w:spacing w:after="120" w:line="276" w:lineRule="auto"/>'
    output = [
        f'<w:styles xmlns:w="{_W}">',
        f"<w:docDefaults><w:rPrDefault><w:rPr>{normal_run}</w:rPr></w:rPrDefault>"
        f"<w:pPrDefault><w:pPr><w:widowControl/>{spacing}</w:pPr></w:pPrDefault></w:docDefaults>",
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/>'
        f"<w:pPr><w:widowControl/>{spacing}</w:pPr><w:rPr>{normal_run}</w:rPr></w:style>",
    ]
    for name, label, size, before, after, outline in (
        ("Title", "Title", 44, 0, 240, None),
        ("Heading1", "heading 1", 32, 240, 120, 0),
        ("Heading2", "heading 2", 26, 180, 100, 1),
        ("Heading3", "heading 3", 22, 120, 80, 2),
    ):
        level = "" if outline is None else f'<w:outlineLvl w:val="{outline}"/>'
        output.append(
            f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{label}"/>'
            '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            "<w:pPr><w:keepNext/><w:keepLines/>"
            f'<w:spacing w:before="{before}" w:after="{after}"/>{level}</w:pPr>'
            '<w:rPr><w:b/><w:bCs/><w:color w:val="000000"/>'
            f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr></w:style>'
        )
    for name, label in (("ListBullet", "List Bullet"), ("ListNumber", "List Number")):
        output.append(
            f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{label}"/>'
            '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            '<w:pPr><w:spacing w:after="60"/></w:pPr></w:style>'
        )
    return "".join(output) + "</w:styles>"


def _numbering(last_number_id: int) -> str:
    output = [f'<w:numbering xmlns:w="{_W}">']
    for index, fmt, marker in ((0, "bullet", "•"), (1, "decimal", "%1.")):
        output.append(
            f'<w:abstractNum w:abstractNumId="{index}"><w:multiLevelType w:val="singleLevel"/>'
            f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
            f'<w:lvlText w:val="{marker}"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:tabs><w:tab w:val="num" w:pos="360"/></w:tabs>'
            '<w:ind w:left="360" w:hanging="360"/></w:pPr>'
            '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/></w:rPr></w:lvl></w:abstractNum>'
        )
    output.append('<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>')
    for index in range(2, last_number_id + 1):
        output.append(
            f'<w:num w:numId="{index}"><w:abstractNumId w:val="1"/>'
            '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
        )
    return "".join(output) + "</w:numbering>"


def _parts(document: str, number_id: int) -> tuple[tuple[str, str], ...]:
    word_type = "application/vnd.openxmlformats-officedocument.wordprocessingml."
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/word/document.xml" ContentType="{word_type}document.main+xml"/>'
        + "".join(
            f'<Override PartName="/word/{name}.xml" ContentType="{word_type}{name}+xml"/>'
            for name in ("styles", "numbering", "settings")
        )
        + "</Types>"
    )
    rels_start = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    )
    root_rels = (
        rels_start
        + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="word/document.xml"/>'
        + "</Relationships>"
    )
    doc_rels = (
        rels_start
        + "".join(
            f'<Relationship Id="rId{index}" Type="{_R}/{name}" Target="{name}.xml"/>'
            for index, name in enumerate(("styles", "numbering", "settings"), start=1)
        )
        + "</Relationships>"
    )
    settings = (
        f'<w:settings xmlns:w="{_W}"><w:compat>'
        '<w:compatSetting w:name="compatibilityMode" '
        'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>'
    )
    return (
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", root_rels),
        ("word/document.xml", document),
        ("word/_rels/document.xml.rels", doc_rels),
        ("word/styles.xml", _styles()),
        ("word/numbering.xml", _numbering(number_id)),
        ("word/settings.xml", settings),
    )


def create_docx(
    paragraphs: tuple[NewParagraph, ...] = (),
    *,
    creation_limits: CreationLimits | None = None,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
) -> bytes:
    """Return a deterministic, validated new document without persistence or I/O."""
    if creation_limits is None:
        creation_limits = CreationLimits()
    if type(creation_limits) is not CreationLimits or type(paragraphs) is not tuple:
        raise CreationError("invalid_input")
    creation_limits.__post_init__()
    if limits is not None:
        if type(limits) is not DocxLimits:
            raise DocxError("invalid_input")
        limits.__post_init__()
    if projection_limits is not None:
        if type(projection_limits) is not ProjectionLimits:
            raise ProjectionError("invalid_input")
        projection_limits.__post_init__()
    if max(1, len(paragraphs)) > creation_limits.max_paragraphs:
        raise CreationError("generation_limit_exceeded")
    total = 0
    for paragraph in paragraphs:
        if type(paragraph) is not NewParagraph:
            raise CreationError("invalid_input")
        paragraph.__post_init__()
        total += len(paragraph.text)
        if total > creation_limits.max_text_chars:
            raise CreationError("generation_limit_exceeded")
        for char in paragraph.text:
            point = ord(char)
            if not (
                point in (9, 10)
                or 0x20 <= point <= 0xD7FF
                or 0xE000 <= point <= 0xFFFD
                or 0x10000 <= point <= 0x10FFFF
            ):
                raise CreationError("invalid_input")
    document, number_id = _document(paragraphs or (NewParagraph(),))
    buffer = BytesIO()
    with ZipFile(buffer, "w") as package:
        for name, markup in _parts(document, number_id):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_DEFLATED
            package.writestr(info, (_XML + markup).encode("utf-8"), compresslevel=6)
    data = buffer.getvalue()
    project_docx(data, limits=limits, projection_limits=projection_limits)
    return data
