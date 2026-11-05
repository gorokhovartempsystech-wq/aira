# Inline raster images in the analysis source

`ara.docx_analysis.visible_inline_images` provides `build_inline_image_snapshot`,
`map_inline_image_spans` and `map_inline_image_span`. Its fixed profile is
`docx-analysis/final-visible-inline-images-v1`. The reader extends the
[plain-control profile](docx-visible-plain-controls.md) with the same NoteSnapshot,
exact identity, limits, style context and original source addresses.

One inline DrawingML object must contain a recognized picture, with closed structure
and an embedded image relationship in its own story. PNG and 8-bit baseline/progressive
JPEG are accounted after bounded binary framing checks. Declared MIME or filename
alone is insufficient. PNG chunk lengths/CRC/order and JPEG frame/scan/segment framing
are checked without decoding pixels, decompressing image metadata, allocating from
declared dimensions or opening remote targets. This establishes raster accounting;
it does not establish complete codec conformance or native rendering quality.

A visible inline image separates neighboring literal text fragments. It contributes
no invented character, alternate text or OCR output. Each side keeps its actual
paragraph/cell/story and original XML slices. Consecutive images create no empty
requirements. Note references keep their nearest nonempty text fragments. Current
run visibility and proven object-hidden flags suppress the image boundary, after
the same syntax/target validation. Field-code images do not become visible content.

The supported picture grammar includes integral positions/dimensions, crop rectangles,
stretch fill, a rectangular shape, basic transform and frame/picture locks. It supports
matching Transitional and Strict namespaces, including source-selected MC wrappers.
The declared base-Word compatibility capability set is unchanged. An unknown DrawingML
extension is not understood merely because a simple picture can be read.

Nonempty alternative descriptions/titles, floating anchors, VML, text boxes, shapes
with text/effects, charts, OLE, SVG, linked/external targets and other image encodings
remain explicit gates. Plain-text controls continue refusing images. Any unsupported
active structure or unaccounted part yields an atomic incomplete snapshot. Valid unused
raster parts are excluded only after complete active story/reference closure succeeds.
Neither ignored branches nor deleted content are revived through image references.

Raw drawings, including excluded branches, are counted before the first DOM, up to
min(10000,max_pieces). Binary chunks/segments/restarts share a package-wide counter
up to min(100000,max_pieces), including unreferenced images. Package byte limits and
all existing semantic/output/coverage/manifest bounds remain active. Every mapping
batch rebuilds once from pinned bytes, including an empty batch. A recomputed digest
does not authorize changed text or coverage; older profiles remain mutually closed.

This is an opt-in analysis reader. Application admission, full editing/export and
native Word/Windows acceptance remain separate. Original document bytes are unchanged.
See the [contract](d03-17a2b5d1-contract.md) and [verification result](d03-17a2b5d1-result.md).
