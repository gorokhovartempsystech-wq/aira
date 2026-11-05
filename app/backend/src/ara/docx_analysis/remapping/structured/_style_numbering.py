"""Physical inherited style origins enter the new profile's correspondence key."""

from ._source import address


def provenance(item, relative):
    # Caller has rederived both snapshots/results from the original packages. Do not
    # turn a style numPr into a fictitious paragraph-relative address. Non-main part
    # seals independently require unchanged original style/numbering bytes.
    return dict(
        properties=relative(item["properties_anchor"])
        if item["numbering_source"] == "direct"
        else address(item["properties_anchor"]),
        numbering_source=item["numbering_source"],
        style_reference=relative(item["style_reference_anchor"])
        if item["style_reference_anchor"] is not None
        else None,
        style_chain=[address(a) for a in item["style_chain"]],
        level_style=address(item["level_style_anchor"])
        if item["level_style_anchor"] is not None
        else None,
    )
