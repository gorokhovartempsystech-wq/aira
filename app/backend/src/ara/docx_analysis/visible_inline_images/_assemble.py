"""Separate literal fragments at visible images without inventing text or offsets."""

from ara.docx_analysis.visible_notes._assemble import Output as NoteOutput

from ._reader import IMAGE


class Output(NoteOutput):
    marker_codes = NoteOutput.marker_codes | {IMAGE: "inline_raster_boundary"}
