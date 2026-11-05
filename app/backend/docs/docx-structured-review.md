# Structured DOCX review v2

`ara.docx_analysis.structured_review` bridges the fixed
`docx-analysis/final-visible-direct-lists-v1` source snapshot to `docx-review/2`.
`prepare_structured_review` and `validate_structured_reply` accept the same provenance,
limits and immutable byte envelopes as review v1. Each public call verifies the DOCX
source again; labels, anchors and fragment associations cannot be authorized by a rehash.

`engine_request.document_context` contains exact `lists` and `note_references` from the
verified snapshot. The separate `engine_request_json` includes it too. Literal fragment
text/offsets remain unchanged: a generated label is context, not a fabricated XML text
slice. Results contain the same context at top level, including when findings are empty.
All context contributes to the canonical wire byte limit and snapshot identity.

Replies retain the closed engine0.1.0 literal-span syntax. Primary evidence must match
source text exactly; related evidence must quote the complete other fragment. Existing
count, provenance, duplicate, questions and semantic identity rules apply. One source
mapping batch handles all findings. Unsupported and marker-only documents cannot be
reported as successful empty reviews. Fixture results always have no_findings=false.

[Schema](../contracts/docx-review-v2.json) is self-contained, with closed objects and local
references. Old `docx-review/1` and old APIs remain unchanged and reject new snapshots.
No public plug-in registry or caller-defined context is admitted. The schema describes
wire shape; actual source proof remains mandatory.

This cycle supplies a pure protocol, not an executing ML adapter or runtime admission.
Storage codec, fixture2 worker, saved checks/retries and application reads need the next
bounded cycles. The real model package is still unavailable. [Contract](d03-17a2b6a-contract.md)
and [verification](d03-17a2b6a-result.md) record the precise boundary.
