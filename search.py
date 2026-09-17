"""
Global search — one box that finds a shipment by any reference anyone actually
quotes in a conversation: the shipment number, ACID, bill of lading or air waybill,
the PO, the supplier's invoice number, a machine's serial number, a product or model,
or a customer, supplier or forwarder name.

Role scoping is respected throughout: a sales user only ever sees results tied to
their own customers.
"""
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from ..models import (db, Shipment, ShipmentItem, Asset, Allocation, PurchaseOrder,
                      SupplierInvoice, FreightQuotation, BankRegistration, Customer,
                      Supplier, Carrier, Stage)
from ..auth import can_view_shipment
from ..exports import export_response

bp = Blueprint("search", __name__)

# What each reference type is called, for the "matched on" label.
MATCH_LABELS = {
    "reference_no": "Shipment reference",
    "acid_number": "ACID number",
    "bl_awb_no": "BL / AWB number",
    "po_number": "PO number",
    "invoice_no": "Supplier invoice",
    "serial_no": "Serial number",
    "description": "Description",
    "model_no": "Model",
    "hs_code": "HS code",
    "quote_ref": "Quotation reference",
    "registration_no": "Form 4 registration",
    "customer": "Customer",
    "supplier": "Supplier",
    "carrier": "Carrier / forwarder",
    "origin": "Origin",
    "destination": "Destination",
    "remarks": "Remarks",
}


def _visible(shipment):
    return shipment is not None and can_view_shipment(shipment)


def _add(results, shipment, field, value, detail=None):
    """Record a hit, keeping one entry per shipment with all the reasons it matched."""
    if not _visible(shipment):
        return
    entry = results.get(shipment.id)
    if entry is None:
        entry = dict(shipment=shipment, matches=[])
        results[shipment.id] = entry
    label = MATCH_LABELS.get(field, field)
    reason = f"{label}: {value}"
    if detail:
        reason += f" — {detail}"
    if reason not in entry["matches"]:
        entry["matches"].append(reason)


def run_search(term):
    """Returns (shipment_results, other_results) for a free-text term."""
    like = f"%{term}%"
    results = {}

    # ---- shipment header fields ----
    header = Shipment.query.filter(db.or_(
        Shipment.reference_no.ilike(like),
        Shipment.acid_number.ilike(like),
        Shipment.bl_awb_no.ilike(like),
        Shipment.description.ilike(like),
        Shipment.origin.ilike(like),
        Shipment.destination.ilike(like),
        Shipment.remarks.ilike(like),
    )).all()
    for s in header:
        for field in ("reference_no", "acid_number", "bl_awb_no", "description",
                      "origin", "destination", "remarks"):
            value = getattr(s, field)
            if value and term.lower() in str(value).lower():
                _add(results, s, field, value)

    # ---- item level: product, model, HS code ----
    items = ShipmentItem.query.filter(db.or_(
        ShipmentItem.description.ilike(like),
        ShipmentItem.model_no.ilike(like),
        ShipmentItem.hs_code.ilike(like),
    )).all()
    for item in items:
        for field in ("description", "model_no", "hs_code"):
            value = getattr(item, field)
            if value and term.lower() in str(value).lower():
                _add(results, item.shipment, field, value, detail="item line")

    # ---- serial numbers ----
    for asset in Asset.query.filter(Asset.serial_no.ilike(like)).all():
        _add(results, asset.shipment, "serial_no", asset.serial_no,
             detail=asset.status_label)

    # ---- purchase orders ----
    pos = PurchaseOrder.query.filter(PurchaseOrder.po_number.ilike(like)).all()
    for po in pos:
        for s in po.shipments:
            _add(results, s, "po_number", po.po_number)

    # ---- supplier invoices ----
    for inv in SupplierInvoice.query.filter(SupplierInvoice.invoice_no.ilike(like)).all():
        target = inv.shipment
        if target is None and inv.po:
            for s in inv.po.shipments:
                _add(results, s, "invoice_no", inv.invoice_no, detail="via PO")
        else:
            _add(results, target, "invoice_no", inv.invoice_no)

    # ---- quotations ----
    for q in FreightQuotation.query.filter(FreightQuotation.quote_ref.ilike(like)).all():
        _add(results, q.shipment, "quote_ref", q.quote_ref)

    # ---- Form 4 registrations ----
    for reg in BankRegistration.query.filter(BankRegistration.registration_no.ilike(like)).all():
        _add(results, reg.shipment, "registration_no", reg.registration_no)

    # ---- customers (via allocation) ----
    customers = Customer.query.filter(Customer.customer_name.ilike(like)).all()
    for cust in customers:
        for alloc in cust.allocations:
            _add(results, alloc.shipment, "customer", cust.customer_name,
                 detail=(alloc.asset.serial_no if alloc.asset else "bulk allocation"))

    # ---- suppliers and carriers ----
    suppliers = Supplier.query.filter(Supplier.name.ilike(like)).all()
    for sup in suppliers:
        for s in sup.shipments:
            _add(results, s, "supplier", sup.name)

    carriers = Carrier.query.filter(Carrier.name.ilike(like)).all()
    for car in carriers:
        for s in Shipment.query.filter(db.or_(Shipment.forwarder_id == car.id,
                                              Shipment.express_carrier_id == car.id)).all():
            _add(results, s, "carrier", car.name)

    shipment_results = sorted(results.values(),
                              key=lambda e: (-len(e["matches"]), -e["shipment"].id))

    # ---- related records worth showing in their own right ----
    other = dict(
        purchase_orders=pos if current_user.can("view_all") else [],
        customers=[c for c in customers
                   if current_user.can("view_all") or c.sales_owner_id == current_user.id],
        suppliers=suppliers if current_user.can("view_all") else [],
        carriers=carriers if current_user.can("view_all") else [],
        assets=[a for a in Asset.query.filter(Asset.serial_no.ilike(like)).all()
                if _visible(a.shipment)],
    )
    return shipment_results, other


@bp.route("/")
@login_required
def index():
    term = (request.args.get("q") or "").strip()
    if not term:
        return render_template("search.html", term="", shipment_results=None, other=None)

    shipment_results, other = run_search(term)

    fmt = request.args.get("export")
    if fmt:
        headers = ["Reference", "Stage", "Brand", "Supplier", "Route", "ETA",
                   "Matched on", "Value", "Total cost (EGP)"]
        rows = [[e["shipment"].reference_no, e["shipment"].stage_label,
                 e["shipment"].brand.brand_name if e["shipment"].brand else "",
                 e["shipment"].supplier.name if e["shipment"].supplier else "",
                 f"{e['shipment'].origin or ''} → {e['shipment'].destination or ''}",
                 e["shipment"].eta.strftime("%d %b %Y") if e["shipment"].eta else "",
                 "; ".join(e["matches"]),
                 round(e["shipment"].total_value, 2),
                 round(e["shipment"].total_cost, 2)] for e in shipment_results]
        return export_response(fmt, "search_results", f"Search results for '{term}'",
                               headers, rows, subtitle=f"{len(rows)} shipment(s)")

    return render_template("search.html", term=term,
                           shipment_results=shipment_results, other=other)
