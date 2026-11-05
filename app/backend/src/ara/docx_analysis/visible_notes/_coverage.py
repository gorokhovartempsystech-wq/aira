"""No orphan/special exclusions until the entire retained reference closure is proved."""

from ara.docx_analysis.inventory import _classify
from ara.docx_analysis.visible_main._build import PROPERTIES
from ara.docx_analysis.visible_main._models import VisibleCoverage, budget
from ara.docx_analysis.visible_stories._parse import SETTINGS_MIME, STORY_TYPES, STYLES_MIME

from ._parse import NOTE_TYPES


def package_coverage(
    source, sections, notes, styles, used_notes, failures, limits, *, accounted_parts=None
):
    stories = {s.part_name for s in sections.stories}
    accounted_parts = {} if accounted_parts is None else accounted_parts

    def classification(entry):
        if entry.name in accounted_parts:
            return "additional"
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
        if entry.content_type in NOTE_TYPES:
            return "notes"
        return "unknown"

    def known(entry):
        kind = classification(entry)
        if kind == "styles":
            return styles.status == "ready" and entry.name == styles.styles_part
        if kind == "settings":
            return sections.status == "indexed" and entry.name == sections.settings_part
        return kind != "unknown"

    proven = (
        not failures
        and sections.status == "indexed"
        and notes.status in ("indexed", "absent")
        and styles.status in ("ready", "absent")
        and all(known(e) for e in source.entries)
    )
    coverage = []

    def add(status, code, part, anchor=None):
        budget(len(coverage) + 1, limits.max_coverage_items)
        coverage.append(VisibleCoverage(status, code, part, anchor, None))

    for entry in source.entries:
        kind = classification(entry)
        if kind == "additional":
            status, code = (
                accounted_parts[entry.name] if proven else ("blocked", "additional_usage_unproven")
            )
        elif kind == "main":
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
        elif kind == "notes":
            status, code = (
                ("metadata", "note_part_accounted")
                if proven
                else ("blocked", "note_usage_unproven")
            )
        elif kind == "story":
            if not proven:
                status, code = "blocked", "story_usage_unproven"
            elif entry.name in stories:
                status, code = "metadata", "section_story_part"
            else:
                status, code = "excluded", "unreferenced_section_story"
        else:
            status, code = "blocked", "unread_part"
        add(status, code, entry.name)
    if proven:
        for part in notes.parts:
            for definition in part.definitions:
                if definition.note_type != "normal":
                    status, code = "excluded", "special_note"
                elif definition.anchor in used_notes:
                    status, code = "metadata", "note_definition_read"
                else:
                    status, code = "excluded", "unreferenced_note"
                add(status, code, part.part_name, definition.anchor)
    for part, code, anchor in failures:
        add("blocked", code, part, anchor)
    return proven, coverage
