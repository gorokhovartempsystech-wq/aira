# D03-18A2-S — Word review latency completed

5 November 2026. Implementation removes repeated full validation of the exact same
immutable origin records within one synchronous HTTP review. Every distinct origin
still undergoes complete codec validation. No global/hash cache or persistence;
custom limits, different objects, new requests and other threads cannot reuse proof.
Nested scopes isolate their proof; exceptions and exit clear it, including contexts
copied before exit. Old tests and their five-second timeout remain unchanged.

Diagnostic before: full restore approximately 1.1s, four restores in review 4.427s.
After: ordinary review approximately 1.1–1.3s; review after retry with a hidden
finding's distinct old origin 2.308s. Measurements are local observations, not a
performance SLA. The existing Word HTTP suite plus first three proof-boundary tests
passed: 8 passed, 2 warnings, 169.87s. Four final focused proof tests passed in 27.91s.
Initial two tests failed red with missing private implementation, 7.54s.

Only two prior source files differ from the 1,071-entry A2 frozen-input manifest:
storage_codec/_records.py and docx_review_api/_view.py, authorized by this fix's
contract. All old tests, runner, dependencies and migrations retain their hashes.
Read-only main database schema/count snapshot matches the previous baseline.

Full `bash scripts/check.sh` passed: **6938 passed, 45 skipped, 79 warnings,
24 subtests, 1300.87s, exit 0**. Main schema/count snapshot unchanged after the run.
A2 full acceptance and this stability fix are now closed. Real model, final GUI, native Windows and visual Word compatibility
remain external gates. The current scenario uses explicitly labelled fixtures.
