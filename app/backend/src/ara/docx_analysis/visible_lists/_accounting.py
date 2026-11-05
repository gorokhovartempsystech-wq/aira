"""No numbering-used/unused assertion survives incomplete retained story closure."""

from ara.docx_analysis.visible_inline_images._media import Media
from ara.docx_analysis.visible_notes._coverage import package_coverage


class Accounting(Media):
    def __init__(self, data, source, bounds, limits, lists):
        self.lists = lists
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
        if self.lists.part is not None:
            accounted[self.lists.part] = (
                ("metadata", "numbering_definition_used")
                if self.lists.used
                else ("excluded", "unused_numbering_definition")
            )
        if self.lists.failed:
            failures = [*failures, (source.main_part, "unproved_numbering_definition", None)]
        return package_coverage(
            source, sections, notes, styles, used_notes, failures, limits, accounted_parts=accounted
        )
