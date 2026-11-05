# Visible selected Word stories and source mapping

`ara.docx_analysis.visible_compatibility` provides `build_compatibility_snapshot`,
`map_compatibility_spans` and `map_compatibility_span`. The fixed profile is
`docx-analysis/final-visible-compatibility-v1`; the style context uses C2B's explicit
MC profile. Inputs are original DOCX bytes, document/revision identity and optional
exact VisibleLimits. Public APIs accept no caller view, catalog or capability override.

Each build prepares one fresh [coherent context bundle](docx-compatibility-contexts.md).
That same immutable view supplies selected styles, table styles, section/settings and
note definitions, main/header/footer/note trees, move proofs, table/history/revision
proofs and visible-run readers. No transformed package is serialized. All text slices,
paragraphs, cell flows, story roots and note references retain their original XML
addresses; a promoted logical child is never assigned its new positional index.

The existing visible table/control grammar is reused: final tracked content, effective
run visibility, stored field results, rich controls, current table grids, section stories
and referenced notes. Compatibility wrappers are transparent to field flow. Existing
control, table and story barriers still apply. Original relationships determine targets;
generated note labels do not become fabricated text or numbers.

An early blocked context returns a canonical incomplete NoteSnapshot with a blocked MC
style context and safe source coverage. A later content, proof or package failure also
clears text, fragments, paragraphs, runs and note references. Unknown retained content
and unaccounted parts stay explicit gates. Compatibility decision coverage records ignored
elements as excluded and unwrap/attribute/alternate decisions as metadata; stripping
attributes does not exclude a whole node. Raw and semantic limits apply before use,
including discarded branches, and the final combined evidence has an aggregate bound.

Every mapping batch, including an empty request tuple, rebuilds once from original bytes
and compares the exact snapshot. Recomputed hashes do not authorize changed provenance,
text, styles, coverage or note references. Old and new profiles reject each other's
snapshots. Unicode slice offsets refer to original literal nodes.

This is an opt-in analysis reader, not application admission or an editing/export API.
Plain/bound/placeholder and other control types, media/text boxes, numbering/font/theme
parts and unsupported tracked boundaries remain separate work. Existing public readers
retain their previous behavior. Native Word/Windows fidelity is not claimed by these
synthetic tests. See [the cycle contract](d03-17a2b5c2c-contract.md).
