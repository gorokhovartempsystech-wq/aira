"""Compare a bounded trusted-connection observation; this does not open a connection."""

import re

from ._models import ProfileError, database_name, require
from ._plan import PATH_SETTINGS, SETTING_NAMES, path, validate_plan

_NAMES_SQL = ",".join("'" + name + "'" for name in SETTING_NAMES)
OBSERVATION_SQL = (
    """
SELECT pg_catalog.jsonb_build_object(
  'server_version_num', pg_catalog.current_setting('server_version_num')::integer,
  'system_identifier', (SELECT system_identifier::text FROM pg_catalog.pg_control_system()),
  'database', pg_catalog.current_database(),
  'user', current_user,
  'session_user', session_user,
  'in_recovery', pg_catalog.pg_is_in_recovery(),
  'encoding', (SELECT pg_catalog.pg_encoding_to_char(encoding) FROM pg_catalog.pg_database
               WHERE datname = pg_catalog.current_database()),
  'collate', (SELECT datcollate FROM pg_catalog.pg_database
              WHERE datname = pg_catalog.current_database()),
  'ctype', (SELECT datctype FROM pg_catalog.pg_database
            WHERE datname = pg_catalog.current_database()),
  'settings', (SELECT pg_catalog.jsonb_object_agg(name,
                CASE WHEN name = 'archive_command' AND setting = '(disabled)'
                       AND pg_catalog.current_setting('archive_mode') = 'off'
                     THEN '' ELSE setting END) FROM pg_catalog.pg_settings
                WHERE name IN ("""
    + _NAMES_SQL
    + ")))"
)
_FIELDS = {
    "server_version_num",
    "system_identifier",
    "database",
    "user",
    "session_user",
    "in_recovery",
    "encoding",
    "collate",
    "ctype",
    "settings",
}


def identifier(value, code):
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None, code)
    require(int(value) <= 2**64 - 1, code)
    return value


def check_observation(plan, observation, *, expected_system_identifier, database="aira"):
    validate_plan(plan)
    database = database_name(database)
    expected = identifier(expected_system_identifier, "validation_error")
    code = "postgres_mismatch"
    require(type(observation) is dict and set(observation) == _FIELDS, code)
    version = observation["server_version_num"]
    require(type(version) is int and 180000 <= version < 190000, code)
    require(identifier(observation["system_identifier"], code) == expected, code)
    require(observation["in_recovery"] is False, code)
    for name, value in (
        ("database", database),
        ("user", "aira_local"),
        ("session_user", "aira_local"),
        ("encoding", "UTF8"),
        ("collate", "C"),
        ("ctype", "C"),
    ):
        require(type(observation[name]) is str and observation[name] == value, code)
    values = observation["settings"]
    require(type(values) is dict and set(values) == set(plan._expected_settings), code)
    for name, value in plan._expected_settings.items():
        actual = values[name]
        require(type(actual) is str, code)
        if name in PATH_SETTINGS and plan.target == "windows-x86_64":
            try:
                actual = path(actual, True).casefold()
            except ProfileError:
                raise ProfileError(code) from None
            value = value.casefold()
        require(actual == value, code)
