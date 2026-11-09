"""Atomic controller over a forked trusted core and byte-free cursor metadata."""

from copy import copy
from dataclasses import dataclass, replace

from ..boundaries import BoundaryError, JoinParagraphs, SplitParagraph
from ..projection import SourceAnchor
from ..session import DocxSession
from ._models import (
    Caret,
    CaretTarget,
    EditorError,
    EditorSelection,
    EditorSnapshot,
    SelectionTarget,
)


@dataclass(frozen=True, slots=True)
class _Frame:
    position_id: int
    points: tuple


@dataclass(frozen=True, slots=True, repr=False)
class _State:
    core: DocxSession
    current: _Frame
    undo: tuple[_Frame, ...]
    redo: tuple[_Frame, ...]
    next_id: int


def _invalid():
    raise EditorError("invalid_selection")


def _body(snapshot):
    return {p.anchor.path: p for p in snapshot.projection.blocks if p.kind == "paragraph"}


def _selection_points(selection, snapshot):
    if type(selection) is not EditorSelection:
        raise EditorError("invalid_input")
    selection.__post_init__()
    points, paragraphs = [], _body(snapshot)
    for caret in (selection.anchor, selection.focus):
        a = caret.anchor
        if a.source_sha256 != snapshot.projection.source.sha256:
            raise EditorError("stale_selection")
        if a.part_name != snapshot.projection.source.main_part or a.path not in paragraphs:
            _invalid()
        if caret.offset > len(paragraphs[a.path].text):
            _invalid()
        points.append((a.path, caret.offset, caret.affinity))
    return tuple(points)


def _target_points(target, snapshot):
    if type(target) is not SelectionTarget:
        raise EditorError("invalid_input")
    target.__post_init__()
    points = []
    for caret in (target.anchor, target.focus):
        blocks = snapshot.projection.blocks
        if caret.block_index >= len(blocks):
            _invalid()
        paragraph = blocks[caret.block_index]
        if paragraph.kind != "paragraph" or caret.offset > len(paragraph.text):
            _invalid()
        points.append((paragraph.anchor.path, caret.offset, caret.affinity))
    return tuple(points)


def _public_selection(points, document):
    source = document.projection.source
    carets = [
        Caret(SourceAnchor(source.sha256, source.main_part, path), offset, affinity)
        for path, offset, affinity in points
    ]
    return EditorSelection(*carets)


class EditorSession:
    __slots__ = ("_state",)

    def __init__(self, data, *, limits=None, projection_limits=None, session_limits=None):
        core = DocxSession(
            data, limits=limits, projection_limits=projection_limits, session_limits=session_limits
        )
        document = core.snapshot()
        first = next((p for p in document.projection.blocks if p.kind == "paragraph"), None)
        if first is None:
            _invalid()
        point = first.anchor.path, 0, "right"
        self._state = _State(core, _Frame(0, (point, point)), (), (), 1)

    @classmethod
    def restore(
        cls,
        data,
        *,
        saved_sha256,
        selection,
        limits=None,
        projection_limits=None,
        session_limits=None,
    ):
        """Recover a source-bound selection without inventing a base undo frame."""
        core = DocxSession.restore(
            data,
            saved_sha256=saved_sha256,
            limits=limits,
            projection_limits=projection_limits,
            session_limits=session_limits,
        )
        document = core.snapshot()
        points = _selection_points(selection, document)
        restored = cls.__new__(cls)
        restored._publish(_State(core, _Frame(0, points), (), (), 1), document)
        return restored

    def _reply(self, state, document=None):
        document = state.core.snapshot() if document is None else document
        if len(state.undo) != document.undo_depth or len(state.redo) != document.redo_depth:
            raise RuntimeError("Inconsistent editor history")
        selection = _public_selection(state.current.points, document)
        _selection_points(selection, document)
        return EditorSnapshot(document, selection, state.current.position_id)

    def _publish(self, state, document):
        reply = self._reply(state, document)
        self._state = state
        return reply

    def snapshot(self):
        return self._reply(self._state)

    def _retained_packages(self) -> tuple[bytes, ...]:
        return self._state.core._retained_packages()

    def capture(self, selection, *, expected_revision):
        state = self._state
        state.core._check_revision(expected_revision)
        document = state.core.snapshot()
        frame = replace(state.current, points=_selection_points(selection, document))
        return self._publish(replace(state, current=frame), document)

    def _apply(self, method, value, expected_revision, after, limits):
        state = self._state
        state.core._check_revision(expected_revision)
        if method in ("apply", "apply_structure") and after is None:
            raise EditorError("invalid_input")
        before = state.core.snapshot()
        candidate = copy(state.core)
        document = getattr(candidate, method)(value, expected_revision=expected_revision, **limits)
        if method == "apply_boundary":
            source_anchor = value.anchor if type(value) is SplitParagraph else value.left_anchor
            index = next(
                i for i, p in enumerate(before.projection.blocks) if p.anchor == source_anchor
            )
            if type(value) is SplitParagraph:
                point = CaretTarget(index + 1, 0)
            else:
                point = CaretTarget(index, len(before.projection.blocks[index].text))
            points = _target_points(SelectionTarget(point, point), document)
        elif after is None:
            # Format-only operations leave body paths and text coordinates intact.
            points = state.current.points
        else:
            points = _target_points(after, document)
        return self._adopt(state, before, candidate, document, points)

    def _adopt(self, state, before, candidate, document, points):
        if document.revision == before.revision:
            frame = replace(state.current, points=points)
            proposed = replace(state, core=candidate, current=frame)
        else:
            undo = state.undo + (state.current,)
            undo = undo[-document.undo_depth :] if document.undo_depth else ()
            proposed = _State(candidate, _Frame(state.next_id, points), undo, (), state.next_id + 1)
        return self._publish(proposed, document)

    def _collapsed(self, expected_revision):
        state = self._state
        state.core._check_revision(expected_revision)
        anchor, focus = state.current.points
        if anchor[:2] != focus[:2]:
            raise EditorError("unsupported_intent")
        before = state.core.snapshot()
        index = next(i for i, p in enumerate(before.projection.blocks) if p.anchor.path == focus[0])
        return state, before, index, focus[1]

    def enter(self, *, expected_revision):
        from ._intents import prepare_enter

        state, before, index, offset = self._collapsed(expected_revision)
        data, destination = prepare_enter(state.core, before, index, offset)
        from ._typing import seed_after_enter

        data = seed_after_enter(
            state.core, before, data, index, offset, state.current.points[1][2], destination
        )
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        caret = CaretTarget(destination, 0)
        points = _target_points(SelectionTarget(caret, caret), document)
        return self._adopt(state, before, candidate, document, points)

    def insert_table(self, rows, columns, *, expected_revision):
        from ._objects import table

        state, before, index, offset = self._collapsed(expected_revision)
        data, destination = table(state.core, before, index, offset, rows, columns)
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        caret = CaretTarget(destination, 0)
        points = _target_points(SelectionTarget(caret, caret), document)
        return self._adopt(state, before, candidate, document, points)

    def insert_image(self, data, *, alt_text="", expected_revision):
        from ._images import ImageData, insert

        state, before, index, offset = self._collapsed(expected_revision)
        data, destination = insert(state.core, before, index, offset, ImageData(data, alt_text))
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        caret = CaretTarget(destination, 0)
        points = _target_points(SelectionTarget(caret, caret), document)
        return self._adopt(state, before, candidate, document, points)

    def insert_text(self, text, *, expected_revision):
        from ._typing import insert_text, validate_text

        state, before, index, offset = self._collapsed(expected_revision)
        validate_text(text)
        if not text:
            return self.snapshot()
        data = insert_text(state.core, before, index, offset, text, state.current.points[1][2])
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        caret = CaretTarget(index, offset + len(text), "left")
        points = _target_points(SelectionTarget(caret, caret), document)
        return self._adopt(state, before, candidate, document, points)

    def paste_text(self, text, *, expected_revision, paste_limits=None):
        from ._paste import prepare_paste, validate_paste

        state = self._state
        state.core._check_revision(expected_revision)
        anchor, focus = state.current.points
        if anchor[0] != focus[0]:
            raise EditorError("unsupported_intent")
        normalized = validate_paste(text, paste_limits)
        before = state.core.snapshot()
        index = next(
            i for i, p in enumerate(before.projection.blocks) if p.anchor.path == anchor[0]
        )
        lo, hi = sorted((anchor[1], focus[1]))
        if lo == hi and not normalized:
            return self.snapshot()
        old = before.projection.blocks[index]
        if "\n" not in normalized and old.text[lo:hi] == normalized:
            data, destination, offset = before.data, index, lo + len(normalized)
        else:
            data, destination, offset = prepare_paste(
                state.core, before, index, lo, hi, normalized, focus[2] if lo == hi else "right"
            )
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        caret = CaretTarget(destination, offset, "left")
        points = _target_points(SelectionTarget(caret, caret), document)
        return self._adopt(state, before, candidate, document, points)

    def insert_soft_break(self, *, expected_revision):
        from ._typing import insert_soft_break

        state = self._state
        state.core._check_revision(expected_revision)
        anchor, focus = state.current.points
        if anchor[0] != focus[0]:
            raise EditorError("unsupported_intent")
        before = state.core.snapshot()
        index = next(
            i for i, p in enumerate(before.projection.blocks) if p.anchor.path == anchor[0]
        )
        lo, hi = sorted((anchor[1], focus[1]))
        data = insert_soft_break(
            state.core, before, index, lo, hi, focus[2] if lo == hi else "right"
        )
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        caret = CaretTarget(index, lo + 1, "left")
        points = _target_points(SelectionTarget(caret, caret), document)
        return self._adopt(state, before, candidate, document, points)

    def _join_intent(self, expected_revision, previous):
        _, before, index, offset = self._collapsed(expected_revision)
        p = before.projection.blocks[index]
        if offset != (0 if previous else len(p.text)):
            raise EditorError("invalid_selection")
        other_index = index - 1 if previous else index + 1
        if not 0 <= other_index < len(before.projection.blocks):
            return self.snapshot()
        other = before.projection.blocks[other_index]
        if other.kind != "paragraph":
            raise BoundaryError("nonadjacent_paragraphs")
        left, right = (other, p) if previous else (p, other)
        return self.apply_boundary(
            JoinParagraphs(left.anchor, right.anchor, left.text, right.text),
            expected_revision=expected_revision,
        )

    def join_previous(self, *, expected_revision):
        return self._join_intent(expected_revision, True)

    def join_next(self, *, expected_revision):
        return self._join_intent(expected_revision, False)

    def apply_boundary(self, command, *, expected_revision, boundary_limits=None):
        return self._apply(
            "apply_boundary", command, expected_revision, None, {"boundary_limits": boundary_limits}
        )

    def apply(self, edits, *, after, expected_revision, range_limits=None):
        return self._apply("apply", edits, expected_revision, after, {"range_limits": range_limits})

    def apply_structure(self, commands, *, after, expected_revision, structure_limits=None):
        return self._apply(
            "apply_structure",
            commands,
            expected_revision,
            after,
            {"structure_limits": structure_limits},
        )

    def apply_formats(self, formats, *, expected_revision, after=None, format_limits=None):
        return self._apply(
            "apply_formats", formats, expected_revision, after, {"format_limits": format_limits}
        )

    def undo(self, *, expected_revision):
        state = self._state
        candidate = copy(state.core)
        document = candidate.undo(expected_revision=expected_revision)
        proposed = _State(
            candidate, state.undo[-1], state.undo[:-1], state.redo + (state.current,), state.next_id
        )
        return self._publish(proposed, document)

    def redo(self, *, expected_revision):
        state = self._state
        candidate = copy(state.core)
        document = candidate.redo(expected_revision=expected_revision)
        proposed = _State(
            candidate, state.redo[-1], state.undo + (state.current,), state.redo[:-1], state.next_id
        )
        return self._publish(proposed, document)

    def mark_saved(self, *, expected_revision):
        state = self._state
        candidate = copy(state.core)
        document = candidate.mark_saved(expected_revision=expected_revision)
        return self._publish(replace(state, core=candidate), document)
