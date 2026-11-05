# D03-17A2b6c5 — explicit structured fixture desktop composition

5 November 2026. Baseline: verified C4 `aed79fb`. F04/F06–F09/F11/F12:
connect source-verified structured review to the existing owned desktop runtime and verify
create/import, editing, persisted hides, full restart, retry and unchanged DOCX export.
This is a synthetic fixture path, not real inference, a GUI or release readiness.

## Allowed changes and verification

Exactly four existing source hooks:
- `src/ara/desktop/composition/_models.py`: final optional `FixtureConfig.analysis_mode`.
- `src/ara/desktop/composition/_wiring.py`: closed mode guard and fixed supervisor selection.
- `src/ara/docx_analysis_api/_wire.py`: nested public result version metadata.
- `src/ara/docx_review_api/_wire.py`: nested public view version metadata.

New `tests/acceptance/test_desktop_structured_review.py`, this contract/result,
`docs/desktop-structured-review.md`, `docs/development-queue.md` and ignored `.runtime`.
No other source, old tests/contracts, SQL/migrations, defaults, routes, dependencies,
runner/tasks/progress or user files. MainV8 remains unchanged. No remote publication.
Freeze/red, target tests, review/regression, full `bash scripts/check.sh`, frozen hashes,
readonly main database comparison and selective local commit. New-test preparation-only
corrections may be documented with frozen assertions retained; no weaker acceptance.
Do not edit implementation/tests/frozen contract during the full gate.

## Explicit selection and ownership

`analysis_mode` is exact `str` in `legacy_fixture`, `structured_fixture`. Default remains
`legacy_fixture`; add the field last so existing positional arguments remain compatible.
Reject every other value with content-safe `DesktopError(validation_error)` during config
construction. Recheck the same closed enum in `Session.start` before opening Home or any
native/DB/network resource, including a manually altered frozen config.

Select the existing `create_structured_fixture_supervisor` only for structured mode, using a
fixed lazy import. Legacy mode resolves its existing factory at call time. No caller-supplied
factory, registry, dynamic module name, subclass or type/ownership bypass. Both factories
issue the same verified Supervisor class. Existing start order, exact issued handles, native
process containment, database binding, licensing, request drain and shutdown stay unchanged.
Constructing FixtureDesktop stays inert. This remains a macOS programmatic composition;
native Windows composition and a user-facing launcher are separate work.

## Public API metadata

Retain existing outer HTTP/1 envelopes, URLs and response types. Nested result metadata
remains an object and requires `schema_version` with enum `docx-review/1`, `docx-review/2`;
nested view similarly declares `docx-review-view/1`, `docx-review-view/2`. Descriptions name
both versions. This is partial version metadata, not a replacement for the complete standalone
contracts or source-backed runtime validation. No runtime schema file loading or dependencies.

## Native acceptance

Tests use separate temporary Home/owned PostgreSQL and synthetic license responses only.
The new config option must be exercised directly, with no supervisor monkeypatch or fallback.
Default construction/inertness and invalid enum types are checked. A forged mode must fail
before Home creation. Existing legacy composition/lifecycle regressions remain unchanged.

Through the real loopback server, document access is denied before activation. Create a blank
document, type text, format a numbered paragraph, save and check it. Require structured review2/
view2, matching full list/note context, fixture2 provenance, literal evidence, no private stored
keys/provenance and no false real no-findings assertion. Hide with revision CAS, fully close
the desktop/owned PG, restart the same Home and perform a fresh online license check. Exact
saved DOCX, result/presentation and preferences must survive. Retry the pinned run, retain
the hide, explicitly show it again and export exactly the saved DOCX bytes.

Import a newly generated AIRA heading/numbered/bullet template and verify both list contexts
survive filtering with an empty visible result; analysis/filtering never change original bytes.
For an imported table containing a list, hide its literal finding; a distant ordinary text edit
preserves the hide after save/recheck, while changing another cell of that table shows it again.
The original stored decision remains intact. Use current projected text-span anchors and an
explicit resulting selection for range edits, per the existing editor contract.

Preparation probes ran before freezing with a scratch-only old-config/factory override to
verify HTTP examples and owned resource cleanup. They do not prove the new config feature and
are not part of committed acceptance. Two preparation mistakes (missing range-edit selection,
paragraph rather than text-span address) were corrected before freeze; all three workflows
then passed. Real weights are absent by the user's instruction; do not imply model quality.
