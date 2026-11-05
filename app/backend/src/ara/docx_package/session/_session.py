"""Sequential, atomic in-memory commands over exact DOCX package bytes."""

from dataclasses import dataclass, fields, replace
from hashlib import sha256
from typing import TYPE_CHECKING

from .. import DocxError, DocxLimits
from ..projection import ProjectionError, ProjectionLimits, project_docx
from ..ranges import RangeEdit, RangeLimits, export_docx_ranges
from ._models import SessionError, SessionLimits, SessionSnapshot

if TYPE_CHECKING:
    from ..boundaries import BoundaryLimits, JoinParagraphs, SplitParagraph
    from ..formatting import FormatLimits, ParagraphFormat
    from ..structure import DeleteParagraph, InsertParagraph, StructureLimits


def _copy_limits(value, cls, error):
    if value is None:
        return cls()
    if type(value) is not cls:
        raise error("invalid_input")
    # Reconstruct to validate even objects damaged via object.__setattr__ or
    # __delattr__, and to detach caller-owned frozen DTOs from the session.
    return cls(**{item.name: getattr(value, item.name, None) for item in fields(cls)})


@dataclass(frozen=True, slots=True, repr=False)
class _State:
    data: bytes
    revision: int
    undo: tuple[bytes, ...]
    redo: tuple[bytes, ...]
    saved_digest: bytes


class DocxSession:
    """Edit an open DOCX in memory; callers serialize commands for one session.

    Undo/redo retain exact packages, not replayable text operations. Saving is
    only an acknowledgement of a successful external write, never persistence.
    Returned projections are rebuilt and never stored in the internal state.
    """

    __slots__ = ("_limits", "_projection_limits", "_session_limits", "_state")

    def __init__(
        self,
        data: bytes,
        *,
        limits: DocxLimits | None = None,
        projection_limits: ProjectionLimits | None = None,
        session_limits: SessionLimits | None = None,
    ) -> None:
        self._limits = _copy_limits(limits, DocxLimits, DocxError)
        self._projection_limits = _copy_limits(projection_limits, ProjectionLimits, ProjectionError)
        self._session_limits = _copy_limits(session_limits, SessionLimits, SessionError)
        project_docx(data, limits=self._limits, projection_limits=self._projection_limits)
        self._check_size(data)
        self._state = _State(data, 0, (), (), sha256(data).digest())

    @classmethod
    def restore(
        cls,
        data: bytes,
        *,
        saved_sha256: str,
        limits: DocxLimits | None = None,
        projection_limits: ProjectionLimits | None = None,
        session_limits: SessionLimits | None = None,
    ) -> "DocxSession":
        """Recover working bytes and a caller-verified saved digest, with no history."""
        if (
            type(saved_sha256) is not str
            or len(saved_sha256) != 64
            or any(c not in "0123456789abcdef" for c in saved_sha256)
        ):
            raise SessionError("invalid_input")
        restored = cls(
            data, limits=limits, projection_limits=projection_limits, session_limits=session_limits
        )
        restored._publish(replace(restored._state, saved_digest=bytes.fromhex(saved_sha256)))
        return restored

    def _check_size(self, data: bytes) -> None:
        if len(data) > self._session_limits.max_history_bytes:
            raise SessionError("session_limit_exceeded")

    def _retained_packages(self) -> tuple[bytes, ...]:
        state = self._state
        return (state.data, *state.undo, *state.redo)

    def _check_revision(self, expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise SessionError("invalid_input")
        if expected_revision != self._state.revision:
            raise SessionError("stale_revision")

    def _snapshot(self, state: _State) -> SessionSnapshot:
        projection = project_docx(
            state.data, limits=self._limits, projection_limits=self._projection_limits
        )
        return SessionSnapshot(
            revision=state.revision,
            data=state.data,
            projection=projection,
            is_dirty=sha256(state.data).digest() != state.saved_digest,
            undo_depth=len(state.undo),
            redo_depth=len(state.redo),
        )

    def _publish(self, state: _State) -> SessionSnapshot:
        # Preparing even the returned DTO may fail. Commit a single state only
        # after every operation that can fail has completed successfully.
        snapshot = self._snapshot(state)
        self._state = state
        return snapshot

    def snapshot(self) -> SessionSnapshot:
        """Return an independent view without changing the session."""
        return self._snapshot(self._state)

    def apply(
        self,
        edits: tuple[RangeEdit, ...],
        *,
        expected_revision: int,
        range_limits: RangeLimits | None = None,
    ) -> SessionSnapshot:
        """Validate and apply one range batch, retaining history only on change."""
        self._check_revision(expected_revision)
        state = self._state
        data = export_docx_ranges(
            state.data,
            edits,
            limits=self._limits,
            projection_limits=self._projection_limits,
            range_limits=range_limits,
        )
        return self._accept_change(data)

    def apply_boundary(
        self,
        command: "SplitParagraph | JoinParagraphs",
        *,
        expected_revision: int,
        boundary_limits: "BoundaryLimits | None" = None,
    ) -> SessionSnapshot:
        """Apply one split/join as one exact, reversible history position."""
        self._check_revision(expected_revision)
        from ..boundaries import export_boundary

        data = export_boundary(
            self._state.data,
            command,
            limits=self._limits,
            projection_limits=self._projection_limits,
            boundary_limits=boundary_limits,
        )
        return self._accept_change(data)

    def apply_structure(
        self,
        commands: "tuple[InsertParagraph | DeleteParagraph, ...]",
        *,
        expected_revision: int,
        structure_limits: "StructureLimits | None" = None,
    ) -> SessionSnapshot:
        """Apply an atomic insertion/deletion batch to the shared history."""
        self._check_revision(expected_revision)
        from ..structure import export_structure

        data = export_structure(
            self._state.data,
            commands,
            limits=self._limits,
            projection_limits=self._projection_limits,
            structure_limits=structure_limits,
        )
        return self._accept_change(data)

    def apply_formats(
        self,
        formats: "tuple[ParagraphFormat, ...]",
        *,
        expected_revision: int,
        format_limits: "FormatLimits | None" = None,
    ) -> SessionSnapshot:
        """Apply an atomic style/list batch without separating text history."""
        self._check_revision(expected_revision)
        from ..formatting import export_formats

        data = export_formats(
            self._state.data,
            formats,
            limits=self._limits,
            projection_limits=self._projection_limits,
            format_limits=format_limits,
        )
        return self._accept_change(data)

    def _accept_change(self, data: bytes) -> SessionSnapshot:
        """Prepare the shared history transition and response before publishing."""
        state = self._state
        if data == state.data:
            return self._snapshot(state)

        self._check_size(data)
        undo = state.undo + (state.data,)
        retained_bytes = len(data) + sum(len(item) for item in undo)
        oldest = 0
        while (
            len(undo) - oldest + 1 > self._session_limits.max_history_states
            or retained_bytes > self._session_limits.max_history_bytes
        ):
            retained_bytes -= len(undo[oldest])
            oldest += 1
        return self._publish(
            _State(data, state.revision + 1, undo[oldest:], (), state.saved_digest)
        )

    def undo(self, *, expected_revision: int) -> SessionSnapshot:
        """Restore the latest undo position exactly; revisions keep increasing."""
        self._check_revision(expected_revision)
        state = self._state
        if not state.undo:
            raise SessionError("nothing_to_undo")
        return self._publish(
            _State(
                state.undo[-1],
                state.revision + 1,
                state.undo[:-1],
                state.redo + (state.data,),
                state.saved_digest,
            )
        )

    def redo(self, *, expected_revision: int) -> SessionSnapshot:
        """Restore the latest redo position without re-exporting its package."""
        self._check_revision(expected_revision)
        state = self._state
        if not state.redo:
            raise SessionError("nothing_to_redo")
        return self._publish(
            _State(
                state.redo[-1],
                state.revision + 1,
                state.undo + (state.data,),
                state.redo[:-1],
                state.saved_digest,
            )
        )

    def mark_saved(self, *, expected_revision: int) -> SessionSnapshot:
        """Acknowledge externally saved current bytes, without performing I/O."""
        self._check_revision(expected_revision)
        state = self._state
        return self._publish(replace(state, saved_digest=sha256(state.data).digest()))
