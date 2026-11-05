"""Bounded inventory of one explicit source tree, using the existing no-follow reader."""

import os
import stat
from dataclasses import dataclass

from ara.desktop.installation._files import _admit, _stamp
from ara.desktop.installation._manifest import _path
from ara.desktop.installation._models import require


@dataclass(frozen=True)
class Inventory:
    sizes: dict
    directories: tuple
    stamps: dict


def scan(tree):
    stamps = {"": _stamp(tree.root.lstat())}
    require(stamps[""] == _stamp(tree.initial))
    sizes, directories, total = {}, [], 0

    def walk(parent, fd):
        nonlocal total
        seen = False
        with os.scandir(
            fd if fd is not None else tree.root.joinpath(*parent.split("/"))
        ) as entries:
            for entry in entries:
                seen = True
                path = parent + "/" + entry.name if parent else entry.name
                _path(path)
                require(path not in stamps and len(stamps) < 65536)
                info = tree.info(parent, entry.name, fd)
                directory = stat.S_ISDIR(info.st_mode)
                _admit(info, directory=directory)
                stamps[path] = _stamp(info)
                if directory:
                    directories.append(path)
                    with tree.directory(parent, entry.name, fd, info) as child:
                        walk(path, child)
                else:
                    require(len(sizes) < 32768 and 0 <= info.st_size <= 8 * 1024**3)
                    total += info.st_size
                    require(total <= 16 * 1024**3)
                    sizes[path] = info.st_size
        require(seen)  # Empty directories are not part of the installation inventory grammar.

    walk("", tree.fd)
    return Inventory(sizes, tuple(sorted(directories, key=lambda p: (p.count("/"), p))), stamps)
