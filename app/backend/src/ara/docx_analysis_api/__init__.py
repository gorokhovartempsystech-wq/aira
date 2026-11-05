"""Explicit saved-DOCX analysis HTTP integration; no configuration or I/O on import."""


def install_analysis(app, runtime, supervisor):
    from ._http import install

    install(app, runtime, supervisor)
