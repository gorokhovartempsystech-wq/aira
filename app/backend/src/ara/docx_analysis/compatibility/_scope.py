"""Reversible prefix and inherited URI rules; no per-node copies of the full scope."""

from collections import Counter

from ._models import require
from ._names import CORE, MC, PREFIX, XML, ncname, split, words


class Scope:
    def __init__(self):
        self.namespaces = {"xml": XML}
        self.pending = []
        self.ignorable = Counter()
        self.process = Counter()

    def start_ns(self, prefix, uri):
        self.pending.append((prefix or "", uri))

    def resolve(self, prefix, anchor):
        require(ncname(prefix), anchor)
        uri = self.namespaces.get(prefix)
        require(bool(uri) and uri != MC, anchor)
        return uri

    def prefixes(self, value, anchor):
        return tuple(self.resolve(prefix, anchor) for prefix in words(value))

    def enter(self, attrs, anchor):
        undo = []
        for prefix, uri in self.pending:
            undo.append((prefix, self.namespaces.get(prefix)))
            self.namespaces[prefix] = uri
        self.pending.clear()
        for name in attrs:
            require(
                not name.startswith(PREFIX) or name in CORE,
                anchor,
                "unsupported_compatibility_markup",
            )
        ignorable = self.prefixes(attrs.get(PREFIX + "Ignorable", ""), anchor)
        self.ignorable.update(ignorable)
        process = []
        for token in words(attrs.get(PREFIX + "ProcessContent", "")):
            pair = token.split(":")
            require(len(pair) == 2 and (pair[1] == "*" or ncname(pair[1])), anchor)
            uri = self.resolve(pair[0], anchor)
            require(self.ignorable[uri] > 0, anchor)
            process.append((uri, pair[1]))
        self.process.update(process)
        must = self.prefixes(attrs.get(PREFIX + "MustUnderstand", ""), anchor)
        return undo, ignorable, process, must

    def leave(self, saved):
        undo, ignorable, process, _ = saved
        for counter, keys in ((self.ignorable, ignorable), (self.process, process)):
            for key in keys:
                counter[key] -= 1
                if not counter[key]:
                    del counter[key]
        for prefix, old in reversed(undo):
            if old is None:
                del self.namespaces[prefix]
            else:
                self.namespaces[prefix] = old

    def unwrap(self, uri, local):
        return self.process[(uri, local)] > 0 or self.process[(uri, "*")] > 0

    def compatibility_attrs(self, attrs, anchor, *, choice=False):
        for name in attrs:
            uri, local = split(name)
            require(
                (not uri and choice and local == "Requires")
                or uri == MC
                or (uri not in ("", XML) and self.ignorable[uri] > 0),
                anchor,
            )
