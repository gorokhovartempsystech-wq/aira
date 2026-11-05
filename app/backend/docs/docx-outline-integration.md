# Outline checks in the owned fixture desktop

D03-17A2b7B connects the [direct outline reader](docx-visible-outline.md) to source-proven
review3, storage, native fixture2 processing, presentation3 and persisted hides. It is an
explicit programmatic fixture mode, not a real model or a shipped GUI.

```python
from dataclasses import replace
from ara.desktop.composition import FixtureDesktop

config = replace(existing_config, analysis_mode="outline_fixture")
desktop = FixtureDesktop(config)
```

Construction is inert; the existing explicit startup/license/owned PostgreSQL lifecycle
still applies. Only `legacy_fixture`, `structured_fixture` and `outline_fixture` are accepted.
The default remains legacy. The outline mode selects a fixed owned Supervisor and the existing
native review2 transport; it cannot load a caller-selected algorithm or dynamically named model.
Use the existing [desktop structured guide](desktop-structured-review.md) for lifecycle/API
setup, with the mode and nested versions described here. Native owned composition was exercised
on macOS; portable Windows child-body checks do not prove native Windows startup/cleanup.

Every new outline-mode check uses `docx-analysis/final-visible-direct-outline-v1` and
`docx-review/3`, including simple files. Source bytes, revision, exact snapshot, execution spec
and validated reply/result are persisted in the unchanged storage format/schema. Retrying or
replaying an already accepted check retains its original source profile and exact manifest,
even after the current document changes. Previously accepted review1 and review2 remain
supported by the fixture2 path; no historical result is silently upgraded.

Public `docx-review-view/3` retains the full list/note context even when filters or hides leave
no visible findings. Generated labels have level/ordinal/format/source provenance, while
findings cite only real text. Hidden items do not change the original no-findings flag. Private
stored provenance and dismissal keys stay outside the public view. The outer HTTP/1 routes
and envelopes are unchanged; their nested metadata now lists all three supported versions.
Full standalone shapes are [review3](../contracts/docx-review-v3.json) and
[view3](../contracts/docx-review-view-v3.json). XML/source reproof remains authoritative;
JSON shape alone cannot validate a label or a claimed quote.

Same-source hides survive restart/retry. Across edits, a hide transfers only when literal and
structural correspondence is proved. Changed counters, list definitions, labels, literal text,
ancestors or ambiguous context can make the finding visible again. Distant ordinary text edits
can retain a hide. A mode change to a different source profile does not transfer historical
hides; their original decisions remain stored. Label/suffix work counts against codec and hide
resolution limits in addition to literal text.

Synthetic acceptance covers imported nested Roman/decimal context, exact two-slice literal
quotes around hidden runs, native stop/restart, retries of all3 profiles, and the real owned
Home/PG/loopback/license sequence: import/check/hide/full close/new online grant/retry/show/exact
DOCX export. It also checks a distant edit followed by a changed literal, corrupt rehashed
records, mixed wire/profile pairs, generated-label fake evidence and unchanged old byte probes.
All fixture output explicitly states that the real model did not run. Letter/inherited/picture
numbering and other reader gates, native Word visual checks, real model assets, Anya's UI,
Windows native acceptance and signed installers remain separate work.
