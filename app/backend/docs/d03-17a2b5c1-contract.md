# D03-17A2b5c1 — Original-source compatibility decision catalog

5 November 2026; F05/F06/F11, baseline `9da0058` (b5b2). Pure MCE decisions for a fixed base-Word
capability profile. This catalog is NOT a visible snapshot or completeness/admission
proof; no reader/style/table/section/note integration yet. Source bytes are immutable.

## Scope and allowed paths

Allowed paths:
- `src/ara/docx_analysis/compatibility/` (new namespace only);
- `tests/acceptance/test_docx_compatibility_catalog.py`;
- `tests/docx_documents/test_compatibility_catalog_edges.py`;
- `docs/d03-17a2b5c1-contract.md`, `docs/d03-17a2b5c1-result.md`;
- `docs/docx-compatibility-catalog.md`, `docs/development-queue.md`.
Ignored `.runtime` scratch/evidence may be written. No old source/test/schema/API/runner,
dependency or product scope changes. All prior hashes unchanged. Freeze/red → implement
→ review/targeted/full gate → readonly main V8 → selective local commit, then C2 design.
Documented preparation corrections in these new tests allowed with assertions unchanged.
No source/test/contract edits during full gate. No application/network/environment I/O.

## Sources and capability boundary

Primary: [ECMA-376 Part3, fifth edition 2015](https://ecma-international.org/wp-content/uploads/ECMA-376-3_5th_edition_december_2015.zip),
§7–9, obtained via [official download](https://ecma-international.org/publications-and-standards/standards/ecma-376/).
Original PDF/text held only in .runtime. These define URI-based compatibility lists,
selection order, ignored elements/attributes and ProcessContent unwrapping.
[Microsoft introduction](https://learn.microsoft.com/en-us/office/open-xml/general/introduction-to-markup-compatibility)
confirms capability-driven processing; saving a preprocessed tree can lose original
markup. We return decisions, never a rewritten package. SDK's [MCContext](https://raw.githubusercontent.com/dotnet/Open-XML-SDK/main/src/DocumentFormat.OpenXml.Framework/MCContext.cs)
also resolves Choice prefixes in the Choice scope, not a later parser position.

Fixed understood namespace set: both Strict/Transitional WordprocessingML, both
OfficeDocument relationship namespaces, XML namespace. MC is processed specially and
cannot appear in any compatibility prefix list. No inferred Office version, caller
capability injection, graphics/VML/w14 support or designated extension elements.
Core supports Ignorable, ProcessContent, MustUnderstand only. PreserveElements/
PreserveAttributes, unknown MC attrs/elements and application-extension semantics remain
explicit gates. Do not silently whitelist them because one SDK knows those names.
Active unknown MustUnderstand blocks also on ordinary elements: a conservative boundary
consistent with §9.1's stated intent; §9.4's ordinary-case wording is not used to bypass
it. No claim of complete standards/native Word parity from this first catalog.

## API / records

read_compatibility_catalog(data, *, source_sha256, limits=None). Exact bytes and lowerhex
SHA256, archive size before hashing, verified original DocxSource. Exact immutable
CompatibilityLimits; bad input/source mismatch raise CompatibilityCatalogError with
fixed messages/codes invalid_input, source_mismatch, compatibility_limit_exceeded.
Reuse DocxError for invalid packages; no payload values in errors/repr.

Frozen slotted records:
- CompatibilityAction(kind, anchor, selected_anchor, attribute_names): kinds
  ignore_element / unwrap_element / alternate_content / strip_attributes. Only
  alternate_content may have selected_anchor (Choice/Fallback actual source node or
  None). Only strip_attributes has nonempty sorted exact expanded attribute names.
- CompatibilityPart(part_name, root_anchor, actions): all actual scoped parts, sorted
  by part name; actions sorted by physical path then kind. Anchors use original element
  indices (comments/PIs do not count). No child promotion/renumbering or XML copy.
- CompatibilityIssue(code, anchor); first semantic refusal only, fixed safe code.
- CompatibilityCatalog(source_sha256, profile, status, main_part, parts, issues,
  catalog_sha256), fixed `docx-compatibility/base-word-selection-v1`.
Private values/collections/names/anchors repr=False. No text, metadata attribute values,
XML/source objects, paths to local files or asserted `complete` field. Canonical streaming
SHA256 excludes catalog_sha256 and enforces serialized manifest size before accumulation.
Status indexed if scoped source contains MC element/attribute, otherwise absent (parts
still report scoped XML scan with empty actions); blocked has parts=() and one issue.
An unknown non-ignorable namespace stays untouched: MC success does not prove that
application readers understand it. A Word semantic checker must still prove its content.

Scope parts: main part plus all entries of exact styles/settings/header/footer/footnotes/
endnotes MIME types, including unused/unbound candidates. Other parts are not declared
read by this catalog. This does not replace package coverage or comments policy.

## Namespace scope / grammar

Resolve prefixes against actual in-scope declarations including implicit xml binding;
namespace aliases and rebinding must work. Default namespace is not an empty prefix
list token. Lists split only on XML whitespace (space/tab/CR/LF), not arbitrary Unicode
whitespace. Ignorable/MustUnderstand/ProcessContent may be empty; Choice Requires may not.
Unknown prefix, MC namespace in lists or invalid ProcessContent QName is a refusal.
ProcessContent tokens are prefix:NCName or prefix:*; URI must be declared ignorable on
that node or an ancestor. URI/pair declarations inherit by union; rebinding prefixes
does not alter earlier URI declarations. Validate NCName by [XML 1.0 fifth edition §2.3](https://www.w3.org/TR/xml/#sec-common-syn)
NameStartChar/NameChar excluding colon (Unicode,
underscore/hyphen/dot allowed as specified), not Python identifier or ASCII-only guesses.

Every scoped node is syntactically checked for core MC attributes, including discarded
branches. This initial catalog conservatively blocks malformed MC in such branches;
it does NOT require unsupported capabilities in discarded branches. Unknown ordinary
markup remains opaque. No generic root/body/content grammar is asserted here.

AlternateContent: no unqualified/XML attributes; qualified attrs only MC or namespaces
declared ignorable there/ancestors. One or more direct Choice children then at most one
Fallback. Other direct children require ignorable namespaces and must actually be
ignored (understood or ProcessContent wrappers there block an active alternative).
Non-whitespace character data directly in AlternateContent is refused. Choice/Fallback
physical parent must be AlternateContent. Choice has only unqualified Requires, required;
Fallback no unqualified attrs. Same qualified/XML attribute rules. Unknown MC elements,
duplicate fallback, choice after fallback, nested direct AlternateContent are refused.

Select the FIRST Choice whose resolved Requires URIs are all understood; else Fallback,
else selected_anchor=None. Never concatenate alternatives. Retained selected branches
contribute descendant decisions; unselected branches contribute no actions. Ignored
ancestors suppress descendant actions, including nested selected alternatives.

On an unknown ignorable element: ignore subtree unless it matches inherited/same-node
ProcessContent exact URI/local or URI/*; then unwrap (keep children original). Unwrapped
elements cannot carry xml:base/lang/space. Unwrap checks active MustUnderstand. Ignored
subtrees do not. Active AlternateContent checks its own and selected branch MU, including
no-selection case for its own MU; unselected branch MU does not require capabilities.
Other active ordinary nodes check MU before removal. All retained ordinary nodes strip
core MC attrs and unknown ignorable attrs; understood attrs are retained even when
namespace is declared ignorable. Whole ignored/unwrapped/alternative elements need no
extra strip action, and Choice/Fallback wrappers are handled by their parent action.

## Bounds and stream processing

CompatibilityLimits maxima: max_xml_nodes100000, max_xml_depth128,
max_xml_characters8388608, max_parts128, max_mc_items10000,
max_namespace_declarations10000, max_actions10000, max_manifest_bytes33554432.
Aggregate safe raw SAX preflight for ALL scope parts precedes semantic scanning, even
if an earlier part could fail syntax. Count text, attr values/expanded names, element
expanded names and namespace bindings (prefix+URI). MC items count MC elements, MC attrs
and tokens in the three core lists / Choice Requires. No product size limit/truncation.
Namespace/MC counts include excluded/unused/history branches. Actions global, not per part.

Semantic reader may be streaming (no DOM required). Namespace map with reversible scoped
updates, and inherited rule scopes with bounded memory; do not copy all namespaces/rules
onto every node. Physical path counters use actual source children. No untrusted regex
backtracking or tree serialization. Catalog is atomic across parts; any semantic refusal
leaves no earlier decisions available. Bounds raise, rather than fabricate blocked success.

## Acceptance

Strict/UTF16/custom parts; known/unknown Choice order, fallback/no-match, nested selection;
namespace aliases/rebinding and sibling restoration; Ignorable URI inheritance and empty
lists; exact/wildcard ProcessContent, retained descendants and unknown markup left intact;
ignored attrs versus known attrs; active/discarded MU; XML attr constraints; qualified
MC attrs and ignored extension children; malformed structure/lists/Unicode whitespace;
unused/style/note parts all scanned and atomic failures; aggregate namespace/MC/XML/action/
manifest limits before semantic scan; canonical immutable metadata-only output, source
bytes unchanged, invalid inputs and inert subprocess. Full gate/prior hashes/main V8.
