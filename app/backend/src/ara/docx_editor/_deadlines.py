"""Transaction-local SQL limits on a private, caller-pool-sharing engine wrapper."""


def scoped_runtime(runtime):
    from dataclasses import replace

    from sqlalchemy import event

    from ara.config import ConfigurationError
    from ara.documents.runtime import DocumentRuntime

    if type(runtime) is not DocumentRuntime or runtime.engine.dialect.name != "postgresql":
        raise ConfigurationError("Editor deadlines require an explicit PostgreSQL runtime")
    engine = runtime.engine.execution_options()

    def begin(connection):
        # Instance-only OptionEngine listener. SET LOCAL is reset by PostgreSQL
        # on commit/rollback, including when its pooled connection is reused.
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")

    event.listen(engine, "begin", begin)
    return replace(runtime, engine=engine)
