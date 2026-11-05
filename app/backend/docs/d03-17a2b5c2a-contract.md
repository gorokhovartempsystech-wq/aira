# D03-17A2b5c2a — Immutable original-address compatibility view

5 November 2026; F05/F06/F11. Baseline `0d2d3bd` (C1). Technical adapter only, not visible
analysis/admission, editor/export or native Word parity. Core MCE decisions remain C1's
fixed capability profile and original source hash. This cycle supplies the shared view
needed by subsequent coherent catalog and story integration.

## Scope

Allowed paths:
- new `src/ara/docx_analysis/compatibility_view/`;
- `tests/acceptance/test_docx_compatibility_view.py`;
- `tests/docx_documents/test_compatibility_view_edges.py`;
- `docs/d03-17a2b5c2a-contract.md`, `docs/d03-17a2b5c2a-result.md`;
- `docs/docx-compatibility-view.md`, `docs/development-queue.md`.
Ignored `.runtime` research/evidence may be written. No old source/test/API/schema/deps/
runner/product rules changed. All prior hashes unchanged. Freeze/red → implementation
→ targeted/review/full gate → readonly main V8 → selective local commit. Documented
preparation corrections in new tests allowed with assertions unchanged. Do not edit
source/tests/frozen contract during full gate.

## Factory and types

`build_compatibility_view(data, *, source_sha256, limits=None)` always calls C1 factory
on supplied original bytes before any semantic DOM. It accepts only C1's exact immutable
CompatibilityLimits and inherits C1's input/source/limit errors and DocxError. No caller
catalog, capability list, path to a file or already-filtered tree input. Limits are raw,
all scoped parts, including unused and ignored branches, exactly as C1 defines them.
No network/environment/storage I/O or XML/package serialization.

Read-only records (frozen slots, node equality/hash by identity):
- ViewNode: anchor, tag, attrib, text, tail, children (all repr=False). `attrib` is a
  read-only mapping; children a tuple; supports get(name, default=None), len(), integer/
  slice indexing and iteration. No setters/mutators/ET.Element subclass/source tree.
- ViewPart: part_name, root, nodes mapping original path→retained ViewNode (all repr=False).
- CompatibilityView: source_sha256, profile=`docx-compatibility/original-logical-view-v1`,
  status ready/blocked, catalog (C1 immutable record), parts, issues (private repr).
  No complete, analysis_text or new XML bytes. `node(anchor)` returns same retained node
  object or None if not present/retained; exact SourceAnchor with same SHA required.
  Wrong SHA raises source_mismatch; malformed anchor raises invalid_input. Anchor path
  exact tuple of nonnegative exact ints, <=128 depth, part nonempty str, SHA lowerhex.

Ready contains every scoped part in catalog order, even when C1 status absent; blocked
contains parts=() and exactly one safe issue. C1 refusal propagated without allocating
DOM. Projection refusal anywhere discards every earlier view part. Catalog may remain
indexed while projection status blocked; callers must test the view status. Future
admission will re-create all proofs from the same factory, not trust caller-built views.

## Source identity and transformation

Each retained node has exactly its original physical SourceAnchor, tag, text and tail.
Attributes differ only by a C1 strip_attributes action. No copied/created source text,
reordered retained nodes, fabricated paths, logical-index anchors or changed w:t text.
One ViewNode per retained source node, reused by tree and lookup. Original XML parsed
once per scoped part after C1 validation, then discarded; public result holds no ET tree.

ignore_element removes the whole subtree from logical children. unwrap_element promotes
its selected logical children. alternate_content promotes only children of the exact
selected original Choice/Fallback, or none; selection wrappers are not retained nodes.
Unselected branch, ignored subtree, dropped wrapper anchors are absent from nodes lookup.
Nested promotion preserves source order. Unknown non-ignorable elements/attributes stay.
Known ordinary root is retained; structural replacement/removal of a part root is refused
with unsupported_compatibility_root (a C1 decision is not root-shape/content proof).

Character ownership is conservative and explicit. Whenever ordinary node's direct child
is structurally removed/promoted, that parent .text and every direct child .tail must be
XML whitespace or empty; also the parent cannot be either Word namespace's text leaf
`t`, `delText`, `instrText`, `delInstrText`. Every unwrapped container or selected branch
must likewise have only XML whitespace in its direct .text/child tails. Non-whitespace
payload of an ignored subtree or unselected branch is discarded by C1 semantics and
does not trigger this boundary. Non-whitespace tail belongs outside that subtree, so
cannot be silently dropped. Failure is unsupported_compatibility_text_boundary. Use
XML whitespace, not Unicode str.strip(). No concatenation/normalization of source text.
Whitespace at removed structural wrappers may disappear only under these stated rules;
ordinary retained node text and tail remain exact. This bounds initial source mapping,
not an assertion that arbitrary XML mixed content or all MCE documents are supported.

## Bounds and consumer integration boundary

Raw full preflight and decisions before DOM; no second capability interpretation. Bounded
C1 XML nodes/depth/characters/parts cap allocation; each retained source node indexed
once, no cross-product copies of descendant lists in nested wrappers. Streaming yield
promotion or equivalent linear traversal, with recursion bounded by raw depth128. No
repeated reparsing per lookup or serialization to create source identities.

Consumers will need explicit original-anchor hooks: Reader/Context/Grammar indexing,
settings_flag, note read_part and exact note lookup, move marker logical parent anchor
rather than path[:-1]. Those hooks and coherent whole-story visibility are later cycles;
none is added here, and old public readers continue to block unrecognized MCE.

## Acceptance

Strict/UTF16, custom part paths; fallback/no-selection/nested/empty expansion; exact source
order and anchors after skipped/promoted siblings; current attrs/text unchanged; URI
selection from C1; cross-part styles/settings/stories/notes; arbitrary opaque node kept;
immutability/identity/no repr contents; no serialized XML or mutated bytes; no DOM before
all bounds/MC syntax; atomic root/mixed-content refusals, including non-XML whitespace,
retained parent w:t/instruction gates; all raw budgets, exact inputs and inert process.
Full gate, all old hashes, readonly main V8.
