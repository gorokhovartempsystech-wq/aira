"""Small synthetic inputs shared by independent D02-06 acceptance."""

from importlib import import_module

from docx_projection_fixtures import package, paragraph


def api():
    return import_module("ara.docx_documents")


def raw(text="alpha"):
    return package(paragraph(text))[0]
