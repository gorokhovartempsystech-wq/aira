# Workspace, tabs and recovery

D03-18A5. `createConnectedWorkspace({origin, sessionToken, onState})` composes the
existing editor, analysis and review modules with a trusted live host connection.
Construction does not open documents or start network/timers. `onState` also receives
updates caused by composed clients; read their individual status for details.

`await workspace.open(documentId)` reads recovery first. With absent/empty recovery
it opens current bytes. A working/pending copy returns a `recovery_required` tab;
only an explicit `open(documentId, {recover:true})` restores it. No automatic discard.
An unfinished save can produce `recovery_pending`: explicit `reconcile(documentId)`
completes its existing server operation. On uncertainty call reconcile again with
the retained identity; do not invent another operation. Conflict is not editable.

`retryOpen(documentId)` resends the exact unknown opening request. Duplicate open
of an already open document focuses the same actor. `focus(documentId)` changes
selection without saving/closing other tabs. `status()` describes tabs; `metadata(id)`
provides detached last editor state, including unresolved recovery/close cases.

`client(id)` returns guarded editor/analysis/review facades. Use editor.edit/save,
analysis.check/stop and review.load/filters as described in their usage guides.
Workspace owns start/stop/disposal; these lifecycle methods are not exposed on
facades. Writes are blocked after closing starts. Resolve pending editor/analysis/
review operations before close. Analysis Stop must reach terminal state first.

`close(id)` acknowledges a checkpoint before freezing timers and submitting default
checkpoint-close. A lost response retains the exact close request. `retryClose(id)`
repeats it; if the actor is gone, fresh recovery must prove the same bytes are saved
or still present in a durable working copy. Missing proof leaves the tab uncertain.
There is no automatic release_local/discard fallback. A checkpoint failure leaves
the tab and actor available for their existing explicit retry/recovery path.

`await closeAll()` is the host shutdown handshake. Do not terminate the host on a
rejection or assume browser unload can await it. Recovery previews with no actor
can be closed without changing the stored draft. Final native shell/UI must wire
this handshake; the module does not intercept operating-system shutdown itself.
