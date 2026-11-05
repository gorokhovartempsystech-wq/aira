"""All semantic ownership is logical; every stored address belongs to original XML."""

from ara.docx_analysis.compatibility_contexts._anchors import SourceAnchors
from ara.docx_analysis.visible_control_tables._context import ControlContext
from ara.docx_analysis.visible_control_tables._reader import TableControlReader
from ara.docx_analysis.visible_notes._proofs import NoteTables
from ara.docx_analysis.visible_stories._proofs import StoryTables


class SourceControls(SourceAnchors, ControlContext):
    pass


class SourceReader(SourceAnchors, TableControlReader):
    def control_context_type(self):
        return SourceControls


class SourceStoryTables(SourceAnchors, StoryTables):
    pass


class SourceNoteTables(SourceAnchors, NoteTables):
    pass
