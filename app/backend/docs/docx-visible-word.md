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
