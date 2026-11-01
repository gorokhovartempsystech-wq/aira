"""Strong immutable package references; the registry owns synchronization."""

from ._errors import error


class PackageBudget:
    def __init__(self, maximum):
        self.maximum = maximum
        self.groups = {}

    def reserve(self, token, packages):
        packages = tuple(packages)
        unique = {}
        for group in (*self.groups.values(), packages):
            for data in group:
                if type(data) is not bytes:
                    raise ValueError("Invalid retained package")
                unique[id(data)] = data
        if sum(map(len, unique.values())) > self.maximum:
            error("editor_limit_exceeded", 413)
        self.groups[token] = packages

    def release(self, token):
        self.groups.pop(token, None)
