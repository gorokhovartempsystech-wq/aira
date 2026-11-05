"""Safe metadata errors; no native paths or exception strings cross this boundary."""


class WindowsRuntimeError(Exception):
    def __init__(self, code="runtime_unavailable"):
        self.code = (
            code
            if code
            in (
                "validation_error",
                "platform_unavailable",
                "clock_unavailable",
                "runtime_unavailable",
                "runtime_busy",
                "invalid_handle",
            )
            else "runtime_unavailable"
        )
        super().__init__(self.code)


class LocalResource:
    __slots__ = ("__weakref__",)

    def __copy__(self):
        raise TypeError("process-local resource")

    def __deepcopy__(self, memo):
        raise TypeError("process-local resource")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local resource")

    def __repr__(self):
        return "<process-local resource>"
