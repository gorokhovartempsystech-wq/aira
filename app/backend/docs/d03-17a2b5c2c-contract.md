# D03-17A2b5c2c — visible stories and mapping over coherent compatibility contexts

5 November 2026; F05/F06/F11. Baseline `c9c71ae` is verified C2B.
One cycle: new opt-in original-source snapshot/mapping. No product admission, editing,
export, XML rewriting, model/UI work or expansion of supported Word grammar.

## Allowed paths and sequence

New src/ara/docx_analysis/visible_compatibility/; new
tests/acceptance/test_docx_visible_compatibility.py and
tests/docx_documents/test_visible_compatibility_edges.py; this contract/result,
docs/docx-visible-compatibility.md, docs/development-queue.md and ignored .runtime.
Exactly eleven old private-hook files under src/ara/docx_analysis:
visible_main/_reader.py, tables/_context.py, current_tables/_context.py,
retained_tables/_context.py, visible_control_tables/_reader.py,
visible_stories/_proofs.py, visible_notes/_proofs.py, moves/_index.py,
visible_notes/_build.py, visible_main/_shape.py, visible_notes/_shape.py.
Old public APIs/profiles/default behavior and all old tests remain unchanged.
No dependencies/schema/runner/task/status/product-scope changes. All prior hashes
outside these hooks remain identical. Freeze/red, implementation, review and targeted
regression, full check, readonly main V8, selective local commit. No code/tests/frozen
contract edits during full gate. New-test preparation corrections are allowed only
with unchanged assertions and explicit result documentation.

## Fixed public API / semantics

build_compatibility_snapshot(data, *, document_id, storage_revision, source_sha256,
limits=None); map_compatibility_spans(data, snapshot, *, requests, limits=None) and
map_compatibility_span(... fragment_id,start,end,quote,limits=None). Export the same
NoteSnapshot, VisibleLimits/VisibleViewError/VisibleSpanRequest/mapping DTOs.
Exact original bytes/identity/limits checks before semantics, existing archive/package
errors, no caller view/context/capability/profile injection. Fixed snapshot profile
docx-analysis/final-visible-compatibility-v1, existing final-visible-no-comments-v2
policy, fixed C2B mc-styles-context-v1 style context. Same canonical snapshot, text and
fragment hashing rules with new profile separation.

Every call builds fresh C2B.prepare from original bytes. The same view supplies all
metadata, main/header/footer/note trees, table/history/revision/move proof and Reader.
No old semantic reparse, filtered serialization or ambient/global XML mode. Reuse shared
notes build through a private provider; original path defaults remain dynamic/unchanged.
Source relationships still resolve against the original package. One view DOM per part;
note parts cached; each mapping batch, including empty, rebuilds once and compares exact
snapshot rather than trusting hashes or arbitrary DTOs.

Supported content is the existing table-control reader grammar applied to selected nodes:
visible runs/styles, retained revisions/moves, controls, current/logical tables,
sections/header/footer closure and referenced notes, stored field results. MC wrappers
are semantically transparent, not field boundaries; existing control/table/story barriers
remain. Unknown retained Word/foreign content, unresolved styles/refs, unsupported fields,
table geometry/revisions and unaccounted package parts remain explicit gates.

All output anchors use ViewNode's original source anchor. Logical ancestry determines
ownership; no deriving a physical parent by truncating a promoted node's path. Table
history/deleted-cell early proofs use child anchor hooks even before descendants are
indexed. Move markers use their logical paragraph's actual anchor. Notes resolve the
full target anchor through view.node, never target.path[0]. Nested physical definition
paths, actual cell flows and Unicode text offsets remain exact. No application acceptance
of this profile is added.

## Atomic completeness / evidence / bounds

For blocked C2B bundle produce an explicit incomplete NoteSnapshot: no paragraphs,
runs, fragments, text or references; valid canonical blocked MC style context with fixed
compatibility_context_blocked issue (not an invented absent/ready context), source-bound
blocked package coverage and the original safe refusal issue/anchor. Bounded coverage
and manifest. For later proof/reader/package failure use existing shared atomic behavior,
clearing all output and keeping explicit blocked coverage. A ready catalog is never
substituted for a proof of actual usage.

Add bounded source-backed coverage for every C1 decision: ignored element excluded;
unwrapped/stripped attrs/alternate selection metadata. Attribute stripping does not
claim the node is excluded. Record the AC decision anchor, with its selection already
bound by original SHA and fixed algorithm; do not fabricate anchors for discarded branches.
All source/raw, style-chain, semantic, output and aggregate manifest limits remain active.
No truncation or partial successful text. Empty complete documents are legitimate.

Shape validation gets explicit private fixed style-profile parameter; no global enum
mutation and no widening old validators. Rehashed changed text/anchors/contexts/coverage/
references, old/new profile swaps, wrong-source snapshots, malformed exact DTOs and
invalid intervals/quotes reject. Map Unicode source slices only, no range across generated
note labels or hidden/deleted/unselected text. Import/build/map do not access files,
network, environment, secrets or XML serialization. Private text stays out of repr/errors.

## Acceptance

Strict UTF16 + custom parts; first-understood/fallback/no selection; ProcessContent,
ignored children/attrs; exact original piece/paragraph/flow/story anchors; selected styles
and hidden text; tables with nested controls, retained insert/delete/property histories,
logical grids; move paragraph ownership; transparent field boundaries; coherent selected
headers/settings and nested note definitions/references; old public profiles mutually
reject. Active unsupported content/catalogs/package parts atomic, discarded payload
does not contaminate semantics. Forged DTO/source/profile and batch rebuild/cap checks;
one view/DOM with legacy parse guards; inert import/calls and input/repr/manifest limits.
Full regression, old hashes and readonly V8 required.
