# Direct outline numbering for DOCX analysis

D03-17A2b7A adds a pure source reader for direct main-story list levels0–8. It preserves
original DOCX bytes and returns generated numbering as context, separately from literal spans.
Application storage/runtime/desktop admission is a separate B7B cycle.

```python
from hashlib import sha256
from ara.docx_analysis.visible_outline import build_outline_snapshot, map_outline_span

snapshot = build_outline_snapshot(
    original_docx,
    document_id=document_id,
    storage_revision=revision,
    source_sha256=sha256(original_docx).hexdigest(),
)
```

Check `snapshot.complete` before offering a full analysis. Failure never returns a partial
literal text/list collection. `VisibleViewError` reports bounded technical failures. Mapping
an exact `OutlineSnapshot` re-derives it against original bytes even for an empty request;
recomputing a caller-modified snapshot hash does not authorize false evidence.

`lists` records retain paragraph/numPr/level/instance/startOverride anchors, numId, level,
ordinal, format, label, suffix and owned fragment IDs. A paragraph split by an image or note
reference still consumes only one list number. Blank and hidden-literal items also count.
The exact new profile is `docx-analysis/final-visible-direct-outline-v1`; old profile DTOs and
algorithms are unchanged. New types are not accepted by the previous list mapper.

Counters are per instance and level. Missing restart uses the preceding level or higher;
explicit0 keeps counting; other supported triggers reset on that level or higher. A replacement
level supplies a complete new definition/defaults, while Word's restart policy still comes
from its abstract level. A startOverride is reused after restart. Parent references require an
actually consumed, non-reset counter; uncertain initial ancestors are not invented.

Supported labels are decimal, literal bullet (including percent characters), upper/lower Roman
and legal decimal rendering of known numeric references. Roman conversion uses subtractive
notation and repeated M beyond3999. Each label is conservatively limited to31 UTF16 units,
with at most9 substitutions and whole-document budgets; output is never truncated. Reference
indices cannot exceed the current level. Suffix is separate from literal text.

This is a deliberately bounded implementation of the full product DOCX requirement. Inherited
or style-linked numbering, language-dependent letter formats, none/custom/picture numbering,
numbered note/header stories, unknown ancestor counters and unproved active properties remain
explicit gates. Strict/UTF16 XML, tables, selected wrappers, hidden literals, raster splits and
ordinary referenced notes have synthetic source/mapping coverage. Native Word layout parity
has not been demonstrated; the prior Word automation timeout is unchanged. This reader neither
reformats nor edits/accepts tracked changes in a document and does not run a real ML model.

Technical semantics and primary sources: [B7A contract](d03-17a2b7a-contract.md).
