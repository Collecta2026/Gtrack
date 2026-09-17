from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required

from ..models import (db, Supplier, Brand, Carrier, ConsigneeEntity, Customer, Bank,
                      Location, CustomsBroker, User, PARTY_TYPES, LOCATION_TYPES)
from ..auth import permission_required

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


@bp.route("/<entity>")
@login_required
def listing(entity):
    if entity not in REGISTRY:
        abort(404)
    model, label, fields = REGISTRY[entity]
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
