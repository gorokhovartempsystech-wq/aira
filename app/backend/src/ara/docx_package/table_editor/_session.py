"""Fixed opt-in cell positions and edits, using the existing exact-package history."""

from copy import copy
from dataclasses import replace

from ..editor import EditorError, EditorSession, EditorSnapshot
from ..editor._paste import validate_paste
from ..editor._session import _Frame, _public_selection, _State
from ..editor._typing import validate_text
from ..session import DocxSession
from ._selection import paragraphs, points
from ._typing import change


class TableEditorSession(EditorSession):
    __slots__ = ()

    def __init__(self, data, *, limits=None, projection_limits=None, session_limits=None):
        core = DocxSession(
            data, limits=limits, projection_limits=projection_limits, session_limits=session_limits
        )
        document = core.snapshot()
        first = next((p for p in document.projection.blocks if p.kind == "paragraph"), None)
        if first is None:
            first = next(paragraphs(document.projection), None)
        if first is None:
            raise EditorError("invalid_selection")
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
        core = DocxSession.restore(
            data,
            saved_sha256=saved_sha256,
            limits=limits,
            projection_limits=projection_limits,
            session_limits=session_limits,
        )
        document = core.snapshot()
        selected = points(selection, document)
        restored = cls.__new__(cls)
        restored._publish(_State(core, _Frame(0, selected), (), (), 1), document)
        return restored

    def _reply(self, state, document=None):
        document = state.core.snapshot() if document is None else document
        if len(state.undo) != document.undo_depth or len(state.redo) != document.redo_depth:
            raise RuntimeError("Inconsistent editor history")
        selection = _public_selection(state.current.points, document)
        points(selection, document)
        return EditorSnapshot(document, selection, state.current.position_id)

    def capture(self, selection, *, expected_revision):
        state = self._state
        state.core._check_revision(expected_revision)
        document = state.core.snapshot()
        frame = replace(state.current, points=points(selection, document))
        return self._publish(replace(state, current=frame), document)

    def _cell_selected(self):
        document = self._state.core.snapshot()
        body = {p.anchor.path for p in document.projection.blocks if p.kind == "paragraph"}
        return any(point[0] not in body for point in self._state.current.points)

    def _cell_change(self, text, expected_revision, *, soft_break=False):
        state = self._state
        state.core._check_revision(expected_revision)
        anchor, focus = state.current.points
        if anchor[0] != focus[0]:
            raise EditorError("unsupported_intent")
        before = state.core.snapshot()
        p = next(p for p in paragraphs(before.projection) if p.anchor.path == anchor[0])
        lo, hi = sorted((anchor[1], focus[1]))
        if lo == hi and not text and not soft_break:
            return self.snapshot()
        data = change(state.core, before, p, lo, hi, text, focus[2], soft_break=soft_break)
        candidate = copy(state.core)
        document = candidate._accept_change(data)
        point = p.anchor.path, lo + (1 if soft_break else len(text)), focus[2]
        return self._adopt(state, before, candidate, document, (point, point))

    def insert_text(self, text, *, expected_revision):
        if not self._cell_selected():
            return super().insert_text(text, expected_revision=expected_revision)
        validate_text(text)
        return self._cell_change(text, expected_revision)

    def insert_soft_break(self, *, expected_revision):
        if not self._cell_selected():
            return super().insert_soft_break(expected_revision=expected_revision)
        return self._cell_change("", expected_revision, soft_break=True)

    def paste_text(self, text, *, expected_revision, paste_limits=None):
        if not self._cell_selected():
            return super().paste_text(
                text, expected_revision=expected_revision, paste_limits=paste_limits
            )
        text = validate_paste(text, paste_limits)
        if "\n" in text or "\t" in text:
            raise EditorError("unsupported_intent")
        return self.insert_text(text, expected_revision=expected_revision)

    def _collapsed(self, expected_revision):
        if self._cell_selected():
            self._state.core._check_revision(expected_revision)
            raise EditorError("unsupported_intent")
        return super()._collapsed(expected_revision)
