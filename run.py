"""Gtrack development entry point:  python run.py"""
import os
import sys

from sqlalchemy import inspect

from app import create_app
from app.models import db
from config import Config

app = create_app()


@app.cli.command("init-db")
def init_db():
    """Create tables without seeding."""
    with app.app_context():
        db.create_all()
        print("Tables created.")


def preflight():
    """Check the database is actually set up before serving, so a missing table
    produces a one-line instruction rather than a stack trace in the browser."""
    with app.app_context():
        try:
            tables = set(inspect(db.engine).get_table_names())
        except Exception as exc:
            print("\n  Cannot reach the database.")
            print(f"  Target: {Config.database_label()}")
            print(f"  Error:  {exc}\n")
            print("  If you did not intend to use an external database, clear the variable:")
            print("      Windows:      set GTRACK_DATABASE_URL=")
            print("      macOS/Linux:  unset GTRACK_DATABASE_URL\n")
            return False

        if "shipments" not in tables or "users" not in tables:
            print("\n  The database has no Gtrack tables yet.")
            print(f"  Target: {Config.database_label()}\n")
            print("  Build it first:")
            print("      python seed.py\n")
            return False
    return True


if __name__ == "__main__":
    if not preflight():
        sys.exit(1)

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"\n  {Config.APP_NAME} — {Config.APP_TAGLINE}")
    print(f"  {Config.ORG_NAME}")
    print(f"  Data: {Config.database_label()}")
    print(f"\n  Open http://127.0.0.1:{port}")
    print(f"  No accounts yet — the app walks you through creating the admin one.")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
