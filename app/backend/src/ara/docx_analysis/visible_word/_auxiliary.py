"""Exact auxiliary closure. Failures never become successful unused-part exclusions."""

import re

from ara.docx_analysis.visibility._grammar import Unsupported, check
from ara.docx_analysis.visible_inline_images._media import Media
from ara.docx_analysis.visible_notes._coverage import package_coverage

from . import _appearance
from ._fonts import font_table
from ._roles import (
    BASE,
    CUSTOM_PROPS,
    EFFECTS,
    EFFECTS_REL,
    SR,
    THEME,
    THUMBNAIL,
    R,
    role,
    standard,
)
from ._styles import agree

BIB = "http://schemas.openxmlformats.org/officeDocument/2006/bibliography"
DS = "{http://schemas.openxmlformats.org/officeDocument/2006/customXml}"


def thumbnail(source):
    images = {e.name for e in source.entries if e.content_type in {"image/png", "image/jpeg"}}
    links = [
        r
        for r in source.relationships
        if r.relationship_type == THUMBNAIL or (r.source_part == "/" and r.resolved_part in images)
    ]
    if not links:
        return None
    check(len(links) == 1)
    link = links[0]
    check(
        link.source_part == "/"
        and link.target_mode == "Internal"
        and link.relationship_type == THUMBNAIL
    )
    part = link.resolved_part
    check(
        any(
            e.name == part and e.content_type in {"image/png", "image/jpeg"} for e in source.entries
        )
    )
    check([r for r in source.relationships if r.resolved_part == part] == links)
    check(not any(r.source_part == part for r in source.relationships))
    return part


def bibliography(source, roots):
    links = [
        r
        for r in source.relationships
        if r.relationship_type in {R + "customXml", SR + "customXml"}
    ]
    props = {e.name for e in source.entries if e.content_type == CUSTOM_PROPS}
    prop_links = [
        r
        for r in source.relationships
        if r.relationship_type in {R + "customXmlProps", SR + "customXmlProps"}
    ]
    if not links and not props and not prop_links:
        return ()
    check(len(links) == len(props) == len(prop_links) == 1)
    link = links[0]
    check(link.source_part == source.main_part and link.target_mode == "Internal")
    part = link.resolved_part
    check(any(e.name == part and e.content_type == "application/xml" for e in source.entries))
    check([r for r in source.relationships if r.resolved_part == part] == links)
    prop = role(source, CUSTOM_PROPS, {R + "customXmlProps", SR + "customXmlProps"}, part)
    check([r for r in source.relationships if r.source_part == part] == prop_links)
    root = roots[part]
    _appearance.empty_text(root)
    check(root.tag == "{" + BIB + "}Sources" and not len(root))
    check(set(root.attrib) <= {"SelectedStyle", "StyleName", "Version"})
    item = roots[prop]
    _appearance.empty_text(item)
    check(item.tag == DS + "datastoreItem" and set(item.attrib) == {DS + "itemID"})
    check(
        re.fullmatch(
            r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}", item.get(DS + "itemID")
        )
        is not None
    )
    check(len(item) == 1 and item[0].tag == DS + "schemaRefs" and not item[0].attrib)
    refs = item[0]
    _appearance.empty_text(refs)
    check(len(refs) == 1 and refs[0].tag == DS + "schemaRef" and not len(refs[0]))
    _appearance.empty_text(refs[0])
    check(dict(refs[0].attrib) == {DS + "uri": BIB})
    return part, prop


def auxiliary(source, prepared):
    roots = {p.part_name: p.root for p in prepared.view.parts}
    accounted = font_table(source, roots)
    for suffix, mime, proof in (
        ("webSettings", BASE + "webSettings+xml", _appearance.web),
        ("theme", THEME, _appearance.theme),
    ):
        part = standard(source, suffix, mime)
        if part is not None:
            proof(roots[part])
            accounted[part] = ("metadata", "word_" + suffix + "_accounted")
    effects = role(source, EFFECTS, {EFFECTS_REL}, source.main_part)
    if effects is not None:
        base = prepared.contexts.styles.styles_part
        check(base is not None)
        agree(roots[base], roots[effects], prepared.view)
        accounted[effects] = ("metadata", "equivalent_styles_copy")
    thumb = thumbnail(source)
    if thumb is not None:
        accounted[thumb] = ("excluded", "package_thumbnail")
    for part in bibliography(source, roots):
        check(part not in accounted)
        accounted[part] = ("excluded", "empty_bibliography_store")
    return accounted


class Accounting(Media):
    def __init__(self, data, source, bounds, limits, lists, prepared):
        self.lists, self.additional, self.failed = lists, {}, False
        try:
            self.additional = auxiliary(source, prepared)
        except Unsupported:
            self.failed = True
        super().__init__(data, source, bounds, limits)

    def coverage(self, source, sections, notes, styles, used_notes, failures, limits):
        accounted = {
            part: (
                ("metadata", "raster_image_part")
                if part in self.used
                else ("excluded", "unreferenced_raster_image")
            )
            for part in self.parts
        }
        accounted.update(self.additional)
        if self.lists.part is not None:
            accounted[self.lists.part] = (
                ("metadata", "numbering_definition_used")
                if self.lists.used
                else ("excluded", "unused_numbering_definition")
            )
        if self.lists.failed:
            failures = [*failures, (source.main_part, "unproved_numbering_definition", None)]
        if self.failed:
            failures = [*failures, (source.main_part, "word_package_auxiliary_unproven", None)]
        return package_coverage(
            source, sections, notes, styles, used_notes, failures, limits, accounted_parts=accounted
        )
