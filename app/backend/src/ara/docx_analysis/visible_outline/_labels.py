"""Bound generated numbering before expansion, independently of literal source spans."""

from ara.docx_analysis.visible_lists._definitions import require
from ara.docx_analysis.visible_main._models import budget

NUMERIC = ("decimal", "upperRoman", "lowerRoman")
ROMAN = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def units(value):
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def template(value, fmt, level):
    budget(len(value), 8192)
    if fmt == "bullet":
        budget(units(value), 31)
        return (value,)
    pieces = value.split("%")
    require(len(pieces) <= 10)
    result = [pieces[0]]
    for piece in pieces[1:]:
        require(bool(piece) and piece[0] in "123456789")
        require(len(piece) == 1 or not piece[1].isdigit())
        index = int(piece[0]) - 1
        require(index <= level)
        result.extend((index, piece[1:]))
    return tuple(result)


def number(ordinal, fmt):
    if fmt == "decimal":
        return str(ordinal)
    require(ordinal > 0, "unsupported_roman_number")
    result, size = [], 0
    for value, symbol in ROMAN:
        count, ordinal = divmod(ordinal, value)
        size += count * len(symbol)
        budget(size, 31)
        result.append(symbol * count)
    rendered = "".join(result)
    return rendered.lower() if fmt == "lowerRoman" else rendered


def label(definition, num_id, counters, resolve):
    result, size = [], 0
    for piece in definition.pieces:
        if type(piece) is int:
            key = (num_id, piece)
            require(key in counters, "unresolved_parent_counter")
            referenced = resolve(num_id, piece)
            require(referenced.format in NUMERIC)
            rendered = number(counters[key], "decimal" if definition.legal else referenced.format)
        else:
            rendered = piece
        size += units(rendered)
        budget(size, 31)
        result.append(rendered)
    return "".join(result)
