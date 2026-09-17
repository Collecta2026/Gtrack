"""
Gtrack — seed the test system from the real "Shipments Tracking.xlsx".

Run:  python seed.py            (rebuilds the database from scratch)
      python seed.py --keep     (adds only if the database is empty)

The migration follows Section 10 of the data design:
  1. master data extracted and de-duplicated
  2. numeric fields split from their embedded units/currency symbols
  3. free-text status mapped onto the twelve-stage pipeline
  4. one row -> one Shipment + one ShipmentItem, original description preserved
  5. shipping/customs costs split out into CostLine records
  6. nothing discarded — the original text is kept in legacy_status / remarks

Serial numbers, customers and allocations do not exist in the spreadsheet; a
representative demo set is generated so the equipment and allocation features
can be exercised.
"""
import os
import random
import re
import sys
from datetime import date, datetime, timedelta

import openpyxl

from app import create_app
from app.models import (db, Role, User, Supplier, Brand, Carrier, ConsigneeEntity, Customer,
                        Bank, PurchaseOrder, PurchaseOrderLine, SupplierInvoice,
                        FreightQuotation, Shipment, ShipmentItem, Asset, Allocation,
                        StatusHistory, Document, CostLine, BankRegistration, Comment,
                        ExchangeRate, Location, CustomsBroker, AssetMovement,
                        Stage, DOC_TYPES)
from app.auth import ROLE_DEFINITIONS
from app.notifications import seed_default_rules

SOURCE = os.path.join(os.path.dirname(__file__), "data", "Shipments_Tracking.xlsx")
random.seed(42)


# --------------------------------------------------------------------------
# Cleaning helpers
# --------------------------------------------------------------------------

def clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    if text in ("-", "—", "", "None", "Unknown", "?"):
        return None
    return re.sub(r"\s+", " ", text)


def fit_to_columns(session):
    """Truncate any string that exceeds its column's declared length.

    SQLite ignores VARCHAR limits; PostgreSQL rejects the insert outright. Real
    spreadsheet data is unpredictable — one cell in the source holds three HS codes —
    so rather than let a production seed die halfway through, over-long values are
    trimmed and reported.
    """
    from sqlalchemy import String

    trimmed = []
    for obj in list(session.new):
        table = getattr(obj, "__table__", None)
        if table is None:
            continue
        for col in table.columns:
            if not isinstance(col.type, String) or col.type.length is None:
                continue
            value = getattr(obj, col.name, None)
            if isinstance(value, str) and len(value) > col.type.length:
                setattr(obj, col.name, value[:col.type.length])
                trimmed.append(f"{table.name}.{col.name} ({len(value)} -> {col.type.length})")
    return trimmed


def canonical(value):
    """Normalise a master-data name so spelling/spacing variants collapse to one record."""
    text = clean_text(value)
    if not text:
        return None
    return text.strip(" .,").title() if text.isupper() or text.islower() else text.strip(" .,")


def parse_number(value):
    """Pull a number out of a cell that may carry units or a currency symbol."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def parse_currency(value, default="USD"):
    if value is None:
        return default
    text = str(value).upper()
    if "EGP" in text or "EG" in text and "$" not in text:
        return "EGP"
    if "$" in text or "USD" in text:
        return "USD"
    if "€" in text or "EUR" in text:
        return "EUR"
    return default


def parse_unit(value, default="unit"):
    if value is None:
        return default
    text = str(value).lower()
    for unit in ("bottle", "pallet", "carton", "box", "set", "pcs", "piece", "kg"):
        if unit in text:
            return unit
    return default


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


# SGE's own facilities. "Dubai" in the source sheet means the Jebel Ali free-zone
# fulfilment centre; goods land there and are re-exported to Egypt when needed.
HUB_PLACES = {"dubai", "jebel ali", "jabal ali", "uae"}
EGYPT_PLACES = {"cairo", "egypt", "alexandria", "sokhna"}
SYRIA_PLACES = {"syria", "damascus"}


def classify_route(origin, destination):
    """Work out how a leg sits in the two-step route, from where it ran.

    China -> Cairo   is a direct import.
    China -> Dubai   is an inbound leg to the fulfilment centre.
    Dubai -> Cairo   is a re-export out of the fulfilment centre.
    """
    o = (origin or "").strip().lower()
    d = (destination or "").strip().lower()
    o_hub = any(k in o for k in HUB_PLACES)
    d_hub = any(k in d for k in HUB_PLACES)
    o_eg = any(k in o for k in EGYPT_PLACES)
    d_eg = any(k in d for k in EGYPT_PLACES)
    d_sy = any(k in d for k in SYRIA_PLACES)

    if d_hub and not o_hub:
        return "inbound_hub"
    if o_hub and (d_eg or d_sy):
        return "reexport_hub"
    if o_eg and not d_eg:
        return "outbound"
    if o_hub and d_hub:
        return "internal"
    return "direct"


def split_route(pathway):
    """'From Dubai To Cairo' -> ('Dubai', 'Cairo')"""
    text = clean_text(pathway)
    if not text:
        return None, None
    match = re.search(r"from\s+(.+?)\s+to\s+(.+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().title(), match.group(2).strip().title()
    match = re.search(r"(.+?)\s+to\s+(.+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().title(), match.group(2).strip().title()
    return text, None


def parse_mode_service(shipping_type):
    """'FCL Al Sokhna Port' -> ('sea', 'fcl', 'Al Sokhna Port')"""
    text = (clean_text(shipping_type) or "").lower()
    if not text:
        return None, None, None
    port = None
    if "air" in text:
        return "air", "express", None
    if "land" in text:
        return "land", "general", None
    if "fcl" in text:
        extra = re.sub(r"fcl|-|\d+ft", "", text).strip()
        port = extra.title() if extra else None
        size = re.search(r"(\d+)\s*ft", text)
        return "sea", "fcl", (f"{size.group(1)}ft" if size else port)
    if "lcl" in text:
        extra = text.replace("lcl", "").strip()
        return "sea", "lcl", (extra.title() or None)
    if "sea" in text:
        return "sea", "general", None
    return None, None, None


STATUS_MAP = {
    "delivered": Stage.WAREHOUSE,
    "preparing": Stage.PREPARING,
    "in transit": Stage.IN_TRANSIT,
    "cancelled": Stage.CANCELLED,
    "canceled": Stage.CANCELLED,
}


def map_stage(status_text):
    text = (clean_text(status_text) or "").lower()
    if not text:
        return Stage.PREPARING
    if "تصدير" in text or "re-export" in text:
        return Stage.RE_EXPORTED
    for key, stage in STATUS_MAP.items():
        if key in text:
            return stage
    return Stage.PREPARING


def payment_status_from(text):
    """'Yes' / 'No' / 'Yes/ 10,000' / Arabic note -> unpaid|partial|paid"""
    if text is None:
        return "unpaid"
    lowered = str(text).lower()
    if "لم يتم" in lowered:            # "not paid"
        return "unpaid"
    if "no shipping fees" in lowered:
        return "paid"
    if lowered.strip() in ("no",):
        return "unpaid"
    if "yes" in lowered or "done" in lowered or "تم" in lowered:
        return "paid"
    if parse_number(text):
        return "paid"
    return "unpaid"


# Scientific Gate's own entities. Al Bawaba is SGE's free-zone arm, not a third party,
# so its shipments are intercompany movements rather than external purchases.
INTERNAL_PARTIES = {"al bawaba", "albawaba", "scientific gate", "scientific"}


def classify_party(name):
    """Return (party_type, is_internal) for a trading party."""
    lowered = (name or "").lower()
    if any(k in lowered for k in INTERNAL_PARTIES):
        return "internal_entity", True
    if any(k in lowered for k in ("freight", "cargo", "logistics", "shipping", "fzco")):
        return "freight_agent", False
    # Named manufacturers of the brands SGE carries
    if any(k in lowered for k in ("largev", "riton", "zotion", "alltion", "exocad",
                                  "aidite", "kingcera", "vhf", "shining", "launca",
                                  "technology", "instrument", "corp", "gmbh", "co.,ltd")):
        return "manufacturer", False
    return "trading_supplier", False


def carrier_type_for(name):
    lowered = (name or "").lower()
    if any(k in lowered for k in ("fedex", "dhl", "ups", "aramex")):
        return "express_courier"
    return "freight_forwarder"


def brand_category(brand_name):
    lowered = (brand_name or "").lower()
    if "spare" in lowered or "screen" in lowered:
        return "spare_part"
    if "powder" in lowered or "disc" in lowered or "cocr" in lowered or "titanium" in lowered \
            or "nickle" in lowered or "nickel" in lowered:
        return "consumable"
    if "exocad" in lowered:
        return "software"
    return "equipment"


def base_brand(shipment_type):
    """'Zotion Spare Parts' -> 'Zotion'; keeps consumables as their own line."""
    text = clean_text(shipment_type)
    if not text:
        return "Unclassified"
    return text


# --------------------------------------------------------------------------
# Master-data caches
# --------------------------------------------------------------------------

class Cache:
    def __init__(self):
        self.suppliers, self.brands, self.carriers = {}, {}, {}
        self.consignees, self.banks = {}, {}

    def supplier(self, name, country=None):
        key = (canonical(name) or "").lower()
        if not key:
            return None
        if key not in self.suppliers:
            party_type, internal = classify_party(canonical(name))
            rec = Supplier(name=canonical(name), country=country,
                           party_type=party_type, is_internal=internal,
                           lead_time_days=random.choice([21, 30, 45, 60]),
                           payment_terms=random.choice(["30% advance, 70% before shipment",
                                                        "100% advance", "L/C at sight",
                                                        "50% advance, 50% on delivery"]))
            db.session.add(rec)
            db.session.flush()
            self.suppliers[key] = rec
        return self.suppliers[key]

    def brand(self, name):
        key = (canonical(name) or "").lower()
        if not key:
            return None
        if key not in self.brands:
            rec = Brand(brand_name=canonical(name), category=brand_category(name))
            db.session.add(rec)
            db.session.flush()
            self.brands[key] = rec
        return self.brands[key]

    def carrier(self, name):
        key = (canonical(name) or "").lower()
        if not key:
            return None
        if key not in self.carriers:
            rec = Carrier(name=canonical(name), type=carrier_type_for(name))
            db.session.add(rec)
            db.session.flush()
            self.carriers[key] = rec
        return self.carriers[key]

    def consignee(self, name):
        key = (canonical(name) or "").lower()
        if not key:
            return None
        if key not in self.consignees:
            rec = ConsigneeEntity(name=canonical(name), is_importer_of_record=True)
            db.session.add(rec)
            db.session.flush()
            self.consignees[key] = rec
        return self.consignees[key]

    def bank(self, name):
        key = (canonical(name) or "").lower()
        if not key:
            return None
        if key not in self.banks:
            rec = Bank(bank_name=canonical(name))
            db.session.add(rec)
            db.session.flush()
            self.banks[key] = rec
        return self.banks[key]


# --------------------------------------------------------------------------
# Users and roles
# --------------------------------------------------------------------------

DEMO_USERS = [
    ("Zak Saleh", "zak@scientificgate.test", "admin"),
    ("Amr El-Bagoury", "amr@scientificgate.test", "management"),
    ("Mostafa Hassan", "procurement@scientificgate.test", "procurement"),
    ("Nourhan Adel", "logistics@scientificgate.test", "logistics"),
    ("Khaled Salah", "finance@scientificgate.test", "finance"),
    ("Sara Mahmoud", "sales1@scientificgate.test", "sales"),
    ("Omar Fathy", "sales2@scientificgate.test", "sales"),
    ("Hesham Zaki", "warehouse@scientificgate.test", "warehouse"),
]

DEMO_CUSTOMERS = [
    ("Nile Dental Centre", "Cairo", "Dr Hany Sobhy"),
    ("Alexandria Smile Clinic", "Alexandria", "Dr Mona Farid"),
    ("New Cairo Dental Lab", "New Cairo", "Eng. Tarek Aziz"),
    ("Giza Orthodontic Group", "Giza", "Dr Yara Selim"),
    ("Delta Prosthetics Lab", "Tanta", "Mr Sameh Nabil"),
    ("Maadi Implant Centre", "Cairo", "Dr Karim Wahba"),
    ("Heliopolis Dental Hospital", "Cairo", "Dr Laila Roushdy"),
    ("Damascus Dental Supplies", "Damascus", "Mr Bassel Haddad"),
]


def seed_roles_and_users():
    roles = {}
    for code, name, description, perms in ROLE_DEFINITIONS:
        role = Role(code=code, role_name=name, description=description, permissions=perms)
        db.session.add(role)
        roles[code] = role
    db.session.flush()

    users = {}
    for name, email, role_code in DEMO_USERS:
        user = User(name=name, email=email, role_id=roles[role_code].id, is_active_flag=True)
        user.set_password("demo1234")
        db.session.add(user)
        users[email] = user
    db.session.flush()
    return roles, users


SGE_LOCATIONS = [
    ("Jebel Ali Free Zone Fulfilment Centre", "fulfilment_centre", "Dubai",
     "United Arab Emirates", True,
     "Goods land here from origin suppliers and are re-exported to Egypt when needed."),
    ("Cairo Warehouse", "warehouse", "Cairo", "Egypt", False,
     "Main receiving warehouse for the Egyptian entity."),
    ("Damascus Office", "office", "Damascus", "Syria", False, "Syria branch."),
    ("Al Sokhna Port", "port", "Ain Sokhna", "Egypt", False, "Sea arrivals."),
    ("Cairo Airport", "port", "Cairo", "Egypt", False, "Air arrivals."),
]

# Brokers named in the source sheet's customs notes.
BROKERS = [("Hany", "+20 100 000 0000"), ("Tamer", "+20 101 000 0000"),
           ("Egyptian Freight Services", "+20 102 000 0000")]


def seed_locations():
    out = {}
    for name, ltype, city, country, free_zone, note in SGE_LOCATIONS:
        rec = Location(name=name, type=ltype, city=city, country=country,
                       is_free_zone=free_zone, notes=note)
        db.session.add(rec)
        out[ltype if ltype != "port" else name] = rec
    db.session.flush()
    return out


def seed_brokers():
    out = []
    for name, phone in BROKERS:
        rec = CustomsBroker(name=name, phone=phone)
        db.session.add(rec)
        out.append(rec)
    db.session.flush()
    return out


def seed_customers(users):
    sales_users = [u for u in users.values() if u.role and u.role.code == "sales"]
    customers = []
    for i, (name, city, contact) in enumerate(DEMO_CUSTOMERS):
        cust = Customer(customer_name=name, city=city, contact_name=contact,
                        install_site=f"{name}, {city}",
                        sales_owner_id=sales_users[i % len(sales_users)].id if sales_users else None,
                        contact_phone=f"+20 1{random.randint(10,29)} {random.randint(1000000,9999999)}")
        db.session.add(cust)
        customers.append(cust)
    db.session.flush()
    return customers


# --------------------------------------------------------------------------
# Spreadsheet migration
# --------------------------------------------------------------------------

def load_rows():
    wb = openpyxl.load_workbook(SOURCE, data_only=True)
    ws = wb["Raw Data"]
    headers = [c.value for c in ws[2]]          # real header row is row 2
    rows = []
    for r in range(3, ws.max_row + 1):
        row = {headers[i]: ws.cell(row=r, column=i + 1).value
               for i in range(len(headers)) if headers[i]}
        if any(v is not None for v in row.values()):
            rows.append(row)
    return rows


def migrate(cache, users, locations, brokers):
    rows = load_rows()
    admin = users["zak@scientificgate.test"]
    logistics = users["logistics@scientificgate.test"]
    shipments = []

    for idx, row in enumerate(rows, start=1):
        origin, destination = split_route(row.get("Pathway"))
        mode, service, container = parse_mode_service(row.get("Shipping type"))
        stage = map_stage(row.get("Status"))

        invoice_date = parse_date(row.get("Invoice Date"))
        clearance_date = parse_date(row.get(" Clearance Date"))
        eta = parse_date(row.get("Estimated Date of Arrival (ETA)"))
        etd = parse_date(row.get("Estimated Date of Departure (ETD)"))
        ets = parse_date(row.get("Estimated Date of Sailling (ETS)"))

        # Where the sheet has no ETD/ETA, derive plausible ones from the known dates
        if not etd and invoice_date:
            etd = invoice_date + timedelta(days=random.randint(5, 20))
        if not eta and etd:
            eta = etd + timedelta(days=random.randint(3, 40) if mode != "air" else random.randint(2, 6))

        route_type = classify_route(origin, destination)
        supplier_rec = cache.supplier(row.get("Supplier"))

        # Which SGE facility each end of this leg touches.
        hub = locations.get("fulfilment_centre")
        cairo = locations.get("warehouse")
        from_loc = hub if route_type in ("reexport_hub", "internal") else None
        to_loc = (hub if route_type == "inbound_hub"
                  else cairo if route_type in ("reexport_hub", "direct") else None)

        # On a re-export out of the free zone the shipper is SGE's own entity;
        # on a direct import it is the origin supplier itself.
        exporter_rec = supplier_rec
        if route_type == "reexport_hub":
            exporter_rec = cache.supplier("Al Bawaba") or supplier_rec

        shipment = Shipment(
            reference_no=f"SHP-{idx:04d}",
            direction=clean_text(row.get("Import / Export")) or "Import",
            route_type=route_type,
            from_location_id=from_loc.id if from_loc else None,
            to_location_id=to_loc.id if to_loc else None,
            exporter_id=exporter_rec.id if exporter_rec else None,
            customs_broker_id=(random.choice(brokers).id
                               if clean_text(row.get("Note/ Customs")) or
                               parse_number(row.get("Customs clearance cost")) else None),
            supplier_id=supplier_rec.id if supplier_rec else None,
            brand_id=(cache.brand(base_brand(row.get("Shipment type"))).id
                      if cache.brand(base_brand(row.get("Shipment type"))) else None),
            consignee_id=(cache.consignee(row.get("Consingnee")).id
                          if cache.consignee(row.get("Consingnee")) else None),
            origin=origin, destination=destination,
            mode=mode, service_type=service, container_size=container,
            forwarder_id=(cache.carrier(row.get("freight forwarder")).id
                          if cache.carrier(row.get("freight forwarder")) else None),
            express_carrier_id=(cache.carrier(row.get("Express Shipping")).id
                                if cache.carrier(row.get("Express Shipping")) else None),
            acid_number=clean_text(row.get("ACID")),
            bl_awb_no=clean_text(row.get("BL.Number")),
            gross_weight_kg=parse_number(row.get("G.W Weight")),
            # Not in the source sheet; derived so the fields are exercised and the
            # figures are plausible. Real values are entered going forward.
            chargeable_weight_kg=(round(parse_number(row.get("G.W Weight")) * 1.08, 1)
                                  if parse_number(row.get("G.W Weight")) else None),
            measurement_cbm=(round(parse_number(row.get("G.W Weight")) / 167.0, 2)
                             if parse_number(row.get("G.W Weight")) and mode == "sea" else None),
            bl_type=("master" if clean_text(row.get("BL.Number")) else None),
            payment_terms=random.choice(["advance", "cad", "lc"]),
            cut_off_date=(etd - timedelta(days=random.randint(2, 6))) if etd else None,
            customs_note=clean_text(row.get("Note/ Customs")),
            description=clean_text(row.get("Content Shipment")),
            etd=etd, eta=eta, ets=ets,
            clearance_date=clearance_date,
            current_stage=stage,
            stage_entered_at=clearance_date or eta or invoice_date or date.today(),
            legacy_status=clean_text(row.get("Status")),
            remarks=clean_text(row.get("Notes")) or clean_text(row.get("Remarks")),
            created_by_id=admin.id,
        )

        # closed shipments get their actual dates filled in from what the sheet knows
        if stage in (Stage.WAREHOUSE, Stage.RE_EXPORTED):
            shipment.actual_departure = etd
            shipment.actual_arrival = eta
            shipment.warehouse_date = clearance_date
        elif stage == Stage.IN_TRANSIT:
            shipment.actual_departure = etd

        db.session.add(shipment)
        db.session.flush()

        # ---- item line ----
        qty_raw = row.get("QTY")
        brand_rec = cache.brand(base_brand(row.get("Shipment type")))
        gross = parse_number(row.get("G.W Weight"))
        item = ShipmentItem(
            shipment_id=shipment.id,
            # The item carries its own origin supplier and brand. For the migrated
            # rows these match the header, but from here a consolidated re-export can
            # hold several suppliers on one shipment.
            supplier_id=supplier_rec.id if supplier_rec else None,
            brand_id=brand_rec.id if brand_rec else None,
            category=(brand_rec.category if brand_rec else None),
            description=clean_text(row.get("Content Shipment")) or clean_text(row.get("Shipment type")),
            model_no=clean_text(row.get("Shipment type")),
            hs_code=clean_text(row.get("HS.Code")),
            qty=parse_number(qty_raw) or 1,
            unit=parse_unit(qty_raw),
            unit_value=None,
            invoice_no=clean_text(row.get("InvoiceNo.")),
            invoice_date=invoice_date,
            currency=parse_currency(row.get("Invoice Value")),
            weight_kg=gross,
            gross_weight_kg=gross,
            net_weight_kg=round(gross * 0.94, 1) if gross else None,
        )
        invoice_value = parse_number(row.get("Invoice Value"))
        if invoice_value and item.qty:
            item.unit_value = invoice_value / item.qty
            item.invoice_value = invoice_value
            # The sheet records one figure only; actual value is left equal to the
            # invoiced figure so the variance reads zero until someone enters the real one.
            item.actual_value = invoice_value
        db.session.add(item)
        db.session.flush()

        # ---- supplier invoice ----
        invoice_no = clean_text(row.get("InvoiceNo."))
        if invoice_no or invoice_value:
            db.session.add(SupplierInvoice(
                shipment_id=shipment.id, invoice_no=invoice_no or f"INV-{idx:04d}",
                invoice_date=invoice_date, invoice_value=invoice_value,
                currency=parse_currency(row.get("Invoice Value")),
                payment_status="paid" if stage in (Stage.WAREHOUSE, Stage.RE_EXPORTED) else "unpaid"))

        # ---- costs ----
        freight_cost = parse_number(row.get("Shipping Cost"))
        if freight_cost:
            currency = parse_currency(row.get("Shipping Cost"), default="EGP")
            db.session.add(CostLine(
                shipment_id=shipment.id, cost_type="freight",
                description="Freight charge (migrated)",
                amount=freight_cost, currency=currency,
                amount_base=freight_cost * (48.5 if currency == "USD" else 1.0),
                payable_to=canonical(row.get("freight forwarder")),
                payment_status=payment_status_from(row.get("Paid/Shipper")),
                paid_by=random.choice(["company", "forwarder"]),
                paid_date=clearance_date if payment_status_from(row.get("Paid/Shipper")) == "paid" else None,
                note=clean_text(row.get("Note/Shipper"))))

        customs_cost = parse_number(row.get("Customs clearance cost")) or parse_number(row.get("Paid/Customs"))
        if customs_cost:
            db.session.add(CostLine(
                shipment_id=shipment.id, cost_type="customs_duty",
                description="Customs duty & clearance (migrated)",
                amount=customs_cost, currency="EGP", amount_base=customs_cost,
                payable_to="Egyptian Customs Authority", paid_by="company",
                payment_status=payment_status_from(row.get("Paid/Customs")),
                paid_date=clearance_date if payment_status_from(row.get("Paid/Customs")) == "paid" else None,
                note=clean_text(row.get("Note/ Customs"))))

        # ---- bank registration / Form 4 ----
        form4 = clean_text(row.get("نموذج 4 "))
        if form4:
            if "2000" in form4 or "<" in form4:
                db.session.add(BankRegistration(
                    shipment_id=shipment.id, is_exempt=True,
                    exempt_reason="Shipment value below the USD 2,000 reporting threshold"))
            else:
                bank = cache.bank(form4)
                db.session.add(BankRegistration(
                    shipment_id=shipment.id, bank_id=bank.id if bank else None,
                    registration_no=f"F4-{idx:05d}",
                    registration_date=invoice_date, is_exempt=False,
                    advance_payment_ref=f"APF-{invoice_date.year if invoice_date else 2024}-{idx:04d}",
                    swift_1=f"SWFT{random.randint(10**7, 10**8 - 1)}",
                    swift_2=(f"SWFT{random.randint(10**7, 10**8 - 1)}"
                             if random.random() > 0.65 else None),
                    amount=invoice_value, currency=parse_currency(row.get("Invoice Value")),
                    transfer_date=invoice_date))

        # ---- document checklist ----
        docs_held = (clean_text(row.get("DOC in Office")) or "").lower().startswith("yes")
        required_types = ["commercial_invoice", "packing_list", "bl_awb"]
        if shipment.acid_number:
            required_types.append("acid_certificate")
        if form4 and "2000" not in form4:
            required_types.append("form_4")
        for doc_type in required_types:
            db.session.add(Document(
                shipment_id=shipment.id, doc_type=doc_type, is_required=True,
                is_received=docs_held,
                file_name=f"{shipment.reference_no}_{doc_type}.pdf" if docs_held else None,
                uploaded_by_id=logistics.id if docs_held else None,
                uploaded_at=datetime.utcnow() if docs_held else None,
                notes="Migrated from 'DOC in Office' flag" if docs_held else "Outstanding"))

        # ---- status history reconstructed from known dates ----
        history_points = []
        if invoice_date:
            history_points.append((Stage.ORDER_CONFIRMED, invoice_date))
            history_points.append((Stage.PREPARING, invoice_date + timedelta(days=2)))
        if shipment.actual_departure:
            history_points.append((Stage.DEPARTED, shipment.actual_departure))
        if shipment.actual_arrival:
            history_points.append((Stage.ARRIVED, shipment.actual_arrival))
        if clearance_date:
            history_points.append((Stage.CUSTOMS_FILING, clearance_date - timedelta(days=3)))
            history_points.append((Stage.CLEARED, clearance_date))
        if stage == Stage.WAREHOUSE and clearance_date:
            history_points.append((Stage.WAREHOUSE, clearance_date + timedelta(days=1)))
        if stage == Stage.RE_EXPORTED and clearance_date:
            history_points.append((Stage.RE_EXPORTED, clearance_date + timedelta(days=5)))
        if not history_points:
            history_points.append((stage, shipment.stage_entered_at or date.today()))

        seen = set()
        for code, when in history_points:
            if code in seen or when is None:
                continue
            seen.add(code)
            db.session.add(StatusHistory(
                shipment_id=shipment.id, status_code=code, event_date=when,
                recorded_by_id=logistics.id, note="Reconstructed during migration"))

        shipments.append(shipment)

    db.session.commit()
    return shipments


# --------------------------------------------------------------------------
# Demo layer: serials, allocations, POs, quotations, comments
# --------------------------------------------------------------------------

def seed_demo_layer(shipments, customers, users):
    procurement = users["procurement@scientificgate.test"]
    logistics = users["logistics@scientificgate.test"]
    sales_users = [u for u in users.values() if u.role and u.role.code == "sales"]

    equipment_shipments = [s for s in shipments
                           if s.brand and s.brand.category == "equipment"][:45]

    # ---- serial numbers for equipment units ----
    assets = []
    for s in equipment_shipments:
        for item in s.items:
            qty = int(min(item.qty or 1, 6))
            item.is_serialised = True
            raw_prefix = (s.brand.brand_name if s.brand else "SGE")
            prefix = "".join(ch for ch in raw_prefix if ch.isalnum())[:3].upper() or "SGE"
            for n in range(qty):
                asset = Asset(
                    shipment_item_id=item.id,
                    serial_no=f"{prefix}-{s.reference_no.split('-')[1]}-{n+1:02d}",
                    model_no=item.model_no,
                    status=("in_stock" if s.current_stage == Stage.WAREHOUSE
                            else "in_transit" if s.is_open else "delivered"),
                    warranty_months=12)
                if s.current_stage in (Stage.WAREHOUSE, Stage.INSTALLATION) and s.warehouse_date:
                    asset.warranty_start_date = s.warehouse_date
                db.session.add(asset)
                assets.append(asset)
    db.session.flush()

    # ---- allocate roughly two-thirds of units to customers ----
    for asset in assets:
        if random.random() > 0.66:
            continue
        customer = random.choice(customers)
        shipment = asset.shipment
        allocated_on = (shipment.eta or shipment.stage_entered_at or date.today())
        alloc = Allocation(
            shipment_item_id=asset.shipment_item_id,
            asset_id=asset.id,
            customer_id=customer.id,
            quantity=1,
            allocated_date=allocated_on,
            allocated_by_id=random.choice(sales_users).id if sales_users else None,
            expected_install_date=allocated_on + timedelta(days=random.randint(7, 45)),
            sales_notes=random.choice([
                "Customer confirmed site readiness.",
                "Awaiting clinic refurbishment before installation.",
                "Deposit received; balance due on installation.",
                "Training session to be scheduled with the installation team.",
                None]))
        if asset.status in ("in_stock", "in_transit"):
            asset.status = "allocated"

        # Anything that landed in the warehouse more than 90 days ago would long since
        # have been installed — leaving those "pending" forever would misrepresent the
        # backlog. Recent arrivals stay pending so the installation queue is realistic.
        landed = shipment.warehouse_date or shipment.actual_arrival
        long_settled = landed and (date.today() - landed).days > 90
        if long_settled or (asset.status == "delivered" and random.random() > 0.4):
            install_on = (landed or allocated_on) + timedelta(days=random.randint(5, 30))
            alloc.install_confirmed_date = min(install_on, date.today())
            asset.status = "installed"
            if not asset.warranty_start_date:
                asset.warranty_start_date = alloc.install_confirmed_date
        db.session.add(alloc)
    db.session.flush()

    # ---- purchase orders for the more recent shipments ----
    recent = sorted([s for s in shipments if s.supplier_id], key=lambda s: s.id)[-30:]
    by_supplier = {}
    for s in recent:
        by_supplier.setdefault(s.supplier_id, []).append(s)

    po_count = 0
    for supplier_id, group in by_supplier.items():
        for s in group[:3]:
            po_count += 1
            order_date = (s.etd or date.today()) - timedelta(days=random.randint(25, 60))
            po = PurchaseOrder(
                po_number=f"PO-{order_date.year}-{po_count:03d}",
                supplier_id=supplier_id,
                brand_id=s.brand_id,
                order_date=order_date,
                expected_ready_date=order_date + timedelta(days=random.randint(20, 55)),
                status="fulfilled" if not s.is_open else random.choice(["confirmed", "part_shipped"]),
                currency="USD",
                incoterm=random.choice(["FOB", "CIF", "EXW", "CFR"]),
                created_by_id=procurement.id,
                notes="Created from the migrated shipment history.")
            db.session.add(po)
            db.session.flush()

            for item in s.items:
                line = PurchaseOrderLine(
                    po_id=po.id, description=item.description, model_no=item.model_no,
                    qty_ordered=item.qty or 1, unit=item.unit,
                    unit_price=item.unit_value or 0, currency=item.currency or "USD")
                db.session.add(line)
                db.session.flush()
                item.po_line_id = line.id

            s.po_id = po.id

    # a couple of deliberately overdue POs so the alert is visible
    for po in PurchaseOrder.query.filter_by(status="confirmed").limit(3).all():
        po.expected_ready_date = date.today() - timedelta(days=random.randint(5, 25))

    db.session.flush()

    # ---- freight quotations on open shipments ----
    forwarders = Carrier.query.filter_by(type="freight_forwarder").all()
    open_shipments = [s for s in shipments if s.is_open][:25]
    for s in open_shipments:
        if not forwarders:
            break
        chosen = random.sample(forwarders, k=min(3, len(forwarders)))
        base = random.randint(900, 6500)
        for i, fwd in enumerate(chosen):
            quote = FreightQuotation(
                shipment_id=s.id, forwarder_id=fwd.id,
                quote_ref=f"Q-{s.reference_no.split('-')[1]}-{i+1}",
                quote_date=(s.etd or date.today()) - timedelta(days=random.randint(5, 20)),
                quoted_amount=round(base * random.uniform(0.85, 1.3)),
                currency="USD", mode=s.mode,
                transit_days=random.randint(3, 40),
                valid_until=(s.etd or date.today()) + timedelta(days=20),
                is_selected=(i == 0))
            db.session.add(quote)
        if chosen:
            s.forwarder_id = chosen[0].id

    # ---- a realistic scatter of comments ----
    comment_texts = [
        "Supplier confirmed the units are ready for collection.",
        "Forwarder advised a two-day delay at origin — updated ETA accordingly.",
        "Customs requested the original certificate of origin; courier sent it today.",
        "Form 4 registered with the bank; copy uploaded to documents.",
        "Sales informed — customer notified that installation is approaching.",
        "Warehouse confirmed all serials match the packing list.",
        "Clearance agent's invoice received, passed to finance for payment.",
    ]
    all_users = list(users.values())
    for s in random.sample(shipments, k=min(35, len(shipments))):
        for _ in range(random.randint(1, 3)):
            db.session.add(Comment(
                shipment_id=s.id, user_id=random.choice(all_users).id,
                body=random.choice(comment_texts),
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 120))))

    # ---- due dates on unpaid costs so the overdue alert has something to find ----
    for cost in CostLine.query.filter(CostLine.payment_status != "paid").all():
        anchor = cost.shipment.eta if cost.shipment and cost.shipment.eta else date.today()
        cost.due_date = anchor + timedelta(days=random.randint(-20, 30))

    # ---- exchange rates ----
    for code, rate in [("EGP", 1.0), ("USD", 48.5), ("EUR", 52.0), ("CNY", 6.7), ("AED", 13.2)]:
        db.session.add(ExchangeRate(code=code, rate_to_base=rate, rate_date=date.today()))

    db.session.commit()


def link_hub_journeys(shipments, locations):
    """Connect the two halves of the route.

    Where goods came into the fulfilment centre on one leg and left on another, tie
    the re-export item line back to the inbound line it came from, and record the
    movement against each serialised unit. That is what lets a machine in Cairo be
    traced back through Jebel Ali to the shipment that first brought it in.
    """
    hub = locations.get("fulfilment_centre")
    cairo = locations.get("warehouse")

    inbound = [s for s in shipments if s.route_type == "inbound_hub"]
    reexport = sorted([s for s in shipments if s.route_type == "reexport_hub"],
                      key=lambda s: s.etd or date.today())

    # Index the inbound lines by brand so a re-export is matched to goods that
    # plausibly arrived earlier — the sheet never recorded the link explicitly.
    by_brand = {}
    for s_in in inbound:
        for item in s_in.items:
            if item.brand_id:
                by_brand.setdefault(item.brand_id, []).append(item)

    linked = 0
    for s_out in reexport:
        for item in s_out.items:
            candidates = by_brand.get(item.brand_id) or []
            match = next((c for c in candidates
                          if c.shipment and (not s_out.etd or not c.shipment.eta
                                             or c.shipment.eta <= s_out.etd)), None)
            if match:
                item.source_item_id = match.id
                linked += 1

    # Every serialised unit gets its movement history.
    moves = 0
    for s in shipments:
        for asset in s.assets:
            if s.route_type == "inbound_hub" and s.actual_arrival:
                db.session.add(AssetMovement(
                    asset_id=asset.id, shipment_id=s.id, movement_type="received",
                    movement_date=s.actual_arrival,
                    to_location_id=hub.id if hub else None,
                    note="Received into the fulfilment centre"))
                asset.current_location_id = hub.id if hub else None
                moves += 1
            elif s.route_type == "reexport_hub" and s.warehouse_date:
                db.session.add(AssetMovement(
                    asset_id=asset.id, shipment_id=s.id, movement_type="re_exported",
                    movement_date=s.warehouse_date,
                    from_location_id=hub.id if hub else None,
                    to_location_id=cairo.id if cairo else None,
                    note="Re-exported from the fulfilment centre to Cairo"))
                asset.current_location_id = cairo.id if cairo else None
                moves += 1
            elif s.warehouse_date:
                db.session.add(AssetMovement(
                    asset_id=asset.id, shipment_id=s.id, movement_type="received",
                    movement_date=s.warehouse_date,
                    to_location_id=cairo.id if cairo else None,
                    note="Received direct from origin"))
                asset.current_location_id = cairo.id if cairo else None
                moves += 1

    db.session.commit()
    return linked, moves


def make_open_pipeline(shipments):
    """The sheet is almost entirely historical ("Delivered"), which would leave the
    board empty. Everything still marked Preparing, plus the most recent deliveries,
    is spread across the live stages so the test system has a working pipeline.
    Historical records further back keep their migrated state untouched."""
    candidates = [s for s in shipments if s.current_stage == Stage.PREPARING]
    recent_delivered = sorted([s for s in shipments if s.current_stage == Stage.WAREHOUSE],
                              key=lambda s: s.id)[-22:]
    candidates = candidates + recent_delivered
    live_stages = [Stage.PO_RAISED, Stage.ORDER_CONFIRMED, Stage.PREPARING, Stage.DEPARTED,
                   Stage.IN_TRANSIT, Stage.ARRIVED, Stage.CUSTOMS_FILING, Stage.CLEARANCE,
                   Stage.CLEARED, Stage.OUT_FOR_DELIVERY]
    for i, s in enumerate(candidates):
        stage = live_stages[i % len(live_stages)]
        s.current_stage = stage
        s.stage_entered_at = date.today() - timedelta(days=random.randint(1, 28))
        if Stage.index(stage) >= Stage.index(Stage.DEPARTED):
            s.actual_departure = s.actual_departure or (date.today() - timedelta(days=random.randint(10, 40)))
        if Stage.index(stage) >= Stage.index(Stage.ARRIVED):
            s.actual_arrival = s.actual_arrival or (date.today() - timedelta(days=random.randint(1, 9)))
            s.eta = s.eta or s.actual_arrival
        else:
            # some of these should be running late, so the delay alert has real cases
            s.eta = date.today() + timedelta(days=random.randint(-12, 25))
        db.session.add(StatusHistory(
            shipment_id=s.id, status_code=stage, event_date=s.stage_entered_at,
            note="Set for the test pipeline"))
    db.session.commit()


# --------------------------------------------------------------------------

def confirm_target(keep):
    """Seeding DROPS and rebuilds every Gtrack table. Gtrack's table names are generic
    (users, roles, customers, documents...), so if this ever pointed at another
    application's database it would destroy that application's data. Refuse to run
    against anything but a local SQLite file unless the operator explicitly forces it."""
    from config import Config

    print(f"Target database: {Config.database_label()}")

    if Config.is_sqlite() or keep:
        return True

    if "--force" in sys.argv:
        print("  --force given: proceeding against a non-SQLite database.")
        return True

    print()
    print("  REFUSING TO CONTINUE.")
    print("  Seeding drops and recreates every Gtrack table, and this is not a local")
    print("  SQLite file. If GTRACK_DATABASE_URL points at a database another app uses,")
    print("  continuing would delete that app's tables.")
    print()
    print("  To seed a local test database instead, clear the variable for this window:")
    print("      Windows:      set GTRACK_DATABASE_URL=")
    print("      macOS/Linux:  unset GTRACK_DATABASE_URL")
    print()
    print("  If you really do intend to rebuild the database above, re-run with --force.")
    return False


def install_length_guard():
    """Apply fit_to_columns automatically before every flush during seeding."""
    from sqlalchemy import event

    reported = set()

    @event.listens_for(db.session, "before_flush")
    def _fit(session, flush_context, instances):
        for note in fit_to_columns(session):
            if note not in reported:
                reported.add(note)
                print(f"  note: trimmed over-long value in {note}")


def main():
    keep = "--keep" in sys.argv

    # Checked before the app is even created, so nothing connects to — let alone
    # touches — a database we have not cleared as safe.
    if not confirm_target(keep):
        sys.exit(1)

    app = create_app()
    with app.app_context():
        if keep:
            try:
                already = Shipment.query.count()
            except Exception:
                already = 0          # tables not created yet
            if already:
                print("Database already populated — nothing to do (--keep).")
                return

        install_length_guard()
        db.drop_all()
        db.create_all()
        print("Schema created.")

        roles, users = seed_roles_and_users()
        print(f"  {len(roles)} roles, {len(users)} users")

        locations = seed_locations()
        brokers = seed_brokers()
        print(f"  {len(locations)} locations, {len(brokers)} customs brokers")

        customers = seed_customers(users)
        print(f"  {len(customers)} customers")

        cache = Cache()
        shipments = migrate(cache, users, locations, brokers)
        print(f"  {len(shipments)} shipments migrated from the spreadsheet")
        print(f"  {len(cache.suppliers)} suppliers, {len(cache.brands)} brands, "
              f"{len(cache.carriers)} carriers, {len(cache.consignees)} consignees")

        make_open_pipeline(shipments)
        seed_demo_layer(shipments, customers, users)

        linked, moves = link_hub_journeys(shipments, locations)
        print(f"  {linked} re-export lines traced back through the fulfilment centre")
        print(f"  {moves} asset movements recorded")

        print(f"  {Asset.query.count()} serialised units, {Allocation.query.count()} allocations")
        print(f"  {PurchaseOrder.query.count()} purchase orders, "
              f"{FreightQuotation.query.count()} quotations")
        print(f"  {CostLine.query.count()} cost lines, {Document.query.count()} document records")

        seed_default_rules()
        from app.notifications import run_rule_sweep
        fired = run_rule_sweep()
        print(f"  {len(fired)} notifications generated by the first rule sweep")

        print("\nSeed complete. Sign in with any demo account, password: demo1234")
        for name, email, role in DEMO_USERS:
            print(f"  {email:42s} {role}")


if __name__ == "__main__":
    main()
