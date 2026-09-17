"""
Rule-based notification engine.

Every alert is internal: it goes to SGE staff, most importantly the sales owner of an
allocated customer, so that person can then contact the customer directly.

In the test system alerts are written to NotificationLog rather than emailed
(set NOTIFICATIONS_LIVE=1 and wire an SMTP backend in _deliver() to send for real).
"""
from datetime import date, timedelta

from flask import current_app

from .models import (db, Shipment, PurchaseOrder, CostLine, User, Role,
                     NotificationRule, NotificationLog, Stage)


DEFAULT_RULES = [
    dict(name="PO overdue against expected ready date", trigger_type="po_overdue",
         trigger_value="0", audience_role="logistics_admin", channel="email",
         template="Purchase order {po_number} to {supplier} passed its expected ready date "
                  "({expected_ready_date}). Chase the supplier before it becomes a shipment delay."),
    dict(name="Quotation not selected after order confirmation", trigger_type="quote_pending",
         trigger_value="5", audience_role="logistics_admin", channel="email",
         template="Shipment {reference_no} has been at '{stage}' for {days} days with no freight "
                  "quotation selected. Booking is at risk of delay."),
    dict(name="ETA within 7 days", trigger_type="eta_within_days", trigger_value="7",
         audience_role="sales", channel="email",
         template="Shipment {reference_no} ({brand}) is due to arrive on {eta}. "
                  "Allocated customers: {customers}. Give them advance notice."),
    dict(name="Cleared customs — near installation", trigger_type="stage_reached",
         trigger_value=Stage.CLEARED, audience_role="sales", channel="email",
         template="Shipment {reference_no} ({brand}) has cleared customs. "
                  "Customers awaiting installation: {customers}. Contact them to arrange scheduling."),
    dict(name="Received into warehouse", trigger_type="stage_reached",
         trigger_value=Stage.WAREHOUSE, audience_role="logistics_admin", channel="in_app",
         template="Shipment {reference_no} has been received into the warehouse. "
                  "Confirm condition and serial numbers, then hand over for installation."),
    dict(name="Shipment delayed past ETA", trigger_type="delay", trigger_value="0",
         audience_role="logistics_admin", channel="email",
         template="Shipment {reference_no} has passed its ETA of {eta} without arriving. "
                  "Current stage: {stage}. Escalate with {forwarder}."),
    dict(name="Required document missing", trigger_type="missing_document", trigger_value="3",
         audience_role="logistics_admin", channel="email",
         template="Shipment {reference_no} is missing required documents: {missing}. "
                  "Current stage: {stage}."),
    dict(name="Cost line overdue", trigger_type="payment_overdue", trigger_value="0",
         audience_role="finance", channel="email",
         template="Payment overdue on shipment {reference_no}: {cost_type} of "
                  "{amount} {currency} to {payable_to}, due {due_date}."),
    dict(name="Weekly management digest", trigger_type="digest", trigger_value="weekly",
         audience_role="md", channel="email",
         template="Weekly pipeline: {open_count} open shipments, {delayed_count} delayed, "
                  "{unallocated_count} units awaiting customer allocation."),
]


def seed_default_rules():
    if NotificationRule.query.count():
        return
    for spec in DEFAULT_RULES:
        db.session.add(NotificationRule(**spec))
    db.session.commit()


def _recipients(role_code, shipment=None):
    """Resolve a rule's audience to actual users.

    For sales, only the account managers who own a customer allocated on this shipment
    are notified — not the whole sales team.
    """
    if role_code == "sales" and shipment is not None:
        owners = {a.customer.sales_owner for a in shipment.allocations
                  if a.customer and a.customer.sales_owner}
        return [u for u in owners if u and u.is_active]
    role = Role.query.filter_by(code=role_code).first()
    if not role:
        return []
    return [u for u in role.users if u.is_active]


def _customers_text(shipment):
    names = [c.customer_name for c in shipment.allocated_customers]
    return ", ".join(names) if names else "none allocated yet"


def _context(shipment):
    return dict(
        reference_no=shipment.reference_no,
        brand=shipment.brand.brand_name if shipment.brand else "—",
        supplier=shipment.supplier.name if shipment.supplier else "—",
        forwarder=shipment.forwarder.name if shipment.forwarder else "the forwarder",
        eta=shipment.eta.strftime("%d %b %Y") if shipment.eta else "—",
        stage=shipment.stage_label,
        days=shipment.days_in_stage,
        customers=_customers_text(shipment),
        missing=", ".join(shipment.missing_documents) or "none",
    )


def _deliver(rule, recipient, shipment, subject, body):
    log = NotificationLog(
        shipment_id=shipment.id if shipment else None,
        rule_id=rule.id,
        recipient_id=recipient.id,
        recipient_email=recipient.email,
        subject=subject,
        body=body,
        channel=rule.channel,
        status="sent" if current_app.config.get("NOTIFICATIONS_LIVE") else "logged",
    )
    db.session.add(log)
    return log


def _already_sent(rule, shipment, within_days=1):
    """Prevent the same rule firing repeatedly for the same shipment."""
    cutoff = date.today() - timedelta(days=within_days)
    q = NotificationLog.query.filter(NotificationLog.rule_id == rule.id)
    if shipment is not None:
        q = q.filter(NotificationLog.shipment_id == shipment.id)
    for log in q.all():
        if log.sent_at and log.sent_at.date() > cutoff:
            return True
    return False


def fire_stage_rules(shipment, stage_code):
    """Called whenever a shipment moves into a new stage."""
    rules = NotificationRule.query.filter_by(trigger_type="stage_reached", is_active=True).all()
    fired = []
    for rule in rules:
        if rule.trigger_value != stage_code:
            continue
        ctx = _context(shipment)
        body = rule.template.format(**ctx)
        subject = f"[{shipment.reference_no}] {rule.name}"
        for user in _recipients(rule.audience_role, shipment):
            fired.append(_deliver(rule, user, shipment, subject, body))
    db.session.commit()
    return fired


def run_rule_sweep():
    """Evaluate every time-based rule. Would normally run on a schedule."""
    today = date.today()
    fired = []
    rules = {r.trigger_type: r for r in NotificationRule.query.filter_by(is_active=True).all()}

    # --- ETA approaching ---
    rule = rules.get("eta_within_days")
    if rule:
        window = int(rule.trigger_value or 7)
        for s in Shipment.query.filter(Shipment.eta.isnot(None)).all():
            if not s.is_open or not s.eta:
                continue
            if 0 <= (s.eta - today).days <= window and Stage.index(s.current_stage) < Stage.index(Stage.ARRIVED):
                if _already_sent(rule, s, within_days=3):
                    continue
                body = rule.template.format(**_context(s))
                for u in _recipients(rule.audience_role, s):
                    fired.append(_deliver(rule, u, s, f"[{s.reference_no}] Arriving soon", body))

    # --- delayed past ETA ---
    rule = rules.get("delay")
    if rule:
        for s in Shipment.query.all():
            if s.is_delayed and not _already_sent(rule, s, within_days=3):
                body = rule.template.format(**_context(s))
                for u in _recipients(rule.audience_role, s):
                    fired.append(_deliver(rule, u, s, f"[{s.reference_no}] Delayed past ETA", body))

    # --- missing documents ---
    rule = rules.get("missing_document")
    if rule:
        grace = int(rule.trigger_value or 3)
        for s in Shipment.query.all():
            if not s.is_open or not s.missing_documents:
                continue
            if s.days_in_stage < grace:
                continue
            if _already_sent(rule, s, within_days=7):
                continue
            body = rule.template.format(**_context(s))
            for u in _recipients(rule.audience_role, s):
                fired.append(_deliver(rule, u, s, f"[{s.reference_no}] Missing documents", body))

    # --- overdue payments ---
    rule = rules.get("payment_overdue")
    if rule:
        for c in CostLine.query.filter(CostLine.due_date.isnot(None)).all():
            if not c.is_overdue or not c.shipment:
                continue
            if _already_sent(rule, c.shipment, within_days=7):
                continue
            body = rule.template.format(
                reference_no=c.shipment.reference_no, cost_type=c.type_label,
                amount=f"{c.amount:,.0f}", currency=c.currency,
                payable_to=c.payable_to or "—",
                due_date=c.due_date.strftime("%d %b %Y"))
            for u in _recipients(rule.audience_role, c.shipment):
                fired.append(_deliver(rule, u, c.shipment, f"[{c.shipment.reference_no}] Payment overdue", body))

    # --- overdue purchase orders ---
    rule = rules.get("po_overdue")
    if rule:
        for po in PurchaseOrder.query.all():
            if not po.is_overdue:
                continue
            body = rule.template.format(
                po_number=po.po_number,
                supplier=po.supplier.name if po.supplier else "—",
                expected_ready_date=po.expected_ready_date.strftime("%d %b %Y"))
            for u in _recipients(rule.audience_role):
                existing = NotificationLog.query.filter_by(rule_id=rule.id, recipient_id=u.id).all()
                if any(l.subject == f"[{po.po_number}] PO overdue" and l.sent_at
                       and l.sent_at.date() > today - timedelta(days=7) for l in existing):
                    continue
                fired.append(_deliver(rule, u, None, f"[{po.po_number}] PO overdue", body))

    # --- weekly digest ---
    rule = rules.get("digest")
    if rule and not _already_sent(rule, None, within_days=7):
        open_shipments = [s for s in Shipment.query.all() if s.is_open]
        delayed = [s for s in open_shipments if s.is_delayed]
        unallocated = 0
        for s in open_shipments:
            for item in s.items:
                unallocated += item.qty_unallocated
        body = rule.template.format(open_count=len(open_shipments), delayed_count=len(delayed),
                                    unallocated_count=int(unallocated))
        for u in _recipients(rule.audience_role):
            fired.append(_deliver(rule, u, None, "Weekly shipment pipeline digest", body))

    db.session.commit()
    return fired
