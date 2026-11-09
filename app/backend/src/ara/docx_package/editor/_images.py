"""Bounded inline raster insertion; no files, network, pixel decoding or OCR."""

import re
from dataclasses import dataclass, field

from ara.docx_analysis.visible_inline_images import _raster
from ara.docx_analysis.visible_main._models import VisibleLimits, VisibleViewError
from ara.docx_analysis.visible_main._reader import Refusal

from ..boundaries._tree import bounded_join, escape
from ..structure._models import text_valid
from ..structure._package import repack_parts
from ..structure._xml import scan
from . import _image_package
from ._models import EditorError
from ._objects import body_geometry, split_for_block

MAX_BYTES = 4 * 1024 * 1024
MAX_BASE64 = 4 * ((MAX_BYTES + 2) // 3)


@dataclass(frozen=True, slots=True)
class ImageData:
    data: bytes = field(repr=False)
    alt_text: str = field(default="", repr=False)

    def __post_init__(self):
        data, alt = getattr(self, "data", None), getattr(self, "alt_text", None)
        if (
            type(data) is not bytes
            or not 0 < len(data) <= MAX_BYTES
            or type(alt) is not str
            or len(alt) > 2000
            or not text_valid(alt)
        ):
            raise EditorError("invalid_input")


def raster(data):
    counter = _raster.Counter(VisibleLimits())
    try:
        if data.startswith(b"\x89PNG"):
            _raster.png(data, counter)
            width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            extension, mime = "png", "image/png"
        else:
            _raster.jpeg(data, counter)
            at = 2
            while at < len(data):
                while data[at] == 0xFF:
                    at += 1
                marker, at = data[at], at + 1
                size = int.from_bytes(data[at : at + 2], "big")
                if marker in (0xC0, 0xC2):
                    height = int.from_bytes(data[at + 3 : at + 5], "big")
                    width = int.from_bytes(data[at + 5 : at + 7], "big")
                    break
                at += size
            extension, mime = "jpg", "image/jpeg"
        if width * height > 20000000:
            raise EditorError("invalid_input")
        return width, height, extension, mime
    except (Refusal, VisibleViewError):
        raise EditorError("invalid_input") from None


def drawing(ns, rid, identity, width, height, alt):
    strict = ns.startswith("http://purl.oclc.org/")
    base = (
        "http://purl.oclc.org/ooxml/drawingml/"
        if strict
        else "http://schemas.openxmlformats.org/drawingml/2006/"
    )
    rel = (
        "http://purl.oclc.org/ooxml/officeDocument/relationships"
        if strict
        else "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    alt = escape(alt).replace("\n", "&#10;").replace("\t", "&#9;")
    return (
        f'<w:p xmlns:w="{ns}" xmlns:r="{rel}"><w:r><w:drawing '
        f'xmlns:wp="{base}wordprocessingDrawing" xmlns:a="{base}main" xmlns:pic="{base}picture">'
        f'<wp:inline><wp:extent cx="{width}" cy="{height}"/>'
        f'<wp:docPr id="{identity}" name="AIRA image {identity}" descr="{alt}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        f'<a:graphic><a:graphicData uri="{base}picture"><pic:pic><pic:nvPicPr>'
        f'<pic:cNvPr id="{identity}" name="AIRA image {identity}"/><pic:cNvPicPr/>'
        "</pic:nvPicPr><pic:blipFill>"
        f'<a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def insert(core, before, index, offset, value):
    ImageData(value.data, value.alt_text)
    width, height, extension, mime = raster(value.data)
    data, view, main, at, codec, ns = split_for_block(core, before, index, offset)
    available_w, available_h = body_geometry(main, ns, view.blocks[index + 1].anchor.path[-1])
    scale = min(9525, available_w * 635 / width, available_h * 635 / height)
    cx, cy = max(1, int(width * scale)), max(1, int(height * scale))
    used = set()
    for entry in view.source.entries:
        if (
            entry.content_type
            and entry.content_type.endswith("+xml")
            and entry.name.endswith(".xml")
        ):
            raw = (
                main
                if entry.name == view.source.main_part
                else _image_package.read(data, view.source, core._limits, entry.name)
            )
            nodes, _, _ = scan(raw)
            for node in nodes.values():
                if node.name in (
                    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr",
                    "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing}docPr",
                ):
                    identity = node.attrs.get("id", "")
                    if (
                        re.fullmatch(r"[+]?[0-9]{1,10}", identity) is None
                        or int(identity) > 0xFFFFFFFF
                    ):
                        raise EditorError("unsupported_intent")
                    used.add(int(identity))
    identity = next(n for n in range(1, len(used) + 2) if n not in used)
    rel = (
        "http://purl.oclc.org/ooxml/officeDocument/relationships/"
        if ns.startswith("http://purl.oclc.org/")
        else "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    )
    rid, replacements, additions = _image_package.resources(
        data, view.source, core._limits, value.data, extension, mime, rel
    )
    xml = drawing(ns, rid, identity, cx, cy, value.alt_text).encode(codec)
    replacements[view.source.main_part] = bounded_join(
        (main[:at], xml, main[at:]), core._limits.max_xml_bytes
    )
    return repack_parts(
        data, view.source, replacements, core._limits, additions=additions
    ), index + 2
