"""Unused numbering is conditional on complete retained text and relationship proof."""

from ara.docx_analysis.visible_inline_images._media import Media
from ara.docx_analysis.visible_notes._coverage import package_coverage

from ._numbering import unused


class Accounting(Media):
    def __init__(self, data, source, bounds, limits, namespace):
        super().__init__(data, source, bounds, limits)
        self.numbering, self.numbering_failed = unused(data, source, bounds, namespace)

    def coverage(self, source, sections, notes, styles, used_notes, failures, limits):
        accounted = {
            name: (
                ("metadata", "raster_image_part")
                if name in self.used
                else ("excluded", "unreferenced_raster_image")
            )
            for name in self.parts
        }
        accounted.update(
            {name: ("excluded", "unused_numbering_definition") for name in self.numbering}
        )
        if self.numbering_failed:
            failures = [*failures, (source.main_part, "unproved_numbering_definition", None)]
        return package_coverage(
            source,
            sections,
            notes,
            styles,
            used_notes,
            failures,
            limits,
            accounted_parts=accounted,
        )
