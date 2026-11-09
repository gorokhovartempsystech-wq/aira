"""Explicit factory for the loopback-only local development launcher."""

import os
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ara import config, db
from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
from ara.models import Project, User

LOCAL_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
LOCAL_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000002")


def create_local_app():
    """Provision only the synthetic local identity at startup, never migrations."""
    if os.environ.get("ARA_ENVIRONMENT") != "local":
        raise config.ConfigurationError("Local document API requires ARA_ENVIRONMENT=local")
    engine = db.create_database_engine(config.load_settings())
    try:
        runtime = DocumentRuntime(
            engine=engine, user_id=LOCAL_USER_ID, project_id=LOCAL_PROJECT_ID, mode="local"
        )
        app = create_app(document_runtime=runtime)
    except Exception:
        engine.dispose()
        raise

    @asynccontextmanager
    async def lifespan(app):
        try:
            try:
                with Session(engine) as session, session.begin():
                    session.execute(insert(User).values(id=LOCAL_USER_ID).on_conflict_do_nothing())
                    session.execute(
                        insert(Project)
                        .values(
                            id=LOCAL_PROJECT_ID,
                            owner_id=LOCAL_USER_ID,
                            name="Local development",
                        )
                        .on_conflict_do_nothing()
                    )
                    project = session.get(Project, LOCAL_PROJECT_ID, with_for_update=True)
                    if project.owner_id != LOCAL_USER_ID:
                        raise config.ConfigurationError("Local project ownership conflict")
            except SQLAlchemyError:
                raise config.ConfigurationError(
                    "Unable to initialize local document storage"
                ) from None
            yield
        finally:
            shutdown = getattr(app.state, "shutdown_local_model", None)
            if shutdown is not None:
                shutdown()
            engine.dispose()

    app.router.lifespan_context = lifespan
    return app
