# Coherent selected metadata contexts

`ara.docx_analysis.compatibility_contexts.read_compatibility_contexts(data,
source_sha256=...)` reads styles, table-style visibility proof, sections/settings and
note definitions from one fresh [original-address view](docx-compatibility-view.md).
The fixed bundle profile is `docx-compatibility/selected-contexts-v1`. It accepts
original bytes and exact VisibleLimits; it never accepts a caller-built view or catalog.

Each nested catalog has an explicit MC profile and source-bound canonical hash.
Selected definitions keep their physical XML addresses, including definitions nested
under Choice/Fallback or ProcessContent wrappers. Semantic consumers use cached nodes
from that same view, without separately parsing unselected XML. Source relationships
and package validation still use the original bytes. Missing styles or notes retain
their proper absent catalogs.

`ready` means the four catalogs were built, not that every style or every document
fragment can be analyzed. Individual unresolved style records still require proof when
used. A blocked view or whole catalog yields `blocked`, one safe issue and all four
catalog fields set to None; earlier successful catalogs are not leaked as partial proof.
The public DTO contains no text snapshot, completeness flag, XML or source bytes.

Before allocating DOM trees, aggregate raw limits cover all relevant original parts,
including unused or ambiguous style/settings candidates and discarded MC branches.
Semantic graph and issue limits remain active. The entire nested bundle also has a
streamed manifest-size bound. Limit failures are explicit, without truncation.

Existing public readers keep their original profiles and behavior. The private prepared
source/view bundle is a composition aid for the next whole-story reader; it is not a
caller capability and does not enable application admission or editing/export by itself.
See [the cycle contract](d03-17a2b5c2b-contract.md).
