"""Complete immutable save proof; it contains no working package bytes."""

from dataclasses import asdict, dataclass, field
from uuid import UUID

from ara.docx_package.checkpoint import CheckpointMetadata

from ._dto import MAX_REVISION, DocxSummary, StoredDocx, _hash, valid_integer
from .checkpoint_fingerprints import save_identity_fingerprint
from .checkpoint_models import CheckpointSnapshot


def _identity_wire(metadata):
    return {
        "selection": asdict(metadata.selection),
        "origin": {
            "session_id": str(metadata.origin.session_id),
            "session_revision": str(metadata.origin.session_revision),
            "position_id": str(metadata.origin.position_id),
        },
        "pending": {
            "operation_id": str(metadata.pending.operation_id),
            "request_sha256": metadata.pending.request_sha256,
        },
    }


@dataclass(frozen=True, slots=True)
class SaveHandle:
    document_id: UUID
    prepared_checkpoint_revision: int
    base_storage_revision: int
    base_sha256: str
    working_sha256: str
    working_size_bytes: int
    metadata: CheckpointMetadata = field(repr=False)

    def __post_init__(self):
        valid = (
            type(getattr(self, "document_id", None)) is UUID
            and valid_integer(getattr(self, "prepared_checkpoint_revision", None), 2, MAX_REVISION)
            and valid_integer(getattr(self, "base_storage_revision", None), 1, MAX_REVISION)
            and _hash(getattr(self, "base_sha256", None))
            and _hash(getattr(self, "working_sha256", None))
            and valid_integer(getattr(self, "working_size_bytes", None), 1, 33554432)
            and type(getattr(self, "metadata", None)) is CheckpointMetadata
        )
        if valid:
            self.metadata.__post_init__()
            valid = self.metadata.pending is not None and all(
                c.anchor.source_sha256 == self.working_sha256
                for c in (self.metadata.selection.anchor, self.metadata.selection.focus)
            )
        if valid:
            valid = self.request_sha256 == save_identity_fingerprint(
                self.document_id,
                self.prepared_checkpoint_revision,
                self.base_storage_revision,
                self.base_sha256,
                self.working_sha256,
                self.working_size_bytes,
                _identity_wire(self.metadata),
            )
        if not valid:
            raise ValueError("Invalid DOCX save identity")

    @property
    def operation_id(self):
        return self.metadata.pending.operation_id

    @property
    def request_sha256(self):
        return self.metadata.pending.request_sha256


@dataclass(frozen=True, slots=True)
class PreparedSave:
    snapshot: CheckpointSnapshot = field(repr=False)
    handle: SaveHandle = field(repr=False)

    def __post_init__(self):
        if type(self.snapshot) is not CheckpointSnapshot or type(self.handle) is not SaveHandle:
            raise ValueError("Invalid prepared DOCX save")
        self.handle.__post_init__()
        c, h = self.snapshot.checkpoint, self.handle
        if (
            c.phase != "pending"
            or c.document_id != h.document_id
            or c.checkpoint_revision != h.prepared_checkpoint_revision
            or c.base_storage_revision != h.base_storage_revision
            or c.base_sha256 != h.base_sha256
            or c.working_sha256 != h.working_sha256
            or len(c.working_data) != h.working_size_bytes
            or c.metadata != h.metadata
        ):
            raise ValueError("Invalid prepared DOCX save")


@dataclass(frozen=True, slots=True)
class CommittedSave:
    receipt: DocxSummary = field(repr=False)
    document: StoredDocx = field(repr=False)
    handle: SaveHandle = field(repr=False)

    def __post_init__(self):
        if (
            type(self.receipt) is not DocxSummary
            or type(self.document) is not StoredDocx
            or type(self.handle) is not SaveHandle
        ):
            raise ValueError("Invalid committed DOCX save")
        self.handle.__post_init__()
        self.receipt.__post_init__()
        self.document.__post_init__()
        r, d, h = self.receipt, self.document, self.handle
        if (
            r.document_id != h.document_id
            or d.document_id != h.document_id
            or r.storage_revision != h.base_storage_revision + 1
            or r.storage_revision > d.storage_revision
            or r.current_sha256 != h.working_sha256
            or r.current_size_bytes != h.working_size_bytes
            or r.created_at != d.created_at
        ):
            raise ValueError("Invalid committed DOCX save")
        if r.storage_revision == d.storage_revision and (
            r.title,
            r.current_sha256,
            r.current_size_bytes,
            r.updated_at,
        ) != (d.title, d.current_sha256, len(d.current_data), d.updated_at):
            raise ValueError("Invalid committed DOCX save")

    @property
    def current_matches_receipt(self):
        return self.document.storage_revision == self.receipt.storage_revision


@dataclass(frozen=True, slots=True)
class SaveStatus:
    state: str
    document: StoredDocx = field(repr=False)
    handle: SaveHandle = field(repr=False)
    receipt: DocxSummary | None = field(repr=False)
    checkpoint_revision: int | None

    def __post_init__(self):
        if (
            type(self.state) is not str
            or self.state
            not in (
                "ready",
                "conflict",
                "exhausted",
                "committed",
                "committed_outdated",
                "superseded",
            )
            or type(self.document) is not StoredDocx
            or type(self.handle) is not SaveHandle
        ):
            raise ValueError("Invalid DOCX save status")
        self.document.__post_init__()
        self.handle.__post_init__()
        if self.receipt is not None:
            committed = CommittedSave(self.receipt, self.document, self.handle)
            expected = "committed" if committed.current_matches_receipt else "committed_outdated"
            valid = self.state == expected and self.checkpoint_revision is None
        else:
            valid = self.state in ("ready", "conflict", "exhausted", "superseded") and (
                self.checkpoint_revision is None
                or valid_integer(self.checkpoint_revision, 1, MAX_REVISION)
            )
            if self.state != "superseded":
                valid = (
                    valid and self.checkpoint_revision == self.handle.prepared_checkpoint_revision
                )
                base_matches = (self.document.storage_revision, self.document.current_sha256) == (
                    self.handle.base_storage_revision,
                    self.handle.base_sha256,
                )
                exhausted = (
                    self.checkpoint_revision == MAX_REVISION
                    or self.handle.base_storage_revision == MAX_REVISION
                )
                valid = valid and (
                    self.state
                    == (
                        "exhausted"
                        if base_matches and exhausted
                        else "ready"
                        if base_matches
                        else "conflict"
                    )
                )
        if not valid:
            raise ValueError("Invalid DOCX save status")


@dataclass(frozen=True, slots=True)
class FinalizedSave:
    snapshot: CheckpointSnapshot = field(repr=False)
    receipt: DocxSummary = field(repr=False)
    handle: SaveHandle = field(repr=False)

    def __post_init__(self):
        if type(self.snapshot) is not CheckpointSnapshot:
            raise ValueError("Invalid finalized DOCX save")
        self.snapshot.__post_init__()
        CommittedSave(self.receipt, self.snapshot.document, self.handle)
        c, h = self.snapshot.checkpoint, self.handle
        c.__post_init__()
        if (
            c.phase != "working"
            or c.checkpoint_revision != h.prepared_checkpoint_revision + 1
            or c.base_storage_revision != self.receipt.storage_revision
            or c.base_sha256 != h.working_sha256
            or c.working_sha256 != h.working_sha256
            or len(c.working_data) != h.working_size_bytes
            or c.metadata.pending is not None
            or c.metadata.origin != h.metadata.origin
            or c.metadata.selection != h.metadata.selection
            or (
                self.current_matches_receipt
                and c.working_data != self.snapshot.document.current_data
            )
        ):
            raise ValueError("Invalid finalized DOCX save")

    @property
    def current_matches_receipt(self):
        return self.snapshot.document.storage_revision == self.receipt.storage_revision


@dataclass(frozen=True, slots=True)
class DiscardedSave:
    snapshot: CheckpointSnapshot = field(repr=False)
    handle: SaveHandle = field(repr=False)
    receipt: DocxSummary | None = field(repr=False)

    def __post_init__(self):
        if type(self.snapshot) is not CheckpointSnapshot or type(self.handle) is not SaveHandle:
            raise ValueError("Invalid discarded DOCX save")
        self.snapshot.__post_init__()
        self.snapshot.document.__post_init__()
        self.handle.__post_init__()
        c = self.snapshot.checkpoint
        c.__post_init__()
        if (
            c.phase != "empty"
            or c.checkpoint_revision != self.handle.prepared_checkpoint_revision + 1
            or c.document_id != self.handle.document_id
        ):
            raise ValueError("Invalid discarded DOCX save")
        if self.receipt is not None:
            CommittedSave(self.receipt, self.snapshot.document, self.handle)

    @property
    def save_confirmed(self):
        return self.receipt is not None

    @property
    def current_matches_receipt(self):
        return (
            self.receipt is not None
            and self.snapshot.document.storage_revision == self.receipt.storage_revision
        )
