from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required

from ..models import (db, Supplier, Brand, Carrier, ConsigneeEntity, Customer, Bank,
                      Location, CustomsBroker, User, Stage, PARTY_TYPES, LOCATION_TYPES)
from ..auth import permission_required
from ..exports import export_response, to_excel_workbook

bp = Blueprint("masters", __name__)

# entity key -> (model, label, fields[(name, label, type, options_key)])
REGISTRY = {
    "suppliers": (Supplier, "Suppliers & trading parties", [
        ("name", "Name", "text", None),
        ("party_type", "Party type", "select", "party_types"),
        ("country", "Country", "text", None),
        ("contact_name", "Contact", "text", None),
        ("contact_phone", "Phone", "text", None),
        ("contact_email", "Email", "text", None),
        ("brand_lines", "Brand lines", "text", None),
        ("payment_terms", "Payment terms", "text", None),
        ("lead_time_days", "Lead time (days)", "number", None),
    ]),
    "locations": (Location, "Locations & facilities", [
        ("name", "Name", "text", None),
        ("type", "Type", "select", "location_types"),
        ("is_free_zone", "Free zone", "checkbox", None),
        ("city", "City", "text", None),
        ("country", "Country", "text", None),
        ("address", "Address", "text", None),
        ("notes", "Notes", "text", None),
    ]),
    "brokers": (CustomsBroker, "Customs brokers", [
        ("name", "Name", "text", None),
        ("phone", "Phone", "text", None),
        ("contact_email", "Email", "text", None),
        ("licence_no", "Licence no", "text", None),
        ("notes", "Notes", "text", None),
    ]),
    "brands": (Brand, "Brands & product lines", [
        ("brand_name", "Brand", "text", None),
        ("category", "Category", "select", "categories"),
        ("notes", "Notes", "text", None),
    ]),
    "carriers": (Carrier, "Carriers & forwarders", [
        ("name", "Name", "text", None),
        ("type", "Type", "select", "carrier_types"),
        ("account_no", "Account no", "text", None),
        ("contact_name", "Contact", "text", None),
        ("contact_email", "Email", "text", None),
    ]),
    "consignees": (ConsigneeEntity, "Consignee entities", [
        ("name", "Name", "text", None),
        ("reg_no", "Registration no", "text", None),
        ("address", "Address", "text", None),
        ("contact_name", "Contact", "text", None),
        ("contact_phone", "Phone", "text", None),
    ]),
    "customers": (Customer, "Customers", [
        ("customer_name", "Customer", "text", None),
        ("sales_owner_id", "Sales owner", "select", "sales_owners"),
        ("install_site", "Install site", "text", None),
        ("city", "City", "text", None),
        ("contact_name", "Contact", "text", None),
        ("contact_phone", "Phone", "text", None),
    ]),
    "banks": (Bank, "Banks", [
        ("bank_name", "Bank", "text", None),
        ("branch", "Branch", "text", None),
    ]),
}

OPTIONS = {
    "party_types": PARTY_TYPES,
    "location_types": LOCATION_TYPES,
    "categories": [("equipment", "Equipment"), ("spare_part", "Spare part"),
                   ("consumable", "Consumable"), ("software", "Software licence")],
    "carrier_types": [("freight_forwarder", "Freight forwarder"), ("express_courier", "Express courier"),
                      ("shipping_line", "Shipping line"), ("airline", "Airline")],
}


def _options(key):
    if key == "sales_owners":
        return [(str(u.id), u.name) for u in User.query.order_by(User.name).all()]
    return OPTIONS.get(key, [])


@bp.route("/")
@login_required
def index():
    counts = {key: spec[0].query.count() for key, spec in REGISTRY.items()}
    return render_template("masters/index.html", registry=REGISTRY, counts=counts)


def _master_rows(entity):
    """One master-data list as (headers, rows), rendered the way the screen shows
    it — select fields resolved to their labels, not their stored codes."""
    model, label, fields = REGISTRY[entity]
    records = model.query.all()
    sort_field = fields[0][0]
    records.sort(key=lambda r: (getattr(r, sort_field) or "").lower()
                 if isinstance(getattr(r, sort_field), str) else "")

    headers = [f_label for _name, f_label, _type, _opts in fields]
    rows = []
    for record in records:
        row = []
        for name, _f_label, f_type, opts_key in fields:
            value = getattr(record, name, None)
            if f_type == "select" and opts_key:
                value = dict(_options(opts_key)).get(value, value)
            elif f_type == "checkbox":
                value = "Yes" if value else "No"
            row.append("" if value is None else value)
        rows.append(row)
    return label, headers, rows


@bp.route("/export")
@login_required
def export_all():
    """Every list in the system, as one Excel workbook — a sheet per dataset.
    Master data first, then the operational registers, so the whole thing can be
    handed to an accountant or kept as a point-in-time record."""
    from ..models import (Shipment, ShipmentItem, PurchaseOrder, SupplierInvoice,
                          FreightQuotation, CostLine, Asset, Allocation,
                          BankRegistration, Document)

    sheets = []
    for key in REGISTRY:
        label, headers, rows = _master_rows(key)
        sheets.append((label, headers, rows))

    sheets.append(("Shipments",
                   ["Reference", "Stage", "Status", "Route type", "Brand", "Supplier",
                    "Forwarder", "Origin", "Destination", "Mode", "ACID", "BL/AWB",
                    "ETD", "ETA", "Cleared", "Quantity", "Goods value", "Total cost"],
                   [[s.reference_no, s.stage_label, Stage.status_of(s.current_stage) or "",
                     s.route_label, s.brand.brand_name if s.brand else "",
                     s.supplier.name if s.supplier else "",
                     s.forwarder.name if s.forwarder else "",
                     s.origin, s.destination, (s.mode or "").upper(), s.acid_number,
                     s.bl_awb_no,
                     s.etd.strftime("%d %b %Y") if s.etd else "",
                     s.eta.strftime("%d %b %Y") if s.eta else "",
                     s.clearance_date.strftime("%d %b %Y") if s.clearance_date else "",
                     round(s.invoiced_qty, 2), round(s.total_value, 2),
                     round(s.total_cost, 2)]
                    for s in Shipment.query.order_by(Shipment.id).all()]))

    sheets.append(("Shipment items",
                   ["Shipment", "Description", "Model", "Category", "Qty", "Unit",
                    "Invoice value", "Actual value", "Currency", "HS code"],
                   [[i.shipment.reference_no if i.shipment else "", i.description,
                     i.model_no, i.category_label, i.qty, i.unit,
                     i.invoice_value, i.actual_value, i.currency, i.hs_code]
                    for i in ShipmentItem.query.order_by(ShipmentItem.id).all()]))

    sheets.append(("Purchase orders",
                   ["PO number", "Supplier", "Brand", "Ordered", "Expected ready",
                    "Status", "Models", "Quantity", "Lines", "Value", "Currency"],
                   [[p.po_number, p.supplier.name if p.supplier else "",
                     p.brand.brand_name if p.brand else "",
                     p.order_date.strftime("%d %b %Y") if p.order_date else "",
                     p.expected_ready_date.strftime("%d %b %Y") if p.expected_ready_date else "",
                     p.status_label, p.models_summary or "", p.qty_ordered_total,
                     len(p.lines), round(p.total_value, 2), p.currency]
                    for p in PurchaseOrder.query.order_by(PurchaseOrder.id).all()]))

    sheets.append(("Supplier invoices",
                   ["Invoice no", "Date", "Purchase order", "Shipment", "Quantity",
                    "Value", "Currency", "Status"],
                   [[v.invoice_no,
                     v.invoice_date.strftime("%d %b %Y") if v.invoice_date else "",
                     v.po.po_number if v.po else "",
                     v.shipment.reference_no if v.shipment else "",
                     v.quantity, v.invoice_value, v.currency, v.payment_status_label]
                    for v in SupplierInvoice.query.order_by(SupplierInvoice.id).all()]))

    sheets.append(("Freight quotations",
                   ["Shipment", "Brand", "Forwarder", "Quote ref", "Date", "Mode",
                    "Amount", "Currency", "Transit days", "Selected"],
                   [[q.shipment.reference_no if q.shipment else "",
                     q.shipment.brand.brand_name if q.shipment and q.shipment.brand else "",
                     q.forwarder.name if q.forwarder else "", q.quote_ref,
                     q.quote_date.strftime("%d %b %Y") if q.quote_date else "",
                     (q.mode or "").upper(), q.quoted_amount, q.currency,
                     q.transit_days, "Yes" if q.is_selected else "No"]
                    for q in FreightQuotation.query.order_by(FreightQuotation.id).all()]))

    sheets.append(("Costs",
                   ["Shipment", "Cost type", "Description", "Amount", "Currency",
                    "Amount (base)", "Payable to", "Status", "Due", "Paid"],
                   [[c.shipment.reference_no if c.shipment else "", c.type_label,
                     c.description, c.amount, c.currency, c.amount_base, c.payable_to,
                     c.payment_status_label,
                     c.due_date.strftime("%d %b %Y") if c.due_date else "",
                     c.paid_date.strftime("%d %b %Y") if c.paid_date else ""]
                    for c in CostLine.query.order_by(CostLine.id).all()]))

    sheets.append(("Serial register",
                   ["Serial no", "Model", "Brand", "Shipment", "Status", "Customer",
                    "Warranty start", "Warranty months"],
                   [[a.serial_no, a.model_no,
                     a.brand.brand_name if a.brand else "",
                     a.item.shipment.reference_no if a.item and a.item.shipment else "",
                     a.status_label,
                     a.allocation.customer.customer_name
                     if a.allocation and a.allocation.customer else "",
                     a.warranty_start_date.strftime("%d %b %Y") if a.warranty_start_date else "",
                     a.warranty_months]
                    for a in Asset.query.order_by(Asset.id).all()]))

    sheets.append(("Allocations",
                   ["Customer", "Shipment", "Serial no", "Quantity", "Allocated",
                    "Expected install", "Installed"],
                   [[al.customer.customer_name if al.customer else "",
                     al.item.shipment.reference_no if al.item and al.item.shipment else "",
                     al.asset.serial_no if al.asset else "", al.quantity,
                     al.allocated_date.strftime("%d %b %Y") if al.allocated_date else "",
                     al.expected_install_date.strftime("%d %b %Y") if al.expected_install_date else "",
                     al.install_confirmed_date.strftime("%d %b %Y") if al.install_confirmed_date else ""]
                    for al in Allocation.query.order_by(Allocation.id).all()]))

    sheets.append(("Form 4 register",
                   ["Shipment", "Bank", "Registration no", "Date", "Exempt",
                    "Amount", "Currency"],
                   [[b.shipment.reference_no if b.shipment else "",
                     b.bank.bank_name if b.bank else "", b.registration_no,
                     b.registration_date.strftime("%d %b %Y") if b.registration_date else "",
                     "Yes" if b.is_exempt else "No", b.amount, b.currency]
                    for b in BankRegistration.query.order_by(BankRegistration.id).all()]))

    sheets.append(("Documents",
                   ["Shipment", "Type", "Required", "Received", "File", "Notes"],
                   [[d.shipment.reference_no if d.shipment else "", d.type_label,
                     "Yes" if d.is_required else "No", "Yes" if d.is_received else "No",
                     d.file_name or "", d.notes or ""]
                    for d in Document.query.order_by(Document.id).all()]))

    stamp = date.today().strftime("%Y-%m-%d")
    return to_excel_workbook(f"gtrack_full_export_{stamp}", sheets)


@bp.route("/<entity>")
@login_required
def listing(entity):
    if entity not in REGISTRY:
        abort(404)
    model, label, fields = REGISTRY[entity]

    fmt = request.args.get("export")
    if fmt:
        export_label, headers, rows = _master_rows(entity)
        return export_response(fmt, f"master_{entity}", export_label, headers, rows)

    records = model.query.all()
    # sort by first text field
    sort_field = fields[0][0]
    records.sort(key=lambda r: (getattr(r, sort_field) or "").lower()
                 if isinstance(getattr(r, sort_field), str) else "")
    return render_template("masters/listing.html", entity=entity, label=label,
                           fields=fields, records=records, options_fn=_options)


@bp.route("/<entity>/save", methods=["POST"])
@permission_required("edit_masters")
def save(entity):
    if entity not in REGISTRY:
        abort(404)
    model, label, fields = REGISTRY[entity]

    record_id = request.form.get("id", type=int)
    record = db.session.get(model, record_id) if record_id else model()

    for name, _label, ftype, options_key in fields:
        raw = request.form.get(name)
        if ftype == "checkbox":
            value = bool(raw)
        elif ftype == "number":
            value = int(raw) if raw not in (None, "") else None
        elif name.endswith("_id"):
            value = int(raw) if raw not in (None, "") else None
        else:
            value = raw
        setattr(record, name, value)

    if not record_id:
        db.session.add(record)
    db.session.commit()
    flash(f"{label[:-1] if label.endswith('s') else label} saved.", "success")
    return redirect(url_for("masters.listing", entity=entity))
