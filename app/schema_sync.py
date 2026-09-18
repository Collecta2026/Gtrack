"""Additive, non-destructive schema sync — for deployments with no migration
framework.

There is no Alembic in this project (see golive.py's migrate-command
detection), and Flask-SQLAlchemy's create_all() only creates *missing
tables*: it never adds a column to a table that already exists. golive.py
also only ever runs seed.py once against a production database (its
state["migrated"] guard, precisely so a redeploy never wipes real data).
Put those two things together and a column added to a model here would
silently never reach an already-migrated production database — the app
would boot, then fall over with "column does not exist" the first time a
request touched it.

This closes that gap: on every app start, compare each model's columns
against what the database actually has and ADD COLUMN for anything
missing. It only ever adds columns — it never drops, renames, retypes or
alters one — so it is safe to run unconditionally, every time, against a
database that already holds real shipments, costs and users.
"""
import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def sync_schema(app, db):
    """Add any column a model declares that the live database is missing."""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            existing_tables = set(inspector.get_table_names())
        except Exception:
            logger.exception("Schema sync: could not inspect the database — skipping.")
            return

        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                # A brand-new table is handled by create_all() / seed.py instead —
                # this routine only ever patches tables that already exist.
                continue
            try:
                existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            except Exception:
                logger.exception("Schema sync: could not read columns for %s — skipping.",
                                 table.name)
                continue

            for column in table.columns:
                if column.name in existing_cols:
                    continue
                try:
                    col_type = column.type.compile(dialect=db.engine.dialect)
                    ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                    with db.engine.begin() as conn:
                        conn.execute(text(ddl))
                    logger.info("Schema sync: added column %s.%s", table.name, column.name)
                except Exception:
                    # Most likely another worker just added the same column, or the
                    # DB user lacks DDL rights — either way, log it and keep booting
                    # rather than take the whole app down over a schema patch.
                    logger.exception("Schema sync: could not add %s.%s",
                                     table.name, column.name)
