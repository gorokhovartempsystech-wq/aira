# Обычный текст шаблона AIRA и неиспользуемые списки

D03-17A2b5e1 adds opt-in `visible_unlisted.build_unlisted_snapshot` and source-derived
batch/singular mapping. Fixed `docx-analysis/final-visible-unlisted-v1` uses
`docx-visibility/mc-pagination-styles-v1`; old public readers retain old behavior.

New body/heading1/2/3 DOCX from the actual creation service can be read without modifying
source bytes, including Unicode, tabs, soft breaks and empty documents. Paragraph
widowControl is closed pagination metadata in defaults, used styles and direct pPr.
It does not turn hidden text visible. Hidden paragraph boundaries remain their prior gate.

An unused numbering definition part is not blindly metadata: original aggregate XML
limits precede DOM, the closed unbound grammar forbids reverse style associations and
unknown/MC definitions, and relationships/namespace/IDs/overrides are validated. Only
complete retained story closure permits `excluded/unused_numbering_definition`. Any
active numPr through direct/default/style/table properties retains its existing gate.

Strict schema intersection matters: left/right alignment/tab aliases and left/right
indents are Transitional only. This first Strict subset accepts center alignment and
other listed common tabs; start/end alignment is not added silently. Numbering labels,
counters, hierarchy and supported active lists are the next bounded work. Their metadata
must not be fabricated as original literal text offsets or hidden in the old ML wire.

All previous selected-view fields/controls/tables/notes/raster policies remain. Mapping
rebuilds once per batch (even empty), checks source/profile/coverage and rejects rehashed
edits. No I/O, XML rewriting, DB/schema/dependencies or public capability injection.

See [contract](d03-17a2b5e1-contract.md) and [verification](d03-17a2b5e1-result.md).
This is reader support; application codec/worker admission, editor/export/native layout
and real model delivery remain separate gates.
