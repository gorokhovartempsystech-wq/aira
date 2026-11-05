# Versioned structured DOCX storage

`ara.docx_analysis.storage_codec` accepts exactly the legacy visible-main snapshot and the
new direct-lists snapshot. Existing capture/restore/prepare_attempt/capture_result/restore_result
signatures remain. Saved SourceBundle.format_version=1 describes the unchanged record layout;
profile identifies the source semantics independently. No SQL migration is required or applied.

New records store their full canonical list/note manifest and produce docx-review/2 requests
and results. Legacy records preserve docx-review/1 bytes. Restore starts with strict scalar,
buffer and digest checks, rebuilds the selected snapshot from the original DOCX and compares
its entire manifest. An altered label, link or profile is not authorized by recomputing hashes.
The request/result pair is also source-rederived before any restored envelope is returned.

New attempts retain the saved source profile/revision. RetryCheckCommand can capture the same
snapshot without upgrading it; selecting that behavior in the live retry path is a later
runtime cycle. Unknown versions/profiles fail explicitly; known profile substitution is
corruption. There is no permissive profile registry or context supplied independently of DOCX.

Existing fragment/byte/reply limits remain. For structured sources the custom text cap counts
literal characters plus generated labels and suffixes, including blank list items. Literal
fragment IDs and source slices remain unchanged. A marker-only document is still not checkable.
Private content remains out of record reprs; pure codecs do not open files, DB or network.

This extension alone does not enable the new profile in the application. A distinct executor,
versioned presentation and safe dismissal correspondence must be connected before the desktop
path selects it. Real ML weights remain absent; fixtures cannot claim actual no-findings.
[Contract](d03-17a2b6b-contract.md) and [verification](d03-17a2b6b-result.md) list exact evidence.
