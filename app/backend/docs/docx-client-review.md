# Review client integration

D03-18A4. `createReviewTransport({origin, sessionToken, documentId})` returns the pinned
review HTTP port. `createReviewSession({documentId, editor, send, onState})` is inert.
The editor must be the same document's sole current `createDocxSession` actor.

After successful analysis call `await review.load(receipt.run_id)`. Explicit
`load()` without ID loads the last successful result for recovery. `status()` returns
a detached review envelope, phase, pending retry availability and freshness flags.
Display the `fixture` label. `view.no_findings` is the original analysis outcome;
`view.no_visible_findings` can instead mean hidden/filtered results.

`canHighlight` is true only for a ready response matching both the saved document
and the current editor RAM hash. Re-read status after every editor update. When
false, show the older result as stale; do not search quotes or move anchors. Undo
may restore identical bytes and make the same result current again.

- `setFilters({disabled_types, show_questions, show_hidden})` persists all filters.
- `setHidden(findingId, true/false)` hides/restores a known finding.
- `clearHidden()` is an explicit action to restore all hidden findings.
- `retry()` repeats the exact pending command after unknown outcome.
- `load(runId)` refreshes after known conflict or failed read. A command already
  acknowledged is not repeated just because this subsequent refresh failed.
- `dispose()` ignores late replies and prevents further operations.

Use action availability/phase while requests run. A preferences conflict needs an
explicit refresh and renewed user choice, not silent overwrite. These operations
change presentation only, never document text or model output. The adapter bounds
metadata/review data, rejects redirects and foreign routes and keeps capability in
closure. Render text as text, not injected HTML. Final frontend remains separate.
