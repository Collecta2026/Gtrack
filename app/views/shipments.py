import os
from datetime import date, datetime, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   abort, send_file, current_app)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..models import (db, Shipment, ShipmentItem, Asset, Allocation, StatusHistory,
                      Document, CostLine, Comment, FreightQuotation, BankRegistration,
                      SupplierInvoice, Supplier, Brand, Carrier, ConsigneeEntity, Customer,
                      Bank, PurchaseOrder, Stage, DOC_TYPES, COST_TYPES, PAYMENT_STATUSES,
                      MODES, SERVICE_TYPES, CURRENCIES, ASSET_STATUSES, to_base,
                      Location, CustomsBroker, ROUTE_TYPES, BL_TYPES,
                      SHIPMENT_PAYMENT_TERMS, PAID_BY, ITEM_CATEGORIES, QUOTE_COST_ELEMENTS)
from ..auth import permission_required, can_view_shipment, visible_shipments
from ..notifications import fire_stage_rules
from ..exports import export_response
from ..audit import log_action
from ..i18n import t

bp = Blueprint("shipments", __name__)


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


def _base_amount(amount, currency):
    rates = current_app.config["DEFAULT_RATES"]
    return (amount or 0) * rates.get(currency, 1.0)


def _get_shipment(shipment_id):
    shipment = db.session.get(Shipment, shipment_id)
    if not shipment:
        abort(404)
    if not can_view_shipment(shipment):
        abort(403)
    return shipment


# --------------------------------------------------------------------------
# List / board
# --------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    q = visible_shipments(Shipment.query)

    stage = request.args.get("stage") or ""
    brand_id = request.args.get("brand", type=int)
    supplier_id = request.args.get("supplier", type=int)
    mode = request.args.get("mode") or ""
    route = request.args.get("route") or ""
    # Sales users care about a customer's machine until it is installed — which is
    # after the import itself closes at warehouse receipt — so their default is "all".
    default_status = "open" if current_user.can("view_all") else "all"
    status_filter = request.args.get("status") or default_status
    search = (request.args.get("q") or "").strip()

    if stage:
        q = q.filter(Shipment.current_stage == stage)
    if brand_id:
        q = q.filter(Shipment.brand_id == brand_id)
    if supplier_id:
        q = q.filter(Shipment.supplier_id == supplier_id)
    if mode:
        q = q.filter(Shipment.mode == mode)
    if route:
        q = q.filter(Shipment.route_type == route)
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(
            Shipment.reference_no.ilike(like),
            Shipment.acid_number.ilike(like),
            Shipment.bl_awb_no.ilike(like),
            Shipment.description.ilike(like),
            Shipment.origin.ilike(like),
            Shipment.destination.ilike(like),
        ))

    shipments = q.order_by(Shipment.id.desc()).all()

    if status_filter == "open":
        shipments = [s for s in shipments if s.is_open]
    elif status_filter == "closed":
        shipments = [s for s in shipments if not s.is_open]
    elif status_filter == "delayed":
        shipments = [s for s in shipments if s.is_delayed]

    fmt = request.args.get("export")
    if fmt:
        headers = ["Reference", "Stage", "Route type", "Exporter", "Brand", "Supplier",
                   "Route", "Mode", "ETA", "Days in stage", "Value", "Customers"]
        rows = [[s.reference_no, s.stage_label, s.route_label,
                 s.exporter.name if s.exporter else "",
                 s.brand.brand_name if s.brand else "",
                 s.supplier.name if s.supplier else "",
                 f"{s.origin or ''} → {s.destination or ''}", (s.mode or "").upper(),
                 s.eta.strftime("%d %b %Y") if s.eta else "",
                 s.days_in_stage, round(s.total_value, 2),
                 ", ".join(c.customer_name for c in s.allocated_customers)]
                for s in shipments]
        return export_response(fmt, "shipments", "Shipment register", headers, rows)

    return render_template("shipments/index.html", shipments=shipments,
                           brands=Brand.query.order_by(Brand.brand_name).all(),
                           suppliers=Supplier.query.order_by(Supplier.name).all(),
                           stages=[(c, Stage.label(c)) for c in Stage.ORDER],
                           modes=MODES, route_types=ROUTE_TYPES, filters=dict(
                               stage=stage, brand=brand_id, supplier=supplier_id,
                               mode=mode, route=route, status=status_filter, q=search))


@bp.route("/board")
@login_required
def board():
    """In-flight work, plus anything received into the warehouse in the last 45 days
    so the warehouse and installation columns still show what has just landed."""
    recent_cutoff = date.today() - timedelta(days=45)
    all_shipments = visible_shipments(Shipment.query).all()

    shipments = []
    for s in all_shipments:
        if s.is_open:
            shipments.append(s)
        elif s.current_stage in (Stage.WAREHOUSE, Stage.INSTALLATION):
            landed = s.warehouse_date or s.stage_entered_at
            if landed and landed >= recent_cutoff:
                shipments.append(s)

    columns = []
    for code in Stage.ORDER:
        items = [s for s in shipments if s.current_stage == code]
        columns.append(dict(code=code, label=Stage.label(code),
                            owner=Stage.OWNERS.get(code, "—"), shipments=items))
    return render_template("shipments/board.html", columns=columns)


# --------------------------------------------------------------------------
# Detail
# --------------------------------------------------------------------------

@bp.route("/<int:shipment_id>")
@login_required
def detail(shipment_id):
    shipment = _get_shipment(shipment_id)

    timeline = []
    history = {h.status_code: h for h in shipment.status_history}
    current_index = Stage.index(shipment.current_stage)
    for i, code in enumerate(Stage.ORDER):
        entry = history.get(code)
        timeline.append(dict(
            code=code, label=Stage.label(code), owner=Stage.OWNERS.get(code, "—"),
            done=entry is not None or (current_index >= 0 and i < current_index),
            current=(code == shipment.current_stage),
            event_date=entry.event_date if entry else None,
            recorded_by=entry.recorded_by.name if entry and entry.recorded_by else None,
            note=entry.note if entry else None,
        ))

    return render_template(
        "shipments/detail.html", s=shipment, timeline=timeline,
        doc_types=DOC_TYPES, cost_types=COST_TYPES, payment_statuses=PAYMENT_STATUSES,
        currencies=CURRENCIES, asset_statuses=ASSET_STATUSES,
        customers=Customer.query.order_by(Customer.customer_name).all(),
        carriers=Carrier.query.order_by(Carrier.name).all(),
        banks=Bank.query.order_by(Bank.bank_name).all(),
        suppliers=Supplier.query.order_by(Supplier.name).all(),
        brands=Brand.query.order_by(Brand.brand_name).all(),
        item_categories=ITEM_CATEGORIES,
        paid_by_options=PAID_BY,
        quote_cost_elements=QUOTE_COST_ELEMENTS,
        next_stage=Stage.next_stage(shipment.current_stage),
    )


# --------------------------------------------------------------------------
# Create / edit
# --------------------------------------------------------------------------

@bp.route("/new", methods=["GET", "POST"])
@permission_required("edit_shipment")
def create():
    if request.method == "POST":
        last = Shipment.query.order_by(Shipment.id.desc()).first()
        next_num = (last.id + 1) if last else 1
        ref = request.form.get("reference_no") or f"SHP-{next_num:04d}"

        s = Shipment(
            reference_no=ref,
            po_id=request.form.get("po_id", type=int) or None,
            direction=request.form.get("direction") or "Import",
            supplier_id=request.form.get("supplier_id", type=int) or None,
            exporter_id=request.form.get("exporter_id", type=int) or None,
            customs_broker_id=request.form.get("customs_broker_id", type=int) or None,
            route_type=request.form.get("route_type") or "direct",
            from_location_id=request.form.get("from_location_id", type=int) or None,
            to_location_id=request.form.get("to_location_id", type=int) or None,
            pickup_address=request.form.get("pickup_address"),
            bl_type=request.form.get("bl_type") or None,
            payment_terms=request.form.get("payment_terms") or None,
            chargeable_weight_kg=_to_float(request.form.get("chargeable_weight_kg"), None),
            measurement_cbm=_to_float(request.form.get("measurement_cbm"), None),
            cut_off_date=_parse_date(request.form.get("cut_off_date")),
            customs_note=request.form.get("customs_note"),
            brand_id=request.form.get("brand_id", type=int) or None,
            consignee_id=request.form.get("consignee_id", type=int) or None,
            origin=request.form.get("origin"),
            destination=request.form.get("destination"),
            mode=request.form.get("mode"),
            service_type=request.form.get("service_type"),
            forwarder_id=request.form.get("forwarder_id", type=int) or None,
            express_carrier_id=request.form.get("express_carrier_id", type=int) or None,
            acid_number=request.form.get("acid_number"),
            bl_awb_no=request.form.get("bl_awb_no"),
            incoterm=request.form.get("incoterm"),
            gross_weight_kg=_to_float(request.form.get("gross_weight_kg"), None),
            description=request.form.get("description"),
            etd=_parse_date(request.form.get("etd")),
            eta=_parse_date(request.form.get("eta")),
            current_stage=request.form.get("current_stage") or Stage.PO_RAISED,
            stage_entered_at=date.today(),
            created_by_id=current_user.id,
        )
        db.session.add(s)
        db.session.flush()
        db.session.add(StatusHistory(shipment_id=s.id, status_code=s.current_stage,
                                     event_date=date.today(), recorded_by_id=current_user.id,
                                     note="Shipment created"))
        db.session.commit()
        flash(f"Shipment {s.reference_no} created.", "success")
        return redirect(url_for("shipments.detail", shipment_id=s.id))

    return render_template(
        "shipments/form.html", s=None,
        suppliers=Supplier.query.order_by(Supplier.name).all(),
        brands=Brand.query.order_by(Brand.brand_name).all(),
        consignees=ConsigneeEntity.query.order_by(ConsigneeEntity.name).all(),
        carriers=Carrier.query.order_by(Carrier.name).all(),
        pos=PurchaseOrder.query.order_by(PurchaseOrder.po_number).all(),
        locations=Location.query.order_by(Location.name).all(),
        brokers=CustomsBroker.query.order_by(CustomsBroker.name).all(),
        route_types=ROUTE_TYPES, bl_types=BL_TYPES,
        payment_terms=SHIPMENT_PAYMENT_TERMS,
        stages=[(c, Stage.label(c)) for c in Stage.ORDER],
        modes=MODES, service_types=SERVICE_TYPES)


@bp.route("/<int:shipment_id>/edit", methods=["GET", "POST"])
@permission_required("edit_shipment")
def edit(shipment_id):
    s = _get_shipment(shipment_id)
    if request.method == "POST":
        s.direction = request.form.get("direction")
        s.po_id = request.form.get("po_id", type=int) or None
        s.supplier_id = request.form.get("supplier_id", type=int) or None
        s.exporter_id = request.form.get("exporter_id", type=int) or None
        s.customs_broker_id = request.form.get("customs_broker_id", type=int) or None
        s.route_type = request.form.get("route_type") or s.route_type
        s.from_location_id = request.form.get("from_location_id", type=int) or None
        s.to_location_id = request.form.get("to_location_id", type=int) or None
        s.pickup_address = request.form.get("pickup_address")
        s.bl_type = request.form.get("bl_type") or None
        s.payment_terms = request.form.get("payment_terms") or None
        s.chargeable_weight_kg = _to_float(request.form.get("chargeable_weight_kg"), None)
        s.measurement_cbm = _to_float(request.form.get("measurement_cbm"), None)
        s.cut_off_date = _parse_date(request.form.get("cut_off_date"))
        s.customs_note = request.form.get("customs_note")
        s.brand_id = request.form.get("brand_id", type=int) or None
        s.consignee_id = request.form.get("consignee_id", type=int) or None
        s.origin = request.form.get("origin")
        s.destination = request.form.get("destination")
        s.mode = request.form.get("mode")
        s.service_type = request.form.get("service_type")
        s.forwarder_id = request.form.get("forwarder_id", type=int) or None
        s.express_carrier_id = request.form.get("express_carrier_id", type=int) or None
        s.acid_number = request.form.get("acid_number")
        s.bl_awb_no = request.form.get("bl_awb_no")
        s.incoterm = request.form.get("incoterm")
        s.gross_weight_kg = _to_float(request.form.get("gross_weight_kg"), None)
        s.description = request.form.get("description")
        s.etd = _parse_date(request.form.get("etd"))
        s.eta = _parse_date(request.form.get("eta"))
        s.actual_departure = _parse_date(request.form.get("actual_departure"))
        s.actual_arrival = _parse_date(request.form.get("actual_arrival"))
        s.clearance_date = _parse_date(request.form.get("clearance_date"))
        s.remarks = request.form.get("remarks")
        db.session.commit()
        flash("Shipment updated.", "success")
        return redirect(url_for("shipments.detail", shipment_id=s.id))

    return render_template(
        "shipments/form.html", s=s,
        suppliers=Supplier.query.order_by(Supplier.name).all(),
        brands=Brand.query.order_by(Brand.brand_name).all(),
        consignees=ConsigneeEntity.query.order_by(ConsigneeEntity.name).all(),
        carriers=Carrier.query.order_by(Carrier.name).all(),
        pos=PurchaseOrder.query.order_by(PurchaseOrder.po_number).all(),
        locations=Location.query.order_by(Location.name).all(),
        brokers=CustomsBroker.query.order_by(CustomsBroker.name).all(),
        route_types=ROUTE_TYPES, bl_types=BL_TYPES,
        payment_terms=SHIPMENT_PAYMENT_TERMS,
        stages=[(c, Stage.label(c)) for c in Stage.ORDER],
        modes=MODES, service_types=SERVICE_TYPES)


# --------------------------------------------------------------------------
# Stage progression
# --------------------------------------------------------------------------

@bp.route("/<int:shipment_id>/advance", methods=["POST"])
@permission_required("edit_stage")
def advance(shipment_id):
    s = _get_shipment(shipment_id)
    target = request.form.get("stage")
    event_date = _parse_date(request.form.get("event_date")) or date.today()
    note = request.form.get("note")

    if not target or target not in Stage.LABELS:
        flash("Unknown stage.", "error")
        return redirect(url_for("shipments.detail", shipment_id=s.id))

    old_stage = s.current_stage
    s.current_stage = target
    s.stage_entered_at = event_date

    # keep the convenience date columns in step with the timeline
    if target == Stage.DEPARTED:
        s.actual_departure = event_date
    elif target == Stage.ARRIVED:
        s.actual_arrival = event_date
    elif target == Stage.CLEARED:
        s.clearance_date = event_date
    elif target == Stage.WAREHOUSE:
        s.warehouse_date = event_date
        for asset in s.assets:
            if asset.status == "in_transit":
                asset.status = "allocated" if asset.allocation else "in_stock"
    elif target == Stage.INSTALLATION:
        for asset in s.assets:
            asset.status = "delivered"
            if not asset.warranty_start_date:
                asset.warranty_start_date = event_date

    db.session.add(StatusHistory(shipment_id=s.id, status_code=target, event_date=event_date,
                                 recorded_by_id=current_user.id, note=note))
    log_action("shipments", s.id, "stage_change", field="current_stage",
               old=old_stage, new=target)
    db.session.commit()

    fired = fire_stage_rules(s, target)
    msg = f"Stage set to {Stage.label(target)}."
    if fired:
        msg += f" {len(fired)} notification(s) generated."
    flash(msg, "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id))


# --------------------------------------------------------------------------
# Items / assets / allocations
# --------------------------------------------------------------------------

@bp.route("/<int:shipment_id>/items/add", methods=["POST"])
@permission_required("edit_shipment")
def add_item(shipment_id):
    s = _get_shipment(shipment_id)
    item = ShipmentItem(
        shipment_id=s.id,
        supplier_id=request.form.get("item_supplier_id", type=int) or None,
        brand_id=request.form.get("item_brand_id", type=int) or None,
        category=request.form.get("category") or None,
        description=request.form.get("description"),
        model_no=request.form.get("model_no"),
        specification=request.form.get("specification"),
        hs_code=request.form.get("hs_code"),
        qty=_to_float(request.form.get("qty"), 1),
        unit=request.form.get("unit") or "unit",
        unit_value=_to_float(request.form.get("unit_value")),
        invoice_value=_to_float(request.form.get("invoice_value"), None),
        actual_value=_to_float(request.form.get("actual_value"), None),
        invoice_no=request.form.get("invoice_no"),
        invoice_date=_parse_date(request.form.get("invoice_date")),
        net_weight_kg=_to_float(request.form.get("net_weight_kg"), None),
        gross_weight_kg=_to_float(request.form.get("gross_weight_kg"), None),
        dimensions=request.form.get("dimensions"),
        currency=request.form.get("currency") or "USD",
        is_serialised=bool(request.form.get("is_serialised")),
    )
    db.session.add(item)
    db.session.commit()
    flash("Item added.", "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id) + "#items")


@bp.route("/items/<int:item_id>/assets/add", methods=["POST"])
@permission_required("edit_asset")
def add_asset(item_id):
    item = db.session.get(ShipmentItem, item_id)
    if not item:
        abort(404)
    serials = [s.strip() for s in (request.form.get("serial_no") or "").split(",") if s.strip()]
    for serial in serials:
        db.session.add(Asset(
            shipment_item_id=item.id, serial_no=serial,
            model_no=request.form.get("model_no") or item.model_no,
            status=request.form.get("status") or "in_transit",
            warranty_months=int(request.form.get("warranty_months") or 12),
        ))
    item.is_serialised = True
    db.session.commit()
    flash(f"{len(serials)} serial number(s) recorded.", "success")
    return redirect(url_for("shipments.detail", shipment_id=item.shipment_id) + "#items")


@bp.route("/items/<int:item_id>/allocate", methods=["POST"])
@permission_required("edit_allocation")
def allocate(item_id):
    item = db.session.get(ShipmentItem, item_id)
    if not item:
        abort(404)

    asset_id = request.form.get("asset_id", type=int)
    customer_id = request.form.get("customer_id", type=int)
    if not customer_id:
        flash("Select a customer to allocate to.", "error")
        return redirect(url_for("shipments.detail", shipment_id=item.shipment_id) + "#items")

    alloc = Allocation(
        shipment_item_id=item.id,
        asset_id=asset_id or None,
        customer_id=customer_id,
        quantity=_to_float(request.form.get("quantity"), 1),
        allocated_date=date.today(),
        allocated_by_id=current_user.id,
        expected_install_date=_parse_date(request.form.get("expected_install_date")),
        sales_notes=request.form.get("sales_notes"),
    )
    db.session.add(alloc)
    if asset_id:
        asset = db.session.get(Asset, asset_id)
        if asset and asset.status in ("in_transit", "in_stock"):
            asset.status = "allocated"
    db.session.commit()
    flash("Allocation recorded.", "success")
    return redirect(url_for("shipments.detail", shipment_id=item.shipment_id) + "#items")


@bp.route("/allocations/<int:alloc_id>/confirm-install", methods=["POST"])
@permission_required("edit_allocation")
def confirm_install(alloc_id):
    alloc = db.session.get(Allocation, alloc_id)
    if not alloc:
        abort(404)
    alloc.install_confirmed_date = _parse_date(request.form.get("install_date")) or date.today()
    if alloc.asset:
        alloc.asset.status = "installed"
        if not alloc.asset.warranty_start_date:
            alloc.asset.warranty_start_date = alloc.install_confirmed_date
    db.session.commit()
    flash("Installation confirmed.", "success")
    return redirect(request.referrer or url_for("shipments.detail", shipment_id=alloc.shipment.id))


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

@bp.route("/<int:shipment_id>/documents/upload", methods=["POST"])
@permission_required("edit_document")
def upload_document(shipment_id):
    s = _get_shipment(shipment_id)
    doc_type = request.form.get("doc_type")
    file = request.files.get("file")

    if not file or not file.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("shipments.detail", shipment_id=s.id) + "#documents")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in current_app.config["ALLOWED_EXTENSIONS"]:
        flash(f"File type .{ext} is not allowed.", "error")
        return redirect(url_for("shipments.detail", shipment_id=s.id) + "#documents")

    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], s.reference_no)
    os.makedirs(folder, exist_ok=True)
    safe = secure_filename(file.filename)
    path = os.path.join(folder, safe)
    file.save(path)

    existing = Document.query.filter_by(shipment_id=s.id, doc_type=doc_type).first()
    if existing:
        existing.file_name = safe
        existing.file_path = path
        existing.file_size = os.path.getsize(path)
        existing.is_received = True
        existing.version = (existing.version or 1) + 1
        existing.uploaded_by_id = current_user.id
        existing.uploaded_at = datetime.utcnow()
    else:
        db.session.add(Document(
            shipment_id=s.id, doc_type=doc_type, file_name=safe, file_path=path,
            file_size=os.path.getsize(path), is_required=True, is_received=True,
            uploaded_by_id=current_user.id, uploaded_at=datetime.utcnow()))
    db.session.commit()
    flash("Document uploaded.", "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id) + "#documents")


@bp.route("/documents/<int:doc_id>/download")
@login_required
def download_document(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        abort(404)
    if not can_view_shipment(doc.shipment):
        abort(403)
    if not doc.file_path or not os.path.exists(doc.file_path):
        flash("The stored file is no longer available on disk.", "error")
        return redirect(url_for("shipments.detail", shipment_id=doc.shipment_id) + "#documents")
    log_action("documents", doc.id, "download", field="file_name", new=doc.file_name)
    db.session.commit()
    return send_file(doc.file_path, as_attachment=True, download_name=doc.file_name)


@bp.route("/<int:shipment_id>/documents/require", methods=["POST"])
@permission_required("edit_document")
def require_document(shipment_id):
    s = _get_shipment(shipment_id)
    doc_type = request.form.get("doc_type")
    if doc_type and not Document.query.filter_by(shipment_id=s.id, doc_type=doc_type).first():
        db.session.add(Document(shipment_id=s.id, doc_type=doc_type,
                                is_required=True, is_received=False))
        db.session.commit()
        flash("Document added to the checklist.", "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id) + "#documents")


# --------------------------------------------------------------------------
# Costs, quotations, bank registration, comments
# --------------------------------------------------------------------------

@bp.route("/<int:shipment_id>/costs/add", methods=["POST"])
@permission_required("edit_cost")
def add_cost(shipment_id):
    s = _get_shipment(shipment_id)
    amount = _to_float(request.form.get("amount"))
    currency = request.form.get("currency") or "EGP"
    db.session.add(CostLine(
        shipment_id=s.id,
        cost_type=request.form.get("cost_type"),
        description=request.form.get("description"),
        amount=amount, currency=currency,
        amount_base=_base_amount(amount, currency),
        payable_to=request.form.get("payable_to"),
        paid_by=request.form.get("paid_by") or "company",
        payment_status=request.form.get("payment_status") or "unpaid",
        due_date=_parse_date(request.form.get("due_date")),
        paid_date=_parse_date(request.form.get("paid_date")),
        payment_reference=request.form.get("payment_reference"),
        note=request.form.get("note")))
    db.session.commit()
    flash("Cost line added.", "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id) + "#costs")


@bp.route("/costs/<int:cost_id>/pay", methods=["POST"])
@permission_required("edit_cost")
def mark_cost_paid(cost_id):
    cost = db.session.get(CostLine, cost_id)
    if not cost:
        abort(404)
    cost.payment_status = "paid"
    cost.paid_date = date.today()
    cost.payment_reference = request.form.get("payment_reference") or cost.payment_reference
    db.session.commit()
    flash("Cost marked as paid.", "success")
    return redirect(url_for("shipments.detail", shipment_id=cost.shipment_id) + "#costs")


def _quotation_kwargs(form):
    """Build FreightQuotation kwargs from a submitted form — shared by the quick
    add on the shipment page and the standalone entry screen under Finance."""
    elements = {field: _to_float(form.get(field), None) for field, _ in QUOTE_COST_ELEMENTS}
    elements_total = sum(v or 0 for v in elements.values())
    # A forwarder's quote is usually broken down; fall back to a manually typed
    # lump sum for the rare one that only ever gives a single total.
    quoted_amount = elements_total if elements_total else _to_float(form.get("quoted_amount"), None)
    kwargs = dict(
        forwarder_id=form.get("forwarder_id", type=int) or None,
        quote_ref=form.get("quote_ref"),
        quote_date=_parse_date(form.get("quote_date")) or date.today(),
        quoted_amount=quoted_amount,
        currency=form.get("currency") or "USD",
        mode=form.get("mode"),
        transit_days=form.get("transit_days", type=int),
        valid_until=_parse_date(form.get("valid_until")),
        notes=form.get("notes"))
    kwargs.update(elements)
    return kwargs


@bp.route("/<int:shipment_id>/quotations/add", methods=["POST"])
@permission_required("edit_quotation")
def add_quotation(shipment_id):
    s = _get_shipment(shipment_id)
    db.session.add(FreightQuotation(shipment_id=s.id, **_quotation_kwargs(request.form)))
    db.session.commit()
    flash("Quotation logged.", "success")
    return redirect(request.form.get("next") or (url_for("shipments.detail", shipment_id=s.id) + "#quotations"))


@bp.route("/quotations/<int:quote_id>/select", methods=["POST"])
@permission_required("edit_quotation")
def select_quotation(quote_id):
    quote = db.session.get(FreightQuotation, quote_id)
    if not quote:
        abort(404)
    for other in quote.shipment.quotations:
        other.is_selected = False
    quote.is_selected = True
    if quote.forwarder_id:
        quote.shipment.forwarder_id = quote.forwarder_id
    db.session.commit()
    flash(f"Quotation {quote.quote_ref or ''} selected and forwarder set.", "success")
    return redirect(url_for("shipments.detail", shipment_id=quote.shipment_id) + "#quotations")


@bp.route("/<int:shipment_id>/bank-registration", methods=["POST"])
@permission_required("edit_bank_reg")
def bank_registration(shipment_id):
    """Add a banking record. A shipment part-paid in advance and part against
    documents produces more than one, so these accumulate rather than overwrite."""
    s = _get_shipment(shipment_id)
    record_id = request.form.get("record_id", type=int)
    reg = db.session.get(BankRegistration, record_id) if record_id else BankRegistration(shipment_id=s.id)
    reg.bank_id = request.form.get("bank_id", type=int) or None
    reg.registration_no = request.form.get("registration_no")
    reg.registration_date = _parse_date(request.form.get("registration_date"))
    reg.is_exempt = bool(request.form.get("is_exempt"))
    reg.exempt_reason = request.form.get("exempt_reason")
    reg.advance_payment_ref = request.form.get("advance_payment_ref")
    reg.swift_1 = request.form.get("swift_1")
    reg.swift_2 = request.form.get("swift_2")
    reg.amount = _to_float(request.form.get("amount"), None)
    reg.currency = request.form.get("currency") or None
    reg.transfer_date = _parse_date(request.form.get("transfer_date"))
    reg.notes = request.form.get("notes")
    if reg.id is None:
        db.session.add(reg)
    db.session.commit()
    flash("Banking record saved.", "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id) + "#customs")


@bp.route("/<int:shipment_id>/comments/add", methods=["POST"])
@permission_required("comment")
def add_comment(shipment_id):
    s = _get_shipment(shipment_id)
    body = (request.form.get("body") or "").strip()
    if body:
        db.session.add(Comment(shipment_id=s.id, user_id=current_user.id, body=body))
        db.session.commit()
        flash("Comment added.", "success")
    return redirect(url_for("shipments.detail", shipment_id=s.id) + "#comments")


# --------------------------------------------------------------------------
# Cost & contents statement
# --------------------------------------------------------------------------

def _upstream_cost_per_unit(item, _seen=None):
    """Freight, duty and handling already spent on an item before this leg.

    A machine that came into Cairo from the Jebel Ali fulfilment centre carries the
    cost of the inbound leg that first brought it into the free zone. Costing the
    re-export leg alone would understate what the unit actually cost to land, so the
    chain is walked back through `source_item` and each upstream leg's costs are
    apportioned by that line's share of its own shipment's goods value.
    """
    _seen = _seen or set()
    src = item.source_item
    if src is None or src.id in _seen:
        return 0.0
    _seen.add(src.id)

    up_ship = src.shipment
    if up_ship is None:
        return 0.0

    up_goods = up_ship.total_value_base or 0
    up_costs = sum((c.amount_base or 0) for c in up_ship.costs)
    line_base = to_base(src.line_value, src.currency)
    share = (line_base / up_goods) if up_goods else 0
    qty = src.qty or 0
    own = (up_costs * share / qty) if qty else 0.0

    # keep walking — a unit can cross more than one hub
    return own + _upstream_cost_per_unit(src, _seen)


def _statement_data(s):
    """Build the full cost trace and item listing for one shipment."""
    goods_base = s.total_value_base

    # costs grouped by category, in base currency
    by_type = {}
    for c in s.costs:
        row = by_type.setdefault(c.cost_type, dict(
            cost_type=c.cost_type, label=c.type_label, amount_base=0.0, lines=[], paid=0.0, unpaid=0.0))
        row["amount_base"] += (c.amount_base or 0)
        row["lines"].append(c)
        if c.payment_status == "paid":
            row["paid"] += (c.amount_base or 0)
        else:
            row["unpaid"] += (c.amount_base or 0)

    cost_total = sum(r["amount_base"] for r in by_type.values())
    landed_total = goods_base + cost_total

    # Landed cost is apportioned across items by their share of goods value —
    # the standard basis, and the only defensible one when a shipment mixes
    # a CBCT unit with a box of consumables.
    # NB: the key is 'item_rows', not 'items' — in Jinja, d.items on a dict
    # resolves to the dict's own .items() method, not this key.
    item_rows = []
    for item in s.items:
        line_base = to_base(item.line_value, item.currency)
        share = (line_base / goods_base) if goods_base else 0
        apportioned = cost_total * share
        landed = line_base + apportioned
        qty = item.qty or 0
        up_per_unit = _upstream_cost_per_unit(item)
        upstream = up_per_unit * qty
        item_rows.append(dict(
            item=item,
            line_base=line_base,
            share=share,
            apportioned=apportioned,
            landed=landed,
            landed_per_unit=(landed / qty) if qty else None,
            upstream=upstream,
            upstream_per_unit=up_per_unit,
            true_landed=landed + upstream,
            true_landed_per_unit=((landed + upstream) / qty) if qty else None,
            serials=[a.serial_no for a in item.assets],
            allocations=item.allocations,
        ))

    upstream_total = sum(r["upstream"] for r in item_rows)

    # the earlier legs whose costs are being carried forward, listed once each
    seen_legs, upstream_legs = set(), []
    for row in item_rows:
        if not row["upstream"]:
            continue
        src, walked = row["item"].source_item, set()
        while src is not None and src.id not in walked:
            walked.add(src.id)
            leg = src.shipment
            if leg is not None and leg.id not in seen_legs:
                seen_legs.add(leg.id)
                upstream_legs.append(leg)
            src = src.source_item

    return dict(
        goods_base=goods_base,
        upstream_total=upstream_total,
        true_landed_total=landed_total + upstream_total,
        upstream_legs=upstream_legs,
        by_type=sorted(by_type.values(), key=lambda r: -r["amount_base"]),
        cost_total=cost_total,
        landed_total=landed_total,
        paid_total=sum(r["paid"] for r in by_type.values()),
        unpaid_total=sum(r["unpaid"] for r in by_type.values()),
        item_rows=item_rows,
        quote=s.selected_quote,
        quoted_base=s.quoted_base,
        freight_actual_base=s.freight_actual_base,
        variance=s.quote_variance,
    )


# The plain top-down build-up a finance person actually thinks in — goods value,
# then shipping, customs, bank charges and last-mile — rather than the finer
# cost-type list the detailed Statement breaks costs into. Every cost_type in
# COST_TYPES must appear in exactly one bucket here, or its amount silently
# falls into "Other costs" instead (see the leftover fold below).
COST_BUILDUP_GROUPS = [
    ("shipping", "Shipping (freight)", {"freight", "ex_works", "thc", "express_fee"}),
    ("customs", "Customs & clearance", {"customs_duty", "customs_fees", "clearance_fee",
                                        "broker_fee", "inspection", "fumigation"}),
    ("bank", "Bank charges", {"bank_charges"}),
    ("last_mile", "Last-mile delivery", {"last_mile", "delivery_order"}),
    ("other", "Other costs", {"storage", "repacking", "relabelling", "insurance", "other"}),
]


def _cost_buildup(data):
    """Fold the Statement's by-type totals into the five named buckets above,
    so the build-up screen always reconciles exactly with the detailed Statement."""
    by_code = {row["cost_type"]: row for row in data["by_type"]}
    claimed = set()
    groups = []
    for key, label, codes in COST_BUILDUP_GROUPS:
        amount = sum(by_code[c]["amount_base"] for c in codes if c in by_code)
        claimed |= (codes & by_code.keys())
        groups.append(dict(key=key, label=t(label), amount=amount))
    leftover = sum(row["amount_base"] for code, row in by_code.items() if code not in claimed)
    if leftover:
        groups[-1]["amount"] += leftover
    return groups


@bp.route("/<int:shipment_id>/cost-buildup")
@login_required
def cost_buildup(shipment_id):
    """A separate, plain-English screen: goods value from the invoice, plus the
    shipping cost from the winning quote (or, once booked, what was actually
    spent), plus customs, bank charges and last-mile delivery, arriving at the
    total cost of the machine — as opposed to the detailed Statement, which
    apportions all of this down to a landed cost per item and per serial."""
    s = _get_shipment(shipment_id)
    data = _statement_data(s)
    groups = _cost_buildup(data)
    return render_template("shipments/cost_buildup.html", s=s, d=data, groups=groups)


@bp.route("/<int:shipment_id>/statement")
@login_required
def statement(shipment_id):
    s = _get_shipment(shipment_id)
    data = _statement_data(s)

    fmt = request.args.get("export")
    if fmt:
        base = current_app.config["BASE_CURRENCY"]
        headers = ["Section", "Detail", "Reference", "Qty", f"Amount ({base})", "Status"]
        rows = []

        rows.append(["ROUTING", s.route_label,
                     f"{s.origin or ''} → {s.destination or ''}", "", "", s.stage_label])
        if s.exporter:
            rows.append(["", "Exporter", s.exporter.name, "", "", ""])
        if s.customs_broker:
            rows.append(["", "Customs broker", s.customs_broker.name, "", "", ""])

        rows.append(["ITEMS", "", "", "", "", ""])
        for row in data["item_rows"]:
            item = row["item"]
            rows.append(["Item", item.description or "—",
                         f"{item.model_no or item.hs_code or ''}"
                         f"{(' · ' + item.supplier.name) if item.supplier else ''}".strip(),
                         f"{item.qty or 0:g} {item.unit or ''}".strip(),
                         round(row["line_base"], 2),
                         (", ".join(row["serials"])[:80] or "")])
        rows.append(["", "Goods value", "", "", round(data["goods_base"], 2), ""])

        rows.append(["COSTS", "", "", "", "", ""])
        for group in data["by_type"]:
            for c in group["lines"]:
                rows.append(["Cost", group["label"],
                             f"{c.description or ''} {('· ' + c.payable_to) if c.payable_to else ''}".strip(),
                             f"{c.amount:,.2f} {c.currency}" if c.amount else "",
                             round(c.amount_base or 0, 2),
                             c.payment_status_label])
        rows.append(["", "Total shipment cost", "", "", round(data["cost_total"], 2), ""])
        rows.append(["", "LANDED TOTAL", "", "", round(data["landed_total"], 2), ""])
        if data["upstream_total"]:
            legs = ", ".join(l.reference_no for l in data["upstream_legs"])
            rows.append(["", "Earlier leg costs carried forward", legs, "",
                         round(data["upstream_total"], 2), ""])
            rows.append(["", "TRUE LANDED TOTAL", "", "",
                         round(data["true_landed_total"], 2), ""])

        rows.append(["LANDED COST BY ITEM", "", "", "", "", ""])
        for row in data["item_rows"]:
            rows.append(["Landed", row["item"].description or "—",
                         f"incl. {row['upstream']:,.2f} earlier leg" if row["upstream"] else "",
                         f"{row['item'].qty or 0:g}",
                         round(row["true_landed"], 2),
                         f"{row['true_landed_per_unit']:,.2f}/unit" if row["true_landed_per_unit"] else ""])

        return export_response(fmt, f"statement_{s.reference_no}",
                               f"Cost & contents statement — {s.reference_no}",
                               headers, rows,
                               subtitle=f"{s.origin or ''} → {s.destination or ''} · {s.stage_label}")

    return render_template("shipments/statement.html", s=s, d=data)
