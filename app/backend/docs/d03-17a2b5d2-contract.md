# D03-17A2b5d2 — floating raster anchors and logical text continuity

5 November 2026, F05/F06/F11. Baseline: verified D1 `68eeecf`.
One opt-in analysis reader/mapping extension. No page layout/occlusion engine,
text boxes, image editing, application admission or native Word fidelity claim.

## Paths and verification

New src/ara/docx_analysis/visible_floating_images/;
tests/acceptance/test_docx_visible_floating_images.py and
 tests/docx_documents/test_visible_floating_images_edges.py; this contract/result,
 docs/docx-visible-floating-images.md, docs/development-queue.md and ignored .runtime.
Only two old private hooks, under src/ara/docx_analysis/visible_inline_images:
_api.py (extract fixed private builder) and _grammar.py (extract graphic proof).
Old public behavior/defaults/profiles/tests unchanged. No schema/dependencies/runner/
tasks/progress/scope changes. Freeze/red → implement/review/regression → full gate →
readonly mainV8/hashes → selective local commit. Documented new-test preparation
corrections allowed while assertions stay unchanged. No source/test/contract edits
while the full gate runs. Continue next bounded cycle after completion.

## Evidence and semantics

[ECMA-376 Part1 fifth edition](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
Strict CT_Anchor, CT_PosH/V, CT_WrapNone/Square/Tight/Through/TopBottom/Path and enums
inspected from official schema archive. [Microsoft Anchor](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.wordprocessing.anchor?view=openxml-3.0.1)
distinguishes an inline character-like object from a floating object positioned relative
to the page. Our logical-reading inference: a floating raster's source anchor contributes
no inline glyph, literal character or fragment boundary. Text retains its source order
and continuity; coordinates and wrap geometry are metadata. This does not establish
physical page reading order or which glyphs are occluded in a rendered page.

[WrapNone](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.wordprocessing.wrapnone?view=openxml-3.0.1)
allows an object in front of text. Keep wrapNone with behindDoc=false as an explicit
unsupported_floating_overlay gate, including hidden objects. Behind-text wrapNone and
the four supported wrapping modes may be accounted. The gate avoids a claim about
foreground occlusion; it is not a replacement for native visual QA of other layout.

## Closed retained grammar

One w:drawing contains exactly one wp:anchor. Transitional or Strict namespaces match
its owning Word story, sharing D1's exact picture/embedded-raster relationship proof.
Required attrs: relativeHeight uint32; behindDoc/locked/layoutInCell/allowOverlap exact
XML booleans. Optional simplePos/hidden exact XML booleans and distT/B/L/R uint32.
No unknown attrs, namespaced aliases, wp14 positioning extensions or multiple objects.

Ordered children: simplePos with integral x/y, positionH, positionV, positive extent,
optional effectExtent, exactly one wrap, docPr, optional cNvGraphicFramePr, a:graphic.
Common effect/object/frame/graphic/picture rules are exactly D1's. Validate all position
fields even when simplePos selects its own coordinates. positionH/V each has required
relativeFrom enum and exactly one leaf align enum or integral signed32 posOffset.
H reference values margin/page/column/character/leftMargin/rightMargin/insideMargin/
outsideMargin; V margin/page/paragraph/line/topMargin/bottomMargin/insideMargin/
outsideMargin. H align left/right/center/inside/outside; V top/bottom/center/inside/outside.
No hidden text/tails/unknown child in any metadata container. Integral coordinate
subset and positive size bounds remain the same as D1; no unit conversion/layout.

wrapNone is empty with no attrs. wrapSquare requires wrapText enum bothSides/left/
right/largest, optional distances and effectExtent. wrapTopAndBottom allows distT/B
and optional effectExtent. wrapTight/Through require wrapText, optional distL/R,
exactly one wrapPolygon: optional edited bool, start then at least two lineTo leaves,
all integral x/y within D1 bounds. Raw node/character/depth limits cover all polygon
points before semantic DOM, including excluded/discarded branches; no polygon-sized
pixel allocation or geometric rendering. Correct order/cardinality/attrs everywhere.

Anchor hidden OR existing docPr/cNvPr hidden records object exclusion only after
full structure/raster-target proof. Ordinary floating objects record original drawing
metadata floating_raster_reference, without emitting a new text atom. Run visibility,
field-code filtering and note links keep their existing behavior. Plain controls still
refuse images. Inline objects delegate to D1 unchanged and still split fragments.
Nonempty alternative descriptions/titles, text boxes, VML, charts/OLE/SVG, unsupported
shape effects and raster formats, external/linked images remain explicit gates.

## API, evidence and bounds

New build_floating_image_snapshot, map_floating_image_spans and singular map, fixed
profile docx-analysis/final-visible-floating-images-v1. Same exact identity, VisibleLimits,
NoteSnapshot/style profile/span DTOs. No public reader/view/capability injection.
Extract D1 _build_snapshot(data, identity, limits, reader_type, profile); its old public
function pins the old reader/profile. New public API pins FloatingReader/new profile.
Extract Grammar.graphic(node) returning existing picture hidden state and preserving
all attributes/URI/relationship proof; inline drawing delegates unchanged.

No global enum/capability/default mutation or XML serialization. One fresh coherent
view and source-derived raster accounting per build. Existing raw drawing count,
aggregate raster chunk/segment/restart budgets, package byte bounds, semantic and
combined output/coverage/manifest limits remain. Mapping rebuilds once per batch,
including empty, and rejects altered/rehashed source/text/coverage/provenance. Profiles
remain mutually closed. Any unproved active structure/part gives atomic incomplete
output; valid unused raster exclusion still requires complete active story closure.

## Acceptance

All five wrapping modes, supported alignment/offset contexts, optional/required bools,
Strict UTF16, original custom source addresses; mixed inline/floating Unicode text,
consecutive/image-only/deleted/hidden cases, table/rich/MC ownership, headers/notes and
field code/results. Independent original XML slice resolution. Unknown/duplicate/missing
metadata, invalid polygons/positions/bools and foreground wrapNone refuse atomically.
Old profiles/rehashed evidence, exact manifest/coverage limits, raw excluded polygon
bounds before DOM, one fresh rebuild, inert process. Full gate, unchanged previous
hashes outside two hooks and readonly main V8 mandatory.

Next large product gap: source reading for AIRA's own template defaults and numbering,
then common Word metadata and explicit application/codec/worker admission. Existing
unsupported reader capabilities remain work, not silently removed product scope.
