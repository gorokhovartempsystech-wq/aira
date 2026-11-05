# DOCX editor Fetch transport

D03-18A2,5 November2026. `createEditorTransport` from
`ara.desktop.client/editor-transport.mjs` supplies the `send` dependency of
[the command/autosave coordinator](docx-client-session.md).

The caller provides a trusted live desktop connection and an already opened actor:

```js
const send = createEditorTransport({
  origin,
  sessionToken,
  documentId: view.document_id,
  sessionId: view.session_id,
});
const client = createDocxSession({view, send, onState});
client.start();
```

`origin` is the exact owned `http://127.0.0.1:<port>` address; the canonical port is
1024..65535. `sessionToken` is the host's32-byte capability represented as64lowercase hex.
The native host passes it directly to its trusted client. This module does not discover a
key, read environment/browser storage, open a license session or log the capability.
Do not put it in URLs, saved configuration, logs or a webpage shared outside the local app.
Use a fresh connection/actor after host restart; a previous origin/token/registry is not
an authentication method for the new host. Browser use requires the trusted same-origin
renderer; this module does not enable cross-origin access or build Anya's frontend bridge.

Construction/import is inert. The returned function accepts only `{path, body}` for the
bound actor's commands/checkpoint/save. It POSTs the already serialized body unchanged.
It cannot open/discard/close actors, submit analysis, fetch arbitrary URLs or download DOCX.
No hidden retry is performed. The coordinator owns uncertain operation identity; a transport
timeout never proves rollback of an accepted backend write.

Each request has a30second total deadline through response reading, an AbortController and
one active request per transport. Requests are bounded to8MiB for commands/64KiB for controls.
Responses are bounded to64KiB decoded bytes and4096chunks, with JSON media type, fatalUTF8
conversion and JSON.parse syntax. Content-Length must match when supplied; encoded responses
other than identity are refused. Only the exact nonredirected response URL is accepted.
Cookies/cache/referrer and redirects are disabled. Stream cancellation and timer cleanup cannot
hang the caller or replace an accepted response; stale callbacks cannot affect another request.
These are transport limits, not a new product document-size limit.

Fetch behavior uses the standard [redirect and credentials controls](https://fetch.spec.whatwg.org/#concept-request-redirect-mode)
and [fatal UTF8 decoding](https://encoding.spec.whatwg.org/#interface-textdecoder).
Parsing validates the transport envelope; the coordinator checks actor acknowledgement and
the backend checks DOCX semantics. Bounded JSON403/409/410/413/422/5xx replies reach the
coordinator for its domain policy. Other errors expose fixed codes without input, capability,
response text or underlying exception messages. Explicit invalid dependency overrides fail
before work; optional fetch/clock seams are for testing, not alternate production addresses.

Acceptance runs actual Node Fetch against an owned licensed macOS fixture desktop, with
plain and merged-cell Word files, lost editACK/exactretry, two-minute virtual-clock checkpoint,
restart/fresh online-license check, explicit recovery and save/export. Untouched DOCX parts
stay exact. An actual local307 redirect does not reach a second server. These checks do not
establish native Windows, browser UI, real ML, Word rendering or release readiness.
