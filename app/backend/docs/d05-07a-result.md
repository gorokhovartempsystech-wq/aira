# D05-07A — offline desktop payload builder

5 November 2026. Baseline `fb7bfda`, freeze `a10b234`. Six synthetic staged shapes were
preflighted against the unchanged installation parser before freezing. Red **55 failed /0.91s**;
first implementation **55 passed /0.95s**. Review added four cases for a competing destination,
descriptor cleanup, captured options and a failed CLI output stream. The latter prompted fixed
CLI error sanitization. Final target **59 passed /0.50s**. All original frozen acceptance bytes
remain an exact prefix; no preparation correction or weakened assertion.

Three-file old installation parser/files/edge regression: **86 passed,1 skipped /8.81s**;
the skip is the existing native Windows installation gate. New modules are pure at import,
copy only an explicit staged tree, validate roles/limits before output, create exclusively,
stream/hash complete ancillary inventory, detect observed source changes, write manifest last
and revalidate the whole output. Partial failures retain output without a success receipt or
destructive cleanup. A CLI exposes only the pin/summary or fixed error code.

The existing generic build/ ignore pattern also matches the new package. Five exact source
files were explicitly added to Git; normal recursive Ruff excludes this directory, so the
full gate wrapper additionally checks/formats it explicitly. Setuptools discovery with the
already bundled runtime confirms ara.desktop.build is included. The project venv lacks
setuptools; no dependency was installed, and no wheel/native installer build is claimed.

`bash scripts/check.sh`: **6469 passed,45 skipped,79 warnings,24 subtests passed /835.09s**,
exit0; recursive Ruff892 files plus explicit check/format of the five builder modules.
Pre/post976 hashes match;969 prior frozen files unchanged, no old source/tests/contracts/SQL/
dependency changes. Readonly mainV8 schema/revision/counts match C5; no row content read.
Cycle complete. All executable/model/UI test data remain synthetic; actual installers,
trusted launch/signing and real assets remain separate. Next DOCX work is multilevel numbering,
with source semantics established before implementation and separate application integration.
