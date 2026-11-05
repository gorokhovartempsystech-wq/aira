"""Prove recorded plain controls before any paragraph/run output is assembled."""

from ara.docx_analysis.visible_compatibility._reader import SourceReader

from ._grammar import Grammar
from ._proof import Proof


class PlainReader(SourceReader):
    def __init__(self, root, *args, **kwargs):
        self.logical_parents, self.plain_controls = {}, {}
        stack = [(root, None)]
        while stack:
            node, parent = stack.pop()
            self.logical_parents[node] = parent
            stack.extend((child, node) for child in node)
        super().__init__(root, *args, **kwargs)

    def grammar_type(self):
        return Grammar

    def plans(self):
        plans = super().plans()
        for node, content in self.plain_controls.items():
            Proof(self).validate(node, content)
        return plans
