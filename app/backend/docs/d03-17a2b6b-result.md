# D03-17A2b6b — structured source storage roundtrip

5 November 2026. Baseline `50de930`, frozen contract/acceptance `183dc62`.
Red **35 failed,1 passed /0.81s** (legacy byte comparison already green).
First implementation **36 passed /1.87s**, no frozen-test correction. Review added4
checks: blank list-item/suffix cost for all3 suffix values and note-link/split-fragment
roundtrip plus rehashed note-target forgery. Added missing imports used only by the new
review test; old/frozen function ASTs unchanged. Final targeted **40 passed /2.28s**.
Regression9 files **230 passed /12.69s**, including native old fixture + disposable PG.

Only source change: storage_codec/_records.py selects exactly the old VisibleSnapshot
or new ListSnapshot protocol/builder. Restore validates all record buffers and identities
before choosing a fixed builder, compares full fresh canonical manifest, and validates
attempt/result by the original source. SourceBundle format1, command/execution layout,
SQL/models/dependencies and old v1 bytes unchanged. New profile's reduced custom text
cap includes generated labels/suffixes, including marker-only items within checkable text.
Rehashed profile/manifest/request/result/attempt/context swaps fail atomically. No caller
profile registry or arbitrary builder injection; unsupported DTOs stay rejected.

Actual AIRA-created heading/body/numbered/bullet document roundtrips; original Unicode,
hidden gaps, literal evidence and note-link associations survive restore. Source bytes
unchanged. Both modes remain pure codecs, not proof of worker/model execution or application
admission. Presentation/remapping and native fixture2/runtime must be integrated before
new records become the application default. Fixture empty remains no_findings=false.

947 frozen hashes and943 previous files outside the one hook verified before full gate.
`bash scripts/check.sh`: **6228 passed,45 skipped,77 warnings,24 subtests passed /798.23s**, exit0; Ruff875 files. Post-gate947 hashes match;943 old files outside the one hook unchanged. Readonly mainV8 schema/revision/counts match B6A; no row content read. Cycle complete. Native Windows/Word, actual model and application/runtime/presentation integration remain separate work.
