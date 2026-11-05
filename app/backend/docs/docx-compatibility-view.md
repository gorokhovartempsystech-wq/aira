# Immutable original-address compatibility view

`ara.docx_analysis.compatibility_view.build_compatibility_view(data, source_sha256=...)`
creates a read-only logical tree from the original source, with the fixed
`docx-compatibility/original-logical-view-v1` profile. It takes the same exact limits as
[the decision catalog](docx-compatibility-catalog.md) and always rebuilds that catalog.
There is no caller catalog/capability override or transformed XML/package input.

A `ready` view contains all scoped parts; `blocked` contains no parts and one issue.
Check the view status: a syntactically valid catalog can still have an unsupported
character-ownership boundary for projection. Neither status asserts content completeness,
analysis eligibility, visible text or export support.

`ViewNode` supports tag/attrib/get/text/tail, len/index/iteration and a tuple of children.
Attributes and part path indexes are read-only mappings. Every retained node uses its
original SourceAnchor and unchanged tag/text/tail; attributes change only as explicitly
listed in the catalog. Lookup `view.node(anchor)` returns that same node or None for
an absent/removed node. Invalid or wrong-source anchors raise fixed safe errors.

Ignored subtrees disappear only from logical navigation; unwrapped content and selected
Choice/Fallback children retain original ordering and source positions. The factory never
modifies the parsed original tree, emits XML, rewrites ZIP bytes or invents w:t contents.
It allocates one tree per part after aggregate validation, with bounded promotion and
identity indexing. Text and private metadata are omitted from repr.

Initial projection refuses structural root replacement and mixed direct character data
at transformation boundaries. It also refuses structural changes inside Word t/delText/
instrText/delInstrText even if the affected text is whitespace. This prevents silently
inventing source offsets or losing tails. XML whitespace outside these text leaves may
be dropped at removed wrappers; retained ordinary node text/tail remain exact. Arbitrary
mixed XML text is an explicit remaining boundary, not a successful lossy import.

The next stages must use this same view for styles, structure, references, visibility
and source mapping. Existing public readers are unchanged and do not gain MCE support
by the existence of this adapter. See [the cycle contract](d03-17a2b5c2a-contract.md).
