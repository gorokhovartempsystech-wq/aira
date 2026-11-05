# Structured semantic fixture2

`ara.docx_analysis_worker.structured_fixture.fixture_execution()` returns a distinct explicit
fixture identity. `reply_for(WireMessage)` validates a real bounded worker request and emits
an engine0.1.0 synthetic reply. It performs no inference, filesystem or network actions.

Two exact input pairs are supported with fixture2 execution: structured docx-review/2 with
direct-lists source profile and required document_context; legacy docx-review/1 with
visible-main profile and no context. The second pair lets a later runtime retry saved old
snapshots without upgrading their source interpretation. Malformed or mismatched pairs fail;
there is no fallback. The old fixture1 remains closed to its original version and identity.

Lists and note links have strict closed keys, source-bound original anchors, valid literal
fragment associations, uniqueness and resource bounds. Labels contribute to the total text
budget. Multiple references may point to the same note definition. A blank list item cannot
supply a fabricated span or lend its label to unrelated ordinary text.

The example uses the first available list item's real literal fragment, otherwise the first
literal fragment. Its quote is at most64 source characters. Explanation includes a bounded
label sample and list/note counts, and clearly says «Учебный пример» and «Реальная модель не
запускалась». Private document content never appears in errors. No-finding status is not
asserted by the fixture. The parent still revalidates source, request and literal evidence;
this does not establish semantic correctness of a model explanation.

This cycle does not add a native launch mode or select fixture2 in the desktop application.
Those are separate lifecycle/integration cycles, followed by structured presentation and
safe dismissal correspondence. Actual ML package/native Windows/Word/release gates remain.
[Contract](d03-17a2b6c1-contract.md) and [verification](d03-17a2b6c1-result.md) describe the boundary.
