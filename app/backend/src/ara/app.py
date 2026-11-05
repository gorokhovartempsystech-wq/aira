"""Application factory with no external setup at import or construction time."""

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from ara.documents.runtime import DocumentRuntime


def create_app(
    *,
    document_runtime: "DocumentRuntime | None" = None,
    analysis_supervisor=None,
    table_editor=False,
    field_editor=False,
) -> FastAPI:
    """Create an independent application without configuration or service access."""
    if type(table_editor) is not bool or type(field_editor) is not bool:
        from ara.config import ConfigurationError

        raise ConfigurationError("Invalid editor policy")
    app = FastAPI(title="AI Requirements Assistant")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if document_runtime is not None:
        import os

        from ara.config import ConfigurationError
        from ara.documents.api import install_documents
        from ara.docx_documents.api import install_docx_reads
        from ara.docx_documents.create_http import install_docx_creation
        from ara.docx_documents.paragraph_http import install_paragraph_commands
        from ara.docx_documents.recovery_http import install_recovery
        from ara.docx_documents.text_edit import install_text_edit
        from ara.docx_documents.view import install_docx_view
        from ara.docx_documents.writes import install_docx_writes
        from ara.docx_editor.http import install_editor_json
        from ara.docx_editor.http_discard import install_editor_discard
        from ara.docx_editor.http_downloads import install_editor_downloads
        from ara.drafts.api import install_drafts
        from ara.reviews.api import install_reviews
        from ara.runs.api import install_runs
        from ara.workspace import install_workspace

        if os.environ.get("ARA_ENVIRONMENT", "local") != "local":
            raise ConfigurationError("Local document API requires ARA_ENVIRONMENT=local")
        install_documents(app, document_runtime)
        install_docx_reads(app, document_runtime)
        install_docx_creation(app, document_runtime)
        install_text_edit(app, document_runtime)
        install_paragraph_commands(app, document_runtime)
        install_recovery(app, document_runtime)
        install_docx_view(app, document_runtime)
        install_docx_writes(app, document_runtime)
        install_drafts(app, document_runtime)
        install_runs(app, document_runtime)
        install_reviews(app, document_runtime)
        install_workspace(app)
        install_editor_json(
            app, document_runtime, table_editor=table_editor, field_editor=field_editor
        )
        install_editor_downloads(app)
        install_editor_discard(app)

    if analysis_supervisor is not None:
        from ara.docx_analysis_api import install_analysis

        install_analysis(app, document_runtime, analysis_supervisor)

    return app
