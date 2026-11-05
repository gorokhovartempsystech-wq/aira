# D03-17A2b7A — source-backed direct multilevel numbering

5 November 2026. Baseline `53a8112`. F06/F11: read explicit main-story levels0–8,
retain generated labels separately from literal spans, and prove mappings against original
DOCX bytes. Pure reader cycle; storage/runtime/desktop integration follows separately.

## Boundaries and gate

New `src/ara/docx_analysis/visible_outline/`,
`tests/acceptance/test_docx_visible_outline.py`, this contract/result,
`docs/docx-visible-outline.md`, queue and ignored `.runtime` only. No existing source, tests,
contracts, schema, dependencies, runner/tasks/progress or user-file changes. No native Word
parity claim, real ML, release or remote publication. MainV8 stays unchanged.

Freeze acceptance, actual red, implement, target/review/old-source regression, full
`bash scripts/check.sh` plus explicit Ruff check/format of `src/ara/desktop/build`, frozen
hash comparison, readonly main database snapshot and selective local commit. New test
preparation-only corrections may be documented while retaining frozen assertions; no weaker
acceptance. No implementation/test/frozen-contract editing during the full gate.

## Fixed API and proof

Expose `OutlineSnapshot`, existing exact `ListItem` record, common visible limits/errors/span
DTOs, `build_outline_snapshot`, `map_outline_spans` and `map_outline_span`. Snapshot profile
is `docx-analysis/final-visible-direct-outline-v1`; NoteSnapshot fields plus tuple lists,
canonical digest. Exact DTO validation precedes source re-derivation for every mapping call,
including an empty request. Previous profiles/types remain unchanged and reject this type.
Invalid source identity, snapshot forgery, budgets and incomplete coverage retain existing
safe error/atomic-empty conventions. Generated labels never become literal source slices.

Reuse the existing closed unbound numbering grammar, raw limits/preflight, selected contexts,
list reader/output/accounting and source-backed main/table/notes/media pipeline. No dynamic
registry or caller-provided algorithm. Direct numPr must explicitly identify main-story
level0–8 and positive numId; numId0 removes numbering. Unsupported inherited/style-linked
numbering and numbered non-main stories retain their gates. Unreferenced definitions do not
consume counters. Unsupported active semantics fail whole snapshot without partial text.

## Counter and label semantics

State is independent per `(numId, level)`, consumed once per retained paragraph, including
blank/hidden literal text; ordinary gaps and cells do not restart it. Initial/restarted value
is effective startOverride, else the effective level start, default0; increments are bounded
by2147483647. A matching replacement lvl replaces the base definition, including defaults;
its anchors identify the replacement, and startOverride provenance is retained separately.
Only the matching level override applies. Undefined active base levels are refused.

Use Word's documented restart behavior: missing lvlRestart on levelK resets after levelK-1
or any higher event; explicit0 never resets; explicitN resets after levelN-1 or any higher.
Read this setting from the abstract level even with replacement lvl (Word ignores the
replacement's lvlRestart). Admit explicit values0..min(K,7); outside this proven range refuse.
Reset only that instance's consumed deeper levels. An actually referenced parent must have
a consumed counter since its last reset; otherwise refuse rather than invent a parent number.
Self-only deep labels do not require unused ancestor counters.

Formats: decimal, bullet, upperRoman, lowerRoman. Numeric templates accept literal text and
unambiguous `%1`..`%9`, at most9 substitutions, never deeper than the current level. Unknown
percent tokens or following digits are refused. Referenced levels must use decimal/Roman;
isLgl forces those known references to decimal. Bullet uses literal lvlText including `%`.
Roman rendering requires positive values, uses greedy subtractive symbols and repeated M
above3999; bound output before repetition. Reject active null markers, hidden numbering rPr,
missing lvlText, letter/none/other formats and unproved symbol-reference interactions.

Conservatively bound labels to31 UTF-16 code units (Word's documented expanded limit), also
retain whole-document/generated/manifest limits. No truncation or giant intermediate strings.
Suffix stays tab/space/nothing, defaulttab, separate from literal text. A frozen exact shape
guard enforces the profile, levels, formats, integer bounds, label and reference budgets;
source re-derivation proves semantic truth beyond that guard.

## Evidence and acceptance

ECMA-376 Part1 §17.9.5/.8/.25/.26 describes replacement levels, defaults and start overrides;
§17.18.59 defines Roman conversion and language-dependent repeated-letter numbering. Letters
are deferred pending effective-language proof, not incorrectly treated as Excel columns.
Primary Word behavior notes:
- [restart](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/140a2cd9-2f26-456d-9760-ae6ecef4e8b5)
- [label limits](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/74f54646-dbe0-40ea-90c9-5ec70107e91d)
- [bullet text](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/9f8357d1-a099-44a3-bc18-88b33bae4eab)

Synthetic source tests cover nested/default/custom/never restart, skipped higher events,
independent instances, replacement/startOverride provenance and restart, Roman/legal/bullet,
all9 levels, blank/hidden items, tables/wrappers/Strict UTF16/images, original literal mapping,
source immutability, malformed/unproved source, atomic failures, counters/text/raw limits,
rehashed forged labels/levels/anchors/ordinals and old-profile rejection. No user archive data.
