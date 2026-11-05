# D03-17A2b9A — ordinary Word package source compatibility

5 November 2026. Baseline `cf485fd`. F05/F06/F11 source reader, based on the six independently generated
python-docx default-template documents found by the post-B8 audit. No claim of native Word
layout/rendering, real ML, desktop admission or signed release.

## Paths and cycle

New src/ara/docx_analysis/visible_word/; one existing private hook
src/ara/docx_analysis/visible_style_lists/_shape.py: extract its existing validator policy into
optional fixed defaults (exact snapshot type/profile/style profile), preserving old defaults
and checks. No other old source, test, schema, SQL, dependencies, runner/tasks/progress changes.
New tests/acceptance/test_docx_visible_word.py and tests/fixtures/docx/common-template/
(six synthetic DOCX and provenance README); docs/d03-17a2b9a-contract.md,
docs/d03-17a2b9a-result.md, docs/docx-visible-word.md, docs/development-queue.md; ignored .runtime.
Freeze acceptance then red; source-bound target/negative/review/regression and old exact-byte
probes; full scripts/check.sh plus builder Ruff, frozen hashes, readonly mainV8 comparison,
selective local commit. New-test preparation-only corrections may be documented without
changing frozen assertions. No implementation/test/frozen-contract edits during the full gate.

## Fixed source policy

New exact WordSnapshot (same list/notes/literal shape as StyleListSnapshot), source profile
 docx-analysis/final-visible-word-package-v1, style profile
 docx-visibility/mc-word-package-styles-v1. Public builder and batch/single mapper rebuild the
original source even for empty requests; detached DTOs are never authority. Original DOCX bytes
and every retained node's physical part/path remain unchanged. All old profiles stay fixed.

Closed selected-part MC extension adds numbering/fontTable/webSettings/stylesWithEffects/theme
and the exact paired empty-bibliography customXML parts. Aggregate raw XML/MC/style/drawing
quotas precede selected DOM allocation and include inactive branches and auxiliary parts.
Unknown/unsupported MC requirements and malformed selected data block atomically. No caller
registry or global namespace/part whitelist. ContextualSpacing is a validated on/off leaf in
current paragraph properties (direct/style); all previous visibility/list policy is retained.
Selected numbering reuses nine-level/four-format semantics with original physical anchors;
no raw XML attribute stripping, reconstructed source ZIP or changed counter semantics.

## Auxiliary closure

MIME alone is insufficient. Each admitted auxiliary role has the exact internal relationship,
allowed owner/cardinality/root and no unproved incoming/outgoing edges. Parts cannot serve two
roles. Unlinked/wrong-role/mislabelled/external/duplicate parts remain blocked; no network fetch.
- Font table: Word fonts/font descriptive metadata only; no embedded/external fonts.
- Web settings: closed harmless display/export flags, no active content or unknown children.
- Theme: bounded DrawingML presentation metadata, no text runs, external resources, extension
  payloads or unknown vocabulary. The reader does not claim to render fonts/colors/layout.
- Thumbnail: exactly package-root metadata/thumbnail, PNG/JPEG MIME, no other incoming or
  outgoing edges; retained opaque preview, never a content image or analysis evidence.
- CustomXML: only an empty bibliography Sources store with one matching datastore properties
  part/schema URI/GUID. Arbitrary/nonempty stores, bindings or other relationships remain gates.
- stylesWithEffects: exact main-part relationship; selected base/effects docDefaults and
  latent metadata agree, shared style definitions structurally equal (XML indentation is not
  content). Extra base-only definitions are nondefault and unreferenced from retained stories,
  numbering or shared style graphs. Missing/extra/different relevant styles refuse. No silent
  choice between conflicting visibility or numbering definitions.

Exclusions become valid only after the whole retained story/reference closure succeeds.
On failure no partial text, list labels, note references or mappings escape. A changed source,
rehash-only forged snapshot or original-anchor forgery refuses. Unknown nonauxiliary parts and
previous unsupported text structures remain blocked. Six independent documents must read all
literal text, preserve list context and map every character to original XML, without modifying
any ZIP part. Existing template/strict/MC/style/outline acceptance remains mandatory.
