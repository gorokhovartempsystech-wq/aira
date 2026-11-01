"""Only exact inert parts of our blank template; unknown parts remain blocked."""

from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from ara.docx_package import DocxLimits
from ara.docx_package._zip import parsing_end

KNOWN = {
    "word/settings.xml": "c5433ebf6c20b3e23c951d038d4422f8c6e291d9ef08866113683a79893f97ac",
    "word/numbering.xml": "092fe75bc5ebbea03e39e89e427498a5b1f47ecf943ae1f6684c21abb4321fff",
}


def inert_template_parts(data, root):
    # Numbering is inert only when no paragraph references it. Numbered lists stay blocked.
    if any(node.tag.endswith("}numPr") for node in root.iter()):
        return set()
    result = set()
    with ZipFile(BytesIO(data[: parsing_end(data, DocxLimits())])) as archive:
        for name, digest in KNOWN.items():
            if name not in archive.namelist():
                continue
            info = archive.getinfo(name)
            if info.file_size <= 16384 and sha256(archive.read(name)).hexdigest() == digest:
                result.add(name)
    return result
