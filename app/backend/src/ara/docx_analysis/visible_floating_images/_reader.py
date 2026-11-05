"""An anchored object has source provenance but contributes no inline glyph."""

from ara.docx_analysis.visible_inline_images._reader import ImageReader

from ._grammar import Grammar


class FloatingReader(ImageReader):
    def extended_run(self, child, plan):
        if self.name(child) != "drawing":
            return super().extended_run(child, plan)
        grammar = Grammar(self, self.media)
        if len(child) != 1 or child[0].tag != grammar.wp + "anchor":
            return super().extended_run(child, plan)
        hidden = grammar.drawing(child)
        self.event(
            "excluded" if hidden else "metadata",
            "hidden_floating_image" if hidden else "floating_raster_reference",
            child,
        )
