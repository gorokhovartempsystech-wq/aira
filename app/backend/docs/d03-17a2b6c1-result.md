# D03-17A2b6c1 — structured semantic fixture2

5 November 2026. Baseline `ea357f7`, frozen contract/acceptance `22c0940`.
Red **63 failed /0.91s**. First implementation **63 passed /2.15s** with no frozen-test
or implementation corrections. Review added3 cases: duplicate fragment across distinct list
items, marker-only item next to ordinary text, repeated references to one note target.
Final targeted **66 passed /2.25s**. Regression9 files **212 passed /15.76s**, including
old native fixture lifecycle and disposable PG. Frozen function ASTs unchanged; old tests
unchanged. Five extra literal-boundary probes against the baseline fixture source confirmed
byte-identical old output (single char,64 emoji,65 chars,tabs/newlines,Unicode).

New pure fixture2 has distinct model/adapter identities. It accepts exactly structured wire2/
direct-lists and explicit legacy wire1/visible-main, both with fixture2 execution; old fixture1
still accepts only its original identity/pair. Closed context validation checks list/note
shapes, source-bound anchors, associations/uniqueness, strict types and aggregate literal+
generated cost. It selects actual literal text, optionally shows a bounded list-label sample,
and reports structural counts in an explicitly synthetic explanation. No real model runs.

Only old hook extracts request-header, literal-fragment and synthetic-reply helpers; old
public functions pin original constants at call time. No source codec/SQL/schema/native
launcher/supervisor/admission/HTTP changes. Context shape is not source authority: a changed
AttemptBundle is rejected by parent source validation. A reply alone does not attest model
understanding or semantic truth; accurate literal evidence is not a model-quality proof.
Fixture results cannot claim actual no-findings. No implicit files/env/network/ML imports.

953 frozen hashes and946 prior files outside the one hook verified before full gate.
`bash scripts/check.sh`: **6294 passed,45 skipped,81 warnings,24 subtests passed /797.92s**, exit0; Ruff880 files. Post-gate953 hashes match;946 old files outside one hook unchanged. Readonly mainV8 schema/revision/counts match B6B; no row content read. Cycle complete. Native fixture2/source admission, structured presentation/correspondence, actual ML/native Windows/Word/release gates remain separate.
