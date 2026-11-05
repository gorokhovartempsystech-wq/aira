# Source-proven paragraph-style numbering

D03-17A2b8A adds the opt-in `ara.docx_analysis.visible_style_lists` pure reader:
`build_style_list_snapshot`, `map_style_list_spans` and `map_style_list_span`. The identity
arguments and visible limits are the same as the [outline reader](docx-visible-outline.md).
The new exact DTO is `StyleListSnapshot`, profile
`docx-analysis/final-visible-style-lists-v1`; it is not accepted as an older snapshot type.

A paragraph can select its numbering directly, or through its explicit/default paragraph
style. The reader follows the resolved same-type basedOn chain to the nearest current numPr.
A positive inherited numId requires exactly one abstract level whose pStyle names the actual
applied paragraph style. An ancestor-only association is not guessed. Explicit direct
properties win; numId0 cancels numbering without consuming a marker. Partially specified
direct properties are not merged speculatively with inherited ones.

`StyleListItem` retains the outline fields and adds `numbering_source`,
`style_reference_anchor`, `style_chain` and `level_style_anchor`. An inherited item's
properties_anchor points to the actual numPr in the original styles part. Its chain points
from the applied style to the property owner; the level binding points into the abstract
numbering definition. The selector can be absent only when a default style is proved.
Direct items have no style chain or style-binding anchors. These records never manufacture
a paragraph numPr or a literal text slice for a generated label.

The four outline formats, nine levels, instance counters, restart/start overrides, label
bounds and literal mapping rules are reused. Direct and style-selected items share the
same counters. Blank/hidden-literal paragraphs consume once; table/wrapper paths remain
physical original paths. Inherited selections are attached before the cross-paragraph field
check. Referenced ordinary notes remain literal context; active numbering in non-main
stories remains a gate. Original bytes are never rewritten by this reader.

Only current style numPr containing one numId is admitted. Style ilvl, numbering in document
paragraph defaults/table styles, numbering-style links and replacement-level pStyle remain
unproved. Word explicitly documents unpredictable handling of style ilvl. Letters/pictures
and other outline exclusions remain. This is a bounded semantic reader, not a full Word
layout engine or a native Word parity result.

All contexts and anchors are freshly derived from the supplied source. Mapping rebuilds and
compares the complete source snapshot even for an empty request batch. Technical budgets
cover raw XML before DOM, style chains individually and in aggregate, generated/literal text,
records and canonical manifest size. Repeated style choices are cached only within one
private build; each output chain still counts against the aggregate budget.

Synthetic tests exercise explicit/default/inherited styles, direct overrides/removal, selected
style wrappers, Strict UTF16 and mixed part namespaces, tables/hidden text, notes, ambiguous
bindings, closed grammar/package links, history, all levels/formats and rehashed provenance
forgeries. Previous source profiles remain unchanged. This cycle does not yet admit the new
record through the worker, storage or desktop: the following vertical integration must use
new closed wire/view shapes and preserve old saved profiles.
