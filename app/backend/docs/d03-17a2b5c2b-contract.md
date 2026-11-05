# D03-17A2b5c2b — Coherent metadata contexts over one original-address view

5 November 2026; F05/F06/F11, baseline `d711d22` (C2A). This is shared metadata reading,
not whole-story analysis/admission, editing/export or native Word parity.

## Allowed paths / sequence

New `src/ara/docx_analysis/compatibility_contexts/`; new
`tests/acceptance/test_docx_compatibility_contexts.py` and
`tests/docx_documents/test_compatibility_contexts_edges.py`; `docs/d03-17a2b5c2b-contract.md`, `docs/d03-17a2b5c2b-result.md`,
`docs/docx-compatibility-contexts.md`, `docs/development-queue.md`, ignored .runtime evidence. Exactly eight old private hook/extraction
files are allowed, with unchanged public APIs/default behavior:
- visibility/_grammar.py, visibility/_read.py;
- table_styles/_read.py;
- sections/_context.py, sections/_resolve.py, sections/_read.py;
- notes/_definitions.py, notes/_read.py (all under src/ara/docx_analysis/).
No old tests, profiles/defaults, schema, dependencies, runner or product scope changes.
All prior files outside these eight must hash unchanged. Freeze/red → implementation →
review/targeted/full gate → readonly main V8 → selective commit. Documented preparation
corrections in new tests allowed, assertions unchanged. No code/test/contract edit during
full gate. No global/ambient XML mode or monkeypatch in production.

## API and output

`read_compatibility_contexts(data, *, source_sha256, limits=None)` accepts original bytes,
lowerhex SHA and exact VisibleLimits only. Validate limits/source/size/hash before any
semantic work, with fixed VisibleViewError invalid_input/source_mismatch/view_limit_exceeded
and original DocxError package failures. No caller view, catalog or capability injection.

Frozen slotted metadata CompatibilityContexts(source_sha256, profile, status,
compatibility_sha256, styles, table_styles, sections, notes, issues). The four context
fields and issues repr=False. Issue has fixed safe code + optional original anchor.
No complete, analysis_text, XML, source bytes or local path in public DTO. No redundant
bundle digest; individual source-bound contexts retain canonical hashes. Bound canonical
serialized size of the entire trusted DTO using streaming tokens (including nested hashes),
without accumulating full serialization. Deterministic output and no I/O during imports
or calls; no secrets/config reads.

Fixed profiles (same original SHA, different semantics explicitly versioned):
- bundle `docx-compatibility/selected-contexts-v1`;
- styles `docx-visibility/mc-styles-context-v1`;
- table_styles `docx-table-styles/mc-neutrality-v1`;
- sections `docx-sections/mc-current-references-v1`;
- notes `docx-notes/mc-definitions-v1`.

Bundle status ready means catalogs built, NOT that every style or all content is usable.
Opaque/unresolved individual style records retain existing proof behavior; downstream
actual usage still must be proven. If view or a whole catalog is blocked: bundle blocked,
all four contexts None, exactly one safe issue, no earlier partial proofs. First refusal
order: view/root, styles, table proof, sections, notes. Component issue codes can be
preserved or classified by a fixed safe code; no payload values in errors. Missing
styles/notes remain their proper absent catalogs, not invented defaults/definitions.

Private `prepare` may return source+view+bundle for later C2C composition, but public
factory returns metadata only. Public snapshot/map APIs will always build fresh and
never accept this prepared object as caller authority.

## One view and source anchors

Build one fresh C2A view. Every semantic style/table-style/section/settings/note consumer
reads cached roots from that very view; no fallback semantic parse of original unselected
XML. Source inventory and relationships still refer to actual original bytes. Reuse
existing grammar/graph/inheritance/uniqueness logic through the eight explicit private
hooks. Do not copy the old factory implementation into a competing fork.

Grammar and section Context get original-anchor hooks with old defaults. settings_flag
and note read_part get optional original-anchor callbacks. Default factories keep original
signatures and profiles; extract private variants with tree/grammar/proof/context readers
and explicit profile for the new path. Resolve defaults dynamically to preserve old test
instrumentation; old modules do not import the new view (avoid import cycles). New
SourceAnchors checks exact ViewNode and pinned SHA/part, returns its actual source anchor.
No deriving physical parent from a logical path; no renumbering promoted definitions.

New factory requires a logical Word document root with exactly one direct Word body before
calling section Context, whose old precondition assumes it. Package-invalid original root/body still raises DocxError. A duplicate/invalid logical
body after selection is a blocked bundle, not uncaught StopIteration or a synthesized body. Remaining Word
content/root semantics are still later Reader responsibility. Other roots use old grammar.

## Bounds

Before C2A allocates any DOM: validate package/source, run existing original notes global
preflight and fields/controls preflight; aggregate all exact styles MIME parts with the
existing table-style raw Counter, including unused/ambiguous candidates, tighter style
node/depth/style/region caps; aggregate raw section Counter for main plus all declared
settings parts. Semantic budgets (graph chains/issues/implicit sections) remain active.
Never let discarded MC branches evade raw limits or unselected duplicate markup become
semantic duplicates. View/C1 preflight and fixed capability decisions remain mandatory.

Use VisibleLimits global XML caps. TableStyleLimits uses min(global/style nodes/depth),
styles.max_styles/max_chain_depth/max_issues, existing max_regions/max_chain_links,
max_manifest_bytes. SectionLimits/NoteLimits use global XML caps and manifest cap with
existing per-kind maxima. CompatibilityLimits uses global XML/manifest caps; max_actions
min(10000,max_coverage_items), max_mc_items min(10000,max_pieces); other C1 maxima unchanged.
Translate technical errors to view_limit_exceeded; never truncate output or return success.
Bound full bundle serialization in addition to individual catalogs and C1 manifest.

## Acceptance

Strict/UTF16/custom parts, same-ID alternatives, source-backed hidden/current styles,
defaults/basedOn/neutral conditional tables, selected settings and inherited section refs,
selected note definitions with nested physical paths. Unsupported selected markup/ambiguous
relationships/duplicate active IDs refuse appropriately; discarded Word semantics don't
contaminate selected catalogs. All original IDs/anchors/hashes and profile distinctions.
One view/one DOM per part, no legacy semantic reparse, old public outputs unchanged on
plain and MC sources, no global state, raw quotas before DOM across unused/ambiguous parts,
exact input/manifest and inert subprocess, immutable/private DTO. Full gate/prior hashes/V8.
