# Original-source Markup Compatibility catalog

`ara.docx_analysis.compatibility.read_compatibility_catalog(data, source_sha256=...)`
returns immutable metadata for the fixed `docx-compatibility/base-word-selection-v1`
profile. It is a pure reader of supplied original bytes. It performs no application
I/O, changes no package bytes, and contains no text, attribute values or XML objects.

`status` is absent, indexed or blocked; absent still lists all scoped parts. A blocked
catalog exposes one safe issue and no partial parts. A successful catalog does not
assert that Word content is understood or that the document is eligible for analysis.
Unknown non-ignorable markup remains the responsibility of downstream content proof.

Each original physical anchor has zero or one decision:

- `alternate_content`: selected original Choice/Fallback anchor, or None;
- `ignore_element`: skip original subtree in an eventual logical view;
- `unwrap_element`: promote logical children without changing their original identities;
- `strip_attributes`: exact sorted expanded names; no attribute values are returned.

Both Strict and Transitional base Word and office relationship namespaces plus XML
are understood. MC has special processing rules and cannot be listed as a capability.
No implicit Office release, w14/VML/drawing support or caller capability override exists.
Core Ignorable/ProcessContent/MustUnderstand are supported; unsupported MC extensions
remain explicit gates. Inactive content does not require unavailable capabilities,
but all scoped MC syntax is conservatively validated. This is a bounded initial profile,
not a complete native Word compatibility claim.

Scope includes main and every declared styles/settings/header/footer/footnotes/endnotes
part, including unused candidates. Comments and arbitrary XML are not declared analyzed
by this catalog. Aggregate raw limits apply before semantic selection, including unused
and ignored branches. Technical bounds raise a fixed error rather than truncate output.
The canonical SHA256 is calculated with bounded streaming serialization.

The rules follow [ECMA-376 Part 3](https://ecma-international.org/wp-content/uploads/ECMA-376-3_5th_edition_december_2015.zip)
and [XML 1.0 names/whitespace](https://www.w3.org/TR/xml/#sec-common-syn).
Microsoft warns that saving a preprocessed tree can discard unselected markup in its
[compatibility introduction](https://learn.microsoft.com/en-us/office/open-xml/general/introduction-to-markup-compatibility).
AIRA records decisions against the original package; this API never serializes a filtered
package. Integration into styles, structure, visibility and mapping is a separate cycle.
