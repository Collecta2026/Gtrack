"""Verify the configured database is reachable and report what is in it.

    python check_db.py

Use this after setting GTRACK_DATABASE_URL (e.g. against Neon) to confirm the
connection works before deploying or seeding.
"""
import sys

from sqlalchemy import inspect

from app import create_app
from app.models import db
from config import Config


def main():
    print(f"Target: {Config.database_label()}")
    app = create_app()
    with app.app_context():
        try:
            tables = sorted(inspect(db.engine).get_table_names())
        except Exception as exc:
            print(f"\n  FAILED to connect:\n  {exc}\n")
            print("  Check the connection string, that the database exists, and that")
            print("  your IP is allowed if the provider restricts access.")
            sys.exit(1)

        print(f"Connected. {len(tables)} table(s) present.")
        if not tables:
            print("\n  Database is empty — run 'python seed.py --force' to build it.")
            return

        from app.models import Shipment, User, Asset, Allocation
        try:
            print(f"  shipments : {Shipment.query.count()}")
            print(f"  users     : {User.query.count()}")
            print(f"  machines  : {Asset.query.count()}")
            print(f"  allocations: {Allocation.query.count()}")
        except Exception as exc:
            print(f"  Tables exist but could not be read: {exc}")


if __name__ == "__main__":
    main()
