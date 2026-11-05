"""Bound fourth-profile provenance shape; only parent source proof authorizes semantics."""

from ..review_fixture import _require
from ._context import anchor, descendant


def read_binding(item, source_sha256, paragraph, properties, definition):
    source, chain = item["numbering_source"], item["style_chain"]
    _require(type(source) is str and source in ("direct", "style"))
    _require(type(chain) is list and len(chain) <= 128)
    selector, binding = item["style_reference_anchor"], item["level_style_anchor"]
    if source == "direct":
        _require(not chain and selector is None and binding is None)
        _require(descendant(properties, paragraph))
        return 0
    _require(bool(chain))
    addresses = [anchor(a, source_sha256) for a in chain]
    _require(len(set(addresses)) == len(addresses))
    _require(all(a[0] == properties[0] for a in addresses))
    _require(properties[0] not in (paragraph[0], definition[0]))
    _require(definition[0] != paragraph[0] and descendant(properties, addresses[-1]))
    if selector is not None:
        _require(descendant(anchor(selector, source_sha256), paragraph))
    _require(anchor(binding, source_sha256)[0] == definition[0])
    return len(addresses)
