# D03-17A2b5e2 — direct single-level list evidence and literal mapping

5 November 2026. Baseline verified E1 `0ac7392`. F04/F05/F06/F11.
One opt-in reader extension for actual AIRA bullet/numbered template paragraphs.
No application/codec/ML-wire/schema change or general multilevel-list promise.

## Paths and verification

New src/ara/docx_analysis/visible_lists/;
tests/acceptance/test_docx_visible_lists.py and tests/docx_documents/test_visible_lists_edges.py;
this contract/result, docs/docx-visible-lists.md, development-queue.md, ignored .runtime.
Only old private hook: visible_unlisted/_numbering.py may extract verified source part/root
from its existing proof so a new catalog avoids reparsing. Old unused()/public profiles and
all old tests unchanged. New code composes fixed existing selected contexts, readers/output
and mapping primitives; no public grammar/profile/capability injection or global mutations.
Freeze/red → implementation/review/regression → full gate → readonly mainV8/hashes →
selective local commit → next bounded cycle. No source/test/contract edits during full gate.
Documented new-test preparation corrections allowed only with frozen assertions unchanged.
No dependencies/schema/contracts/runner/tasks/progress/template generator changes.

## Evidence

ECMA-376 Part1 17.9 and Strict schema; Microsoft SDK reference
[LevelText](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.leveltext?view=openxml-3.0.1),
[Start](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.startnumberingvalue?view=openxml-3.0.1),
[Format](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.numberingformat?view=openxml-3.0.1),
[Suffix](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.levelsuffix?view=openxml-3.0.1),
[StartOverride](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.startoverridenumberingvalue?view=openxml-3.0.1),
[NumberingId](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.numberingid?view=openxml-3.0.1).
Missing start=0, numFmt=decimal, suff=tab. Instance startOverride takes precedence.
numId=0 removes numbering and never references an instance. lvlText includes literal
prefix/suffix and level substitution; nonconsecutive paragraphs continue the same instance.
Older examples using instance0 must not override the normative numId rule.

## Public data and authority

build_list_snapshot, map_list_spans, map_list_span; fixed
 docx-analysis/final-visible-direct-lists-v1, same identity/VisibleLimits/source span API.
ListSnapshot extends NoteSnapshot with lists: tuple[ListItem,...]. New exact frozen DTO:
paragraph_anchor, properties_anchor (direct numPr), definition_anchor (abstract lvl),
instance_anchor (num), start_override_anchor optional; num_id int>0, level int=0,
ordinal int0..2147483647, format decimal/bullet, label string, suffix tab/space/nothing,
fragment_ids tuple[str,...]. Content/anchors not exposed by repr. Source digest binds all
items. No label or separator is fabricated as a literal fragment/piece/source offset.
Empty/hidden-literal numbered paragraphs retain item/ordinal, possibly empty fragment_ids.
Ordinary literal analysis_text semantics stay unchanged. This profile is rejected by old
mappers and engine wire; a future explicit adapter must transmit list context, not drop it.

One source-derived selected view and pagination style context, original anchors for
selected paragraphs and numbering XML. Same raster/table/notes/control/visibility policy.
Exact shape validation bounds the NoteSnapshot base and new items before hash/equality;
no global SCHEMAS mutation. Mapping rebuilds once per batch, including empty, and rejects
forged/rehashed labels/counters/anchors/links. Labels cannot be requested as source slices.
Early context failures return ListSnapshot with empty lists and correct style/profile;
all semantic failures are atomic across text, note links and list items.

## Direct list subset

numPr only in retained direct paragraph pPr; empty attrs, XML-whitespace envelope,
optional ilvl then required numId, exact leaf val bounded nonnegative integers, no
duplicates/unknowns/history/numberingChange. Positive numId requires explicit ilvl0;
missing level is gated, not inferred. numId0 may omit ilvl, emits metadata numbering_removed,
requires no definition and creates no ListItem. Existing used/default/style/table numPr
and reverse numbering-style bindings remain gated; no style cascade shortcuts.

Numbering source proof uses E1's closed grammar/one candidate/exact relationship/namespace
rules. Active instance requires valid main internal relationship; orphan definitions may
be excluded but never authorize a positive direct reference. An abstract must have exactly
level0 and multiLevelType absent/singleLevel. Active format only decimal (including default)
or bullet. Starting value abstract start/default0, overridden by instance startOverride;
only startOverride is supported actively. Active replacement lvl override gates.
lvlRestart absent/0, isLgl absent/false, lvlText required val, null absent/false. Active
level rPr must contain no visibility properties, including explicit false; other E1 closed
formatting is metadata without rendered-font equivalence claim. Namespace-specific E1
alignment restrictions remain. Complex/unbound unused definitions keep E1 grammar proof.

Decimal labels accept literal text and %1 substitutions only; all other/ambiguous percent
forms (including %10) gate. Bullet labels are literal Unicode without percent forms.
Suffix defaulttab or explicit tab/space/nothing is recorded separately. No locale, roman,
letter, custom, picture or multilevel counter guessing. Counters advance for every retained
numbered main-story paragraph in final logical order, including blank/hidden literal text,
across ordinary paragraph gaps, table cells and rich/plain/selected wrappers. Each numId
has an independent sequence; ordinary gaps/other instances never restart it. Increment
overflow gates. A main list item may contain an existing note reference/image boundary;
one marker associates with all of its resulting literal fragments, never one per fragment.
Active lists in retained headers/footnotes/endnotes gate rather than guessing cross-story
counter scope. Unreferenced stories and definitions keep prior closure policy.

Existing fields are independently proven first. List paragraphs with an open complex/simple
field at paragraph_start or paragraph_end gate unsupported_list_field_boundary. Determine
boundary depth from retained tokens/original run nodes, because plan atoms are filtered.
Single-paragraph cached field results remain supported. No invented marker inside field code.

## Bounds

Combined original candidate+numbering XML preflight before any semantic DOM; raw limits
include unused/discarded/history branches. ListItems <= max_paragraphs, per-label<=4096
technical character bound; generated label and suffix character cost plus literal text <=
max_text_characters. Aggregate item fragment IDs <= resulting fragment count. Existing
manifest/coverage/paragraph/run/piece limits continue to apply; no DTO retains DOM or caches.
Generated list evidence contributes metadata/list_label; proven used numbering part records
metadata/numbering_definition_used, unused part excluded only after complete story closure.
Any unproved relation/part/active syntax clears all items and prevents unused assertions.
No files/network/subprocess/env access; input bytes are unchanged.

## Acceptance

Actual AIRA template mixed bullets/numbers/heading/plain/restarted groups, Unicode/tab/break
literal source mapping; strict UTF16/custom parts, ordinary gaps/table order/instances/start
and suffix defaults/override, empty/hidden literals and marker-only documents. Original
numPr/lvl/num/startOverride anchors, image and note splits, rich/plain/MC wrappers. All unsupported
active semantics, direct malformed/unknown refs, missing main relation, active other-story
lists, cross-paragraph field marker boundaries and unknown parts gate atomically. No-part
numId0 removal; empty/old snapshots, forged shapes/rehashes/labels/fragment IDs, one rebuild,
raw/output exact limits and inert fresh process. Full gate, previous hashes outside one
hook and readonly mainV8. After this: inherited/multilevel support and explicit application/
worker admission carrying generated metadata; no customer readiness claim from reader tests.
