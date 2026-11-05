# D03-17A2b5e1 — unlisted template reading

5 ноября 2026. Baseline D2 `99ea44c`, frozen acceptance/contract `0acc07d`.
Red **55 failed /0.51s**. First implementation **41 passed,14 failed /0.61s**.
Two new-test preparation mistakes corrected under the contract's explicit allowance:
source helper returned main XML instead of a package-part dictionary; inherited-hidden
fixture hid the paragraph boundary instead of a character-style run. Assertions are
AST-identical to freeze. Corrected **55 passed /0.58s**; no implementation change needed
for those fixture corrections. Old tests unchanged.

Review added4 tests: Strict versus Transitional aliases, normalized IDs/very long
numbers, unknown-part closure, and source-mapped note story. Strict aliases were narrowed
to the official Strict schema: left/right alignment/tab aliases only Transitional,
Strict center remains admitted; start/end alignment is still outside this profile's
closed subset. This is the namespace intersection of the contract grammar, not a claim
that all Word alignment options are supported. Targeted **59 passed /0.61s**.
Reader/context/table/note/section regression **832 passed /3.20s** across28 files.

Actual create_docx body and three heading styles, empty/Unicode/tab/break documents now
produce complete source-backed snapshots with unchanged bytes. widowControl affects
pagination only. A numbering part is excluded only after bounded closed grammar,
relationship/namespace proof, no reverse style associations, and complete active closure.
Active direct/style/default numbering remains an atomic gate; no generated labels lost.
Shared MC view, original source mapping, inherited run visibility, images/tables/notes
remain. Old readers/profile semantics unchanged; this reader is opt-in, not app admission.

Four old private extension hooks; 911 previous files outside them unchanged. 925 hashes
frozen before full gate. Full `bash scripts/check.sh`: **6095 passed,45 skipped,81 warnings,24 subtests passed /805.63s**, exit0; Ruff857 files. Post-gate все925 hashes совпали;911 old files unchanged вне hooks. Readonly mainV8 schema/revision/counts совпали с D2. Цикл завершён; app admission/native layout/active lists остаются отдельной работой.
