# D03-17A2b5e1 — plain AIRA template paragraphs and proven-unused numbering

5 November 2026, F04/F05/F06/F11. Baseline: verified D2 `99ea44c`.
One opt-in reader, not active list support or application admission. Existing template
body and heading1/2/3 documents must be readable without changing generated DOCX bytes.
Bullet/numbered documents remain explicitly incomplete until generated-label semantics
and exact source-bound mapping are designed in the following numbering cycle.

## Paths and gates

New src/ara/docx_analysis/visible_unlisted/; tests/acceptance/test_docx_visible_unlisted.py;
tests/docx_documents/test_visible_unlisted_edges.py; contract/result/guide, queue, .runtime.
Four old private extension hooks only: visibility/_grammar.py (property_names method),
compatibility_contexts/_factories.py (private grammar/style/context profile options),
compatibility_contexts/_read.py (private context factory/profile options), and
visible_compatibility/_failed.py (explicit optional style profile). Defaults and every
old public profile unchanged; no mutation of global property sets. No edits to old tests,
DB/schema/contracts/runner/tasks/progress/dependencies/template generator. Freeze/red →
implementation/review/regression → full gate → readonly mainV8/hashes → selective commit.
Documented new-test preparation corrections allowed only with assertions unchanged.
No source/test/contract edits during full gate. Continue next cycle autonomously.

## Evidence / conservative boundary

Microsoft WidowControl documents paragraph pagination, not omission of literal text.
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.widowcontrol?view=openxml-3.0.1
Microsoft ParagraphStyleIdInLevel documents numbering applied through paragraph style;
therefore absence of direct numPr alone is insufficient proof of unused definitions.
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraphstyleidinlevel?view=openxml-3.0.1
ECMA-376 Part1 17.9 and official strict wml.xsd underpin the closed unbound subset below.
This profile refuses every pStyle/styleLink/numStyleLink association in numbering.
Current direct numPr and style-inherited/default numPr keep their existing gates. An
unsupported active table style/field/control/story also prevents unused exclusion.
Deleted/discarded/unreferenced stories retain prior visibility policy and raw bounds.
No numbering symbol, counter or label is invented or silently removed from an active list.

## New semantics

New public build_unlisted_snapshot, map_unlisted_spans and singular map; fixed
profile docx-analysis/final-visible-unlisted-v1. Same NoteSnapshot/identity/limits/requests.
New style profile docx-visibility/mc-pagination-styles-v1 and private contexts profile
 docx-compatibility/selected-pagination-contexts-v1. Same selected original-anchor view,
including all prior table/note/field/control/inline/floating behavior and media proof.
Only new style/direct paragraph property is widowControl: empty leaf, optional own
Word namespace val, exact on/off boolean set (true/false/1/0/on/off), absent=true.
Reject wrong namespace, extra attrs/children/text and duplicate property. In rPr it is
still unsupported. Style defaults/used inheritance remain source-derived and hiding
is unchanged. Table-style neutrality remains its previous narrower grammar/profile.
Early blocked contexts use the new style profile consistently; old failures unchanged.

Numbering candidates selected by exact numbering MIME. One candidate at most, with
matching Word namespace and root numbering. Optional main relationship must be unique,
internal, exact strict/transitional numbering URI, target this part; any wrong-owner,
wrong-family, unresolved or ambiguous numbering relationship blocks accounting.
No outgoing relationships from numbering. A valid unlinked part may be excluded only
when all retained content/context closure is complete. Every unknown additional part
still blocks; no filename-only trust or broad metadata MIME allow-list.

Closed original numbering grammar: root ordered abstractNum*, num*, numIdMacAtCleanup?.
IDs normalize bounded nonnegative decimal (<=2147483647), numId positive. Abstract IDs
and num IDs unique; num references must resolve. abstractNum: required abstractNumId,
ordered optional nsid (8hex), multiLevelType (singleLevel/multilevel/hybridMultilevel),
tmpl (8hex), name(string), then lvl*; styleLink/numStyleLink forbidden. lvl: required
ilvl0..8, optional tplc8hex/tentative OnOff, each level unique; ordered optional start,
numFmt, lvlRestart, isLgl, suff, lvlText, lvlJc, pPr, rPr. pStyle, picture bullets, legacy,
unknown extensions and MC selection in this part are explicit gates in this first profile.
start/restart bounded nonnegative; numFmt fixed decimal/bullet/none/upperRoman/lowerRoman/
upperLetter/lowerLetter; isLgl OnOff; suff tab/space/nothing; lvlText required val and
optional null OnOff; lvlJc left/right/center. pPr permits tabs (tab val num/left/right/center/
clear/decimal/bar, signed bounded pos, optional leader none/dot/hyphen/underscore/heavy/
middleDot) and ind (left/right/start/end/hanging/firstLine plus corresponding *Chars;
closed numeric attributes; left/right aliases only in Transitional). rPr uses the existing closed formatting/visibility leaves.
num: exactly one abstractNumId then unique lvlOverride*; override ilvl0..8, ordered
optional startOverride and optional lvl whose ilvl agrees. Overrides reference an
existing abstract level; no orphan replacement-level guessing. Empty definitions/unused
instances allowed when structurally valid. All envelopes enforce namespace, order,
cardinality, attrs and XML whitespace, including inactive definitions.

Before any semantic numbering DOM, aggregate raw limits over prior compatibility
candidates plus all numbering candidates; original drawings and full node/depth/char
limits include discarded/history/unused branches. XML/package limits remain. No unsafe
integer conversion, unbounded caches, files/network/subprocess or XML rewriting.
Only proven parts receive excluded/unused_numbering_definition after complete active
closure. On grammar/relationship failure the part stays unaccounted and the snapshot
is atomic incomplete, with no leaked literal text. On other active failure, an otherwise
proven part gets blocked/additional_usage_unproven, never an unused assertion.

Mapping rebuilds once per batch including empty, validates new snapshot/style profiles
and exact source evidence, rejects rehashed edits. Old snapshots stay mutually closed.
Coverage/manifest limits apply including new part entries. New style proof digest binds
unchanged table-style proof; no capability injection on public API.

## Acceptance

Actual create_docx body/headings/empty and Unicode/tab/linebreak files; source bytes
unchanged, exact original slices. Strict UTF16/custom paths, inherited hidden runs,
MC-selected original style anchors, mixed media/tables/notes. Direct/inherited/default
lists and reverse style bindings remain atomic gates. Positive unused overrides;
malformed IDs/order/links/unknowns/MC/embedded text/attrs reject. Old profile immutability,
new profile consistency on early failure, tampered/rehash evidence, one fresh batch,
combined raw/coverage/manifest bounds before DOM and inert fresh-process import/build.
