"""Original-image atoms participate in field filtering and effective run visibility."""

from ara.docx_analysis.visible_plain_controls._reader import PlainReader

from ._grammar import Grammar

IMAGE = "inline_raster"


class ImageReader(PlainReader):
    def __init__(self, *args, media, **kwargs):
        self.media = media
        super().__init__(*args, **kwargs)

    def extended_run(self, child, plan):
        if self.name(child) != "drawing":
            return super().extended_run(child, plan)
        hidden = Grammar(self, self.media).drawing(child)
        if hidden:
            self.event("excluded", "hidden_inline_image", child)
        else:
            plan.atoms.append((IMAGE, child, ""))
