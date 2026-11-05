"""Content-safe correspondence records and bounded pure operation limits."""

from dataclasses import dataclass, fields


class RemapError(ValueError):
    def __init__(self, code="invalid_input"):
        self.code = (
            code
            if code in ("invalid_input", "corrupt_result", "limit_exceeded")
            else "invalid_input"
        )
        super().__init__(self.code)


def require(value, code="corrupt_result"):
    if not value:
        raise RemapError(code)


@dataclass(frozen=True, slots=True)
class RemapLimits:
    max_paragraphs: int = 10000
    max_findings: int = 10000

    def __post_init__(self):
        require(
            all(
                type(getattr(self, f.name, None)) is int and 1 <= getattr(self, f.name) <= f.default
                for f in fields(self)
            ),
            "invalid_input",
        )


@dataclass(frozen=True, slots=True)
class FindingTransfer:
    previous_finding_id: str
    previous_key: str
    current_finding_id: str
    current_key: str
