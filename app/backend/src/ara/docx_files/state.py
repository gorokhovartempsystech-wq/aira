"""Validated private records, independent of native file picker/runtime."""

from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Counter = Annotated[int, Field(ge=1, le=9223372036854775807)]


class Record(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    def __repr__(self):
        return type(self).__name__ + "(<private>)"

    def __str__(self):
        return repr(self)


class Observation(Record):
    path: Annotated[str, Field(min_length=1, max_length=4096, pattern=r"^[^\x00]+$")]
    identity: Annotated[str, Field(min_length=1, max_length=1024)]
    sha256: Hash


class Binding(Record):
    observed: Observation
    saved_revision: Counter


class Intent(Record):
    operation_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    expected_version: Annotated[int, Field(ge=0, le=9223372036854775806)]
    path: Annotated[str, Field(min_length=1, max_length=4096, pattern=r"^[^\x00]+$")]
    previous: Observation | None
    sha256: Hash
    saved_revision: Counter


class State(Record):
    binding: Binding | None = None
    pending: Intent | None = None
    completed: Intent | None = None


@dataclass(frozen=True)
class Snapshot:
    version: int
    state: State = field(repr=False)
    payload: bytes | None = field(default=None, repr=False)

    def dirty_for_file(self, current_sha256: str) -> bool:
        # Caller supplies exact current content hash, not the internal dirty flag.
        if len(current_sha256) != 64 or any(c not in "0123456789abcdef" for c in current_sha256):
            raise ValueError("invalid_hash")
        return self.state.binding is None or self.state.binding.observed.sha256 != current_sha256


def classify(intent: Intent, observed: Observation | None) -> str:
    if observed is not None and observed.path != intent.path:
        return "conflict"
    if observed is not None and observed.sha256 == intent.sha256:
        return "written"
    if observed == intent.previous:
        return "unchanged"
    return "conflict"
