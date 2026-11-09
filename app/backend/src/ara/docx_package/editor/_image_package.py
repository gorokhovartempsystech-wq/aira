"""Append owned image resources without reserializing existing OPC metadata."""

import io
import posixpath
import zipfile
from hashlib import sha256

from .._zip import chunks, parsing_end
from ..boundaries import BoundaryLimits
from ..boundaries._tree import Tree, bounded_join, escape
from ._models import EditorError

TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"


def read(data, source, limits, name):
    with (
        io.BytesIO(data[: parsing_end(data, limits)]) as stream,
        zipfile.ZipFile(stream) as archive,
    ):
        return b"".join(chunks(data, stream, archive, archive.getinfo(name), limits.max_xml_bytes))


def append(raw, namespace, local, xml, limits):
    if raw is None:
        raw = f'<{local} xmlns="{namespace}"/>'.encode()
    tree = Tree(raw, (), BoundaryLimits())
    root = tree.nodes[()]
    if root.name != namespace + "}" + local:
        raise EditorError("unsupported_intent")
    inner = b"" if root.empty else raw[root.opening_end : root.close_start]
    content = bounded_join((inner, xml.encode(tree.codec)), limits.max_xml_bytes)
    return bounded_join(
        (raw[: root.start], tree.wrap(root, content), raw[root.end :]), limits.max_xml_bytes
    )


def resources(data, source, limits, image, extension, mime, relationship_ns):
    directory, filename = posixpath.split(source.main_part)
    relname = posixpath.join(directory, "_rels", filename + ".rels")
    digest = sha256(image).hexdigest()
    media = posixpath.join(directory, "media", "aira-" + digest + "." + extension)
    entries = {e.name: e for e in source.entries}
    replacements, additions, overrides = {}, {}, []
    if media in entries:
        old = entries[media]
        if old.sha256 != digest or old.content_type != mime or old.size_bytes != len(image):
            raise EditorError("unsupported_intent")
    else:
        additions[media] = image
        overrides.append((media, mime))
    used = {r.relationship_id for r in source.relationships if r.source_part == source.main_part}
    identity = next(
        "rIdAira" + str(n) for n in range(len(used) + 1) if "rIdAira" + str(n) not in used
    )
    target = escape(posixpath.relpath(media, directory or "."))
    xml = (
        f'<Relationship xmlns="{RELS}" Id="{identity}" '
        f'Type="{relationship_ns}image" Target="{target}"/>'
    )
    raw = read(data, source, limits, relname) if relname in entries else None
    result = append(raw, RELS, "Relationships", xml, limits)
    (replacements if relname in entries else additions)[relname] = result
    if relname not in entries:
        overrides.append((relname, "application/vnd.openxmlformats-package.relationships+xml"))
    if overrides:
        xml = "".join(
            f'<Override xmlns="{TYPES}" PartName="/{escape(name)}" ContentType="{mime}"/>'
            for name, mime in overrides
        )
        replacements["[Content_Types].xml"] = append(
            read(data, source, limits, "[Content_Types].xml"), TYPES, "Types", xml, limits
        )
    return identity, replacements, additions
