# D03-19C — real Python file IO and recovery

5 November 2026, baseline 2a55890. Current Python host runtime; no GUI framework or
Node dependency selected. Implements NativeFiles for D03-19B coordinator.

Stable bounded reads, canonical explicit destinations, native identity/timestamp/link
checks, private same-directory temporary files, complete write/fsync, atomic replacement
or no-replace link, readback and safe errors. Real-file binding survives through SQL
state. Post-publication uncertainty retains the exact intent for later reconciliation.
Explicit version-guarded Save As retargets the retained payload after a conflict without
re-exporting newer editor contents or modifying the external file. Old writer must be
quiescent before retarget; direct host calls are not an untrusted renderer API.

Verification:
- 16 new native/SQL tests; combined with B: **33 passed**,2warnings,8.08s.
- Actual new Python process reads SQL pending state and writes exact synthetic DOCX.
- Actual file publication followed by simulated failure recovers without rewriting.
- External change/deletion, unsafe links, late destination creation, write/flush/replace
  errors, directory-fsync uncertainty, permission denial and conflict-to-Save-As pass.
- Native exceptions cannot expose injected private path through formatted traceback.
- Three synthetic existing workflow files (new/plain/table) saved, reopened and replaced
  with exact bytes: `.runtime/aira-native-save-demo/run-1qkw81cc/report.json`.
- Failed-close acceptance proves a reused descriptor is not closed twice.
- Full `bash scripts/check.sh`: **7058 passed,45 skipped,79 warnings,24 subtests**,
  1356.04s,exit0. Log `.runtime/d03-19c-full-final.log`;1035 source/test hashes
  unchanged across final gate. Ruff lint/format passed.

An initial full run was interrupted with five old desktop client startup failures.
Another simultaneous project test run (pytest-480) created 30 unattached 56-byte
PostgreSQL segments, exhausting SHMMNI. Segment keys were matched to synthetic
.data18.pending directory inodes, owner checked, creators dead, attachment count zero.
Only those segments were removed; live DB/processes and the older unrelated segment
were preserved. A previously failing client end-to-end test then passed in6.22s.
The parallel run ended, and full gate was restarted in clean conditions. No existing
client tests or startup guards were changed to hide this environment failure.
A subsequent clean run was stopped after1511passes to fix a discovered descriptor
ownership edge: clear local descriptor ownership before close, so a failed close
cannot cause cleanup to close an unrelated reused descriptor. The final run follows
this fix and its new acceptance test.

Limits: no final UI button/picker/IPC wiring and no automatic production desktop V14
upgrade. Services require V14; legacy verified launcher remains V13. Single-owner
host must schedule blocking IO on a worker, preserve pending state, and use exact
confirmed editor revision. Windows native acceptance is pending. Portable compare/
rename cannot exclude a noncooperating external write between check and publication;
ACL/xattr/resource-fork preservation and hostile parent replacement are not claimed.
Manual version history, recents, model answers and real ML were not added.
