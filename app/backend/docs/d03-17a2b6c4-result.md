# D03-17A2b6c4 — structured dismissal correspondence

5 November 2026. Baseline `255a066`, contract/acceptance freeze `c11f4bc`.
Red:25 failed,25 passed /11.78s. First implementation:49 passed,1 failed /13.78s.
The remaining failure was in new fixture preparation: wrapping the raw main body is rejected
by the existing package grammar before analysis. The generator now wraps individual logical
paragraphs inside the required direct body, retaining every frozen correspondence assertion.
All24 original test function ASTs are unchanged. A new negative test preserves rejection of
the original malformed placement. This uses the contract's preparation-only exception.

The frozen test name/design phrase about a wrapper *above* the body was too broad: public
package admission still requires a direct body. No source-reader change or support for that
placement is claimed. The verified case is compatibility wrappers inside the body; existing
source bounds take precedence over that mistaken design example. The internal frame algorithm
does not depend on direct paragraph children, but cannot override package admission.

After preparation correction:51 passed /14.26s. Review added endnote, header/footer and three
Unicode-label/suffix cases (seven total additions including the invalid-package guard).
The latter initially placed suff after lvlText, violating the existing numbering grammar;
corrected only their XML preparation order. Final targeted:57 passed /16.03s. No implementation
logic correction was needed. Six-file old remapping/resolution/preferences/presentation/HTTP/
native regression:177 passed,3 warnings /76.21s. Old tests unchanged.

New fixed-profile correspondence revalidates both records, groups literal fragments by original
part/paragraph, and binds raw Merkle trees, ancestry, global parts/sections, styled prefixes,
neighbors, numbering semantics and note links. Hash caches/indexes avoid repeated subtree or
incoming-reference scans. Uniqueness and inversion rejection prevent arbitrary matches.
Every shared note parent must correspond. Primary and related evidence both retain the old
semantic signature. Exact-source and legacy behavior/keys remain unchanged. Resolution work
estimates now count generated labels/suffix for the structured profile, with strict bounds.

Cross-source paragraph/historical/wrapped section correspondence remains conservative no-match;
exact-source replay still works. Valid unmatched structures return visible findings rather than
storage corruption. Preferences/results/source are never mutated. No SQL/HTTP/desktop changes.
`bash scripts/check.sh`: **6399 passed,45 skipped,81 warnings,24 subtests passed /823.43s**,
exit0; Ruff890 files. Pre/post967 hashes match;959 prior files outside two hooks unchanged.
Readonly mainV8 schema/revision/counts match C3; no row content read. Cycle complete.
Persistent structured HTTP/desktop integration follows. Real ML, UI/native Windows/Word,
installer/signing/public TLS remain separate gates.
