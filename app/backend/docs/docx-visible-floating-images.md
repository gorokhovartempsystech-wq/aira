# Floating raster pictures and source text

`ara.docx_analysis.visible_floating_images` provides `build_floating_image_snapshot`,
`map_floating_image_spans` and `map_floating_image_span`. The fixed profile is
`docx-analysis/final-visible-floating-images-v1`; NoteSnapshot, limits, style context
and source-slice DTOs remain the same as the [inline reader](docx-visible-inline-images.md).

A floating raster anchor contributes metadata and no inline character. Literal text
keeps its source order and continuity across that anchor. Inline pictures still split
text fragments. This follows the format's distinction between character-like inline
objects and separately positioned floating objects; it does not simulate physical page
reading order, pagination or glyph occlusion.

The closed grammar validates required anchor attributes, simple coordinates, horizontal
and vertical alignment/offsets, positive extents, optional effect extents, one wrapping
mode, object/frame properties and the existing embedded PNG/JPEG picture proof. Unused
position branches are validated too. Transitional and Strict namespace families remain
exact. Square, top/bottom, tight and through wrapping are supported; tight/through
polygons have checked start/line points and bounded raw XML. Behind-text wrapNone is
supported. Foreground wrapNone remains `unsupported_floating_overlay`, including when
the object also declares itself hidden.

Anchor/docPr/picture hidden flags record exclusion only after complete structure and
target validation. Run visibility, fields, table ownership, notes and control rules
remain unchanged. A plain-text control still refuses images. Visible floating objects
record `floating_raster_reference` at the original drawing anchor; referenced media
uses the relationship from that actual story. No source range is invented for coordinates.

Alternative descriptions/titles, text boxes, VML, charts/OLE/SVG, shape effects, unknown
extensions, other raster formats and linked/external images remain gates. An unproved
active structure or package part returns no partial text or note references. Unused
raster exclusion still requires complete active reference closure.

One fresh selected view and raster proof is built for every mapping batch, even empty.
Rehashed altered snapshots and older profiles are rejected. Raw XML/drawing counters,
package-wide raster counters and all output/coverage/manifest limits stay active. The
new profile does not change C1's compatibility capabilities or prior public behavior.

This reader remains opt-in; application admission, editor/export and native Word/Windows
acceptance are separate. Original DOCX bytes and exact Unicode source slices are preserved.
See the [contract](d03-17a2b5d2-contract.md) and [verification result](d03-17a2b5d2-result.md).
