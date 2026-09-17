"""Automatic audit logging — records every create, update and delete."""
from flask_login import current_user
from sqlalchemy import event, inspect

from .models import db, AuditLog

# Tables that must not be audited (audit log itself, and high-volume noise).
EXCLUDED = {"audit_logs", "notification_logs"}

# Fields never written to the audit trail.
SENSITIVE_FIELDS = {"password_hash"}


def _actor():
    try:
        if current_user and current_user.is_authenticated:
            return current_user.id, current_user.name
    except Exception:
        pass
    return None, "system"


def _short(value):
    if value is None:
        return None
    text = str(value)
    return text[:500]


def register_audit_listeners():
    @event.listens_for(db.session, "before_flush")
    def before_flush(session, flush_context, instances):
        entries = []
        actor_id, actor_name = _actor()

        for obj in session.new:
            table = getattr(obj, "__tablename__", None)
            if not table or table in EXCLUDED:
                continue
            entries.append(AuditLog(entity=table, entity_id=None, action="create",
                                    changed_by_id=actor_id, changed_by_name=actor_name))

        for obj in session.dirty:
            table = getattr(obj, "__tablename__", None)
            if not table or table in EXCLUDED:
                continue
            state = inspect(obj)
            for attr in state.attrs:
                if attr.key in SENSITIVE_FIELDS:
                    continue
                hist = attr.history
                if not hist.has_changes():
                    continue
                old = hist.deleted[0] if hist.deleted else None
                new = hist.added[0] if hist.added else None
                if old == new:
                    continue
                entries.append(AuditLog(
                    entity=table, entity_id=getattr(obj, "id", None), action="update",
                    field=attr.key, old_value=_short(old), new_value=_short(new),
                    changed_by_id=actor_id, changed_by_name=actor_name))

        for obj in session.deleted:
            table = getattr(obj, "__tablename__", None)
            if not table or table in EXCLUDED:
                continue
            entries.append(AuditLog(entity=table, entity_id=getattr(obj, "id", None), action="delete",
                                    changed_by_id=actor_id, changed_by_name=actor_name))

        for entry in entries:
            session.add(entry)


def log_action(entity, entity_id, action, field=None, old=None, new=None):
    """Manual audit entry for actions that aren't simple column changes."""
    actor_id, actor_name = _actor()
    db.session.add(AuditLog(entity=entity, entity_id=entity_id, action=action, field=field,
                            old_value=_short(old), new_value=_short(new),
                            changed_by_id=actor_id, changed_by_name=actor_name))
