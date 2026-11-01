"""An opt-in grammar for direct property histories, not a styles/visibility resolver."""

from ._reader import Reader

PROPERTIES_PROFILE = "docx-analysis/final-properties-v1"


class PropertiesReader(Reader):
    def property_history(self, node, kind):
        name = self.name(node)
        expected = "pPrChange" if kind == "pPr" else "rPrChange"
        if name != expected:
            return False
        self.revision(node)
        self.containers(node)
        old_name = "pPr" if kind == "pPr" else "rPr"
        self.check(len(node) == 1 and self.name(node[0]) == old_name)
        self.event("excluded", "historical_properties", node)
        return True
