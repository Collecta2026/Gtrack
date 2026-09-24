from datetime import date

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   abort, current_app)
from flask_login import login_required, current_user

from ..models import (db, Asset, Allocation, ShipmentItem, Shipment, Customer,
                      Brand, ASSET_STATUSES, ITEM_CATEGORIES, Stage, to_base)
from ..auth import permission_required, any_permission
from ..exports import export_response

bp = Blueprint("assets", __name__)


@bp.route("/")
@login_required
def index():
    """Serial-number register — every individual unit, searchable."""
    search = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    brand_id = request.args.get("brand", type=int)
    category = request.args.get("category") or ""
    allocation = request.args.get("allocation") or ""

    assets = Asset.query.all()

    if search:
        needle = search.lower()
        assets = [a for a in assets if needle in (a.serial_no or "").lower()
                  or needle in (a.model_no or "").lower()
                  or (a.allocation and a.allocation.customer
                      and needle in a.allocation.customer.customer_name.lower())]
    if status:
        assets = [a for a in assets if a.status == status]
    if brand_id:
        assets = [a for a in assets if a.brand and a.brand.id == brand_id]
    if category:
        assets = [a for a in assets if a.item and a.item.category == category]
    if allocation == "unallocated":
        assets = [a for a in assets if not a.allocation]
    elif allocation == "allocated":
        assets = [a for a in assets if a.allocation]

    # sales users only see units allocated to their own customers
    if not current_user.can("view_all"):
        assets = [a for a in assets if a.allocation and a.allocation.customer
                  and a.allocation.customer.sales_owner_id == current_user.id]

    assets.sort(key=lambda a: (a.serial_no or ""))

    fmt = request.args.get("export")
    if fmt:
        headers = ["Serial no", "Model", "Brand", "Status", "Shipment", "Customer",
                   "Warranty start", "Warranty end", "Warranty active"]
        rows = [[a.serial_no, a.model_no, a.brand.brand_name if a.brand else "",
                 a.status_label, a.shipment.reference_no if a.shipment else "",
                 a.allocation.customer.customer_name if a.allocation and a.allocation.customer else "",
                 a.warranty_start_date.strftime("%d %b %Y") if a.warranty_start_date else "",
                 a.warranty_end_date.strftime("%d %b %Y") if a.warranty_end_date else "",
                 "Yes" if a.warranty_active else "No"] for a in assets]
        return export_response(fmt, "serial_register", "Machine & warranty register", headers, rows)

    return render_template("assets/index.html", assets=assets,
                           statuses=ASSET_STATUSES,
                           categories=ITEM_CATEGORIES,
                           brands=Brand.query.order_by(Brand.brand_name).all(),
                           filters=dict(q=search, status=status, brand=brand_id,
                                        category=category, allocation=allocation))


@bp.route("/<int:asset_id>")
@login_required
def detail(asset_id):
    asset = db.session.get(Asset, asset_id)
    if not asset:
        abort(404)
    if not current_user.can("view_all"):
        alloc = asset.allocation
        if not (alloc and alloc.customer and alloc.customer.sales_owner_id == current_user.id):
            abort(403)
    return render_template("assets/detail.html", a=asset,
                           customers=Customer.query.order_by(Customer.customer_name).all(),
                           statuses=ASSET_STATUSES)


@bp.route("/<int:asset_id>/status", methods=["POST"])
@permission_required("edit_asset")
def set_status(asset_id):
    asset = db.session.get(Asset, asset_id)
    if not asset:
        abort(404)
    asset.status = request.form.get("status") or asset.status
    asset.condition_notes = request.form.get("condition_notes") or asset.condition_notes
    db.session.commit()
    flash("Unit updated.", "success")
    return redirect(url_for("assets.detail", asset_id=asset.id))


@bp.route("/allocations")
@login_required
def allocations():
    """Allocation backlog — what's allocated, what's waiting, what's installed."""
    allocs = Allocation.query.all()
    if not current_user.can("view_all"):
        allocs = [a for a in allocs if a.customer and a.customer.sales_owner_id == current_user.id]

    pending_install = [a for a in allocs if not a.install_confirmed_date]
    installed = [a for a in allocs if a.install_confirmed_date]

    # units with no allocation yet
    unallocated = []
    shipment_q = Shipment.query.all() if current_user.can("view_all") else []
    for s in shipment_q:
        for item in s.items:
            if item.qty_unallocated > 0:
                unallocated.append(dict(shipment=s, item=item, qty=item.qty_unallocated))

    fmt = request.args.get("export")
    if fmt:
        headers = ["Customer", "Shipment", "Item", "Serial no", "Qty", "Allocated",
                   "Expected install", "Installed", "Sales owner"]
        rows = [[a.customer.customer_name if a.customer else "",
                 a.shipment.reference_no if a.shipment else "",
                 a.item.description if a.item else "",
                 a.asset.serial_no if a.asset else "",
                 a.quantity,
                 a.allocated_date.strftime("%d %b %Y") if a.allocated_date else "",
                 a.expected_install_date.strftime("%d %b %Y") if a.expected_install_date else "",
                 a.install_confirmed_date.strftime("%d %b %Y") if a.install_confirmed_date else "",
                 a.customer.sales_owner.name if a.customer and a.customer.sales_owner else ""]
                for a in allocs]
        return export_response(fmt, "allocations", "Customer allocations", headers, rows)

    return render_template("assets/allocations.html", pending=pending_install,
                           installed=installed, unallocated=unallocated)


@bp.route("/hub-stock")
@login_required
@permission_required("view_all")
def hub_stock():
    """What is sitting at the free-zone fulfilment centre.

    Goods on an inbound leg stay at Jebel Ali until an order calls them forward, so
    a line counts as still in stock when its inbound leg has landed and nothing has
    been re-exported against it yet. Part-called lines show the balance.
    """
    inbound = (Shipment.query
               .filter(Shipment.route_type == "inbound_hub")
               .order_by(Shipment.eta.desc()).all())

    rows, locations = [], {}
    for s in inbound:
        for item in s.items:
            called = sum((child.qty or 0) for child in (item.reexported_as or []))
            balance = (item.qty or 0) - called
            if balance <= 0:
                continue
            loc = s.to_location
            key = loc.id if loc else 0
            bucket = locations.setdefault(key, dict(
                location=loc, lines=0, units=0.0, value=0.0))
            bucket["lines"] += 1
            bucket["units"] += balance
            unit_value = item.unit_value or 0
            bucket["value"] += to_base(balance * unit_value, item.currency)
            rows.append(dict(
                shipment=s, item=item, location=loc,
                qty=item.qty or 0, called=called, balance=balance,
                value=to_base(balance * unit_value, item.currency),
                arrived=s.actual_arrival or s.eta,
                days_held=((date.today() - (s.actual_arrival or s.eta)).days
                           if (s.actual_arrival or s.eta) else None),
                serials=[a.serial_no for a in item.assets],
            ))

    rows.sort(key=lambda r: (r["days_held"] is None, -(r["days_held"] or 0)))

    fmt = request.args.get("export")
    if fmt:
        headers = ["Inbound leg", "Item", "Origin supplier", "Location",
                   "Qty in", "Called forward", "Balance held",
                   f"Value ({current_app.config['BASE_CURRENCY']})", "Arrived", "Days held"]
        out = [[r["shipment"].reference_no, r["item"].description or "",
                r["item"].supplier.name if r["item"].supplier else "",
                r["location"].name if r["location"] else "",
                r["qty"], r["called"], r["balance"], round(r["value"], 2),
                r["arrived"].strftime("%d %b %Y") if r["arrived"] else "",
                r["days_held"] if r["days_held"] is not None else ""]
               for r in rows]
        return export_response(fmt, "hub_stock", "Fulfilment centre stock", headers, out)

    return render_template("assets/hub_stock.html", rows=rows,
                           buckets=sorted(locations.values(),
                                          key=lambda b: -b["value"]))


@bp.route("/customers")
@login_required
def customers():
    """Customer view — what each customer is waiting for."""
    custs = Customer.query.order_by(Customer.customer_name).all()
    if not current_user.can("view_all"):
        custs = [c for c in custs if c.sales_owner_id == current_user.id]

    rows = []
    for c in custs:
        allocs = c.allocations
        pending = [a for a in allocs if not a.install_confirmed_date]
        next_eta = None
        for a in pending:
            s = a.shipment
            if s and s.eta and (next_eta is None or s.eta < next_eta):
                next_eta = s.eta
        rows.append(dict(customer=c, total=len(allocs), pending=len(pending),
                         installed=len(allocs) - len(pending), next_eta=next_eta,
                         allocations=pending))
    return render_template("assets/customers.html", rows=rows)
