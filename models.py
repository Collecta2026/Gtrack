"""
Scientific Gate Egypt — Import & Equipment Tracking System
SQLAlchemy models implementing the full data design.

Domains:
  Master data .... Supplier, Brand, Carrier, ConsigneeEntity, Customer, Bank
  Access ......... Role, User
  Procurement .... PurchaseOrder, PurchaseOrderLine, SupplierInvoice, FreightQuotation
  Shipment ....... Shipment, ShipmentItem, Asset, Allocation
  Operations ..... StatusHistory, Document, CostLine, BankRegistration, Comment
  System ......... NotificationRule, NotificationLog, AuditLog, ExchangeRate
"""
from datetime import datetime, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Indicative FX rates to the base currency (EGP) — the fallback used until an
# admin sets a rate from Admin -> FX rates, and for any currency they haven't
# touched. ExchangeRate (below) holds the dated series admins actually edit.
FX_RATES = {"EGP": 1.0, "USD": 48.5, "EUR": 52.0, "CNY": 6.7, "GBP": 61.0, "AED": 13.2}


def get_fx_rate(currency):
    """The rate currently in effect for `currency` -> EGP.

    Prefers the most recent admin-entered ExchangeRate row; falls back to the
    indicative FX_RATES default when nothing has been set. Cached for the
    life of a request (via flask.g) so looping over shipment lines doesn't
    re-query per line.
    """
    currency = currency or "EGP"
    if currency == "EGP":
        return 1.0

    cache = None
    try:
        from flask import g, has_app_context
        if has_app_context():
            cache = g.setdefault("_fx_rate_cache", {})
            if currency in cache:
                return cache[currency]
    except RuntimeError:
        cache = None

    rate = FX_RATES.get(currency, 1.0)
    try:
        row = (ExchangeRate.query.filter_by(code=currency)
               .order_by(ExchangeRate.rate_date.desc(), ExchangeRate.id.desc()).first())
        if row and row.rate_to_base:
            rate = row.rate_to_base
    except Exception:
        pass  # table not ready yet (e.g. pre-migration) — use the default

    if cache is not None:
        cache[currency] = rate
    return rate


def to_base(amount, currency):
    """Convert an amount into the base currency (EGP)."""
    if not amount:
        return 0.0
    return amount * get_fx_rate(currency)


# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------

class Stage:
    """The twelve-stage shipment pipeline from the data design."""
    PO_RAISED = "po_raised"
    ORDER_CONFIRMED = "order_confirmed"
    PREPARING = "preparing"
    DEPARTED = "departed"
    IN_TRANSIT = "in_transit"
    ARRIVED = "arrived"
    CUSTOMS_FILING = "customs_filing"
    CLEARANCE = "clearance"
    CLEARED = "cleared"
    OUT_FOR_DELIVERY = "out_for_delivery"
    WAREHOUSE = "warehouse"
    INSTALLATION = "installation"
    # exception end-states
    CANCELLED = "cancelled"
    RE_EXPORTED = "re_exported"

    ORDER = [PO_RAISED, ORDER_CONFIRMED, PREPARING, DEPARTED, IN_TRANSIT, ARRIVED,
             CUSTOMS_FILING, CLEARANCE, CLEARED, OUT_FOR_DELIVERY, WAREHOUSE, INSTALLATION]

    LABELS = {
        PO_RAISED: "PO Raised to Supplier",
        ORDER_CONFIRMED: "Order Confirmed + Supplier Invoice",
        PREPARING: "Preparing (Quote Selected & Booked)",
        DEPARTED: "Departed Origin",
        IN_TRANSIT: "In Transit",
        ARRIVED: "Arrived Destination",
        CUSTOMS_FILING: "Customs Filing (ACID + Form 4)",
        CLEARANCE: "Clearance In Progress",
        CLEARED: "Cleared / Released",
        OUT_FOR_DELIVERY: "Out for Delivery",
        WAREHOUSE: "Received into Warehouse",
        INSTALLATION: "Handed to Installation Team",
        CANCELLED: "Cancelled",
        RE_EXPORTED: "Re-exported / Returned to Supplier",
    }

    OWNERS = {
        PO_RAISED: "Procurement", ORDER_CONFIRMED: "Procurement", PREPARING: "Logistics",
        DEPARTED: "Logistics", IN_TRANSIT: "Logistics", ARRIVED: "Logistics",
        CUSTOMS_FILING: "Customs", CLEARANCE: "Customs", CLEARED: "Customs",
        OUT_FOR_DELIVERY: "Logistics", WAREHOUSE: "Warehouse", INSTALLATION: "Sales/Ops",
        CANCELLED: "—", RE_EXPORTED: "Customs",
    }

    # The import process itself completes at warehouse receipt — the scope boundary.
    # Installation handover is a post-receipt step tracked through Allocation.
    TERMINAL = {WAREHOUSE, INSTALLATION, CANCELLED, RE_EXPORTED}

    # The twelve stages rolled up into the three plain statuses the business uses
    # day to day. Defined once, here, so the register's status filter and the
    # dashboard's headline figures can never drift apart — they read the same map.
    # "Delivered" means received into the warehouse; installation handover sits
    # beyond that and is still, by definition, delivered.
    STATUS_GROUPS = [
        ("preparing", "Preparing", [PO_RAISED, ORDER_CONFIRMED, PREPARING]),
        ("in_transit", "In Transit", [DEPARTED, IN_TRANSIT, ARRIVED, CUSTOMS_FILING,
                                      CLEARANCE, CLEARED, OUT_FOR_DELIVERY]),
        ("delivered", "Delivered", [WAREHOUSE, INSTALLATION]),
    ]

    @classmethod
    def stages_for_status(cls, status):
        """The stage codes behind one of the three plain statuses, or None."""
        for key, _label, codes in cls.STATUS_GROUPS:
            if key == status:
                return codes
        return None

    @classmethod
    def status_of(cls, code):
        """Which of the three plain statuses a stage rolls up into. Cancelled and
        re-exported belong to none of them — they are reachable under "All"."""
        for key, _label, codes in cls.STATUS_GROUPS:
            if code in codes:
                return key
        return None

    @classmethod
    def label(cls, code):
        from .i18n import t
        return t(cls.LABELS.get(code, code or "—"))

    @classmethod
    def owner(cls, code):
        from .i18n import t
        return t(cls.OWNERS.get(code, "—"))

    @classmethod
    def index(cls, code):
        return cls.ORDER.index(code) if code in cls.ORDER else -1

    @classmethod
    def next_stage(cls, code):
        i = cls.index(code)
        if i < 0 or i >= len(cls.ORDER) - 1:
            return None
        return cls.ORDER[i + 1]


DOC_TYPES = [
    ("commercial_invoice", "Commercial Invoice"),
    ("packing_list", "Packing List"),
    ("bl_awb", "Bill of Lading / AWB"),
    ("acid_certificate", "ACID Certificate"),
    ("form_4", "Form 4 (Bank Import Registration)"),
    ("customs_declaration", "Customs Declaration"),
    ("certificate_of_origin", "Certificate of Origin"),
    ("insurance", "Insurance Certificate"),
    ("delivery_note", "Delivery Note"),
    ("other", "Other"),
]

COST_TYPES = [
    ("freight", "Ocean / Air Freight"),
    ("ex_works", "Ex-Works Charges"),
    ("delivery_order", "Delivery Order"),
    ("thc", "Terminal Handling (THC)"),
    ("customs_duty", "Customs Duty"),
    ("customs_fees", "Customs Fees"),
    ("clearance_fee", "Clearance Fee"),
    ("broker_fee", "Customs Broker Fees"),
    ("express_fee", "Express Courier Fee"),
    ("storage", "Storage / Demurrage"),
    ("fumigation", "Fumigation"),
    ("inspection", "Inspection Fees"),
    ("repacking", "Repacking"),
    ("relabelling", "Relabelling"),
    ("insurance", "Insurance"),
    ("bank_charges", "Bank Charges"),
    ("last_mile", "Last-Mile Delivery"),
    ("other", "Other"),
]

PAYMENT_STATUSES = [("unpaid", "Unpaid"), ("partial", "Partial"), ("paid", "Paid")]

PO_STATUSES = [
    ("draft", "Draft"), ("sent", "Sent"), ("confirmed", "Confirmed"),
    ("part_shipped", "Partially Shipped"), ("fulfilled", "Fulfilled"), ("cancelled", "Cancelled"),
]

ASSET_STATUSES = [
    ("in_transit", "In Transit"), ("in_stock", "In Stock"), ("allocated", "Allocated"),
    ("delivered", "Delivered"), ("installed", "Installed"),
]

# How this shipment leg sits in SGE's two-step supply route. Goods either come
# straight from the origin supplier to Cairo, or land first at the Jebel Ali free-zone
# fulfilment centre and are re-exported to Egypt when needed — and a re-export leg
# routinely consolidates items originally supplied by several different manufacturers.
ROUTE_TYPES = [
    ("direct", "Direct from origin"),
    ("inbound_hub", "Inbound to fulfilment centre"),
    ("reexport_hub", "Re-export from fulfilment centre"),
    ("internal", "Internal transfer"),
    ("outbound", "Outbound / return"),
]

LOCATION_TYPES = [
    ("fulfilment_centre", "Fulfilment centre"),
    ("warehouse", "Warehouse"),
    ("office", "Office"),
    ("port", "Port / airport"),
]

# Trading parties. Al Bawaba is Scientific Gate's own free-zone entity, not a third
# party, so intercompany movements can be told apart from genuine external purchases.
PARTY_TYPES = [
    ("manufacturer", "Manufacturer / brand owner"),
    ("trading_supplier", "Trading supplier"),
    ("internal_entity", "Internal SGE entity"),
    ("freight_agent", "Freight agent"),
]

BL_TYPES = [("master", "Master"), ("house", "House")]

SHIPMENT_PAYMENT_TERMS = [
    ("advance", "Advance"), ("cad", "Cash against documents"),
    ("lc", "Letter of credit"), ("open_account", "Open account"),
]

PAID_BY = [("company", "Company"), ("forwarder", "Forwarder"), ("supplier", "Supplier")]

ITEM_CATEGORIES = [
    ("equipment", "Equipment"), ("spare_part", "Spare part"),
    ("consumable", "Consumable"), ("software", "Software licence"),
]

MOVEMENT_TYPES = [
    ("received", "Received"), ("transferred", "Transferred"),
    ("re_exported", "Re-exported"), ("delivered", "Delivered"),
    ("returned", "Returned"),
]

MODES = [("air", "Air"), ("sea", "Sea"), ("land", "Land")]
SERVICE_TYPES = [("fcl", "FCL"), ("lcl", "LCL"), ("express", "Express"), ("courier", "Courier"), ("general", "General")]
CURRENCIES = ["EGP", "USD", "CNY", "EUR", "GBP", "AED"]


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------

class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    role_name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(300))
    permissions = db.Column(db.Text)  # comma-separated permission keys

    users = db.relationship("User", back_populates="role")

    def perm_list(self):
        return [p.strip() for p in (self.permissions or "").split(",") if p.strip()]

    def has(self, perm):
        perms = self.perm_list()
        return "*" in perms or perm in perms

    @property
    def name_label(self):
        from .i18n import t
        return t(self.role_name)

    def __repr__(self):
        return f"<Role {self.code}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    # On SQLite (dev/test only — Postgres never reuses a serial id), plain INTEGER
    # PRIMARY KEY can hand a deleted user's old id to the next new user. Audit-trail
    # rows referencing a user by id are kept even after that user is deleted, so a
    # reused id would make a brand-new account look like it already has history.
    # AUTOINCREMENT guarantees ids are never reused, matching real Postgres behaviour.
    __table_args__ = {"sqlite_autoincrement": True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    # Set whenever Admin gives this account a password (a brand-new account, or an
    # explicit reset) rather than the user choosing it themselves — cleared the
    # moment they set their own on the forced change-password screen.
    must_change_password = db.Column(db.Boolean, default=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"))
    phone = db.Column(db.String(40))
    language = db.Column(db.String(5), default="en")   # "en" or "ar"
    is_active_flag = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    role = db.relationship("Role", back_populates="users")
    customers = db.relationship("Customer", back_populates="sales_owner")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash or "", pw)

    @property
    def is_active(self):
        return bool(self.is_active_flag)

    def can(self, perm):
        return bool(self.role and self.role.has(perm))

    @property
    def role_code(self):
        return self.role.code if self.role else None

    def __repr__(self):
        return f"<User {self.email}>"


# --------------------------------------------------------------------------
# Master data
# --------------------------------------------------------------------------

class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(80))
    contact_name = db.Column(db.String(120))
    contact_email = db.Column(db.String(160))
    contact_phone = db.Column(db.String(60))
    brand_lines = db.Column(db.String(300))
    payment_terms = db.Column(db.String(120))
    lead_time_days = db.Column(db.Integer)
    # manufacturer / trading_supplier / internal_entity / freight_agent.
    # Internal entities (e.g. the Jebel Ali arm) are intercompany, not third-party spend.
    party_type = db.Column(db.String(40), default="trading_supplier")
    is_internal = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    shipments = db.relationship("Shipment", foreign_keys="Shipment.supplier_id",
                                back_populates="supplier")
    exported_shipments = db.relationship("Shipment", foreign_keys="Shipment.exporter_id",
                                         back_populates="exporter")
    purchase_orders = db.relationship("PurchaseOrder", back_populates="supplier")

    @property
    def party_type_label(self):
        from .i18n import t
        return t(dict(PARTY_TYPES).get(self.party_type, self.party_type))

    def __repr__(self):
        return f"<Supplier {self.name}>"


class Brand(db.Model):
    __tablename__ = "brands"
    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60))  # equipment / spare_part / consumable / software
    notes = db.Column(db.String(300))

    shipments = db.relationship("Shipment", back_populates="brand")

    def __repr__(self):
        return f"<Brand {self.brand_name}>"


class Carrier(db.Model):
    __tablename__ = "carriers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(40))  # freight_forwarder / express_courier / shipping_line / airline
    account_no = db.Column(db.String(80))
    contact_name = db.Column(db.String(120))
    contact_email = db.Column(db.String(160))
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Carrier {self.name}>"


class ConsigneeEntity(db.Model):
    __tablename__ = "consignee_entities"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    reg_no = db.Column(db.String(80))
    is_importer_of_record = db.Column(db.Boolean, default=True)
    address = db.Column(db.String(300))
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(60))

    shipments = db.relationship("Shipment", back_populates="consignee")

    def __repr__(self):
        return f"<Consignee {self.name}>"


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    sales_owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    install_site = db.Column(db.String(300))
    city = db.Column(db.String(80))
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(60))
    notes = db.Column(db.String(400))

    sales_owner = db.relationship("User", back_populates="customers")
    allocations = db.relationship("Allocation", back_populates="customer")

    def __repr__(self):
        return f"<Customer {self.customer_name}>"


class Location(db.Model):
    """An SGE facility — the Jebel Ali free-zone fulfilment centre, the Cairo
    warehouse, the Damascus office. Distinct from a customer's site."""
    __tablename__ = "locations"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    type = db.Column(db.String(40), default="warehouse")
    city = db.Column(db.String(80))
    country = db.Column(db.String(80))
    is_free_zone = db.Column(db.Boolean, default=False)
    address = db.Column(db.String(300))
    notes = db.Column(db.String(300))

    @property
    def type_label(self):
        from .i18n import t
        return t(dict(LOCATION_TYPES).get(self.type, self.type))

    def __repr__(self):
        return f"<Location {self.name}>"


class CustomsBroker(db.Model):
    __tablename__ = "customs_brokers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(60))
    contact_email = db.Column(db.String(160))
    licence_no = db.Column(db.String(80))
    notes = db.Column(db.String(300))
    is_active = db.Column(db.Boolean, default=True)

    shipments = db.relationship("Shipment", back_populates="customs_broker")

    def __repr__(self):
        return f"<Broker {self.name}>"


class Bank(db.Model):
    __tablename__ = "banks"
    id = db.Column(db.Integer, primary_key=True)
    bank_name = db.Column(db.String(160), nullable=False)
    branch = db.Column(db.String(120))

    def __repr__(self):
        return f"<Bank {self.bank_name}>"


class ExchangeRate(db.Model):
    __tablename__ = "exchange_rates"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), nullable=False)
    rate_to_base = db.Column(db.Float, nullable=False)  # base = EGP
    rate_date = db.Column(db.Date, default=date.today)


# --------------------------------------------------------------------------
# Procurement
# --------------------------------------------------------------------------

class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(60), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"))
    order_date = db.Column(db.Date)
    expected_ready_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="draft")
    currency = db.Column(db.String(8), default="USD")
    incoterm = db.Column(db.String(20))
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    supplier = db.relationship("Supplier", back_populates="purchase_orders")
    brand = db.relationship("Brand")
    created_by = db.relationship("User")
    lines = db.relationship("PurchaseOrderLine", back_populates="po", cascade="all, delete-orphan")
    shipments = db.relationship("Shipment", back_populates="po")
    invoices = db.relationship("SupplierInvoice", back_populates="po")

    @property
    def total_value(self):
        return sum((l.line_value or 0) for l in self.lines)

    @property
    def qty_ordered_total(self):
        """Units on the order, across all its lines."""
        return sum((l.qty_ordered or 0) for l in self.lines)

    @property
    def models_summary(self):
        """The models on the order, for the list view. One order usually covers
        one or two models; beyond that the count is more use than the names."""
        models = [l.model_no for l in self.lines if l.model_no]
        seen = list(dict.fromkeys(models))
        if not seen:
            return None
        if len(seen) <= 2:
            return ", ".join(seen)
        return f"{seen[0]}, {seen[1]} +{len(seen) - 2}"

    @property
    def status_label(self):
        from .i18n import t
        return t(dict(PO_STATUSES).get(self.status, self.status))

    @property
    def is_overdue(self):
        return (self.status in ("sent", "confirmed") and self.expected_ready_date
                and self.expected_ready_date < date.today())

    def __repr__(self):
        return f"<PO {self.po_number}>"


class PurchaseOrderLine(db.Model):
    __tablename__ = "purchase_order_lines"
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id"))
    description = db.Column(db.String(400))
    model_no = db.Column(db.String(120))
    qty_ordered = db.Column(db.Float, default=0)
    unit = db.Column(db.String(40), default="unit")
    unit_price = db.Column(db.Float, default=0)
    currency = db.Column(db.String(8), default="USD")

    po = db.relationship("PurchaseOrder", back_populates="lines")
    shipment_items = db.relationship("ShipmentItem", back_populates="po_line")

    @property
    def line_value(self):
        return (self.qty_ordered or 0) * (self.unit_price or 0)

    @property
    def qty_shipped(self):
        return sum((i.qty or 0) for i in self.shipment_items)

    @property
    def qty_outstanding(self):
        return max(0, (self.qty_ordered or 0) - self.qty_shipped)


class SupplierInvoice(db.Model):
    __tablename__ = "supplier_invoices"
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id"))
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    invoice_no = db.Column(db.String(80))
    invoice_date = db.Column(db.Date)
    invoice_value = db.Column(db.Float)
    currency = db.Column(db.String(8), default="USD")
    payment_terms = db.Column(db.String(120))
    payment_status = db.Column(db.String(20), default="unpaid")
    notes = db.Column(db.String(400))

    po = db.relationship("PurchaseOrder", back_populates="invoices")
    shipment = db.relationship("Shipment", back_populates="supplier_invoices")

    @property
    def payment_status_label(self):
        from .i18n import t
        return t(dict(PAYMENT_STATUSES).get(self.payment_status, self.payment_status))

    @property
    def quantity(self):
        """Units on this invoice. The shipment's item lines are entered from the
        supplier's invoice, so their quantities are the invoiced quantity."""
        return self.shipment.invoiced_qty if self.shipment else None


# The cost elements a freight forwarder's quote is actually made of. Column name
# first (what FreightQuotation stores it as, and what the entry form's field is
# named), label second (shown on screen, and passed through t()).
QUOTE_COST_ELEMENTS = [
    ("freight_cost", "Air / sea freight"),
    ("export_clearance_cost", "Export customs clearance"),
    ("xray_cost", "X-ray / scanning"),
    ("origin_handling_cost", "Origin handling"),
    ("documentation_cost", "Documentation fee"),
    ("other_cost", "Other"),
]


class FreightQuotation(db.Model):
    __tablename__ = "freight_quotations"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    forwarder_id = db.Column(db.Integer, db.ForeignKey("carriers.id"))
    quote_ref = db.Column(db.String(80))
    quote_date = db.Column(db.Date)
    quoted_amount = db.Column(db.Float)
    currency = db.Column(db.String(8), default="USD")
    mode = db.Column(db.String(20))
    transit_days = db.Column(db.Integer)
    valid_until = db.Column(db.Date)
    is_selected = db.Column(db.Boolean, default=False)
    notes = db.Column(db.String(300))

    # The quote broken down to what it is actually made of, rather than one lump
    # sum — a forwarder's quote bundles several separate charges, and comparing
    # quotes (or reconciling one against what was actually booked later) needs
    # those separately, not just the total they add up to.
    freight_cost = db.Column(db.Float)
    export_clearance_cost = db.Column(db.Float)
    xray_cost = db.Column(db.Float)
    origin_handling_cost = db.Column(db.Float)
    documentation_cost = db.Column(db.Float)
    other_cost = db.Column(db.Float)

    shipment = db.relationship("Shipment", back_populates="quotations")
    forwarder = db.relationship("Carrier")

    @property
    def elements_total(self):
        return sum((getattr(self, field) or 0) for field, _ in QUOTE_COST_ELEMENTS)

    @property
    def cost_breakdown(self):
        """The non-zero elements, labelled — empty for an older or lump-sum-only quote."""
        from .i18n import t
        return [(t(label), getattr(self, field)) for field, label in QUOTE_COST_ELEMENTS
                if getattr(self, field)]


# --------------------------------------------------------------------------
# Shipment core
# --------------------------------------------------------------------------

class Shipment(db.Model):
    __tablename__ = "shipments"
    id = db.Column(db.Integer, primary_key=True)
    reference_no = db.Column(db.String(40), unique=True, nullable=False)
    po_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id"))
    direction = db.Column(db.String(30), default="Import")
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    # Who ships THIS leg. For a direct import that is the origin supplier; for a
    # re-export it is SGE's own free-zone entity, which is why it is a separate field.
    exporter_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"))
    consignee_id = db.Column(db.Integer, db.ForeignKey("consignee_entities.id"))
    customs_broker_id = db.Column(db.Integer, db.ForeignKey("customs_brokers.id"))
    origin = db.Column(db.String(120))
    destination = db.Column(db.String(120))
    # Where the goods physically move between, when either end is an SGE facility.
    from_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"))
    to_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"))
    route_type = db.Column(db.String(30), default="direct")
    pickup_address = db.Column(db.String(400))
    mode = db.Column(db.String(20))
    service_type = db.Column(db.String(20))
    container_size = db.Column(db.String(30))
    forwarder_id = db.Column(db.Integer, db.ForeignKey("carriers.id"))
    express_carrier_id = db.Column(db.Integer, db.ForeignKey("carriers.id"))
    acid_number = db.Column(db.String(60))
    bl_awb_no = db.Column(db.String(80))
    bl_type = db.Column(db.String(20))
    incoterm = db.Column(db.String(20))
    payment_terms = db.Column(db.String(40))
    gross_weight_kg = db.Column(db.Float)
    # Air freight bills on the higher of actual and volumetric weight; sea LCL
    # prices on volume. Neither reconciles to a forwarder invoice without these.
    chargeable_weight_kg = db.Column(db.Float)
    measurement_cbm = db.Column(db.Float)
    description = db.Column(db.String(500))

    cut_off_date = db.Column(db.Date)
    etd = db.Column(db.Date)
    eta = db.Column(db.Date)
    ets = db.Column(db.Date)
    actual_departure = db.Column(db.Date)
    actual_arrival = db.Column(db.Date)
    clearance_date = db.Column(db.Date)
    warehouse_date = db.Column(db.Date)

    current_stage = db.Column(db.String(40), default=Stage.PO_RAISED)
    stage_entered_at = db.Column(db.Date, default=date.today)
    legacy_status = db.Column(db.String(80))
    remarks = db.Column(db.Text)
    customs_note = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    po = db.relationship("PurchaseOrder", back_populates="shipments")
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id],
                               back_populates="shipments")
    exporter = db.relationship("Supplier", foreign_keys=[exporter_id],
                               back_populates="exported_shipments")
    customs_broker = db.relationship("CustomsBroker", back_populates="shipments")
    from_location = db.relationship("Location", foreign_keys=[from_location_id])
    to_location = db.relationship("Location", foreign_keys=[to_location_id])
    brand = db.relationship("Brand", back_populates="shipments")
    consignee = db.relationship("ConsigneeEntity", back_populates="shipments")
    forwarder = db.relationship("Carrier", foreign_keys=[forwarder_id])
    express_carrier = db.relationship("Carrier", foreign_keys=[express_carrier_id])
    created_by = db.relationship("User")

    items = db.relationship("ShipmentItem", back_populates="shipment", cascade="all, delete-orphan")
    status_history = db.relationship("StatusHistory", back_populates="shipment",
                                     cascade="all, delete-orphan", order_by="StatusHistory.event_date")
    documents = db.relationship("Document", back_populates="shipment", cascade="all, delete-orphan")
    costs = db.relationship("CostLine", back_populates="shipment", cascade="all, delete-orphan")
    comments = db.relationship("Comment", back_populates="shipment", cascade="all, delete-orphan")
    quotations = db.relationship("FreightQuotation", back_populates="shipment", cascade="all, delete-orphan")
    supplier_invoices = db.relationship("SupplierInvoice", back_populates="shipment")
    # One shipment can carry more than one banking record — part paid in advance,
    # the balance against documents — so this is deliberately one-to-many.
    banking_records = db.relationship("BankRegistration", back_populates="shipment",
                                      cascade="all, delete-orphan")
    notifications = db.relationship("NotificationLog", back_populates="shipment", cascade="all, delete-orphan")

    # ---- derived ----
    @property
    def stage_label(self):
        return Stage.label(self.current_stage)

    @property
    def route_label(self):
        from .i18n import t
        return t(dict(ROUTE_TYPES).get(self.route_type, self.route_type or "—"))

    @property
    def bank_registration(self):
        """First banking record — kept so existing screens and the Form 4 register
        continue to work now that banking is one-to-many."""
        return self.banking_records[0] if self.banking_records else None

    @property
    def is_hub_leg(self):
        return self.route_type in ("inbound_hub", "reexport_hub")

    @property
    def bl_type_label(self):
        from .i18n import t
        return t(dict(BL_TYPES).get(self.bl_type, self.bl_type)) if self.bl_type else "—"

    @property
    def payment_terms_label(self):
        from .i18n import t
        return t(dict(SHIPMENT_PAYMENT_TERMS).get(self.payment_terms,
                                                  self.payment_terms)) if self.payment_terms else "—"

    @property
    def cut_off_missed(self):
        """Cargo cut-off passed while the shipment has still not departed."""
        if not self.cut_off_date or self.actual_departure:
            return False
        return self.cut_off_date < date.today()

    @property
    def origin_suppliers(self):
        """Distinct original suppliers across the item lines — a re-export leg from
        the fulfilment centre routinely consolidates several."""
        seen, out = set(), []
        for item in self.items:
            sup = item.supplier
            if sup and sup.id not in seen:
                seen.add(sup.id)
                out.append(sup)
        return out

    @property
    def is_consolidated(self):
        return len(self.origin_suppliers) > 1

    @property
    def stage_owner(self):
        return Stage.owner(self.current_stage)

    @property
    def is_open(self):
        return self.current_stage not in Stage.TERMINAL

    @property
    def days_in_stage(self):
        if not self.stage_entered_at:
            return 0
        return max(0, (date.today() - self.stage_entered_at).days)

    @property
    def is_delayed(self):
        """ETA has passed but the shipment has not yet arrived."""
        if not self.eta or not self.is_open:
            return False
        if self.actual_arrival:
            return False
        return self.eta < date.today() and Stage.index(self.current_stage) < Stage.index(Stage.ARRIVED)

    @property
    def total_value(self):
        return sum((i.line_value or 0) for i in self.items)

    @property
    def invoiced_qty(self):
        """Total units on the shipment, as stated on the supplier invoice — the
        item lines are entered from that invoice, so their quantities are it."""
        return sum((i.qty or 0) for i in self.items)

    @property
    def total_value_base(self):
        """Goods value converted to the base currency, so mixed-currency shipments add up."""
        return sum(to_base(i.line_value, i.currency) for i in self.items)

    @property
    def total_cost(self):
        return sum((c.amount_base or 0) for c in self.costs)

    @property
    def unpaid_cost(self):
        return sum((c.amount_base or 0) for c in self.costs if c.payment_status != "paid")

    @property
    def selected_quote(self):
        return next((q for q in self.quotations if q.is_selected), None)

    @property
    def freight_actual(self):
        return sum((c.amount or 0) for c in self.costs if c.cost_type == "freight")

    @property
    def freight_actual_base(self):
        return sum((c.amount_base or 0) for c in self.costs if c.cost_type == "freight")

    @property
    def quote_variance(self):
        """Actual freight less the selected quote, both in the base currency —
        the quote and the invoice are often raised in different currencies."""
        q = self.selected_quote
        if not q or not q.quoted_amount:
            return None
        actual = self.freight_actual_base
        if not actual:
            return None
        return actual - to_base(q.quoted_amount, q.currency)

    @property
    def quoted_base(self):
        q = self.selected_quote
        return to_base(q.quoted_amount, q.currency) if q else None

    @property
    def transit_days(self):
        """Days in transit, or None when the recorded dates contradict each other.

        The migrated spreadsheet contains rows where departure falls after arrival.
        Returning a negative number would poison every average that consumes this,
        so an impossible value reads as "not known" and is reported separately by
        `date_anomalies` instead of quietly skewing the KPIs.
        """
        if self.actual_departure and self.actual_arrival:
            days = (self.actual_arrival - self.actual_departure).days
            return days if days >= 0 else None
        return None

    @property
    def clearance_days(self):
        """Days from arrival to customs release, or None if the dates contradict."""
        if self.actual_arrival and self.clearance_date:
            days = (self.clearance_date - self.actual_arrival).days
            return days if days >= 0 else None
        return None

    @property
    def date_anomalies(self):
        """Recorded dates that cannot both be true — worth fixing at source."""
        from .i18n import t
        out = []
        if self.actual_departure and self.actual_arrival and self.actual_arrival < self.actual_departure:
            out.append(t("Arrival is recorded before departure"))
        if self.actual_arrival and self.clearance_date and self.clearance_date < self.actual_arrival:
            out.append(t("Customs release is recorded before arrival"))
        if self.clearance_date and self.warehouse_date and self.warehouse_date < self.clearance_date:
            out.append(t("Warehouse receipt is recorded before customs release"))
        if self.etd and self.eta and self.eta < self.etd:
            out.append(t("ETA is earlier than ETD"))
        return out

    @property
    def allocations(self):
        out = []
        for item in self.items:
            out.extend(item.allocations)
        return out

    @property
    def assets(self):
        out = []
        for item in self.items:
            out.extend(item.assets)
        return out

    @property
    def allocated_customers(self):
        seen, out = set(), []
        for a in self.allocations:
            if a.customer and a.customer.id not in seen:
                seen.add(a.customer.id)
                out.append(a.customer)
        return out

    @property
    def missing_documents(self):
        held = {d.doc_type for d in self.documents if d.is_received}
        required = {d.doc_type for d in self.documents if d.is_required}
        return sorted(required - held)

    @property
    def doc_completeness(self):
        required = [d for d in self.documents if d.is_required]
        if not required:
            return 100
        received = [d for d in required if d.is_received]
        return round(100 * len(received) / len(required))

    def __repr__(self):
        return f"<Shipment {self.reference_no}>"


class ShipmentItem(db.Model):
    __tablename__ = "shipment_items"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    po_line_id = db.Column(db.Integer, db.ForeignKey("purchase_order_lines.id"))
    # Who originally supplied THIS line, and what brand it is. Held per item because a
    # re-export from the fulfilment centre consolidates goods from several suppliers,
    # which a single value on the shipment header cannot represent.
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"))
    # For a re-export leg: the inbound item line these goods arrived on, so a machine
    # can be traced back through the hub to the shipment that first brought it in.
    source_item_id = db.Column(db.Integer, db.ForeignKey("shipment_items.id"))
    category = db.Column(db.String(40))
    description = db.Column(db.String(500))
    model_no = db.Column(db.String(120))
    specification = db.Column(db.Text)
    # Wide enough for a multi-product line: the source data has shipments carrying
    # three products with all three HS codes recorded in one cell.
    hs_code = db.Column(db.String(200))
    qty = db.Column(db.Float, default=0)
    unit = db.Column(db.String(40), default="unit")
    unit_value = db.Column(db.Float, default=0)
    # What it was invoiced at, against what it is actually worth. The two diverge on
    # customs valuations and intercompany transfers, and collapsing them loses the trail.
    invoice_value = db.Column(db.Float)
    actual_value = db.Column(db.Float)
    invoice_no = db.Column(db.String(80))
    invoice_date = db.Column(db.Date)
    currency = db.Column(db.String(8), default="USD")
    weight_kg = db.Column(db.Float)
    net_weight_kg = db.Column(db.Float)
    gross_weight_kg = db.Column(db.Float)
    dimensions = db.Column(db.String(80))          # L x W x H in cm
    is_serialised = db.Column(db.Boolean, default=False)

    shipment = db.relationship("Shipment", back_populates="items")
    po_line = db.relationship("PurchaseOrderLine", back_populates="shipment_items")
    supplier = db.relationship("Supplier")
    brand = db.relationship("Brand")
    source_item = db.relationship("ShipmentItem", remote_side="ShipmentItem.id",
                                  backref="reexported_as")
    assets = db.relationship("Asset", back_populates="item", cascade="all, delete-orphan")
    allocations = db.relationship("Allocation", back_populates="item", cascade="all, delete-orphan")

    @property
    def line_value(self):
        return (self.qty or 0) * (self.unit_value or 0)

    @property
    def category_label(self):
        from .i18n import t
        return t(dict(ITEM_CATEGORIES).get(self.category, self.category or "—"))

    @property
    def value_variance(self):
        """Actual value less invoiced value, where both are recorded."""
        if self.actual_value is None or self.invoice_value is None:
            return None
        return self.actual_value - self.invoice_value

    @property
    def origin_trail(self):
        """Walk back through the hub to the item line that first entered the chain."""
        seen, node = set(), self
        while node.source_item and node.source_item.id not in seen:
            seen.add(node.id)
            node = node.source_item
        return node

    @property
    def qty_allocated(self):
        return sum((a.quantity or 0) for a in self.allocations)

    @property
    def qty_unallocated(self):
        return max(0, (self.qty or 0) - self.qty_allocated)


class Asset(db.Model):
    """An individual serial-numbered unit within a shipment item."""
    __tablename__ = "assets"
    id = db.Column(db.Integer, primary_key=True)
    shipment_item_id = db.Column(db.Integer, db.ForeignKey("shipment_items.id"))
    serial_no = db.Column(db.String(120), nullable=False)
    model_no = db.Column(db.String(120))
    status = db.Column(db.String(30), default="in_transit")
    warranty_start_date = db.Column(db.Date)
    warranty_months = db.Column(db.Integer, default=12)
    condition_notes = db.Column(db.String(400))
    current_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"))

    item = db.relationship("ShipmentItem", back_populates="assets")
    allocation = db.relationship("Allocation", back_populates="asset", uselist=False)
    current_location = db.relationship("Location")
    movements = db.relationship("AssetMovement", back_populates="asset",
                                cascade="all, delete-orphan",
                                order_by="AssetMovement.movement_date")

    @property
    def status_label(self):
        from .i18n import t
        return t(dict(ASSET_STATUSES).get(self.status, self.status))

    @property
    def warranty_end_date(self):
        if not self.warranty_start_date:
            return None
        return self.warranty_start_date + timedelta(days=30 * (self.warranty_months or 12))

    @property
    def warranty_active(self):
        end = self.warranty_end_date
        return bool(end and end >= date.today())

    @property
    def shipment(self):
        return self.item.shipment if self.item else None

    @property
    def brand(self):
        """Brand from the item line where it is held, falling back to the shipment."""
        if self.item and self.item.brand:
            return self.item.brand
        s = self.shipment
        return s.brand if s else None

    @property
    def shipments_travelled(self):
        """Every leg this unit has moved on, in order — the full journey through
        the fulfilment centre, not just the shipment it was first recorded against."""
        seen, out = set(), []
        first = self.shipment
        if first:
            seen.add(first.id)
            out.append(first)
        for m in self.movements:
            if m.shipment and m.shipment.id not in seen:
                seen.add(m.shipment.id)
                out.append(m.shipment)
        return out


class AssetMovement(db.Model):
    """One physical machine can travel on more than one shipment — origin to the
    Jebel Ali fulfilment centre, then a separate re-export leg into Cairo. Rather than
    duplicate the serial on each leg, every movement is recorded against the one asset,
    which keeps the unit's whole journey in a single place."""
    __tablename__ = "asset_movements"
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"))
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    movement_type = db.Column(db.String(30), default="received")
    movement_date = db.Column(db.Date, default=date.today)
    from_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"))
    to_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(300))

    asset = db.relationship("Asset", back_populates="movements")
    shipment = db.relationship("Shipment")
    from_location = db.relationship("Location", foreign_keys=[from_location_id])
    to_location = db.relationship("Location", foreign_keys=[to_location_id])
    recorded_by = db.relationship("User")

    @property
    def type_label(self):
        from .i18n import t
        return t(dict(MOVEMENT_TYPES).get(self.movement_type, self.movement_type))


class Allocation(db.Model):
    """Assigns a specific Asset — or a quantity of a bulk item — to a Customer."""
    __tablename__ = "allocations"
    id = db.Column(db.Integer, primary_key=True)
    shipment_item_id = db.Column(db.Integer, db.ForeignKey("shipment_items.id"))
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"))
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"))
    quantity = db.Column(db.Float, default=1)
    allocated_date = db.Column(db.Date, default=date.today)
    allocated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    expected_install_date = db.Column(db.Date)
    install_confirmed_date = db.Column(db.Date)
    sales_notes = db.Column(db.String(500))

    item = db.relationship("ShipmentItem", back_populates="allocations")
    asset = db.relationship("Asset", back_populates="allocation")
    customer = db.relationship("Customer", back_populates="allocations")
    allocated_by = db.relationship("User")

    @property
    def shipment(self):
        return self.item.shipment if self.item else None

    @property
    def is_installed(self):
        return self.install_confirmed_date is not None


# --------------------------------------------------------------------------
# Operational detail
# --------------------------------------------------------------------------

class StatusHistory(db.Model):
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    status_code = db.Column(db.String(40))
    event_date = db.Column(db.Date, default=date.today)
    is_estimate = db.Column(db.Boolean, default=False)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(400))

    shipment = db.relationship("Shipment", back_populates="status_history")
    recorded_by = db.relationship("User")

    @property
    def label(self):
        return Stage.label(self.status_code)


class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    doc_type = db.Column(db.String(50))
    file_name = db.Column(db.String(300))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)
    is_required = db.Column(db.Boolean, default=True)
    is_received = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer, default=1)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_at = db.Column(db.DateTime)
    notes = db.Column(db.String(300))

    shipment = db.relationship("Shipment", back_populates="documents")
    uploaded_by = db.relationship("User")

    @property
    def type_label(self):
        from .i18n import t
        return t(dict(DOC_TYPES).get(self.doc_type, self.doc_type))


class CostLine(db.Model):
    __tablename__ = "cost_lines"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    cost_type = db.Column(db.String(40))
    description = db.Column(db.String(300))
    amount = db.Column(db.Float, default=0)
    currency = db.Column(db.String(8), default="EGP")
    amount_base = db.Column(db.Float, default=0)  # converted to EGP
    payable_to = db.Column(db.String(200))
    # Whether we settled this directly or the forwarder advanced it and recharged.
    paid_by = db.Column(db.String(30), default="company")
    payment_status = db.Column(db.String(20), default="unpaid")
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    payment_reference = db.Column(db.String(120))
    note = db.Column(db.String(400))

    shipment = db.relationship("Shipment", back_populates="costs")

    @property
    def type_label(self):
        from .i18n import t
        return t(dict(COST_TYPES).get(self.cost_type, self.cost_type))

    @property
    def payment_status_label(self):
        from .i18n import t
        return t(dict(PAYMENT_STATUSES).get(self.payment_status, self.payment_status))

    @property
    def paid_by_label(self):
        from .i18n import t
        return t(dict(PAID_BY).get(self.paid_by, self.paid_by or "—"))

    @property
    def is_overdue(self):
        return (self.payment_status != "paid" and self.due_date and self.due_date < date.today())


class BankRegistration(db.Model):
    """Egyptian bank-side import registration — 'Form 4'."""
    __tablename__ = "bank_registrations"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    bank_id = db.Column(db.Integer, db.ForeignKey("banks.id"))
    registration_no = db.Column(db.String(80))
    registration_date = db.Column(db.Date)
    is_exempt = db.Column(db.Boolean, default=False)
    exempt_reason = db.Column(db.String(200))
    # The bank-side payment trail: the advance transfer request, and the SWIFT
    # references that let a payment be traced back through the bank.
    advance_payment_ref = db.Column(db.String(120))
    swift_1 = db.Column(db.String(120))
    swift_2 = db.Column(db.String(120))
    amount = db.Column(db.Float)
    currency = db.Column(db.String(8))
    transfer_date = db.Column(db.Date)
    notes = db.Column(db.String(300))

    shipment = db.relationship("Shipment", back_populates="banking_records")
    bank = db.relationship("Bank")


class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    shipment = db.relationship("Shipment", back_populates="comments")
    user = db.relationship("User")


# --------------------------------------------------------------------------
# Notifications & audit
# --------------------------------------------------------------------------

class NotificationRule(db.Model):
    __tablename__ = "notification_rules"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    trigger_type = db.Column(db.String(50))
    # stage_reached | eta_within_days | delay | missing_document | payment_overdue | po_overdue | digest
    trigger_value = db.Column(db.String(80))
    audience_role = db.Column(db.String(60))
    channel = db.Column(db.String(30), default="email")
    template = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    logs = db.relationship("NotificationLog", back_populates="rule")


class NotificationLog(db.Model):
    __tablename__ = "notification_logs"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"))
    rule_id = db.Column(db.Integer, db.ForeignKey("notification_rules.id"))
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recipient_email = db.Column(db.String(160))
    subject = db.Column(db.String(300))
    body = db.Column(db.Text)
    channel = db.Column(db.String(30))
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(30), default="logged")

    shipment = db.relationship("Shipment", back_populates="notifications")
    rule = db.relationship("NotificationRule", back_populates="logs")
    recipient = db.relationship("User")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    entity = db.Column(db.String(80))
    entity_id = db.Column(db.Integer)
    action = db.Column(db.String(30))  # create / update / delete
    field = db.Column(db.String(80))
    old_value = db.Column(db.String(500))
    new_value = db.Column(db.String(500))
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    changed_by_name = db.Column(db.String(120))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    changed_by = db.relationship("User")
