"""Fixed errors and detached process state."""

from dataclasses import dataclass

MESSAGES = {
    "validation_error": "Invalid command input",
    "invalid_handle": "Invalid process-local command",
    "platform_unavailable": "Command ownership is unavailable on this platform",
    "process_busy": "A command still owns this runtime",
    "process_unavailable": "The owned command is unavailable",
    "process_failed": "The owned command did not complete successfully",
    "output_limit": "The command output exceeded its limit",
    "protocol_error": "Invalid private command status",
    "cleanup_unknown": "Command cleanup has not been confirmed",
}


class CommandError(Exception):
    def __init__(self, code="process_unavailable"):
        self.code = code if type(code) is str and code in MESSAGES else "process_unavailable"
        super().__init__(MESSAGES[self.code])


def require(condition, code="validation_error"):
    if not condition:
        raise CommandError(code) from None


@dataclass(frozen=True)
class ProcessView:
    phase: str
    error_code: str | None
    resources_pending: bool
    returncode: int | None
