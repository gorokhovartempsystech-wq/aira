"""Fixed local access failures without request text or capability values."""

_ERRORS = {
    "validation_error": (422, "Invalid local request"),
    "unsupported_media": (415, "Unsupported local request media"),
    "request_too_large": (413, "Local request is too large"),
    "request_timeout": (408, "Local request timed out"),
    "local_busy": (503, "Local request capacity is busy"),
    "route_unavailable": (404, "Local route is unavailable"),
    "access_denied": (403, "Local access is denied"),
    "invalid_handle": (500, "Local access belongs to another runtime"),
    "local_error": (500, "Local operation failed"),
}


class AccessError(Exception):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "local_error"
        self.status, self.message = _ERRORS[self.code]
        super().__init__(self.message)


def fail(code):
    raise AccessError(code) from None


def require(condition, code):
    if not condition:
        fail(code)
