# D03-17A2b8A — source-proven paragraph-style list bindings

5 November 2026. Baseline: B7B `8952b63`. Pure F06/F11 reader/mapping cycle;
no application admission, real ML or native Word layout claim. Paragraph-style numbering
joins the existing direct multilevel counter policy without inventing a direct numPr node.

## Scope and gates

New `src/ara/docx_analysis/visible_style_lists/`,
`tests/acceptance/test_docx_visible_style_lists.py`, this contract/result,
`docs/docx-visible-style-lists.md`, queue and ignored `.runtime` only. No existing source,
tests, schemas, SQL, dependencies, runner/tasks/progress or user-file changes. Freeze/red,
target/review/regression, full scripts/check.sh plus explicit builder Ruff, frozen hashes,
readonly mainV8 and selective local commit. New-test preparation-only corrections may be
recorded with frozen assertions preserved. No source/test/contract changes during full gate.

## Fixed profile and physical provenance

Expose `StyleListSnapshot`, `StyleListItem`, common visible limits/errors/span DTOs and
`build_style_list_snapshot`, `map_style_list_spans`, `map_style_list_span`.
Snapshot profile `docx-analysis/final-visible-style-lists-v1`; NoteSnapshot fields plus lists.
Style-context profile `docx-visibility/mc-style-numbering-v1`, prepared-context profile
`docx-compatibility/selected-style-numbering-contexts-v1`. Exact DTO/shape/canonical hash and
original-source reconstruction on every mapping call, including zero requests. Old types
and readers stay unchanged. Incomplete source returns no partial literal text/lists/notes.

StyleListItem retains all ListItem fields and adds required `numbering_source` (direct/style),
`style_reference_anchor` (SourceAnchor or None), `style_chain` (tuple of SourceAnchors), and
`level_style_anchor` (SourceAnchor or None). Direct items have null style anchors/empty chain.
For style numbering, properties_anchor is the ACTUAL numPr in Styles.xml, not a fabricated
paragraph descendant. style_chain follows applied paragraph style through the numPr owner;
style_reference_anchor is the original paragraph pStyle selector, or None for a proven default;
level_style_anchor is the associated abstract lvl/pStyle. All source anchors are physical.
Bound each chain by styles.max_chain_depth and total chain entries by max_xml_nodes, in
addition to existing record/manifest/text/raw limits. No raw XML or hidden text in repr.

## Source grammar and selection

Reuse selected original contexts, ordinary source stories/tables/notes/media and B7A's four
formats/counters/labels/restarts/overrides. New fixed style grammar admits only current pPr
numPr with exactly one numId0..2147483647, no ilvl/numberingChange/ins/extra attributes. Other
style formatting/visibility/history rules remain unchanged. numPr under pPrDefault/table
style is not admitted. Existing style closure resolves basedOn identity/type/cycles/limits.

New numbering grammar admits pStyle on ABSTRACT lvl, ordered after lvlRestart and before
isLgl (ECMA Strict XSD CT_Lvl checked). It has one bounded style identity. Keep every previous
closed unbound grammar guard, exact linked numbering part/namespace/relation checks and
preflight before DOM. Do not admit pStyle in replacement lvl, styleLink or numStyleLink.
Source pStyle strings that are not used by an actual inherited selection do not select a list.

For each retained paragraph, process the following before field-boundary validation:
- Explicit direct numPr uses the existing fully specified numId+ilvl rule. numId0 removes
  numbering and suppresses inheritance without consuming a counter. Partial direct properties
  remain a gate; no inferred missing level.
- Otherwise choose its actual paragraph style (explicit selector, else proven default).
  Follow the resolved same-type basedOn chain to the nearest current numPr. No numPr means
  unlisted; numId0 cancels ancestral numbering. Direct formatting takes precedence.
- For positive inherited numId, require linked instance/base definition and exactly one
  abstract level whose pStyle equals the ACTUAL applied style ID. Do not fall back to an
  ancestor's association when the applied style has none. Ambiguous/missing bindings refuse.
  Ordinary replacement appearance/startOverride uses that abstract selected level; replacement
  pStyle is a gate. Record the true chain/selector/numPr/abstract-binding anchors.
- Positive active numbering is main-story only (including retained table paragraphs).
  Numbered note/header stories refuse; an ordinary unnumbered note remains supported.

Use each style part's own proven Word namespace when reading its properties. Do not silently
miss style numbering in a differently namespaced part. The selected view already supplies
original anchors through wrappers/compatibility selection; no rewritten clone acts as source.
Attach inherited selections before the existing cross-paragraph field guard. Consume once
per retained paragraph, including blank/hidden-literal items and split literal fragments.
No whole-list fallback or fake labels when source proof fails.

## Evidence, bounded exclusions and tests

ECMA Part1 §17.7.1/.2 style inheritance/direct formatting, §17.3.1.19 numPr, §17.9.18 numId0,
§17.9.23 pStyle and Strict XSD CT_Lvl. The normative numId0 removal rule overrides erroneous
number0 instance examples. Word explicitly warns of unpredictable behavior for ilvl inside
style numPr: [Microsoft note](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/6a8f14ff-df90-4154-9bc9-e0e88ae5e641).
This cycle refuses that shape. Ancestor-only level fallback, numbering style links, complex
style-numbering interactions, letters/pictures and other B7A gates are not claimed supported.

Synthetic acceptance must cover direct/style interleaving in one counter, explicit/default
paragraph styles, inherited numId with an actual applied-style level association, nearest
numId override/zero removal, direct override/zero suppression, strict/UTF16/wrappers/tables,
blank/hidden items, retained note and numbered-note refusal, ambiguous/unresolved/partial
bindings, style ilvl rejection, replacements, field boundaries, raw/chain/text budgets,
canonical deterministic snapshots, every physical anchor, source immutability, rehashed
provenance forgery and unchanged old readers. Later vertical integration uses a separate
versioned contract so old worker descendant guards and stored profiles are not weakened.
