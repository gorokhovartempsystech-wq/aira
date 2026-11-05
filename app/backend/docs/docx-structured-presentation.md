# Structured review presentation

The existing `ara.docx_analysis.presentation.present(source, attempt, result, ...)` fully
revalidates the stored triplet before applying preferences. Legacy review1 records produce
the original docx-review-view/1 bytes. Structured review2 records produce docx-review-view/2
with required `document_context`, preserving all source-proven lists and note references.

Context is independent of the visible finding set: it remains present when findings or
questions are hidden, when all finding types are filtered, or when a fixture returns no
findings. Empty numbered items are retained as context without invented literal fragments.
Generated labels are metadata; quotes and source slices continue to describe actual text.

Consumers should branch on schema_version. [View2 schema](../contracts/docx-review-view-v2.json)
defines the complete public shape. It contains neither private rules/suggestions nor stored
dismissal keys. Questions keep original finding_ids and separately identify visible_finding_ids.
The fixture flag and original no_findings remain distinct from no_visible_findings.

Same-source dismissal identities remain stable across attempts/revisions. Source or model
changes have distinct keys; cross-source correspondence is a separate feature. This change
does not enable the new supervisor in desktop or replace the HTTP OpenAPI nested-object
descriptions. Those integrations follow after correspondence/resolution acceptance.

See [contract](d03-17a2b6c3-contract.md) and [verification](d03-17a2b6c3-result.md).
