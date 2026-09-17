from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from ..models import (db, PurchaseOrder, PurchaseOrderLine, SupplierInvoice, Supplier,
                      Brand, Shipment, PO_STATUSES, CURRENCIES, PAYMENT_STATUSES)
from ..auth import permission_required
from ..exports import export_response

bp = Blueprint("purchase_orders", __name__)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_float(value, default=0.0):
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return default


@bp.route("/")
@login_required
def index():
    status = request.args.get("status") or ""
    q = PurchaseOrder.query
    if status:
        q = q.filter(PurchaseOrder.status == status)
    pos = q.order_by(PurchaseOrder.id.desc()).all()

    fmt = request.args.get("export")
    if fmt:
        headers = ["PO number", "Supplier", "Brand", "Order date", "Expected ready",
                   "Status", "Lines", "Value", "Currency", "Overdue"]
        rows = [[p.po_number, p.supplier.name if p.supplier else "",
                 p.brand.brand_name if p.brand else "",
                 p.order_date.strftime("%d %b %Y") if p.order_date else "",
                 p.expected_ready_date.strftime("%d %b %Y") if p.expected_ready_date else "",
                 p.status_label, len(p.lines), round(p.total_value, 2), p.currency,
                 "Yes" if p.is_overdue else ""] for p in pos]
        return export_response(fmt, "purchase_orders", "Purchase orders", headers, rows)

    return render_template("purchase_orders/index.html", pos=pos,
                           statuses=PO_STATUSES, current_status=status)


@bp.route("/<int:po_id>")
@login_required
def detail(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    return render_template("purchase_orders/detail.html", po=po,
                           statuses=PO_STATUSES, currencies=CURRENCIES,
                           payment_statuses=PAYMENT_STATUSES)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("edit_po")
def create():
    if request.method == "POST":
        po = PurchaseOrder(
            po_number=request.form.get("po_number") or f"PO-{date.today().year}-{PurchaseOrder.query.count()+1:03d}",
            supplier_id=request.form.get("supplier_id", type=int) or None,
            brand_id=request.form.get("brand_id", type=int) or None,
            order_date=_parse_date(request.form.get("order_date")) or date.today(),
            expected_ready_date=_parse_date(request.form.get("expected_ready_date")),
            status=request.form.get("status") or "draft",
            currency=request.form.get("currency") or "USD",
            incoterm=request.form.get("incoterm"),
            notes=request.form.get("notes"),
            created_by_id=current_user.id)
        db.session.add(po)
        db.session.commit()
        flash(f"Purchase order {po.po_number} created.", "success")
        return redirect(url_for("purchase_orders.detail", po_id=po.id))

    return render_template("purchase_orders/form.html", po=None,
                           suppliers=Supplier.query.order_by(Supplier.name).all(),
                           brands=Brand.query.order_by(Brand.brand_name).all(),
                           statuses=PO_STATUSES, currencies=CURRENCIES)


@bp.route("/<int:po_id>/edit", methods=["GET", "POST"])
@permission_required("edit_po")
def edit(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    if request.method == "POST":
        po.supplier_id = request.form.get("supplier_id", type=int) or None
        po.brand_id = request.form.get("brand_id", type=int) or None
        po.order_date = _parse_date(request.form.get("order_date"))
        po.expected_ready_date = _parse_date(request.form.get("expected_ready_date"))
        po.status = request.form.get("status")
        po.currency = request.form.get("currency")
        po.incoterm = request.form.get("incoterm")
        po.notes = request.form.get("notes")
        db.session.commit()
        flash("Purchase order updated.", "success")
        return redirect(url_for("purchase_orders.detail", po_id=po.id))

    return render_template("purchase_orders/form.html", po=po,
                           suppliers=Supplier.query.order_by(Supplier.name).all(),
                           brands=Brand.query.order_by(Brand.brand_name).all(),
                           statuses=PO_STATUSES, currencies=CURRENCIES)


@bp.route("/<int:po_id>/lines/add", methods=["POST"])
@permission_required("edit_po")
def add_line(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    db.session.add(PurchaseOrderLine(
        po_id=po.id,
        description=request.form.get("description"),
        model_no=request.form.get("model_no"),
        qty_ordered=_to_float(request.form.get("qty_ordered"), 1),
        unit=request.form.get("unit") or "unit",
        unit_price=_to_float(request.form.get("unit_price")),
        currency=request.form.get("currency") or po.currency))
    db.session.commit()
    flash("PO line added.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po.id))


@bp.route("/<int:po_id>/invoices/add", methods=["POST"])
@permission_required("edit_supplier_invoice")
def add_invoice(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    db.session.add(SupplierInvoice(
        po_id=po.id,
        shipment_id=request.form.get("shipment_id", type=int) or None,
        invoice_no=request.form.get("invoice_no"),
        invoice_date=_parse_date(request.form.get("invoice_date")) or date.today(),
        invoice_value=_to_float(request.form.get("invoice_value")),
        currency=request.form.get("currency") or po.currency,
        payment_terms=request.form.get("payment_terms"),
        payment_status=request.form.get("payment_status") or "unpaid",
        notes=request.form.get("notes")))
    if po.status == "sent":
        po.status = "confirmed"
    db.session.commit()
    flash("Supplier invoice recorded.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po.id))


@bp.route("/<int:po_id>/status", methods=["POST"])
@permission_required("edit_po")
def set_status(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    po.status = request.form.get("status") or po.status
    db.session.commit()
    flash(f"PO status set to {po.status_label}.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po.id))
