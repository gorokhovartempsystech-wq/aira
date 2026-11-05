# D03-18A2 — pinned editor HTTP transport and durable autosave integration

5 November2026. Baseline4b1f1ce, A1 full6897passed. F05/F12. No product-scope change.
Allowed: new src/ara/desktop/client/editor-transport.mjs; new acceptance files
 tests/acceptance/test_docx_client_transport.py, docx_client_transport_cases.mjs,
 docx_client_transport_owned.mjs; docs/d03-18a2-contract.md, docs/d03-18a2-result.md,
 docs/docx-client-transport.md, docs/development-queue.md; .runtime.
No edits to A1, old tests, dependencies, SQL, server protocol/defaults or runner.
If actual integration reveals A1 defect, finish evidence and freeze a narrow separate fix;
do not silently widen this contract. New-test preparation-only corrections retain assertions.

createEditorTransport({origin,sessionToken,documentId,sessionId,fetchImpl?,schedule?,cancel?})
returns an inert async send({path,body}) compatible with createDocxSession. Origin must exactly
match the owned server http://127.0.0.1:1024..65535, canonical port, no suffix/path/query/userinfo.
Token is a lower-case64hex capability from explicit host connection only, retained in closure;
never discover it in environment/browser/storage or emit it in diagnostics. IDs canonical UUID.
Only the exact bound actor /commands,/checkpoint,/save paths; body already serializedUTF8,
8MiB commands/64KiB controls, no query/fragment/encoding/traversal/foreign origins. No metadata,
license, opening, recovery/discard, analysis or download endpoints exposed by this adapter.

Use explicit POSTJSON + AcceptJSON + X-AIRA-Session, redirect:error, credentials:omit,
cache:no-store, referrerPolicy:no-referrer, mode:same-origin. Native fetch supplies Host; no
spoofed Origin/cookie plumbing. Browser binding requires the trusted same-origin renderer;
this is not CORS permission for arbitrary websites. No automatic retry. Keep body byte-for-
byte identical; finite30s total deadline through headers/body, AbortController and bounded
stream read (max65536 decodedbytes and4096chunks), Content-Length agreement when supplied,
fatal UTF8 decoding and JSON.parse syntax, JSON media type (optionalUTF8charset). Reject redirects/unexpectedresponseURL,
opaque responses, oversize/nonJSON/malformed/truncated input. Stop body reads/cancel on errors;
cleanup failures cannot override success or hang a timed-out caller. Late promise completion
cannot replace a returned timeout or run another request. One active call per transport.

Return {status,body}, including bounded parsed403/409/410/413/422/5xx for A1's domain policy;
transport errors are fixed safe codes and contain no origin/token/text/body/underlyingmessage.
Constructor/import performs no I/O or scheduling. Default timeout30000ms exportedconstant;
clock injection is test seam, not a new product duration. Terminal cleanup clears own timer.
Timeout does not assert rollback: A1 retains exact request identity and blocks fresh writes.

Acceptance freezes first; actual red before implementation. Pure real-ESM tests use injected
fetch/streams/clock: inert; correct headers/body; URI/token/path refusals beforeI/O; deadline
beforeheaders/duringbody; abort/cleanup; no redirects; responseURL; media/UTF8/JSON/length/size;
non2xxpreserved; failureprivacy; oneactivecall; cancellationthrows; latecallbackignored.
Native ownedmacOS test runs this ESM + A1 with real globalfetch against licensedLoopbackServer,
one disposableHome/PG/V13. Plain and merged-cell ordinary syntheticDOCX: edit, lostACK/exactretry,
autosave virtual120000deadline but realHTTPCP, currentfile stilloriginal, close/restart fresh
licensecheck, explicit recover validates onecopyoftext, JSsave/export preservesauxparts. Bad
capability rejectswithoutmutatingactor. Sessioncapability suppliedtochildstdin only and never
stored/printed. No userdocuments, secrets or externalnetwork. No actual2minsleep.

Full bash scripts/check.sh with explicit builderRuff, frozen hashes and readonly mainV8counts.
Source/docs complete onlyaftertarget/native/review/regression/fullpass. No nativeWindows,
realML, finalGUI/installer or Wordvisualclaim. Next separate save-before-check admission lane.

Primary reference checked5Nov2026: Fetch request redirect mode / credentials mode
https://fetch.spec.whatwg.org/#concept-request-redirect-mode ; streams reader cancellation
https://streams.spec.whatwg.org/#rs-cancel ; fatalUTF8decode
https://encoding.spec.whatwg.org/#interface-textdecoder . Protocol bounds from local wire.py.
