"""Join, numbering and budget transitions across different command families."""

from ara.docx_package.boundaries import JoinParagraphs, SplitParagraph
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.session import DocxSession, SessionLimits
from ara.docx_package.structure import InsertParagraph


def test_split_join_format_undo_restores_exact_numbering_packages():
    raw = create_docx((NewParagraph("Item one", "numbered"), NewParagraph("Item two", "numbered")))
    session = DocxSession(raw)
    p = session.snapshot().projection.blocks[0]
    divided = session.apply_boundary(SplitParagraph(p.anchor, p.text, 4), expected_revision=0)
    a, b = divided.projection.blocks[:2]
    joined = session.apply_boundary(
        JoinParagraphs(a.anchor, b.anchor, a.text, b.text), expected_revision=1
    )
    p = joined.projection.blocks[0]
    styled = session.apply_formats(
        (ParagraphFormat(p.anchor, p.text, "ListBullet", "bullet"),), expected_revision=2
    )
    assert styled.undo_depth == 3
    assert session.undo(expected_revision=3).data == joined.data
    assert session.undo(expected_revision=4).data == divided.data
    assert session.undo(expected_revision=5).data == raw
    assert session.redo(expected_revision=6).data == divided.data
    assert session.redo(expected_revision=7).data == joined.data
    assert session.redo(expected_revision=8).data == styled.data


def test_history_eviction_keeps_latest_cross_family_position_and_saved_digest():
    raw = create_docx((NewParagraph("First"),))
    session = DocxSession(raw, session_limits=SessionLimits(max_history_states=2))
    p = session.snapshot().projection.blocks[0]
    inserted = session.apply_structure(
        (InsertParagraph(p.anchor, p.text, ("Second",)),), expected_revision=0
    )
    session.mark_saved(expected_revision=1)
    p = inserted.projection.blocks[0]
    formatted = session.apply_formats(
        (ParagraphFormat(p.anchor, p.text, "Heading1"),), expected_revision=1
    )
    assert formatted.undo_depth == 1
    undone = session.undo(expected_revision=2)
    assert undone.data == inserted.data and not undone.is_dirty
    assert undone.undo_depth == 0 and undone.redo_depth == 1
    assert session.redo(expected_revision=3).data == formatted.data
