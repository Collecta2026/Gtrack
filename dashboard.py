from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from ..models import (db, Shipment, ShipmentItem, Allocation, Asset, CostLine,
                      PurchaseOrder, NotificationLog, Stage, to_base)
from ..auth import visible_shipments
from ..notifications import run_rule_sweep

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    shipments = visible_shipments(Shipment.query).all()
    open_shipments = [s for s in shipments if s.is_open]

    # pipeline counts by stage
    pipeline = []
    for code in Stage.ORDER:
        count = sum(1 for s in open_shipments if s.current_stage == code)
        pipeline.append(dict(code=code, label=Stage.label(code), count=count,
                             owner=Stage.OWNERS.get(code, "—")))

    delayed = [s for s in open_shipments if s.is_delayed]
    ageing = sorted([s for s in open_shipments if s.days_in_stage > 14],
                    key=lambda s: -s.days_in_stage)[:8]

    arriving_soon = sorted(
        [s for s in open_shipments if s.eta and 0 <= (s.eta - date.today()).days <= 21],
        key=lambda s: s.eta)[:8]

    # Allocation backlog. Counted in machines (serialised units), not bulk quantity —
    # a drum of powder and a CBCT unit are not the same kind of "unit".
    unallocated_units, awaiting_install = 0, 0
    for s in shipments:
        for item in s.items:
            for asset in item.assets:
                if not asset.allocation:
                    unallocated_units += 1
            for alloc in item.allocations:
                if not alloc.install_confirmed_date:
                    awaiting_install += 1

    value_in_transit = sum(s.total_value_base for s in open_shipments)
    unpaid_costs = sum(s.unpaid_cost for s in shipments)

    # Headline figures, alongside the exception alerts rather than instead of them.
    # The three plain statuses come from Stage.STATUS_GROUPS, the same map the
    # register's status filter uses, so a figure here and a filtered list there
    # can never disagree. Delivered means received into the warehouse.
    delivered_stages = Stage.stages_for_status("delivered")
    transit_stages = Stage.stages_for_status("in_transit")
    total_delivered = sum(1 for s in shipments if s.current_stage in delivered_stages)
    total_in_transit = sum(1 for s in shipments if s.current_stage in transit_stages)
    total_invoice_value = sum(s.total_value_base for s in shipments)

    # Stock sitting at the free-zone fulfilment centre. It is neither in transit nor
    # in the Cairo warehouse, so without this it is capital nobody is looking at.
    hub_value, hub_lines, hub_oldest = 0.0, 0, None
    cut_off_risk = []
    if current_user.can("view_all"):
        for s in Shipment.query.filter_by(route_type="inbound_hub").all():
            for item in s.items:
                called = sum((child.qty or 0) for child in (item.reexported_as or []))
                balance = (item.qty or 0) - called
                if balance <= 0:
                    continue
                hub_lines += 1
                hub_value += to_base(balance * (item.unit_value or 0), item.currency)
                landed = s.actual_arrival or s.eta
                if landed and (hub_oldest is None or landed < hub_oldest):
                    hub_oldest = landed
        cut_off_risk = [s for s in open_shipments if s.cut_off_missed][:5]

    recent_alerts = (NotificationLog.query.order_by(NotificationLog.sent_at.desc())
                     .limit(6).all()) if current_user.can("view_all") else (
        NotificationLog.query.filter_by(recipient_id=current_user.id)
        .order_by(NotificationLog.sent_at.desc()).limit(6).all())

    open_pos = PurchaseOrder.query.filter(
        PurchaseOrder.status.in_(["sent", "confirmed", "part_shipped"])).all() \
        if current_user.can("view_all") else []
    overdue_pos = [p for p in open_pos if p.is_overdue]

    stats = dict(
        total_delivered=total_delivered,
        total_in_transit=total_in_transit,
        total_invoice_value=total_invoice_value,
        open_shipments=len(open_shipments),
        delayed=len(delayed),
        arriving_soon=len(arriving_soon),
        unallocated_units=int(unallocated_units),
        awaiting_install=awaiting_install,
        value_in_transit=value_in_transit,
        unpaid_costs=unpaid_costs,
        open_pos=len(open_pos),
        overdue_pos=len(overdue_pos),
        hub_value=hub_value,
        hub_lines=hub_lines,
        hub_days=(date.today() - hub_oldest).days if hub_oldest else None,
        cut_off_risk=len(cut_off_risk),
    )

    return render_template("dashboard.html", stats=stats, pipeline=pipeline,
                           delayed=delayed[:8], ageing=ageing, arriving_soon=arriving_soon,
                           recent_alerts=recent_alerts, overdue_pos=overdue_pos[:5],
                           cut_off_risk=cut_off_risk)


@bp.route("/run-notifications", methods=["POST"])
@login_required
def run_notifications():
    fired = run_rule_sweep()
    flash(f"Notification sweep complete — {len(fired)} alert(s) generated.", "success")
    return redirect(request.referrer or url_for("dashboard.index"))
