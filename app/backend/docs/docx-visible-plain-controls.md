# Saved plain-text content controls

`ara.docx_analysis.visible_plain_controls` exposes `build_plain_control_snapshot`,
`map_plain_control_spans` and `map_plain_control_span`, with the fixed profile
`docx-analysis/final-visible-plain-controls-v1`. Identity, limits, NoteSnapshot and
source-slice DTOs follow the [selected-story reader](docx-visible-compatibility.md).
One fresh selected view supplies every context and original XML address. Public APIs
accept no caller-supplied catalog, reader or alternative profile.

Unbound text controls support inline, block and cell positions. A block/cell control
has at most one paragraph; inline content belongs to one actual logical paragraph.
Controls around rows or tables remain unsupported, even when empty. Ordinary text,
tabs, saved soft breaks, supported comment/bookmark markers and final insertions are
read; deleted content stays excluded. Proven deleted cells retain their existing
exclusion rule. Unsupported content is validated before run visibility is applied.

All retained runs in a plain control must have identical current formatting
properties and style selectors. Property ordering and historical rPrChange do not
change that proof; different styles or explicit versus inherited formatting are not
guessed equivalent. Hidden retained runs participate. Input/end formatting does not
replace the saved runs' formatting. This is a conservative proof of uniformity,
not a general formatting normalizer.

Existing soft breaks are preserved whether multiLine is absent, true or false. That
flag governs adding new breaks; this reader does not edit the control. The rule follows
[ECMA-376 Part 1 §17.5.2.44](https://ecma-international.org/publications-and-standards/standards/ecma-376/).

Rich controls retain their previous supported fields, notes and table behavior.
Fields, nested controls, hyperlinks, note markers, media and page/column breaks inside
plain controls remain explicit gates. Bound controls, active placeholders, unknown or
conflicting types also refuse. A failure returns no partial text, fragments, runs,
paragraphs or note references. Metadata records the control and uniformity proof.

Mapping rebuilds once per batch, including an empty batch, and compares the exact
source-backed snapshot. Rehashed changes are rejected, as are snapshots from earlier
profiles. Original bytes and source-node Unicode offsets remain unchanged. Raw,
semantic, aggregate coverage and manifest limits still apply.

This opt-in reader is not yet application admission, control editing or a claim of
native Word fidelity. Media/text boxes, other control types, numbering/font/theme
parts and unsupported tracked boundaries need their own work. See the
[contract](d03-17a2b5b3-contract.md) and [verification result](d03-17a2b5b3-result.md).
