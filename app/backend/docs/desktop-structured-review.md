# Structured fixture desktop mode

`FixtureConfig(..., analysis_mode="structured_fixture")` connects the source-verified
structured DOCX path to the existing `FixtureDesktop` composition on macOS. The default
remains `legacy_fixture` for existing callers. Both modes are explicitly synthetic; neither
loads the absent model weights or claims useful requirement analysis.

The config option is a closed enum, not a module name or plugin hook. Unknown values fail
before Home/runtime creation, and startup rechecks the value. Constructors stay inert.
Owned PostgreSQL, schema preparation, database binding, process containment, online licensing
and shutdown retain their existing contracts. Windows native composition is still separate.

Structured mode accepts the fixed direct-lists source profile: existing source-verified
sections, notes, tables, fields, selected compatibility content, supported raster images and
the documented direct decimal/bullet subset. Unsupported structures still produce an explicit
admission failure; this does not establish the complete Word feature matrix.

The existing HTTP endpoints return `docx-review/2` and `docx-review-view/2` inside their
unchanged HTTP/1 envelopes. `document_context` carries list labels and note references separately
from literal quotes. Filtering keeps that context intact. OpenAPI nested objects now identify
both old/new version values; full shapes and source authenticity follow the standalone contracts
and storage validation, not that partial metadata alone.

The native integration tests create a document, type and number a paragraph, save, check and
hide a finding, close the entire runtime and reopen the same Home. A fresh online license check
is required. DOCX bytes, results, filters and hides survive restart; retry uses its pinned source.
Imported AIRA templates retain both bullet/decimal contexts under filters. For an imported
table, a distant edit preserves an eligible hide, while changing a related cell shows it again.
Showing it again does not erase the original decision. Review data is never added to DOCX bytes.

For frontend commands, formatting uses a **paragraph** anchor; `range_edit` uses **text-span**
anchors and an explicit `after` selection. Obtain fresh addresses after each successful change.
The tests compare `/content` only when no competing writer exists; an exact save/export workflow
must still use its SavedTarget route as described in [editor API](docx-editor-api.md).

Native app/UI integration, production model quality, native Windows, Word visual parity and
signed installers/public TLS are not established by this fixture mode. See the
[contract](d03-17a2b6c5-contract.md) and [verification](d03-17a2b6c5-result.md).
