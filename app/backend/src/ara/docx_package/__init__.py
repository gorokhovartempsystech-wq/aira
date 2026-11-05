"""Validate and preserve original DOCX packages entirely in memory.

This API inventories an OPC container and exports its original bytes. It does
not project text, edit Word content, render documents or guarantee full OOXML
schema conformance. Unknown parts and External relationships remain inert.
"""

import struct
import zipfile
import zlib
from xml.parsers import expat

from ._models import DocxError, DocxLimits, DocxSource
from ._reader import read_package

__all__ = ["DocxError", "DocxLimits", "DocxSource", "open_docx", "export_original"]


def open_docx(data: bytes, *, limits: DocxLimits | None = None) -> DocxSource:
    """Open bytes within explicit bounds, without filesystem or external I/O."""
    if type(data) is not bytes or (limits is not None and type(limits) is not DocxLimits):
        raise DocxError("invalid_input")
    if limits is None:
        limits = DocxLimits()
    limits.__post_init__()
    if len(data) > limits.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    try:
        return read_package(data, limits)
    except DocxError as error:
        raise error from None
    except NotImplementedError:
        raise DocxError("unsupported_package") from None
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        expat.ExpatError,
        zlib.error,
        struct.error,
        ValueError,
        LookupError,
        EOFError,
        OverflowError,
        RuntimeError,
    ):
        raise DocxError("invalid_package") from None


def export_original(source: DocxSource) -> bytes:
    """Return the authoritative original; never rebuild a ZIP or serialize XML."""
    if type(source) is not DocxSource:
        raise DocxError("invalid_input")
    return source._original
