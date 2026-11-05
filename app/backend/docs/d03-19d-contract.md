# D03-19D — opt-in V14 owned desktop schema and upgrade

5 November 2026. Continue after C gate/commit. Independent of GUI/model results.
Scope: explicit schema_revision=V14 on fixture desktop, schema preparation and database
binding; supported V13->V14 backup/transaction/receipt upgrade using existing owned
machinery. Preserve defaults V13 and legacy V12->V13 behaviour/tests. V12->V14 direct
is not supported: existing V13 preparation is the explicit intermediate step.

Allowed paths: desktop/postgres_schema, postgres_upgrade, database/_connection.py,
composition/_models.py and _wiring.py; new tests/acceptance/test_desktop_file_schema.py;
new cycle docs and existing file handoff/queue. No existing test changes, runner,
main DB migration, arbitrary path HTTP endpoints or GUI framework choice.

Runtime revision selector accepts only V13/V14. It determines target migration,
ready/initializing receipt, exact schema inventory and connection revision probe.
V13 policy still excludes V14 file table and rejects unexpected schema. V14 policy
requires it. Never accept a revision merely because it is the latest in a directory.
Upgrade policy pairs are fixed: V12->V13 default; V13->V14 explicit. Source backup and
journal bind the correct pair and exact original receipt. Unknown commit/publication
outcomes reconcile through the existing durable journal, never a loose version edit.

Acceptance: new owned V14 launch/reopen, existing V13 document retained through V14
upgrade, real file state/save via issued runtime, failure before SQL commit and after
commit/before ready publication then safe restart, invalid target rejection, unchanged
legacy native suite and full scripts/check.sh. Real ML/licensing transport remain
fixtures; final native picker/IPC is not claimed by this task.
