# Ordinary Word package source reader

`ara.docx_analysis.visible_word.build_word_snapshot` reads the original bytes under the fixed
`docx-analysis/final-visible-word-package-v1` profile. It returns an exact `WordSnapshot` with
literal fragments, notes and source-proven style-list context. `map_word_spans` and
`map_word_span` rebuild the same original source, including for an empty mapping request.
It does not upgrade existing snapshots or rewrite the input ZIP.

The six [independent synthetic templates](../tests/fixtures/docx/common-template/README.md)
cover plain paragraphs, headings, bullets, numbers, tables and merged cells. Unlike the earlier
minimal packages, these retain ordinary font/theme/web settings, duplicated styles, thumbnail,
empty bibliography store and numbering MC declarations. These examples exercise source reading
and mapping, not native Microsoft Word rendering or the complete DOCX feature matrix.

Numbering now uses the selected compatibility view with physical original addresses, including
under AlternateContent wrappers. All nine levels, four formats, inherited bindings and prior
counter/visibility rules remain. ContextualSpacing is a validated boolean leaf affecting
paragraph layout, not literal text. [Microsoft's ContextualSpacing reference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.contextualspacing?view=openxml-3.0.1).

Auxiliary parts are accepted by exact internal role/owner/cardinality and bounded selected XML,
not by MIME alone. Font descriptions allow no embedded resources. The web-settings subset is
limited to allowPNG/doNotSaveAsSingleFile. Theme handling is a closed set of presentation
metadata, without text/unknown attributes/extensions/outgoing resources; this is not a layout
engine or full DrawingML schema validator. A package-root thumbnail remains an opaque preview
and cannot double as content imagery. Unknown root image roles refuse even if the raster bytes
are otherwise valid. Only an empty bibliography store with matching schema/GUID properties is
excluded; arbitrary/nonempty customXML and bindings remain unproved.

The selected stylesWithEffects copy must agree with the main styles: defaults and latent
metadata, every shared definition, and all referenced/default definitions. XML indentation is
ignored only where XML whitespace is allowed. Base-only unused nondefault definitions may
remain; a reference makes them relevant and rejects the ambiguity. Conflicting copies do not
silently choose a winner. The archived [MS-DOCX specification, section2.1.1](https://officeprotocoldoc.z19.web.core.windows.net/files/MS-DOCX/%5BMS-DOCX%5D-200818.pdf)
defines this part as a styles copy; this reader requires observed agreement rather than relying
on producer-version assumptions.

All auxiliary/inactive XML contributes to aggregate quotas before selected DOM allocation.
Exclusions become valid only after the whole retained story/reference closure is proved.
Unknown or unsupported content returns an incomplete snapshot with no partial analysis text,
fragments, generated labels or note references. Malformed packages and quota violations retain
the existing explicit exception behavior. No network, external font loading or model call is
performed. Storage/review/native desktop admission follows in its own integration cycle.

## Ordinary layout extension — D03-20B (9 November 2026)

The accepted team reader from `main@e71415c` also handles the bounded CRM layout
subset (proofing/page-cache markers, tab stops, Word theme-family metadata).
The new layout extension retains the original package and supports:

- Optional `w:softHyphen` as a zero-width discretionary layout point, recorded in
  coverage. It does not split the word sent for analysis.
- `w:noBreakHyphen` as U+2011 with source-slice kind `nonbreaking_hyphen` and an
  anchor to that original element. Consumers must not interpret it as a `w:t`.
- Positional tabs as `tab` slices with original `w:ptab` anchors.
- Closed paragraph-border properties in direct formatting and paragraph styles.
- Partial style numbering properties: absent `numId` continues inheritance;
  only explicit `numId=0` cancels numbering. Conflicting levels still refuse.

Older source profiles retain their previous validation rules. This is not a
claim of support for every Word object or the missing original Mac document.

## Closed symbolic atoms — D03-20C (9 November 2026)

The reader also accepts the verified Wingdings check mark (`00FC`/`F0FC`) as
U+2713 and literal inline Office Math runs (`m:oMath/m:r/m:t`). Math is not
computed or rewritten. Word visibility and field-code exclusion still apply.
Unknown font glyphs and structured equations (fractions, powers, matrices)
refuse atomically; VML support is not claimed.

The two v5 review JSON schemas now include `symbol` and `nonbreaking_hyphen`
source-slice kinds. Anchors refer to the original XML elements and offsets to
their decoded characters. Consumers must update their closed enums alongside
the backend. The team synthetic blocker sample now reads all six fragments;
this does not verify the missing original Mac file or ML semantic accuracy.

## Embedded fonts and paragraph metadata — DOCX-COMPAT-01 (14 November 2026)

The Word package profile accepts `w14:paraId` and `w14:textId` on paragraphs as
eight hexadecimal digits. Original XML attributes and physical source anchors
remain intact. Other attributes, malformed identities and identities on runs
remain unsupported. Earlier source profiles retain their existing rules.

Embedded regular, bold, italic and bold-italic fonts are retained as opaque
resources. Each font slot must resolve through its font table's internal font
relationship to a nonempty TrueType/OpenType or obfuscated font part. Keys and
subset flags are validated; obfuscated font slots require a key. Every outgoing
font-table edge must have a slot, and font parts cannot have outgoing edges or
other owners. Unknown roles and orphan parts still refuse the whole snapshot.
Font data is never installed, decoded, executed or included in model text.
Existing archive, XML and aggregate quotas apply before this accounting.
See Microsoft's [font embedding reference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.embedregularfont?view=openxml-3.0.1)
and [font content types](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/1663dabc-5d98-463f-889e-bcd9b77c3d34).

The same bounded extension accepts valid paired `colFirst`/`colLast` bookmark
metadata and explicitly disabled run/style `rtl` formatting. Active right-to-left
formatting is outside this extension. These properties do not remove or reorder
literal text.

Synthetic acceptance covers both Word namespaces, all four font slots and both
font content types, exact source mapping, persisted fixture review, and export
after a manual text edit. The fixture is not real inference. Export without edits
retains exact bytes; a text edit preserves every other package part, including
fonts, and all XML outside the edited text node. This does not claim pixel parity
with Microsoft Word, font rendering in the editor, or a released desktop build.
