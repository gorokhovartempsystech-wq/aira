# Synthetic DOCX control file

`rich-source.docx` was generated for D02-01 on 28 October 2026. It contains synthetic device requirements, not user work artifacts and not an approved AIRA template. The generator used the bundled python-docx runtime; the original and one-page LibreOffice rendering were visually inspected before acceptance was prepared.

The fixture includes headings, bold/italic/underline, numbered and bulleted lists, a table with a horizontally merged cell, an inline PNG, an external hyperlink, a header and a footer with a PAGE field. The hyperlink is test metadata and must never be fetched by the package service.

SHA256: `73009626640400679d2b1a2031c565a964308073aa287067cf39088836176fcd`.

The independent gate verifies byte-identical no-op export and every original ZIP entry. This does not validate editing fidelity or Microsoft Word compatibility; the initial rendering used bundled LibreOffice, not Word. Future changed-document export requires separate visual acceptance.

## word-blockers.docx — D03-20C

Synthetic six-paragraph team example from
`app/frontend/dev/pages/sample-blockers.docx`, PR19 commit
`ad02b9e475ad0dbad53fc9d3f2a12c019ad4564c`. It contains optional hyphens,
a Wingdings check mark and the literal equation `x=2`; no user work archive.
SHA-256: `351a2ece708ea3ec5dccde1b48de25989508e6f145a84e923f9b6c89f0d35fa4`. This is not the unavailable original Word-for-Mac file.
