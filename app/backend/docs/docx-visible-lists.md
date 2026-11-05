# Прямые одноуровневые списки DOCX

`visible_lists.build_list_snapshot` reads actual AIRA bullet/numbered paragraphs under
fixed `docx-analysis/final-visible-direct-lists-v1`. `ListSnapshot.lists` stores separate
`ListItem` data: exact original paragraph/numPr/level/instance/override anchors, num_id,
level, ordinal, decimal/bullet format, logical label, suffix and literal fragment IDs.

Text fragments and SourceSlices remain literal: generated «1.» or «•» is not inserted
into original offsets. Blank or hidden-literal paragraphs can retain a label with no
literal fragments. This does not claim physical font/page fidelity. Source bytes are
unchanged. Mapping rebuilds once per batch, even empty; rehashing forged labels, counters,
anchors or links does not establish source authority. Old profiles reject the new DTO.

Counters continue per instance across ordinary paragraphs/table cells, and new instances
start independently. Missing start=0, missing format=decimal, missing suffix=tab;
startOverride takes precedence. numId0 removes numbering and needs no definition part.
Positive references require direct explicit level0 and a proven main numbering relation.

This first active subset supports decimal %1 labels and literal Unicode bullets; active
multilevel/style inheritance, roman/letter/custom formats, replacement lvl overrides,
label visibility, other-story lists and list boundaries inside spanning fields remain
explicit gates. Existing source-selected tables/controls/fields/notes/rasters remain.
Unknown/unsupported content causes an atomic incomplete snapshot, never partial list text
masquerading as a complete document. Unused definitions are excluded only after closure.

Generated character cost counts with literal text; each label <=4096 chars, item count,
manifest/coverage/source XML bounds remain. Expansion size is checked before substitution.
No DB/schema/dependency/network/environment changes. [Contract](d03-17a2b5e2-contract.md)
and [verification](d03-17a2b5e2-result.md) document the exact subset and evidence.

Next priority: explicit source codec, worker/review adapter and application admission must
carry list context without discarding it or reinterpreting older saved snapshots. The
current app's visible-main-v1 admission is not automatically replaced by reader availability.
Inherited/multilevel and remaining general DOCX support remain separate required work.
