import re
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from ..models import (db, User, Role, Customer, PurchaseOrder, Shipment, AssetMovement,
                      Allocation, StatusHistory, Document, Comment, NotificationRule,
                      NotificationLog, AuditLog, Stage, ExchangeRate, FX_RATES)
from ..auth import permission_required, PERMISSIONS, SYSTEM_ROLE_CODE
from ..exports import export_response
from ..i18n import t

bp = Blueprint("admin", __name__)


@bp.route("/")
@permission_required("*")
def index():
    """Admin hub — the dedicated section for users, roles, the authorisation
    matrix and FX rates, plus the rest of the administration screens."""
    return render_template("admin/index.html",
                           user_count=User.query.count(),
                           role_count=Role.query.count(),
                           currency_count=len({c for c, in db.session.query(ExchangeRate.code).distinct()} | set(FX_RATES)))


@bp.route("/users", methods=["GET", "POST"])
@permission_required("*")
def users():
    if request.method == "POST":
        user_id = request.form.get("id", type=int)
        user = db.session.get(User, user_id) if user_id else User()
        user.name = request.form.get("name")
        user.email = (request.form.get("email") or "").strip().lower()
        user.role_id = request.form.get("role_id", type=int)
        user.phone = request.form.get("phone")
        user.is_active_flag = bool(request.form.get("is_active"))
        password = request.form.get("password")
        if password:
            user.set_password(password)
        elif not user_id:
            user.set_password("demo1234")
        if not user_id:
            db.session.add(user)
        db.session.commit()
        flash(t("User saved."), "success")
        return redirect(url_for("admin.users"))

    all_users = User.query.order_by(User.id).all()
    return render_template("admin/users.html", users=all_users,
                           roles=Role.query.order_by(Role.id).all(),
                           has_history={u.id: _user_has_history(u.id) for u in all_users})


# Every table that records who did something, keyed by (model, column name) — this is
# what "has this user left a footprint" checks against before a hard delete is allowed.
_USER_FOOTPRINT_TABLES = [
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


def _user_has_history(user_id):
    """True if this user is referenced anywhere — a shipment they created, a comment
    they left, a notification sent to them, and so on. Deleting a user with history
    would either fail on a foreign-key constraint or silently orphan those records, so
    this is what decides whether Delete is offered or Admin -> Users points to
    deactivating the account instead."""
    for model, column in _USER_FOOTPRINT_TABLES:
        if db.session.query(getattr(model, column)).filter(
                getattr(model, column) == user_id).first():
            return True
    return False


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@permission_required("*")
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    if user.id == current_user.id:
        flash(t("You can't delete your own account while signed in as it."), "error")
        return redirect(url_for("admin.users"))

    # Never delete the last active user who can manage the system — that would lock
    # everyone out of Admin permanently, with no one able to undo it.
    if user.role and user.role.has("*"):
        other_full_access = User.query.join(Role).filter(
            User.id != user.id, User.is_active_flag.is_(True), Role.permissions == "*").count()
        if other_full_access == 0:
            flash(t("Can't delete the last user with full access — "
                    "create another admin account first, or deactivate this one instead."),
                  "error")
            return redirect(url_for("admin.users"))

    if _user_has_history(user.id):
        flash(t("This user has activity on record (shipments, comments, notifications or "
                "similar) — deleting them would break that history. Set them to Inactive "
                "instead: edit the account and switch Active to No."), "error")
        return redirect(url_for("admin.users"))

    db.session.delete(user)
    db.session.commit()
    flash(t("User deleted."), "success")
    return redirect(url_for("admin.users"))


def _unique_role_code(base):
    code = re.sub(r"[^a-z0-9]+", "_", (base or "role").strip().lower()).strip("_") or "role"
    candidate = code
    i = 1
    while Role.query.filter_by(code=candidate).first():
        i += 1
        candidate = f"{code}_{i}"
    return candidate


@bp.route("/roles", methods=["GET", "POST"])
@permission_required("*")
def roles():
    """The role matrix — who exists as a role. Room to add more roles here at
    any time; what each role can actually access is set separately, on the
    Authorisation matrix."""
    if request.method == "POST":
        role_id = request.form.get("id", type=int)
        role_name = (request.form.get("role_name") or "").strip()
        if not role_name:
            flash(t("A role name is required."), "error")
            return redirect(url_for("admin.roles"))

        role = db.session.get(Role, role_id) if role_id else None
        if role is None:
            role = Role(code=_unique_role_code(request.form.get("code") or role_name),
                       permissions="")
            db.session.add(role)
        role.role_name = role_name
        role.description = (request.form.get("description") or "").strip()
        db.session.commit()
        flash(t("Role saved. Set what it can access on the Authorisation matrix."), "success")
        return redirect(url_for("admin.roles"))

    return render_template("admin/roles.html", roles=Role.query.order_by(Role.id).all())


@bp.route("/authorisation", methods=["GET", "POST"])
@permission_required("*")
def authorisation():
    """The Authorisation matrix — separate from the role list itself: what
    each role can actually see and do, permission by permission."""
    roles_list = Role.query.order_by(Role.id).all()

    if request.method == "POST":
        # The page posts the whole matrix as one form, with a hidden role_ids entry
        # per row, so a genuine submission always names every role. Only touch a role
        # that was actually named in the submitted form — a partial or malformed post
        # (or a future template change that drops a row) then leaves the roles it
        # didn't mention untouched, rather than silently stripping their access.
        submitted_ids = {v for v in request.form.getlist("role_ids") if v.isdigit()}
        for role in roles_list:
            if role.code == SYSTEM_ROLE_CODE:
                continue  # This role always keeps full access — it manages this matrix.
            if str(role.id) not in submitted_ids:
                continue
            if request.form.get(f"full__{role.id}"):
                role.permissions = "*"
            else:
                selected = [key for key, _ in PERMISSIONS
                           if request.form.get(f"perm__{role.id}__{key}")]
                role.permissions = ",".join(selected)
        db.session.commit()
        flash(t("Authorisation matrix updated."), "success")
        return redirect(url_for("admin.authorisation"))

    return render_template("admin/authorisation.html", roles=roles_list, permissions=PERMISSIONS,
                           system_role_code=SYSTEM_ROLE_CODE)


@bp.route("/fx-rates", methods=["GET", "POST"])
@permission_required("*")
def fx_rates():
    """FX rate management — the ExchangeRate table admins can actually edit,
    replacing the indicative hard-coded defaults once a rate is set."""
    if request.method == "POST":
        code = (request.form.get("code") or "").strip().upper()
        rate = request.form.get("rate_to_base", type=float)
        rate_date = request.form.get("rate_date") or date.today().isoformat()
        if not code or not rate:
            flash(t("Currency and rate are both required."), "error")
        else:
            db.session.add(ExchangeRate(code=code, rate_to_base=rate,
                                        rate_date=date.fromisoformat(rate_date)))
            db.session.commit()
            flash(t("FX rate saved."), "success")
        return redirect(url_for("admin.fx_rates"))

    all_codes = sorted({c for c, in db.session.query(ExchangeRate.code).distinct()} | set(FX_RATES))
    current = {}
    history = {}
    for code in all_codes:
        rows = (ExchangeRate.query.filter_by(code=code)
                .order_by(ExchangeRate.rate_date.desc(), ExchangeRate.id.desc()).all())
        history[code] = rows
        current[code] = rows[0] if rows else None

    return render_template("admin/fx_rates.html", codes=all_codes, current=current,
                           history=history, defaults=FX_RATES, today=date.today().isoformat())


@bp.route("/notification-rules", methods=["GET", "POST"])
@permission_required("*")
def notification_rules():
    if request.method == "POST":
        rule_id = request.form.get("id", type=int)
        rule = db.session.get(NotificationRule, rule_id) if rule_id else NotificationRule()
        rule.name = request.form.get("name")
        rule.trigger_type = request.form.get("trigger_type")
        rule.trigger_value = request.form.get("trigger_value")
        rule.audience_role = request.form.get("audience_role")
        rule.channel = request.form.get("channel")
        rule.template = request.form.get("template")
        rule.is_active = bool(request.form.get("is_active"))
        if not rule_id:
            db.session.add(rule)
        db.session.commit()
        flash(t("Notification rule saved."), "success")
        return redirect(url_for("admin.notification_rules"))

    return render_template("admin/notification_rules.html",
                           rules=NotificationRule.query.order_by(NotificationRule.id).all(),
                           roles=Role.query.order_by(Role.id).all(),
                           stages=[(c, Stage.label(c)) for c in Stage.ORDER])


@bp.route("/notifications")
@login_required
def notifications():
    q = NotificationLog.query
    if not current_user.can("view_all"):
        q = q.filter(NotificationLog.recipient_id == current_user.id)
    logs = q.order_by(NotificationLog.sent_at.desc()).limit(300).all()

    fmt = request.args.get("export")
    if fmt:
        headers = ["Sent", "Rule", "Shipment", "Recipient", "Channel", "Subject", "Status"]
        rows = [[l.sent_at.strftime("%d %b %Y %H:%M") if l.sent_at else "",
                 l.rule.name if l.rule else "", l.shipment.reference_no if l.shipment else "",
                 l.recipient_email, l.channel, l.subject, l.status] for l in logs]
        return export_response(fmt, "notification_log", "Notification log", headers, rows)

    return render_template("admin/notifications.html", logs=logs)


@bp.route("/audit")
@permission_required("*")
def audit():
    entity = request.args.get("entity") or ""
    q = AuditLog.query
    if entity:
        q = q.filter(AuditLog.entity == entity)
    logs = q.order_by(AuditLog.changed_at.desc()).limit(400).all()

    entities = sorted({e[0] for e in db.session.query(AuditLog.entity).distinct().all() if e[0]})

    fmt = request.args.get("export")
    if fmt:
        headers = ["When", "Entity", "Record", "Action", "Field", "Old", "New", "By"]
        rows = [[l.changed_at.strftime("%d %b %Y %H:%M") if l.changed_at else "",
                 l.entity, l.entity_id, l.action, l.field, l.old_value, l.new_value,
                 l.changed_by_name] for l in logs]
        return export_response(fmt, "audit_log", "Audit log", headers, rows)

    return render_template("admin/audit.html", logs=logs, entities=entities, current_entity=entity)
