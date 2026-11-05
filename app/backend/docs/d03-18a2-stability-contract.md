# D03-18A2-S — request-local Word review verification

5 November 2026. Authorized by Nikita's explicit request to fix the Word timeout
and continue the remaining integration cycles. This narrow fix is separate from
A2's frozen transport contract. No changes to old acceptance, timeout, SQL,
runner, dependencies, public protocol or product scope.

Observed profiling: one ordinary Word restore costs about 1.1 seconds; review
with hidden findings repeats it four times (4.427 seconds before HTTP overhead).
Use request-local proof reuse only for the exact immutable source/attempt/result
objects already admitted by load_inputs. Every distinct origin must still undergo
full restore_result validation. No process/global/document-hash cache, no reuse
across requests, threads, errors or custom codec limits. Clear on every exit.

Allowed: new private storage_codec/_verification.py; wrapper in _records.py;
request scope in docx_review_api/_view.py; new acceptance test; this contract,
result and development-queue documentation; ignored diagnostic files.

Acceptance: one full validation per exact origin in a scope; standalone calls
still verify; custom limits still enforce; corrupt new records rejected; failed
validation not cached; nested/exception/thread boundaries cannot reuse proof.
Existing owned Word retry/hide/export test and full scripts/check.sh must pass.
