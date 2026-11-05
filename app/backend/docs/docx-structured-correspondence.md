# Structured dismissal correspondence

`ara.docx_analysis.remapping.match_findings(previous, current)` retains its public signature
and FindingTransfer records. Both full stored triplets are source-revalidated before any
identity comparison or no-match decision. Legacy matching and exact-source dismissal keys
are unchanged. The direct-lists profile uses a private part-aware structured matcher.

A paragraph may contain several literal fragments separated by a picture or note reference.
They correspond by original structure and ordered positions, without invented text. Matching
also requires equal source properties, ancestry, numbering labels/counters, styled prefix,
neighbors and unique noncrossing placement. A changed table/grid/control can therefore make
its findings visible again even if the quote is unchanged. Repeated quotes are not guessed.

Note findings additionally require correspondence of every referencing main paragraph and the
complete incoming reference set. Changing one of several parents prevents carrying a hide
to the shared note. Main and note paragraphs with equal numeric paths stay separate because
part identity is always included. Primary and related evidence must both correspond.

Global styles/numbering/images/relationships/note parts and section properties are protected.
Only direct final body sections have cross-source correspondence in this cycle; paragraph,
historical or wrapped section boundaries conservatively return no transfer. Exact-source
replay remains supported. Raw wrappers around the main body remain outside existing package
admission; supported compatibility wrappers are inside that body.

No-match is normal for valid ambiguous/unsupported correspondence. It never silently treats
corrupt records as valid. Existing persisted decisions are retained; displaying a finding again
does not erase its original hide. Resolution limits now include generated label/suffix cost
for every structured source pass; exceeding a limit yields the existing explicit413 response
without partial alias output. Existing legacy estimates remain unchanged.

The implementation is pure and does not infer model quality. Persistent structured HTTP and
desktop integration follow separately. See [contract](d03-17a2b6c4-contract.md) and its
[verification/fixture correction](d03-17a2b6c4-result.md).
