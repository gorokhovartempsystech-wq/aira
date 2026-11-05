"""Local document drafts; importing this package performs no external I/O."""

from ara.drafts.schemas import DraftSnapshot
from ara.drafts.storage import read_draft, save_draft

__all__ = ["DraftSnapshot", "read_draft", "save_draft"]
