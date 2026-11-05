"""Independent synthetic packages and readers for DOCX edit acceptance."""

from importlib import import_module
from io import BytesIO
from zipfile import ZipFile

from docx_package_fixtures import (
    MAIN_CONTENT_TYPE,
    RELS_CONTENT_TYPE,
    build_package,
    content_types_xml,
    minimal_parts,
    relationships_xml,
)

MAIN = "word/document.xml"


def edit_api():
    return import_module("ara.docx_package.editing")


def projection_api():
    return import_module("ara.docx_package.projection")


def raw_package(
    main_xml,
    *,
    main_part=MAIN,
    extra_parts=None,
    extra_types=None,
    links=(),
    comment=b"",
    directories=(),
):
    parts = minimal_parts(main_part)
    parts[main_part] = main_xml
    parts.update(extra_parts or {})
    parts["[Content_Types].xml"] = content_types_xml(
        defaults={
            "rels": RELS_CONTENT_TYPE,
            "xml": "application/xml",
            "bin": "application/octet-stream",
        },
        overrides={
            "/" + main_part: MAIN_CONTENT_TYPE,
            **{"/" + name: value for name, value in (extra_types or {}).items()},
        },
    )
    if links:
        directory, _, basename = main_part.rpartition("/")
        name = f"{directory + '/' if directory else ''}_rels/{basename}.rels"
        parts[name] = relationships_xml(links)
    return build_package(parts, comment=comment, directories=directories)


def text_spans(projection):
    result = []
    stack = list(reversed(projection.blocks))
    while stack:
        block = stack.pop()
        if block.kind == "paragraph":
            result.extend(span for span in block.spans if span.kind == "text")
        elif block.kind == "table":
            children = [child for row in block.rows for cell in row.cells for child in cell.blocks]
            stack.extend(reversed(children))
    return tuple(result)


def zip_parts(data, *, comment=b""):
    # Fixtures know their own comment. Trimming that exact suffix avoids using
    # production ZIP helpers when a synthetic comment contains EOCD signatures.
    if comment:
        assert data.endswith(comment)
        data = data[: -len(comment)]
    with ZipFile(BytesIO(data)) as archive:
        return {item.filename: archive.read(item) for item in archive.infolist()}
