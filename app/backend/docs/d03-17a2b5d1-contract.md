# D03-17A2b5d1 — inline raster images and source-backed text boundaries

5 November 2026, F05/F06/F11. Baseline: verified B3 `d7c1eaf`.
One opt-in reader/mapping extension. Original DOCX untouched. No raster rendering,
OCR, text-box support, application admission, editing/export or native Word parity.

## Paths and checks

New src/ara/docx_analysis/visible_inline_images/, acceptance
 tests/acceptance/test_docx_visible_inline_images.py and edge
 tests/docx_documents/test_visible_inline_images_edges.py; this contract/result,
 docs/docx-visible-inline-images.md, docs/development-queue.md and ignored .runtime.
Only three old private hooks: visible_notes/_build.py, visible_notes/_assemble.py,
visible_notes/_coverage.py under src/ara/docx_analysis. Old public defaults/profiles
and tests unchanged. No schema/dependencies/runner/tasks/progress/scope changes.
Freeze/red → implementation/review/regression → full check → readonly V8/hashes →
selective local commit. Documented new-test preparation corrections may preserve
all assertions; no old-test weakening. No source/test/contract edits during full gate.
Continue the next bounded cycle after completion.

## Evidence and content subset

[ECMA-376 Part1 fifth edition](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
Strict CT_Inline, CT_Picture, CT_BlipFillProperties, CT_NonVisualDrawingProps and
CT_ShapeProperties inspected. [Microsoft inline-picture example](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-insert-a-picture-into-a-word-processing-document)
shows the same ownership chain; [Blip](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.blip)
distinguishes embedded and linked targets. Binary framing uses
[PNG third edition](https://www.w3.org/TR/png-3/) and
[T.81 Annex B](https://www.w3.org/Graphics/JPEG/itu-t81.pdf).

Exactly one wp:inline within w:drawing. Closed ordered grammar: extent, optional
effectExtent, docPr, optional cNvGraphicFramePr, a:graphic/graphicData with exact
picture URI, pic:pic containing nvPicPr(cNvPr,cNvPicPr), blipFill, spPr. Require
one embedded a:blip; optional srcRect, then a:stretch with one fillRect. Shape props:
optional xfrm/off/ext and rect prstGeom with optional empty avLst. No shape effects,
style, fills, lines, scene, extension lists or arbitrary descendants. Lock children
are leaves with known boolean attrs. Exact Transitional/Strict namespace families;
no mixed-family/local-name aliases. Numeric ranges and lexical booleans checked.
Coordinate support is integral EMU; non-integral/unit-bearing variants remain gates.
Crop percentages support family-correct lexical values (Strict percent suffix,
Transitional integral thousandths); no rewrite/geometry calculation. No tile fill.
All attributes/order/cardinality/text/tails checked; missing required fields refuse.

Nonempty descr/title is an explicit alt-text gate pending its separate semantics;
name/id are non-displayed object metadata. True docPr or cNvPr hidden excludes the
image marker only after complete drawing/target proof; current run visibility applies
as before. Zero extent remains unsupported rather than guessing visibility. Floating
anchors, text boxes, VML, charts/OLE/SVG, external or linked images and extension
payloads remain gates. Plain controls continue refusing images. Rich controls, tables,
headers/footer and referenced notes inherit the existing source ownership rules.

Each embed resolves in its own story's relationships: exact image relationship URI,
internal mode, actual target and PNG/JPEG MIME plus matching binary framing. External
resources are never opened. Duplicate/missing/incorrect target follows existing
package validation or explicit incomplete result. Original anchors include drawing
and blip, and exact source SHA binds relationship and image bytes.

PNG proof: signature, bounded CRC-checked chunks, first single valid IHDR dimensions/
color/depth/compression/filter/interlace, legal palette presence/order/size, contiguous
nonempty total IDAT group, empty final IEND at exact EOF. Unknown critical chunks,
reserved invalid chunk names, animation and malformed framing refuse. Ancillary
metadata is nontext, with CRC/length checked. JPEG proof: SOI, bounded marker segments,
one SOF0 or SOF2 frame with positive dimensions/valid components, coherent SOS shape,
nonempty entropy-coded scans with stuffing/restart handling, final EOI at exact EOF.
No unsupported frame/hierarchical/arithmetic/DNL/unknown markers. DQT/DHT/DRI framing
is checked; APP/COM payload remains opaque metadata. No decompression, raster pixel
allocation or text extraction. These bounded format/structure checks identify a
raster part, not full entropy/pixel conformance or a promise that Word renders it.
Native fidelity remains separate.

## Assembly, limits and authority

New fixed profile docx-analysis/final-visible-inline-images-v1 and public
build_inline_image_snapshot, map_inline_image_spans and singular map. Same exact
identity, VisibleLimits, NoteSnapshot, style profile and span DTOs. No public caller
view/reader/part-classification/capability injection. One new coherent C2B view per
build; C1's declared base-Word compatibility selection remains unchanged. Drawing
extension namespaces do not become understood by recognizing an ordinary picture.

Validate bytes/identity/hash/package before use. New aggregate raw drawing count in
all original scoped XML (including discarded/deleted branches) before first DOM,
limited by min(10000,max_pieces). Existing node/depth/character/field/control limits
still apply. Every recognized raster MIME part is read once with bounded package
reads; PNG chunks/JPEG segments and restarts share one aggregate counter limited by
min(100000,max_pieces). Existing part/total-byte limits bound binary reads; never
allocate from declared raster dimensions. Bad raster framing is unaccounted, not
metadata by MIME. Limit errors remain VisibleViewError(view_limit_exceeded).

Used proven raster parts become metadata; valid unused raster parts are excluded
only after complete active story/reference closure. No orphan exclusion after failed
story reading or with any unknown part. Atomic incomplete means no text, fragments,
paragraphs, runs or note references. Previous unrelated gates remain intact.

Each visible image emits a private zero-text atom. Output segments the actual paragraph
at the image anchor, keeping original paragraph/flow ownership and deterministic
unique fragment IDs. Consecutive images produce no empty requirements; neighboring
words are never concatenated across a visible image. Generated note references retain
nearest-fragment links across either marker kind. No invented spaces, alt text, OCR
or source offsets. Hidden images create no visible boundary. Field-code atoms remain
excluded and cached field-result atoms retain their current ordering.

Private hooks: shared build accepts optional output/coverage factories with runtime
old defaults; NoteOutput exposes a default label marker-code map and image subclass
adds its own map; package coverage accepts private additional-part accounting, only
used by the new source-derived media object and only emitted as success after closure.
No global mutation/default profile change. Mapping validates exact NoteSnapshot and
rebuilds once per batch including empty. Rehashed text/provenance/coverage is rejected.
All combined output/coverage/manifest bounds and privacy/inert-import rules persist.

## Acceptance

PNG/baseline+progressive JPEG, Strict UTF16 and original custom part names; inline
boundaries, consecutive/repeated/image-only cases, hidden run/object visibility,
final insertions/deletions, MC, rich controls/table cells, owning header/note links
and note-marker neighbors. Independent XML source slice resolution. Old profiles
closed; manifest tampering rejected. Invalid structural children/attrs/roles,
alternative text, unsupported drawing, target mode/type/owner, MIME spoofing, framing,
CRC/truncation/unknown/animation and unknown parts give atomic refusal. Raw counts
precede DOM including excluded branches/unreferenced images. Limits at exact output
boundaries, input/shape checks, one batch rebuild, no network/application/pixel-codec
imports or serialization. Full gate, hashes and readonly V8 mandatory.
