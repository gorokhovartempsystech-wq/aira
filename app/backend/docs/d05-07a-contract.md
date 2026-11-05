# D05-07A — offline desktop payload builder

5 November 2026. Baseline: verified C5 `fb7bfda`.
F01/F02 independent assembly from explicitly staged runtime/application/frontend/model files.
This builds a verified private payload directory, not an OS installer, signed release or
real-model/UI acceptance. No download, environment/secrets read, asset execution or publication.

## Paths and cycle

Only new src/ara/desktop/build/{__init__,__main__,_models,_inventory,_build}.py and new
tests/acceptance/test_desktop_build.py; this contract/result, docs/desktop-build.md,
docs/development-queue.md and ignored .runtime. No existing source/tests/contracts/SQL/
dependencies/runner/tasks/progress or user files. Reuse unchanged installation parser/verifier
and its Tree helpers, not a relaxed duplicate grammar. Freeze/red, target/review/old installation
regression, full check.sh, frozen hashes/read-only mainV8, selective local commit. New-test
preparation-only fixes may be documented with all frozen assertions retained. Do not edit
source/tests/frozen contract during full gate.

## API and declared inputs

build_payload(source_root, destination, *, version, target, kind, entrypoints,
extra_executables=()) returns frozen BuildReceipt with installation:VerifiedInstallation,
manifest_bytes:bytes and manifest_sha256:str. Hide paths/bytes from repr. Returned metadata
is not an execution capability or authenticity/signature proof.

Root arguments are absolute Paths with no '..', named destination and no actual resolved
source/destination overlap (including an aliased parent). Source is a dedicated caller-prepared
trusted/quiescent staging tree, never an automatic repository/home/archive scan. Destination
parent must exist; destination must not exist, including file/directory/dangling link. Capture
options before work. Exact strings for version/target/kind, exact dict entrypoints with the
D05-03 role keys and valid paths/fixture-null model; extra_executables is an exact tuple of
unique valid relative paths, max32768. Preserve D05-03 target/version/role grammar. Required
executable roles are automatically marked, extra executables explicitly declared. Source mode
alone never assigns a role. Missing/empty/duplicate/incompatible role targets fail before output.

## Inventory and bounded copy

Use no-follow handles and stat observations from the existing installation Tree. Recursively
inventory all files/ancillary libraries, not only entrypoints. Retain case-sensitive exact
names and reject D05-03 case/path collisions. Reject source manifest, links/hardlinks/reparse/
special nodes/empty directories/unsafe names. Bound path depth32, files32768, total nodes65536,
individual file8GiB and total16GiB. Parse a placeholder-hash manifest before output creation
so the old parser enforces shape/role/size/collision and4MiB manifest limits.

Reserve destination by exclusive mkdir0700. No existing output is adopted or overwritten.
Create its exact directories and files exclusively. Copy with <=1MiB reads/writes, handle
short writes, never buffer a whole runtime/model file. Bound reads by declared size plus an
EOF probe; compare actual count and source fstat/initial stamps, hash copied bytes. Set output
POSIX mode0755 for executable records/0644 otherwise (directories0700); source files and their
metadata are not modified. Re-inventory source to detect observed changes before manifest.

Emit canonical sorted JSON manifest LAST by exclusive create. The complete output must pass
unchanged verify_installation with the actual returned external manifest pin and explicit fixture
permission when applicable. Recheck source observations before returning. Equal staged bytes,
options and executable declarations produce identical manifest bytes/pin regardless of source
location, mtime or enumeration order. Timestamp/whole-archive reproducibility is not promised.

This is not an atomic filesystem snapshot or defense against a hostile concurrent directory
owner. Ancestor directories are trusted/quiescent. No portable atomic directory publication is
claimed: this private output is build work, not a public download or active installation.
On failure after reservation, keep partial output, return no receipt and never delete/overwrite
unrelated files. Retry into a fresh destination. Close all opened descriptors even on faults.
Do not load/execute assets to prove platform or model validity. Production-shaped inventory
requires a model-manifest file/hash per D05-03, but inner model/runtime correctness is a separate
gate; fixture remains visibly marked and rejected by default production verification.

## Errors and CLI

BuildError has fixed content-safe codes: validation_error,source_unavailable,source_invalid,
source_changed,destination_exists,destination_unavailable,build_failed. No raw exception/path/
content is printed or retained in its message. An observed change or failed revalidation after
scan cannot return success; final output verification failure maps build_failed.

python -m ara.desktop.build accepts required --source/--destination/--version/--target/--kind/
--roles plus repeated --extra-executable. Explicit roles JSON, kept outside payload, is <=64KiB,
UTF8, bounded depth and duplicate-free, then checked by the same API. Read it without blocking
on a special file. No implicit config/env discovery. Success stdout is only JSON
{manifest_sha256,version,target,kind,files,bytes}. Failure stderr is JSON {code}, exit2 for
validation/CLI input,exit1 for build failure; no traceback/source content. Imported modules
are inert; only the main guard invokes CLI. No dependency or executable installation.

## Acceptance

All assets are synthetic, including production-shaped cases. Actual byte/inventory copy for
all three target profiles and both kinds; fixture rejection; deterministic pin; separate source/
output inodes; executable roles/extras and ancillary/empty files; unchanged source bytes/mtime;
closed inputs, missing model/roles, invalid source nodes and sparse oversize preflight; lexical/
real overlap and existing output preservation; bounded streaming/short writes; source mutation/
new file detection; write/verification fault with no receipt, no destructive cleanup and fresh
retry; inert import; CLI success/content-safe validation/no-overwrite failures. Old installation
parser/file/verifier tests stay unchanged. Native Windows/Word, real weights/frontend, signed
launcher/OS installers and public TLS/release remain separate.
