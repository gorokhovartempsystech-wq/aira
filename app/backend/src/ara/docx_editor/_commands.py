"""Bounded tagged native requests and an explicit deterministic fingerprint."""

from base64 import b64encode
from dataclasses import dataclass, field, fields
from hashlib import sha256
from json import JSONEncoder

from ara.docx_package.editor import Caret, CaretTarget, EditorSelection, SelectionTarget
from ara.docx_package.editor._images import ImageData
from ara.docx_package.editor._objects import TableSize
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.projection import SourceAnchor
from ara.docx_package.ranges import RangeEdit, TextPosition
from ara.docx_package.structure import DeleteParagraph, InsertParagraph

from ._errors import native_errors, validate

ACTIONS = (
    "capture",
    "insert_text",
    "insert_table",
    "insert_image",
    "paste_text",
    "enter",
    "join_previous",
    "join_next",
    "insert_soft_break",
    "range_edit",
    "structure",
    "format",
    "undo",
    "redo",
)


def _integer(value, maximum=2147483647):
    validate(type(value) is int and 0 <= value <= maximum)
    return value


def _string(value, maximum, budget=None, key=None):
    validate(type(value) is str and len(value) <= maximum)
    if budget is not None:
        budget[key] += len(value)
        validate(budget[key] <= 1000000)
    return value


def _anchor(value):
    from ara.docx_documents._dto import _hash

    validate(type(value) is SourceAnchor)
    digest, part, path = (getattr(value, n, None) for n in ("source_sha256", "part_name", "path"))
    validate(
        _hash(digest)
        and type(part) is str
        and 1 <= len(part) <= 1024
        and "\x00" not in part
        and not any(0xD800 <= ord(c) <= 0xDFFF for c in part)
        and type(path) is tuple
        and 1 <= len(path) <= 128
    )
    return SourceAnchor(digest, part, tuple(_integer(v, 100000) for v in path))


def _caret(value, target=False):
    cls = CaretTarget if target else Caret
    validate(type(value) is cls)
    affinity = getattr(value, "affinity", None)
    validate(type(affinity) is str and affinity in ("left", "right"))
    first = (
        _integer(getattr(value, "block_index", None))
        if target
        else _anchor(getattr(value, "anchor", None))
    )
    return cls(first, _integer(getattr(value, "offset", None)), affinity)


def _selection(value, target=False):
    cls = SelectionTarget if target else EditorSelection
    validate(type(value) is cls)
    return cls(
        _caret(getattr(value, "anchor", None), target),
        _caret(getattr(value, "focus", None), target),
    )


def _position(value):
    validate(type(value) is TextPosition)
    return TextPosition(
        _anchor(getattr(value, "anchor", None)), _integer(getattr(value, "offset", None))
    )


def _items(value):
    validate(type(value) is tuple and len(value) <= 1000)
    return value


def _record(value, action, budget):
    if action == "range_edit":
        validate(type(value) is RangeEdit)
        expected = _string(getattr(value, "expected_text", None), 1000000, budget, "expected")
        replacement = _string(getattr(value, "replacement_text", None), 1000000, budget, "text")
        return RangeEdit(
            _position(getattr(value, "start", None)),
            _position(getattr(value, "end", None)),
            expected,
            replacement,
        )
    if action == "format":
        validate(type(value) is ParagraphFormat)
        anchor = _anchor(getattr(value, "anchor", None))
        expected = _string(getattr(value, "expected_text", None), 1000000, budget, "expected")
        style, kind, identity = (
            getattr(value, n, None) for n in ("style_id", "list_kind", "list_id")
        )
        if style is not None:
            _string(style, 255)
        if identity is not None:
            _string(identity, 10)
        validate(type(kind) is str)
        return ParagraphFormat(anchor, expected, style, kind, identity)
    validate(type(value) in (InsertParagraph, DeleteParagraph))
    anchor = _anchor(getattr(value, "anchor", None))
    expected = _string(getattr(value, "expected_text", None), 1000000, budget, "expected")
    if type(value) is DeleteParagraph:
        return DeleteParagraph(anchor, expected)
    texts = _items(getattr(value, "texts", None))
    budget["paragraphs"] += len(texts)
    validate(1 <= len(texts) and budget["paragraphs"] <= 1000)
    texts = tuple(_string(v, 1000000, budget, "text") for v in texts)
    position = getattr(value, "position", None)
    validate(type(position) is str)
    return InsertParagraph(anchor, expected, texts, position)


@dataclass(frozen=True, slots=True)
class EditorCommand:
    action: str
    value: object = field(default=None, repr=False)
    after: SelectionTarget | None = field(default=None, repr=False)

    def __post_init__(self):
        action, value, after = (getattr(self, n, None) for n in ("action", "value", "after"))
        validate(type(action) is str and action in ACTIONS)
        with native_errors():
            if action == "capture":
                validate(after is None)
                value = _selection(value)
            elif action == "insert_table":
                validate(after is None and type(value) is TableSize)
                value = TableSize(getattr(value, "rows", None), getattr(value, "columns", None))
            elif action == "insert_image":
                validate(after is None and type(value) is ImageData)
                value = ImageData(getattr(value, "data", None), getattr(value, "alt_text", None))
            elif action in ("insert_text", "paste_text"):
                validate(after is None)
                value = _string(value, 100000 if action == "insert_text" else 1000000)
                if action == "insert_text":
                    from ara.docx_package.editor._typing import validate_text

                    validate_text(value)
            elif action in ("range_edit", "structure", "format"):
                budget = {"expected": 0, "text": 0, "paragraphs": 0}
                value = tuple(_record(v, action, budget) for v in _items(value))
                if action != "format" or after is not None:
                    after = _selection(after, True)
            else:
                validate(value is None and after is None)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "after", after)


def normalized(command):
    validate(type(command) is EditorCommand)
    return EditorCommand(*(getattr(command, n, None) for n in ("action", "value", "after")))


def _wire(value):
    if type(value) is ImageData:
        return dict(
            type="ImageData",
            data_base64=b64encode(value.data).decode("ascii"),
            alt_text=value.alt_text,
        )
    if value is None or type(value) in (str, int):
        return value
    if type(value) is tuple:
        return [_wire(v) for v in value]
    validate(
        type(value)
        in (
            EditorCommand,
            TableSize,
            SourceAnchor,
            Caret,
            CaretTarget,
            EditorSelection,
            SelectionTarget,
            TextPosition,
            RangeEdit,
            InsertParagraph,
            DeleteParagraph,
            ParagraphFormat,
        )
    )
    return {
        "type": type(value).__name__,
        **{f.name: _wire(getattr(value, f.name)) for f in fields(value)},
    }


def fingerprint(registry_id, document_id, session_id, command_id, sequence, revision, command):
    payload = dict(
        version=1,
        registry_id=str(registry_id),
        document_id=str(document_id),
        session_id=str(session_id),
        command_id=str(command_id),
        expected_command_sequence=str(sequence),
        expected_session_revision=str(revision),
        action=command.action,
        value=_wire(command.value),
        after=_wire(command.after),
    )
    digest = sha256(b"ara.docx.editor-command.v1\0")
    encoder = JSONEncoder(sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    for chunk in encoder.iterencode(payload):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def execute(editor, command, revision):
    action, value, after = command.action, command.value, command.after
    with native_errors():
        if action == "capture":
            return editor.capture(value, expected_revision=revision)
        if action == "insert_table":
            return editor.insert_table(value.rows, value.columns, expected_revision=revision)
        if action == "insert_image":
            return editor.insert_image(
                value.data, alt_text=value.alt_text, expected_revision=revision
            )
        if action == "insert_text":
            return editor.insert_text(value, expected_revision=revision)
        if action == "paste_text":
            return editor.paste_text(value, expected_revision=revision)
        if action == "range_edit":
            return editor.apply(value, after=after, expected_revision=revision)
        if action == "structure":
            return editor.apply_structure(value, after=after, expected_revision=revision)
        if action == "format":
            return editor.apply_formats(value, after=after, expected_revision=revision)
        if action == "enter":
            return editor.enter(expected_revision=revision)
        if action == "join_previous":
            return editor.join_previous(expected_revision=revision)
        if action == "join_next":
            return editor.join_next(expected_revision=revision)
        if action == "insert_soft_break":
            return editor.insert_soft_break(expected_revision=revision)
        if action == "undo":
            return editor.undo(expected_revision=revision)
        if action == "redo":
            return editor.redo(expected_revision=revision)
        validate(False)
