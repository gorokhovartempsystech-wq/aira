# D03-19D — owned V14 schema and V13→V14 upgrade

5 November 2026, baseline bda08ba. Added explicit schema_revision to fixture desktop,
revision to SchemaPreparation and target_revision to UpgradePreparation. Defaults
preserve V13 and V12→V13. V14 targets only fresh/V13/V14 states; direct V12→V14 refused.

Selected revision drives migration target, exact table inventory, durable ready/intent
receipt and every borrowed connection's revision probe. Fixed supported upgrade pairs
bind the backup and journal to the real source/target; source/current document data
are retained across retries. No arbitrary future head acceptance or receipt rewriting.

Nine new owned macOS tests passed in23.45s: fresh V14 + real DOCX file/state/restart,
V13 document with actual retained backup through upgrade, before-commit and after-commit
interruptions then recovery, four invalid target cases and V13 refusal of V14.
No existing tests changed. Full `bash scripts/check.sh`: **7067 passed,45 skipped,
78 warnings,24 subtests**,1536.73s,exit0. Log `.runtime/d03-19d-full.log`.
All1036 source/test hashes and inventory unchanged across gate; lint/format pass.

[Usage](d03-19d-desktop-files.md). This removes the V14 startup integration gap for a
trusted host opting into this profile. It does not wire native file operations into
renderer buttons or change the default profile silently. Host must quiesce native IO
before releasing its data-home. Real ML/licensing transport remain fixtures; Windows
native/GUI/production distribution are not declared ready.
