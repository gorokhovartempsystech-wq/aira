# V14 owned desktop profile for file persistence

5 November 2026. D03-19D adds an explicit profile to the existing programmatic
fixture desktop; it does not select a GUI or replace fixture ML/licensing transport.

```python
from dataclasses import replace
# existing_config is an already validated FixtureConfig.
config = replace(existing_config, schema_revision="0014_docx_file_states")
# desktop = FixtureDesktop(config); desktop.start(); wait for ready...
```

Default remains V13 for compatibility with existing clients. New V14 home installs the
exact V14 schema, seeds existing identities, issues a V14 receipt and pins every
borrowed database connection to that receipt. Existing V13 home upgrades through the
owned backup/transaction/ready-receipt mechanism before application services start.
A failure before SQL commit leaves the old schema; a failure after commit reconciles
the journal/ready receipt on retry. Original documents and backup are retained.

Low-level explicit configuration:
- `SchemaPreparation(..., revision="0014_docx_file_states")` for a fresh V14 schema
  or verification of an already prepared V14 home.
- `UpgradePreparation(..., target_revision="0014_docx_file_states")` for V13→V14.
- `bind_database` verifies the issued receipt's exact revision, not an arbitrary head.

Only V13 and V14 targets are admitted. Defaults retain the V12→V13 upgrade. V12→V14
in one jump is deliberately refused: prepare V13 with the existing profile first.
An old V13 profile does not adopt an existing V14 database silently. Do not change
Alembic rows or receipt JSON by hand to work around these checks.

Use the [file state service](d03-19b-backend-files.md) and
[Python native adapter](d03-19c-native-files.md) from the trusted host with its issued
DocumentRuntime. The host must own the data-home and quiesce native writes before
shutdown/releasing ownership. Native file operations are programmatic host calls,
not path-taking HTTP endpoints. The UI must still pass an acknowledged editor save
before preparing a file write, compare saved-content receipt against current edits,
and present missing/changed-file choices. Private session fields used by acceptance
are not a supported renderer API.

Native acceptance covers fresh V14 launch/reopen, exact saved DOCX and association,
V13 document retained through a real pg_dump-backed upgrade, before-commit and
post-commit/pre-ready injected failure followed by restart, unsupported target and
old-profile refusal. Existing V13 tests remain unchanged.

Final picker/IPC/button wiring, Windows-native acceptance, production TLS/license
service, actual ML pack and signed distribution remain outside this profile test.
