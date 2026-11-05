"""One generated marker per retained paragraph, however many literal fragments it has."""

from ara.docx_analysis.visible_inline_images._assemble import Output as ImageOutput
from ara.docx_analysis.visible_main._models import budget


class Output(ImageOutput):
    def __init__(self, *args, lists, **kwargs):
        self.lists = lists
        super().__init__(*args, **kwargs)

    def paragraph(self, reader, paragraph, visible):
        before = len(self.fragments)
        super().paragraph(reader, paragraph, visible)
        selection = reader.direct_lists.get(paragraph)
        if selection is not None:
            fragments = tuple(f.fragment_id for f in self.fragments[before:])
            self.lists.append(paragraph, selection, fragments)
            self.cover("metadata", "list_label", selection.properties)
        budget(self.position + self.lists.generated, self.limits.max_text_characters)
