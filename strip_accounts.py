"""One-off migration for an EXISTING deployment: removes every user account while
leaving all business data untouched (shipments, customers, purchase orders, cost
lines, documents, comments, notifications, audit history — everything except who
was signed in when it happened).

Use this once, right after deploying the new no-pre-seeded-accounts build to a
database that already has the old demo accounts (or any accounts) in it. Once it
runs, the database has zero users, so the very next person to open the app is
walked through the one-time "create the admin account" setup screen — exactly
like a brand-new install, but with all the real shipment history intact.

This does NOT touch Shipment, Customer, PurchaseOrder, CostLine, Document, Asset,
Allocation or any other business record. It only:
  1. Clears the "who did this" attribution columns that point at a user (they're
     all nullable by design) — created_by, uploaded_by, recorded_by, allocated_by,
     sales_owner, the comment author, the notification recipient, and the audit
     trail's changed_by. Nothing is deleted except the account rows themselves.
  2. Deletes every row in the users table.

Run it exactly like seed.py — same GTRACK_DATABASE_URL, same --force requirement
for anything that isn't a local SQLite file, because this is precisely the kind
of script that must never run against the wrong database by accident.

    GTRACK_DATABASE_URL=<your live connection string> python strip_accounts.py --force

Take a database backup first if your host offers one-click backups (Render and
Neon both do) — this script is safe by construction, but a backup costs nothing
and means "undo" is always available regardless.
"""
import sys

from app import create_app
from app.models import (db, User, Customer, PurchaseOrder, Shipment, AssetMovement,
                        Allocation, StatusHistory, Document, Comment, NotificationLog,
                        AuditLog)

# (model, column name) for every FK that points at users.id
ATTRIBUTION_COLUMNS = [
    (Customer, "sales_owner_id"),
    (PurchaseOrder, "created_by_id"),
    (Shipment, "created_by_id"),
    (AssetMovement, "recorded_by_id"),
    (Allocation, "allocated_by_id"),
    (StatusHistory, "recorded_by_id"),
    (Document, "uploaded_by_id"),
    (Comment, "user_id"),
    (NotificationLog, "recipient_id"),
    (AuditLog, "changed_by_id"),
]


def confirm_target():
    from config import Config
    print(f"Target database: {Config.database_label()}")

    if "--force" in sys.argv:
        print("  --force given: proceeding.")
        return True

    if Config.is_sqlite():
        print("  Local SQLite file — proceeding without --force.")
        return True

    print()
    print("  REFUSING TO CONTINUE.")
    print("  This is not a local SQLite file, and this script deletes every user")
    print("  account on the target database. If GTRACK_DATABASE_URL points at the")
    print("  wrong database, this would sign everyone out for good.")
    print()
    print("  Re-run with --force once you're sure this is the right target —")
    print("  ideally right after taking a backup.")
    return False


def main():
    if not confirm_target():
        sys.exit(1)

    app = create_app()
    with app.app_context():
        user_count = User.query.count()
        if user_count == 0:
            print("No user accounts exist — nothing to do. The setup screen will "
                  "already show on next visit.")
            return

        print(f"\n{user_count} account(s) will be removed:")
        for u in User.query.order_by(User.email).all():
            print(f"  {u.email:42s} {u.role_code or '—'}")

        print("\nClearing attribution columns (business records are kept)...")
        for model, column in ATTRIBUTION_COLUMNS:
            col = getattr(model, column)
            n = model.query.filter(col.isnot(None)).update(
                {column: None}, synchronize_session=False)
            if n:
                print(f"  {model.__tablename__}.{column}: cleared on {n} row(s)")

        deleted = User.query.delete(synchronize_session=False)
        db.session.commit()
        print(f"\nDone — {deleted} account(s) removed, all business data intact.")
        print("The next visit to the app will show the setup screen.")


if __name__ == "__main__":
    main()
