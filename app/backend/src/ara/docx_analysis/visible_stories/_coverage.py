"""Unreferenced stories are excludable only after every active story is proven."""

from ara.docx_analysis.inventory import _classify
from ara.docx_analysis.visible_main._build import PROPERTIES
from ara.docx_analysis.visible_main._models import VisibleCoverage, budget

from ._parse import SETTINGS_MIME, STORY_TYPES, STYLES_MIME


def package_coverage(source, section_catalog, style_context, failures, limits):
    used = {s.part_name for s in section_catalog.stories}

    def classification(entry):
        category, _ = _classify(entry.name, entry.content_type, source.main_part)
        if category == "main_body":
            return "main"
        if category == "package_metadata" or entry.content_type in PROPERTIES:
            return "metadata"
        if category == "comments":
            return "comments"
        if entry.content_type == STYLES_MIME:
            return "styles"
        if entry.content_type == SETTINGS_MIME:
            return "settings"
        if entry.content_type in STORY_TYPES:
            return "story"
        return "unknown"

    def known(entry):
        kind = classification(entry)
        if kind == "styles":
            return style_context.status == "ready" and entry.name == style_context.styles_part
        if kind == "settings":
            return (
                section_catalog.status == "indexed" and entry.name == section_catalog.settings_part
            )
        return kind != "unknown"

    proven = (
        not failures
        and section_catalog.status == "indexed"
        and style_context.status in ("ready", "absent")
        and all(known(e) for e in source.entries)
    )
    coverage = []

    def add(status, code, part, anchor=None):
        budget(len(coverage) + 1, limits.max_coverage_items)
        coverage.append(VisibleCoverage(status, code, part, anchor, None))

    for entry in source.entries:
        kind = classification(entry)
        if kind == "main":
            status, code = "metadata", "main_part"
        elif kind == "metadata":
            status, code = "metadata", "package_metadata"
        elif kind == "comments":
            status, code = "excluded", "comments_policy"
        elif kind == "styles":
            status, code = (
                ("metadata", "style_context_accounted")
                if proven
                else ("blocked", "style_usage_unproven")
            )
        elif kind == "settings":
            status, code = (
                ("metadata", "section_settings_accounted")
                if proven
                else ("blocked", "section_settings_unproven")
            )
        elif kind == "story":
            if not proven:
                status, code = "blocked", "story_usage_unproven"
            elif entry.name in used:
                status, code = "metadata", "section_story_part"
            else:
                status, code = "excluded", "unreferenced_section_story"
        else:
            status, code = "blocked", "unread_part"
        add(status, code, entry.name)
    for part, code, anchor in failures:
        add("blocked", code, part, anchor)
    return proven, coverage
