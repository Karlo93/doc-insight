from alembic import context
from doc_insight.worker.settings import get_settings
from sqlalchemy import Connection, create_engine


def run(connection: Connection) -> None:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


if supplied := context.config.attributes.get("connection"):
    run(supplied)
else:
    engine = create_engine(get_settings().database_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
