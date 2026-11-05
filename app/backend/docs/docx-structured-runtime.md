# Structured fixture runtime

`ara.docx_analysis_worker.supervisor.structured_fixture.create_structured_fixture_supervisor`
accepts the same settings/scope/installation/root arguments as the legacy semantic fixture
factory. Construction is inert; explicit `start()` owns the native worker lifecycle.
Existing supervisor submission, Stop, polling and shutdown operations remain applicable.

Saved checks build the direct-lists snapshot from the exact editor SavedTarget. The distinct
fixture2 receives structured review2 input and returns an explicitly synthetic result.
Retries restore the parent's stored profile and source, including legacy visible-main
records; they never rebuild from the current edited document or silently upgrade an old
snapshot. Existing idempotency keys replay their original acceptance across entry points.

Low-level explicit entry points are `ara.docx_analysis_runs.structured.start_saved` and
`retry_run`. Legacy entry points/factories retain their original defaults. There is no
caller-supplied profile registry, executable, engine module or remote endpoint.

The macOS native lifecycle was exercised with disposable PostgreSQL, success/restart,
immediate Stop and both retry profiles. Windows has the same closed review2 child dispatch,
but native Windows execution is still an external gate. This factory does not select itself
in the desktop application. Structured presentation/correspondence must be integrated first.
The real ML package is absent. See [contract](d03-17a2b6c2-contract.md) and
[verification status](d03-17a2b6c2-result.md).
