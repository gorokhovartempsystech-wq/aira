"""A fixed ordinary-package policy, not an upgrade of stored older snapshots."""

from dataclasses import dataclass

from ara.docx_analysis.visible_style_lists import StyleListSnapshot

PROFILE = "docx-analysis/final-visible-word-package-v1"
STYLE_PROFILE = "docx-visibility/mc-word-package-styles-v1"
CONTEXT_PROFILE = "docx-compatibility/selected-word-package-contexts-v1"
CATALOG_PROFILE = "docx-compatibility/word-package-selection-v1"


@dataclass(frozen=True, slots=True)
class WordSnapshot(StyleListSnapshot):
    pass
