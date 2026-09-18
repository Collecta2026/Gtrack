from datetime import date

from flask import Blueprint, render_template, request
from flask_login import login_required

from ..models import (db, CostLine, SupplierInvoice, FreightQuotation, Shipment,
                      BankRegistration, COST_TYPES, PAYMENT_STATUSES, Carrier,
                      CURRENCIES, QUOTE_COST_ELEMENTS, MODES)
from ..auth import any_permission
from ..exports import export_response

bp = Blueprint("finance", __name__)


@bp.route("/costs")
@any_permission("edit_cost", "view_reports", "view_all")
@login_required
def costs():
    status = request.args.get("status") or ""
    cost_type = request.args.get("cost_type") or ""

    q = CostLine.query
    if status:
        q = q.filter(CostLine.payment_status == status)
    if cost_type:
        q = q.filter(CostLine.cost_type == cost_type)
    lines = q.order_by(CostLine.due_date.is_(None), CostLine.due_date).all()

    totals = dict(
        total=sum((c.amount_base or 0) for c in lines),
        unpaid=sum((c.amount_base or 0) for c in lines if c.payment_status == "unpaid"),
        partial=sum((c.amount_base or 0) for c in lines if c.payment_status == "partial"),
        overdue=sum((c.amount_base or 0) for c in lines if c.is_overdue),
        overdue_count=sum(1 for c in lines if c.is_overdue),
    )

    fmt = request.args.get("export")
    if fmt:
        headers = ["Shipment", "Cost type", "Description", "Amount", "Currency",
                   "Amount (EGP)", "Payable to", "Status", "Due", "Paid"]
        rows = [[c.shipment.reference_no if c.shipment else "", c.type_label, c.description,
                 round(c.amount or 0, 2), c.currency, round(c.amount_base or 0, 2),
                 c.payable_to, c.payment_status_label,
                 c.due_date.strftime("%d %b %Y") if c.due_date else "",
                 c.paid_date.strftime("%d %b %Y") if c.paid_date else ""] for c in lines]
        return export_response(fmt, "shipment_costs", "Shipment costs", headers, rows)

    return render_template("finance/costs.html", lines=lines, totals=totals,
                           cost_types=COST_TYPES, payment_statuses=PAYMENT_STATUSES,
                           filters=dict(status=status, cost_type=cost_type))


@bp.route("/invoices")
@any_permission("edit_supplier_invoice", "view_reports", "view_all")
@login_required
def invoices():
    invoices = SupplierInvoice.query.order_by(SupplierInvoice.invoice_date.desc()).all()

    fmt = request.args.get("export")
    if fmt:
        headers = ["Invoice no", "Date", "PO", "Shipment", "Value", "Currency", "Status"]
        rows = [[i.invoice_no, i.invoice_date.strftime("%d %b %Y") if i.invoice_date else "",
                 i.po.po_number if i.po else "", i.shipment.reference_no if i.shipment else "",
                 round(i.invoice_value or 0, 2), i.currency, i.payment_status_label]
                for i in invoices]
        return export_response(fmt, "supplier_invoices", "Supplier invoices", headers, rows)

    total = sum((i.invoice_value or 0) for i in invoices)
    return render_template("finance/invoices.html", invoices=invoices, total=total)


@bp.route("/quotations")
@any_permission("edit_quotation", "view_reports", "view_all")
@login_required
def quotations():
    quotes = FreightQuotation.query.order_by(FreightQuotation.quote_date.desc()).all()

    # Quoted vs actual, for shipments where both exist. Both sides are converted to
    # the base currency first — quotes are usually in USD, freight invoices often in EGP.
    variances = []
    for s in Shipment.query.all():
        var = s.quote_variance
        if var is None:
            continue
        q = s.selected_quote
        quoted_base = s.quoted_base or 0
        variances.append(dict(shipment=s, quote=q, quoted=quoted_base,
                              actual=s.freight_actual_base, variance=var,
                              pct=(var / quoted_base * 100) if quoted_base else 0))
    variances.sort(key=lambda v: -abs(v["variance"]))

    fmt = request.args.get("export")
    if fmt:
        headers = ["Shipment", "Forwarder", "Quote ref", "Quoted (EGP)", "Actual freight (EGP)",
                   "Variance (EGP)", "Variance %"]
        rows = [[v["shipment"].reference_no,
                 v["quote"].forwarder.name if v["quote"].forwarder else "",
                 v["quote"].quote_ref, round(v["quoted"], 2), round(v["actual"], 2),
                 round(v["variance"], 2), f"{v['pct']:.1f}%"] for v in variances]
        return export_response(fmt, "quote_variance", "Quoted vs actual freight", headers, rows)

    return render_template("finance/quotations.html", quotes=quotes, variances=variances)


@bp.route("/quotations/new")
@any_permission("edit_quotation")
@login_required
def new_quotation():
    """A dedicated entry screen for a received forwarder quote — pick the
    shipment it's for, then break the price down to what it's actually made
    of (freight, export clearance, x-ray, handling, documentation, other)
    rather than logging one lump sum."""
    open_shipments = [s for s in Shipment.query.order_by(Shipment.reference_no.desc()).all()
                      if s.is_open]
    return render_template("finance/quotation_new.html", shipments=open_shipments,
                           carriers=Carrier.query.order_by(Carrier.name).all(),
                           currencies=CURRENCIES, quote_cost_elements=QUOTE_COST_ELEMENTS,
                           modes=MODES, today=date.today())


@bp.route("/bank-registrations")
@any_permission("edit_bank_reg", "view_reports", "view_all")
@login_required
def bank_registrations():
    regs = BankRegistration.query.all()
    shipments_missing = [s for s in Shipment.query.all()
                         if not s.bank_registration and s.is_open]

    fmt = request.args.get("export")
    if fmt:
        headers = ["Shipment", "Bank", "Registration no", "Date", "Exempt", "Reason"]
        rows = [[r.shipment.reference_no if r.shipment else "",
                 r.bank.bank_name if r.bank else "", r.registration_no,
                 r.registration_date.strftime("%d %b %Y") if r.registration_date else "",
                 "Yes" if r.is_exempt else "No", r.exempt_reason] for r in regs]
        return export_response(fmt, "form4_register", "Form 4 / bank registration", headers, rows)

    return render_template("finance/bank_registrations.html", regs=regs,
                           shipments_missing=shipments_missing)
