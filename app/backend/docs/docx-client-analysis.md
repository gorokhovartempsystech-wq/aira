# Saved-version analysis client

D03-18A3, 5 November 2026. Inert ESM modules in `ara.desktop.client`.
Use the live host's trusted origin/capability, never discover credentials in storage.

```js
const send = createAnalysisTransport({origin, sessionToken, documentId});
const analysis = createAnalysisSession({documentId, editor, send, onState: renderAnalysis});
await analysis.check(); // acknowledged editor.save(), then admission
```

`editor` is the single existing `createDocxSession` actor. Route all UI editing through
that actor; disable new editing while save/admission is busy. `check()` saves the current
version. It must not be replaced by `retryAnalysis()`, which checks the old run's source.

- `status()` returns detached state, receipt, Stop intent and action availability.
- `retrySave()` repeats the actor's uncertain save, then submits its confirmed version.
- `retryAdmission()` repeats the exact serialized admission request/key after uncertainty.
- `refresh()` reads the known receipt. Normal waiting polls every 250ms. Network or
  scheduling errors stop automatic polling; explicit refresh/retry recovers it.
- `stop()` has an independent HTTP lane, even when a poll is pending. A request to stop
  is not a cancelled outcome. Only terminal server metadata establishes the outcome;
  already committed success may win. Late responses cannot regress terminal state.
- `retryAnalysis()` starts a new run for the completed old source, without another save.
- `dispose()` clears timers and prevents late replies from creating new admissions.

Metadata is bound to document, request, run and confirmed source revision/hash. The
backend owns the five-minute deadline; a 30-second HTTP deadline is a network error,
not a fabricated terminal analysis outcome. `fixture` must remain visible in the UI.
This module does not fetch result bodies, map findings to RAM or provide final UI;
those remain the next integration cycle. The real model package is still absent.
