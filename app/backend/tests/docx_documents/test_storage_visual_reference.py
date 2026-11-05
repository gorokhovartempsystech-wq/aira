"""Bind persisted rich DOCX bytes to the exact reviewed D02-04 render input."""

from dataclasses import replace
from hashlib import sha256

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ara.docx_documents import get_docx, import_docx, save_docx
from ara.docx_package.ranges import RangeEdit, TextPosition, export_docx_ranges
from ara.docx_package.session import DocxSession
from tests.docx_documents.test_storage_edges import apply_migrations as apply_migrations
from tests.docx_documents.test_storage_edges import empty_pg_engine as empty_pg_engine
from tests.docx_documents.test_storage_edges import pg_engine as pg_engine
from tests.docx_documents.test_storage_edges import runtime as runtime
from tests.docx_session.test_visual_reference import FIXTURE, RENDERED_HASH, SOURCE_HASH, _spans


def test_rich_storage_recovery_matches_exact_reviewed_render_bytes(runtime):
    from uuid import uuid4

    original = FIXTURE.read_bytes()
    assert sha256(original).hexdigest() == SOURCE_HASH
    first = import_docx(
        runtime, document_id=uuid4(), title="Reviewed synthetic DOCX", data=original
    )
    session = DocxSession(first.current_data)
    spans = _spans(session.snapshot().projection)
    first_span, second_span = spans[(0, 4, 1, 1)], spans[(0, 4, 2, 0)]
    cell, link = spans[(0, 10, 5, 1, 1, 1, 1)], spans[(0, 14, 1, 0, 1)]
    edits = (
        RangeEdit(
            TextPosition(first_span.anchor, len("stable ")),
            TextPosition(second_span.anchor, len(" even when")),
            "canonical type even when",
            "device type whenever",
        ),
        RangeEdit(
            TextPosition(cell.anchor, len("Kitchen ")),
            TextPosition(cell.anchor, len(cell.text)),
            "warmth",
            "heating",
        ),
        RangeEdit(
            TextPosition(link.anchor, 0),
            TextPosition(link.anchor, len("Synthetic")),
            "Synthetic",
            "Updated",
        ),
    )
    edited = session.apply(edits, expected_revision=0)
    reference = export_docx_ranges(original, edits)
    assert edited.data == reference
    assert sha256(reference).hexdigest() == RENDERED_HASH
    saved = save_docx(
        runtime,
        document_id=first.document_id,
        expected_storage_revision=first.storage_revision,
        data=edited.data,
    )
    assert saved.original_data == original and saved.original_sha256 == SOURCE_HASH
    assert saved.current_data == reference and saved.current_sha256 == RENDERED_HASH
    assert saved.storage_revision == 2
    assert session.snapshot().revision == 1 and session.snapshot().is_dirty

    new_engine = create_engine(runtime.engine.url, poolclass=NullPool, hide_parameters=True)
    try:
        fresh_runtime = replace(runtime, engine=new_engine)
        recovered = get_docx(fresh_runtime, document_id=saved.document_id)
        assert recovered == saved
        reopened = DocxSession(recovered.current_data).snapshot()
        assert reopened.data == reference
        assert (reopened.revision, reopened.is_dirty, reopened.undo_depth, reopened.redo_depth) == (
            0,
            False,
            0,
            0,
        )
        assert all(
            span.anchor.source_sha256 == RENDERED_HASH
            for span in _spans(reopened.projection).values()
        )
        assert (
            import_docx(
                fresh_runtime,
                document_id=first.document_id,
                title=first.title,
                data=original,
            )
            == saved
        )
    finally:
        new_engine.dispose()
