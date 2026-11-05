"""The source observes real native close, including exceptions after driver finish."""

import os
import threading

import psycopg

from ._models import DatabaseError, require


class TrackedConnection(psycopg.Connection):
    def __init__(self, *args, **kwargs):
        self._desktop_pid = os.getpid()
        self._desktop_lock = threading.Lock()
        self._desktop_attempted = self._desktop_unknown = False
        self._desktop_source = None
        super().__init__(*args, **kwargs)

    def close(self):
        require(self._desktop_pid == os.getpid())
        with self._desktop_lock:
            if self._desktop_attempted:
                require(not self._desktop_unknown, "cleanup_unknown")
                return
            self._desktop_attempted = True
            try:
                super().close()
                require(self.closed, "cleanup_unknown")
            except BaseException:
                self._desktop_unknown = True
                if self._desktop_source is not None:
                    self._desktop_source._unknown()
                raise DatabaseError("cleanup_unknown") from None
            if self._desktop_source is not None:
                self._desktop_source._released(self)


def verify(raw, source):
    """Probe before returning raw to application code; caller transaction is untouched."""
    raw.execute("SET TRANSACTION READ ONLY")
    row = raw.execute(
        "SELECT (SELECT system_identifier::text FROM pg_catalog.pg_control_system()),"
        "(SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=current_database()),"
        "current_database(),current_user,session_user,"
        "current_setting('server_version_num')::int,current_setting('synchronous_commit'),"
        "pg_catalog.pg_is_in_recovery()"
    ).fetchone()
    physical = source._physical
    require(
        row[0] == physical.system_identifier
        and row[1] == physical.database_oid
        and row[2:5] == ("aira", "aira_local", "aira_local")
        and 180000 <= row[5] < 190000
        and row[6] == "on"
        and row[7] is False,
        "database_mismatch",
    )
    require(
        raw.execute("SELECT version_num FROM public.alembic_version LIMIT 2").fetchall()
        == [("0013_docx_review_preferences",)],
        "database_mismatch",
    )
    identity = source._identity
    require(
        raw.execute("SELECT id FROM public.users LIMIT 2").fetchall() == [(identity.user_id,)],
        "database_mismatch",
    )
    require(
        raw.execute("SELECT id,owner_id FROM public.projects LIMIT 2").fetchall()
        == [(identity.project_id, identity.user_id)],
        "database_mismatch",
    )
    require(
        raw.execute(
            "SELECT slot_key,installation_id FROM public.docx_analysis_supervisor LIMIT 2"
        ).fetchall()
        == [(1, identity.installation_id)],
        "database_mismatch",
    )
    raw.rollback()
