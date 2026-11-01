"""Container and OPC validation for the original-byte preservation scenario."""

import hashlib
import io
import zipfile
from collections.abc import Callable

from ._models import DocxError, DocxLimits, DocxSource, Entry, Relationship
from ._names import folded, part_key, relationship_source, target_key
from ._xml import (
    CT_NS,
    MAIN_TYPE,
    OFFICE_TYPES,
    REL_NS,
    RELS_TYPE,
    WORD_NAMESPACES,
    XmlValidator,
    expanded,
    is_xml,
)
from ._zip import chunks, inventory, parsing_end


def _required(attributes: dict[str, str], name: str) -> str:
    value = attributes.get(name, "")
    if not value.strip():
        raise DocxError("invalid_package")
    return value


class _Reader:
    def __init__(
        self, data: bytes, buffer: io.BytesIO, archive: zipfile.ZipFile, limits: DocxLimits
    ) -> None:
        self.data = data
        self.buffer = buffer
        self.archive = archive
        self.limits = limits
        self.files = inventory(archive, limits)
        self.types: dict[str, str] = {}
        self.entries: list[Entry] = []
        self.relationships: list[Relationship] = []

    def _consume(
        self,
        info: zipfile.ZipInfo,
        content_type: str | None,
        start: Callable[[str, dict[str, str], int], None] | None = None,
    ) -> None:
        xml = content_type is None or is_xml(content_type)
        limit = self.limits.max_part_bytes
        if xml:
            limit = min(limit, self.limits.max_xml_bytes)
        if info.file_size > limit:
            raise DocxError("package_limit_exceeded")
        parser = XmlValidator(start) if xml else None
        digest = hashlib.sha256()
        for block in chunks(self.data, self.buffer, self.archive, info, limit):
            digest.update(block)
            if parser is not None:
                parser.feed(block)
        if parser is not None:
            parser.feed(b"", final=True)
        self.entries.append(Entry(info.filename, content_type, info.file_size, digest.hexdigest()))

    def _content_types(self) -> None:
        defaults: dict[str, str] = {}
        overrides: dict[str, str] = {}

        def start(name: str, attributes: dict[str, str], depth: int) -> None:
            if depth == 0:
                if name != expanded(CT_NS, "Types"):
                    raise DocxError("invalid_package")
                return
            if depth != 1:
                raise DocxError("invalid_package")
            content_type = _required(attributes, "ContentType")
            if name == expanded(CT_NS, "Default"):
                extension = _required(attributes, "Extension")
                # An extension is a single suffix, not a URI or dotted name.
                if any(c in extension for c in ".:/\\%?#[]") or any(
                    ord(c) <= 32 or ord(c) == 127 for c in extension
                ):
                    raise DocxError("invalid_package")
                key = folded(extension)
                if key in defaults:
                    raise DocxError("invalid_package")
                defaults[key] = content_type
            elif name == expanded(CT_NS, "Override"):
                part_name = _required(attributes, "PartName")
                if not part_name.startswith("/"):
                    raise DocxError("invalid_package")
                key = part_key(part_name[1:])
                if key in overrides or key not in self.files:
                    raise DocxError("invalid_package")
                overrides[key] = content_type
            else:
                raise DocxError("invalid_package")

        table = self.files.get("[content_types].xml")
        if table is None or "_rels/.rels" not in self.files:
            raise DocxError("invalid_package")
        self._consume(table, None, start)
        for key, info in self.files.items():
            if key == "[content_types].xml":
                continue
            basename = key.rsplit("/", 1)[-1]
            extension = basename.rsplit(".", 1)[-1] if "." in basename else ""
            content_type = overrides.get(key, defaults.get(extension))
            if content_type is None:
                raise DocxError("invalid_package")
            if key.endswith(".rels") != (content_type == RELS_TYPE):
                raise DocxError("invalid_package")
            if is_xml(content_type) and info.file_size > self.limits.max_xml_bytes:
                raise DocxError("package_limit_exceeded")
            self.types[key] = content_type

    def _relationships(self, info: zipfile.ZipInfo, source: str) -> None:
        seen: set[str] = set()

        def start(name: str, attributes: dict[str, str], depth: int) -> None:
            if depth == 0:
                if name != expanded(REL_NS, "Relationships"):
                    raise DocxError("invalid_package")
                return
            if depth != 1 or name != expanded(REL_NS, "Relationship"):
                raise DocxError("invalid_package")
            identity = _required(attributes, "Id")
            rel_type = _required(attributes, "Type")
            target = _required(attributes, "Target")
            mode = attributes.get("TargetMode", "Internal")
            if identity in seen or mode not in ("Internal", "External"):
                raise DocxError("invalid_package")
            seen.add(identity)
            resolved = None
            if mode == "Internal":
                key = target_key(source, target)
                if key not in self.files or key.endswith(".rels"):
                    raise DocxError("invalid_package")
                resolved = self.files[key].filename
            self.relationships.append(
                Relationship(source, identity, rel_type, target, mode, resolved)
            )

        self._consume(info, RELS_TYPE, start)

    def read(self) -> DocxSource:
        self._content_types()
        rels: set[str] = set()
        for key, info in self.files.items():
            source = relationship_source(info.filename)
            if source is None:
                continue
            if source != "/":
                source_info = self.files.get(part_key(source))
                if source_info is None:
                    raise DocxError("invalid_package")
                source = source_info.filename
            rels.add(key)
            self._relationships(info, source)

        main_links = [
            rel
            for rel in self.relationships
            if rel.source_part == "/" and rel.relationship_type in OFFICE_TYPES
        ]
        if len(main_links) != 1 or main_links[0].target_mode != "Internal":
            raise DocxError("invalid_package")
        main_part = main_links[0].resolved_part
        main_key = part_key(main_part)
        if self.types.get(main_key) != MAIN_TYPE:
            raise DocxError("unsupported_package")

        body_name = ""
        bodies = 0

        def main_start(name: str, attributes: dict[str, str], depth: int) -> None:
            nonlocal body_name, bodies
            if depth == 0:
                for namespace in WORD_NAMESPACES:
                    if name == expanded(namespace, "document"):
                        body_name = expanded(namespace, "body")
                        break
                else:
                    raise DocxError("invalid_package")
            elif depth == 1 and name == body_name:
                bodies += 1

        for key, info in self.files.items():
            if key == "[content_types].xml" or key in rels:
                continue
            self._consume(info, self.types[key], main_start if key == main_key else None)
        if bodies != 1:
            raise DocxError("invalid_package")
        # Directory records are absent from the public inventory, but their ZIP
        # headers and CRC still need validation. Nonempty directories are invalid.
        for info in self.archive.infolist():
            if info.is_dir():
                for _ in chunks(self.data, self.buffer, self.archive, info, 0):
                    pass
        return DocxSource(
            sha256=hashlib.sha256(self.data).hexdigest(),
            size_bytes=len(self.data),
            main_part=main_part,
            entries=tuple(sorted(self.entries, key=lambda entry: entry.name)),
            relationships=tuple(
                sorted(self.relationships, key=lambda rel: (rel.source_part, rel.relationship_id))
            ),
            _original=self.data,
        )


def read_package(data: bytes, limits: DocxLimits) -> DocxSource:
    end = parsing_end(data, limits)
    with io.BytesIO(data[:end]) as buffer, zipfile.ZipFile(buffer, "r") as archive:
        return _Reader(data, buffer, archive, limits).read()
