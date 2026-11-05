# Offline payload assembly

`ara.desktop.build.build_payload` copies an explicitly prepared staging directory into a
fresh private output, writes its inventory manifest last, and verifies the complete result
with the unchanged installation verifier. It never downloads dependencies, discovers a user
archive/project, reads credentials, or executes the copied application/model/runtime.

Supply every runtime library, application module, migration/config asset, frontend asset and
required license notice in the staging directory. All entries must be ordinary files and
nonempty directories under the existing portable path rules. Materializing any trusted input
symlinks and selecting actual dependencies are the caller's preparation work. The builder
copies all staged files; it does not infer a correct dependency closure from entrypoint names.

The `entrypoints` dictionary has the existing nine installation roles: python, application,
postgres, initdb, pg_dump, pg_restore, pg_controldata, frontend, model_manifest. Required binary
roles get executable output permissions; declare additional executables explicitly. The
fixture kind requires a null model_manifest and stays visibly synthetic. Production-shaped
inventory requires that file and its hash, but does not establish its internal schema, inference
quality, executable compatibility or readiness for publication.

From the repository, the CLI can be invoked with explicitly prepared paths:

```sh
PYTHONPATH=src .venv/bin/python -m ara.desktop.build \
  --source /absolute/path/to/staging \
  --destination /absolute/path/to/new-payload \
  --version 0.1.0-test --target macos-arm64 --kind fixture \
  --roles /absolute/path/to/roles.json
```

Keep roles.json outside the staged tree. It contains only the entrypoints object, with relative
paths to actual staged files and a null model_manifest in fixture mode. Repeat
`--extra-executable relative/path` for additional executable files. Supported target labels are
macos-arm64, macos-x86_64 and windows-x86_64; testing a label on macOS is not native Windows proof.

Success prints only JSON with manifest_sha256, version, target, kind, files and bytes. This pin
can be passed to a subsequent trusted packaging/signing stage. It is not an authenticity proof
when obtained from an untrusted adjacent file. The Python API returns the same pin, manifest
bytes and VerifiedInstallation metadata; paths and bytes are hidden in its representation.

The output must not already exist, even as an empty directory or a dangling link. Source and
output cannot overlap. Invalid inputs/roles/structure fail before output creation. Copying is
streamed in chunks no larger than1MiB; every file is hashed, source observations are rechecked,
and the final full inventory is independently verified. Existing input files are not changed.
Equal input bytes/options/executable declarations produce an identical manifest and pin.

On a failure after reserving the output, partial files remain for inspection. There is no
success receipt, automatic deletion or overwrite on retry: use a fresh destination. A private
build directory is not atomic release publication, an active installation or a filesystem
snapshot against a hostile concurrent owner. Source/output ancestors must be trusted and quiet.
CLI validation errors exit2; build failures exit1 with a fixed JSON code and no source details.

The module directory is named `build`, which matches the repository's existing generic Git
ignore rule. Its five source files are explicitly tracked; check/lint this package explicitly
when using tools that honor directory ignore patterns. Setuptools package discovery includes
it. No ignore rules, dependencies or global tool installation were changed in this cycle.

OS installer recipes, trusted immutable launch bundle, code signing, real frontend/model assets
and native acceptance remain separate. See [contract](d05-07a-contract.md) and
[verification](d05-07a-result.md).
