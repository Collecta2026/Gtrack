from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from ..models import (db, User, Role, NotificationRule, NotificationLog, AuditLog, Stage)
from ..auth import permission_required
from ..exports import export_response

bp = Blueprint("admin", __name__)


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
        flash("User saved.", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/users.html",
                           users=User.query.order_by(User.id).all(),
                           roles=Role.query.order_by(Role.id).all())


@bp.route("/roles")
@permission_required("*")
def roles():
    return render_template("admin/roles.html", roles=Role.query.order_by(Role.id).all())


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
        flash("Notification rule saved.", "success")
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
