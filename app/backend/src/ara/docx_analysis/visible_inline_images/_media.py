"""Source-owned raster proofs; no unused-image exclusion before story closure."""

import io
import zipfile

from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_notes._coverage import package_coverage
from ara.docx_package._zip import chunks, parsing_end

from ._raster import Counter, jpeg, png

READERS = {"image/png": png, "image/jpeg": jpeg}


class Media:
    def __init__(self, data, source, bounds, limits):
        self.parts, self.used = set(), set()
        counter = Counter(limits)
        with io.BytesIO(data[: parsing_end(data, bounds)]) as buffer, zipfile.ZipFile(buffer) as z:
            for entry in source.entries:
                parser = READERS.get(entry.content_type)
                if parser is None:
                    continue
                raw = b"".join(
                    chunks(data, buffer, z, z.getinfo(entry.name), bounds.max_part_bytes)
                )
                try:
                    parser(raw, counter)
                except Refusal:
                    continue
                self.parts.add(entry.name)

    def use(self, reader, blip, rid):
        relationship = reader.links.get(rid)
        if (
            relationship is None
            or relationship.relationship_type != reader.rel_ns + "/image"
            or relationship.target_mode != "Internal"
            or relationship.resolved_part not in self.parts
        ):
            raise Refusal("unproved_inline_image_target")
        self.used.add(relationship.resolved_part)
        reader.event("metadata", "embedded_raster_reference", blip)

    def coverage(self, *args):
        accounted = {
            name: (
                ("metadata", "raster_image_part")
                if name in self.used
                else ("excluded", "unreferenced_raster_image")
            )
            for name in self.parts
        }
        return package_coverage(*args, accounted_parts=accounted)
