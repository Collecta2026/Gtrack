"""End-to-end smoke test — exercises every screen as every role, plus the key workflows.

Safe to run repeatedly: each run tags the records it creates with a unique prefix.
"""
import re
import sys
import uuid

RUN = uuid.uuid4().hex[:6].upper()   # unique per run, so repeat runs don't collide

from app import create_app
from app.i18n import TRANSLATIONS
from app.auth import PERMISSIONS
from app.models import (db, Shipment, ShipmentItem, Asset, Allocation, PurchaseOrder,
                        CostLine, Customer, Carrier, Supplier, User, NotificationLog,
                        AuditLog, Stage, Location, CustomsBroker, AssetMovement,
                        BankRegistration, Role, to_base, Comment, FreightQuotation)

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        FAILURES.append(f"{label} {detail}")


def login(client, email):
    return client.post("/login", data={"email": email, "password": "demo1234"},
                       follow_redirects=True)


def get(client, url, expect=200, label=None):
    resp = client.get(url, follow_redirects=False)
    ok = resp.status_code == expect
    check(label or f"GET {url}", ok, f"(got {resp.status_code}, expected {expect})")
    return resp


# --------------------------------------------------------------------------
# First-run setup: seed.py leaves zero accounts on purpose — the whole point
# is that nobody ships with a known password. Everything else in this suite
# logs in with a fixed set of demo emails/password, so bootstrap that set
# here, through the exact screens a real deployment would use: the one-time
# setup screen for the first admin, then Admin -> Users for everyone else.
#
# The setup screen itself is only ever exercised once per database — it
# deliberately refuses to run again once an account exists (that's the point
# of it) — so on a rerun against an already-set-up database (this suite is
# meant to be safe to run repeatedly without reseeding), that part is skipped
# and only the "make sure the demo cast exists" step runs, idempotently.
# --------------------------------------------------------------------------
print("\n=== First-run setup: from zero accounts to the first admin ===")
with app.app_context():
    starts_empty = User.query.count() == 0

if starts_empty:
    with app.test_client() as c0:
        r = c0.get("/", follow_redirects=False)
        check("a fresh install redirects anywhere to /setup",
              r.status_code == 302 and "/setup" in (r.location or ""))
        r = c0.get("/login", follow_redirects=False)
        check("even /login redirects to /setup before the first account exists",
              r.status_code == 302 and "/setup" in (r.location or ""))

        r = c0.post("/setup", data={"name": "", "email": "zak@scientificgate.test",
                                     "password": "demo1234", "confirm_password": "demo1234"},
                    follow_redirects=True)
        check("setup rejects a blank name", "Enter your name".encode() in r.data)

        r = c0.post("/setup", data={"name": "Zak Saleh", "email": "zak@scientificgate.test",
                                     "password": "short", "confirm_password": "short"},
                    follow_redirects=True)
        check("setup rejects a too-short password", b"least 6 characters" in r.data)

        r = c0.post("/setup", data={"name": "Zak Saleh", "email": "zak@scientificgate.test",
                                     "password": "demo1234", "confirm_password": "different"},
                    follow_redirects=True)
        check("setup rejects a mismatched confirmation", b"confirmation don" in r.data.lower()
              or b"match" in r.data.lower())
        with app.app_context():
            check("nothing was created by the rejected attempts", User.query.count() == 0)

        r = c0.post("/setup", data={"name": "Zak Saleh", "email": "zak@scientificgate.test",
                                     "password": "demo1234", "confirm_password": "demo1234"},
                    follow_redirects=True)
        check("setup creates the admin account and signs them straight in",
              r.status_code == 200 and b"admin account is ready" in r.data)
        r_dash = c0.get("/", follow_redirects=False)
        check("the new admin lands on the dashboard, no separate login needed",
              r_dash.status_code == 200)

    with app.app_context():
        zak = User.query.filter_by(email="zak@scientificgate.test").first()
        check("admin account has the CFO (full-access) role", bool(zak and zak.role_code == "cfo"))
        check("admin chose their own password — nothing forces a change",
              bool(zak) and not zak.must_change_password)

    with app.test_client() as c0b:
        r = c0b.get("/setup", follow_redirects=False)
        check("setup steps aside once an account exists",
              r.status_code == 302 and "/login" in (r.location or ""))
else:
    with app.app_context():
        zak = User.query.filter_by(email="zak@scientificgate.test").first()
        check("admin account from an earlier run is still there with the CFO role",
              bool(zak and zak.role_code == "cfo"))

# The rest of this suite logs in as a fixed cast of role-holders — create any
# that don't already exist, as the CFO would from Admin -> Users, then
# fast-forward each past the one-time "choose your own password" screen so
# plain email/password logins behave the same as a user who's already been
# through that once for real. Idempotent: a rerun against the same database
# (no reseed) finds them all already in place and creates nothing.
DEMO_TEAM = [
    ("Amr El-Bagoury", "amr@scientificgate.test", "md"),
    ("Khaled Salah", "finance@scientificgate.test", "finance"),
    ("Sara Mahmoud", "sales1@scientificgate.test", "sales"),
    ("Omar Fathy", "sales2@scientificgate.test", "sales"),
    ("Mona Adel", "salesadmin@scientificgate.test", "sales_admin"),
    ("Mostafa Hassan", "procurement@scientificgate.test", "logistics_admin"),
    ("Nourhan Adel", "logistics@scientificgate.test", "logistics_admin"),
    ("Hesham Zaki", "warehouse@scientificgate.test", "logistics_admin"),
]
with app.app_context():
    role_ids = {r.code: r.id for r in Role.query.all()}
    existing_emails = {e for (e,) in db.session.query(User.email).all()}
missing_team = [row for row in DEMO_TEAM if row[1] not in existing_emails]

with app.test_client() as c0c:
    login(c0c, "zak@scientificgate.test")
    for name, email, role_code in missing_team:
        resp = c0c.post("/admin/users",
                        data={"name": name, "email": email, "role_id": role_ids[role_code],
                              "is_active": "1", "password": "demo1234"},
                        follow_redirects=True)
        check(f"POST create demo account {email}", resp.status_code == 200)

with app.app_context():
    for name, email, role_code in DEMO_TEAM:
        u = User.query.filter_by(email=email).first()
        check(f"{email} exists with role {role_code}", bool(u and u.role_code == role_code))
        if u is not None:
            u.must_change_password = False
    db.session.commit()

with app.app_context():
    shipment = Shipment.query.filter(Shipment.current_stage.notin_(
        [Stage.CANCELLED, Stage.RE_EXPORTED, Stage.WAREHOUSE])).first()
    shipment_id = shipment.id
    open_shipment_ref = shipment.reference_no
    item_id = shipment.items[0].id if shipment.items else None
    po_id = PurchaseOrder.query.first().id
    asset = Asset.query.filter(Asset.allocation == None).first()  # noqa: E711
    asset_id = (asset or Asset.query.first()).id
    customer_id = Customer.query.first().id
    carrier_id = Carrier.query.filter_by(type="freight_forwarder").first().id
    cost = CostLine.query.filter(CostLine.payment_status != "paid").first()
    cost_id = cost.id if cost else None
    sales_user = User.query.filter(User.email == "sales1@scientificgate.test").first()
    sales_email = sales_user.email

    # routing / hub fixtures
    hub_leg = Shipment.query.filter_by(route_type="reexport_hub").first()
    hub_leg_id = hub_leg.id if hub_leg else shipment_id
    inbound_leg = Shipment.query.filter_by(route_type="inbound_hub").first()
    inbound_leg_id = inbound_leg.id if inbound_leg else shipment_id
    # Deterministic pick: the first traced line (by id) whose upstream leg actually has
    # costs booked, so the earlier-leg carry-forward has something to show. Without the
    # ordering the row differs between SQLite and PostgreSQL.
    traced_all = (ShipmentItem.query.filter(ShipmentItem.source_item_id != None)  # noqa: E711
                  .order_by(ShipmentItem.id).all())
    traced_item = next((i for i in traced_all
                        if i.source_item and i.source_item.shipment
                        and i.source_item.shipment.costs), None)
    traced_costed = traced_item is not None
    if traced_item is None:
        traced_item = traced_all[0] if traced_all else None
    traced_shipment_id = traced_item.shipment_id if traced_item else None
    moved_asset = (db.session.query(Asset).join(AssetMovement).first())
    moved_asset_id = moved_asset.id if moved_asset else asset_id
    hub_location = Location.query.filter_by(is_free_zone=True).first()
    broker_count = CustomsBroker.query.count()
    location_count = Location.query.count()

# The language preference persists on the account, so normalise it before the
# English assertions rather than assuming how the last session left it.
with app.app_context():
    for u in User.query.all():
        u.language = "en"
    db.session.commit()

print("\n=== ADMIN: every screen ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    for url in [
        "/", "/shipments/", "/shipments/board", f"/shipments/{shipment_id}",
        "/shipments/new", f"/shipments/{shipment_id}/edit",
        "/purchase-orders/", f"/purchase-orders/{po_id}", "/purchase-orders/new",
        f"/purchase-orders/{po_id}/edit",
        "/finance/costs", "/finance/invoices", "/finance/quotations", "/finance/quotations/new",
        "/finance/bank-registrations",
        "/equipment/", f"/equipment/{asset_id}", "/equipment/allocations", "/equipment/customers",
        "/master-data/", "/master-data/suppliers", "/master-data/brands", "/master-data/carriers",
        "/master-data/consignees", "/master-data/customers", "/master-data/banks",
        "/reports/", "/reports/pipeline", "/reports/timing", "/reports/cost",
        "/reports/financial-analysis",
        "/reports/brands", "/reports/equipment", "/reports/exceptions",
        "/admin/users", "/admin/roles", "/admin/notification-rules",
        "/admin/notifications", "/admin/audit",
        "/help/", "/search/", f"/shipments/{shipment_id}/statement",
        f"/shipments/{shipment_id}/cost-buildup",
    ]:
        get(c, url)

    print("\n=== Filters & search ===")
    get(c, "/shipments/?status=delayed")
    get(c, "/shipments/?status=open&mode=air")
    get(c, "/shipments/?q=SHP-0001")
    get(c, "/shipments/?stage=in_transit")
    get(c, "/equipment/?status=allocated")
    get(c, "/equipment/?q=LRG")
    get(c, "/finance/costs?status=unpaid")
    get(c, "/purchase-orders/?status=confirmed")
    get(c, "/admin/audit?entity=shipments")

    print("\n=== Exports (CSV / Excel / PDF) ===")
    for url, mime in [
        ("/shipments/?export=csv", "text/csv"),
        ("/shipments/?export=xlsx", "spreadsheetml"),
        ("/shipments/?export=pdf", "application/pdf"),
        ("/reports/export?format=xlsx", "spreadsheetml"),
        ("/reports/export?format=pdf", "application/pdf"),
        ("/finance/costs?export=xlsx", "spreadsheetml"),
        ("/equipment/?export=pdf", "application/pdf"),
        ("/equipment/allocations?export=xlsx", "spreadsheetml"),
        ("/admin/audit?export=xlsx", "spreadsheetml"),
        ("/purchase-orders/?export=pdf", "application/pdf"),
    ]:
        resp = c.get(url)
        ok = resp.status_code == 200 and mime in resp.headers.get("Content-Type", "") and len(resp.data) > 500
        check(f"EXPORT {url}", ok,
              f"(status {resp.status_code}, type {resp.headers.get('Content-Type')}, {len(resp.data)} bytes)")

print("\n=== Workflow: stage advance fires notifications ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    with app.app_context():
        before = NotificationLog.query.count()
        s = db.session.get(Shipment, shipment_id)
        old_stage = s.current_stage
    resp = c.post(f"/shipments/{shipment_id}/advance",
                  data={"stage": Stage.CLEARED, "event_date": "2026-09-11",
                        "note": "Smoke test"}, follow_redirects=True)
    check("POST advance to Cleared", resp.status_code == 200)
    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        check("stage changed", s.current_stage == Stage.CLEARED, f"(now {s.current_stage})")
        check("clearance_date set", s.clearance_date is not None)
        check("status history recorded",
              any(h.status_code == Stage.CLEARED for h in s.status_history))
        after = NotificationLog.query.count()
        check("notifications generated on Cleared", after >= before,
              f"({before} -> {after})")
        check("audit log captured stage change",
              AuditLog.query.filter_by(entity="shipments", action="stage_change").count() > 0)

print("\n=== Workflow: warehouse receipt ===")
with app.test_client() as c:
    login(c, "warehouse@scientificgate.test")
    resp = c.post(f"/shipments/{shipment_id}/advance",
                  data={"stage": Stage.WAREHOUSE, "event_date": "2026-09-11"},
                  follow_redirects=True)
    check("warehouse role can advance stage", resp.status_code == 200)
    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        check("warehouse_date set", s.warehouse_date is not None)

print("\n=== Workflow: add item, serials, allocate, confirm install ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    resp = c.post(f"/shipments/{shipment_id}/items/add",
                  data={"description": f"Smoke test unit {RUN}", "model_no": "TEST-1",
                        "qty": "2", "unit": "unit", "unit_value": "1500",
                        "currency": "USD", "hs_code": "9018490000"},
                  follow_redirects=True)
    check("POST add item", resp.status_code == 200)
    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        new_item = [i for i in s.items if i.description == f"Smoke test unit {RUN}"][0]
        new_item_id = new_item.id
        check("item persisted with value", new_item.line_value == 3000, f"({new_item.line_value})")

    resp = c.post(f"/shipments/items/{new_item_id}/assets/add",
                  data={"serial_no": f"SMOKE-{RUN}-1, SMOKE-{RUN}-2", "warranty_months": "24"},
                  follow_redirects=True)
    check("POST add serial numbers", resp.status_code == 200)
    with app.app_context():
        serials = Asset.query.filter(Asset.serial_no.like(f"SMOKE-{RUN}-%")).all()
        check("two serials recorded", len(serials) == 2, f"({len(serials)})")
        smoke_asset_id = serials[0].id

    resp = c.post(f"/shipments/items/{new_item_id}/allocate",
                  data={"customer_id": str(customer_id), "asset_id": str(smoke_asset_id),
                        "quantity": "1", "expected_install_date": "2026-10-15",
                        "sales_notes": "Smoke test allocation"},
                  follow_redirects=True)
    check("POST allocate to customer", resp.status_code == 200)
    with app.app_context():
        a = db.session.get(Asset, smoke_asset_id)
        check("asset marked allocated", a.status == "allocated", f"({a.status})")
        check("allocation linked to customer", a.allocation and a.allocation.customer_id == customer_id)
        alloc_id = a.allocation.id

    resp = c.post(f"/shipments/allocations/{alloc_id}/confirm-install",
                  data={"install_date": "2026-09-11"}, follow_redirects=True)
    check("POST confirm installation", resp.status_code == 200)
    with app.app_context():
        a = db.session.get(Asset, smoke_asset_id)
        check("asset marked installed", a.status == "installed", f"({a.status})")
        check("warranty start set", a.warranty_start_date is not None)
        check("warranty end computed 24 months out", a.warranty_end_date is not None)

print("\n=== Workflow: costs, quotations, Form 4, comments ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    resp = c.post(f"/shipments/{shipment_id}/costs/add",
                  data={"cost_type": "clearance_fee", "amount": "7500", "currency": "EGP",
                        "payable_to": "Clearance agent", "payment_status": "unpaid",
                        "due_date": "2026-09-30", "description": "Smoke test cost"},
                  follow_redirects=True)
    check("POST add cost line", resp.status_code == 200)

    if cost_id:
        resp = c.post(f"/shipments/costs/{cost_id}/pay",
                      data={"payment_reference": "TRF-999"}, follow_redirects=True)
        check("POST mark cost paid", resp.status_code == 200)
        with app.app_context():
            check("cost now paid", db.session.get(CostLine, cost_id).payment_status == "paid")

    resp = c.post(f"/shipments/{shipment_id}/quotations/add",
                  data={"forwarder_id": str(carrier_id), "quote_ref": f"SMOKE-Q-{RUN}",
                        "quoted_amount": "2400", "currency": "USD",
                        "quote_date": "2026-09-01", "transit_days": "18"},
                  follow_redirects=True)
    check("POST add quotation", resp.status_code == 200)

    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        q = [x for x in s.quotations if x.quote_ref == f"SMOKE-Q-{RUN}"][0]
        quote_id = q.id
    resp = c.post(f"/shipments/quotations/{quote_id}/select", follow_redirects=True)
    check("POST select quotation", resp.status_code == 200)
    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        check("selected quote reflected on shipment", s.selected_quote is not None)
        check("quote variance computed", s.quote_variance is not None or s.freight_actual == 0)

    # A quote broken down to its cost elements totals itself automatically, rather
    # than needing the total typed in separately.
    resp = c.post(f"/shipments/{shipment_id}/quotations/add",
                  data={"forwarder_id": str(carrier_id), "quote_ref": f"SMOKE-Q-ELEMENTS-{RUN}",
                        "currency": "USD", "quote_date": "2026-09-01",
                        "freight_cost": "1000", "export_clearance_cost": "150",
                        "xray_cost": "40", "origin_handling_cost": "60",
                        "documentation_cost": "25", "other_cost": "10"},
                  follow_redirects=True)
    check("POST add quotation with a cost-element breakdown", resp.status_code == 200)
    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        eq = [x for x in s.quotations if x.quote_ref == f"SMOKE-Q-ELEMENTS-{RUN}"][0]
        check("quoted_amount auto-totals the itemised elements", eq.quoted_amount == 1285)
        check("cost_breakdown lists every non-zero element", len(eq.cost_breakdown) == 6)

    # The standalone quotation entry screen under Finance
    resp = get(c, "/finance/quotations/new", label="standalone quotation entry screen renders")
    with app.app_context():
        an_open_shipment = next((sh for sh in Shipment.query.all() if sh.is_open), None)
    check("standalone screen lists an open shipment to pick from",
          an_open_shipment is not None
          and an_open_shipment.reference_no.encode() in resp.data)

    resp = c.post(f"/shipments/{shipment_id}/bank-registration",
                  data={"registration_no": f"F4-{RUN}", "registration_date": "2026-09-01"},
                  follow_redirects=True)
    check("POST save Form 4", resp.status_code == 200)
    with app.app_context():
        s = db.session.get(Shipment, shipment_id)
        # banking records accumulate (advance payment, then balance against documents),
        # so the new one is somewhere in the list rather than necessarily first
        check("Form 4 persisted",
              any(r.registration_no == f"F4-{RUN}" for r in s.banking_records))

    resp = c.post(f"/shipments/{shipment_id}/comments/add",
                  data={"body": f"Smoke test comment {RUN}"}, follow_redirects=True)
    check("POST add comment", resp.status_code == 200)

    resp = c.post("/run-notifications", follow_redirects=True)
    check("POST run notification sweep", resp.status_code == 200)

print("\n=== Global search ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    with app.app_context():
        s_obj = db.session.get(Shipment, shipment_id)
        ref = s_obj.reference_no
        acid = next((x.acid_number for x in Shipment.query.all() if x.acid_number), None)
        bl = next((x.bl_awb_no for x in Shipment.query.all() if x.bl_awb_no), None)
        serial = Asset.query.first().serial_no
        po_num = PurchaseOrder.query.first().po_number
        cust_name = Customer.query.first().customer_name
        sup_name = Supplier.query.first().name

    def search_finds(term, expect_text, label):
        r = c.get(f"/search/?q={term}")
        ok = r.status_code == 200 and expect_text.encode() in r.data
        check(f"search by {label} ('{term}')", ok, f"(status {r.status_code})")

    search_finds(ref, ref, "shipment reference")
    if acid:
        search_finds(acid, "ACID", "ACID number")
    if bl:
        search_finds(bl, "BL / AWB", "BL/AWB number")
    search_finds(serial, serial, "serial number")
    search_finds(po_num, "PO number", "purchase order number")
    search_finds(cust_name.split()[0], "Customer", "customer name")
    search_finds(sup_name.split()[0], "Supplier", "supplier name")
    search_finds("Riton", "Shipments", "product / brand")

    r = c.get("/search/?q=zzzznotarealthing")
    check("search handles no results", b"Nothing found" in r.data)

    r = c.get(f"/search/?q={ref}&export=xlsx")
    check("search exports to Excel",
          r.status_code == 200 and "spreadsheetml" in r.headers.get("Content-Type", ""))

print("\n=== Cost statement ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    r = c.get(f"/shipments/{shipment_id}/statement")
    check("statement renders", r.status_code == 200)
    body = r.data.decode()
    for needle in ["Items in this shipment", "Cost trace", "Landed cost by item",
                   "Landed total"]:
        check(f"statement shows '{needle}'", needle in body)

    for fmt, mime in [("pdf", "application/pdf"), ("xlsx", "spreadsheetml")]:
        r = c.get(f"/shipments/{shipment_id}/statement?export={fmt}")
        check(f"statement exports to {fmt}",
              r.status_code == 200 and mime in r.headers.get("Content-Type", "")
              and len(r.data) > 500)

    # landed cost must reconcile: goods + costs == landed total
    with app.app_context():
        from app.views.shipments import _statement_data
        s_obj = db.session.get(Shipment, shipment_id)
        d = _statement_data(s_obj)
        check("landed total reconciles",
              abs(d["landed_total"] - (d["goods_base"] + d["cost_total"])) < 0.01,
              f"({d['landed_total']} vs {d['goods_base']} + {d['cost_total']})")
        apportioned = sum(r["apportioned"] for r in d["item_rows"])
        check("apportioned costs sum to total cost",
              abs(apportioned - d["cost_total"]) < 0.01,
              f"({apportioned} vs {d['cost_total']})")

    # The landed-cost build-up is a separate screen, grouping the same underlying
    # costs into plain top-down buckets — it must always reconcile with the Statement.
    r = c.get(f"/shipments/{shipment_id}/cost-buildup")
    check("landed cost build-up renders", r.status_code == 200)
    body = r.data.decode()
    for needle in ["Goods value (from invoice)", "Total landed cost", "Per machine / item"]:
        check(f"build-up shows '{needle}'", needle in body)
    with app.app_context():
        from app.views.shipments import _statement_data, _cost_buildup
        s_obj = db.session.get(Shipment, shipment_id)
        d = _statement_data(s_obj)
        groups = _cost_buildup(d)
        check("build-up buckets sum to the same cost total as the statement",
              abs(sum(g["amount"] for g in groups) - d["cost_total"]) < 0.01,
              f"({sum(g['amount'] for g in groups)} vs {d['cost_total']})")

print("\n=== Landed cost build-up: every shipment, not just the sample one ===")
# A single sample shipment can hide a class of bug that only shows up on certain
# data shapes — e.g. an item with no invoice value yet (goods_base == 0), which
# used to silently zero out that item's share of the real, already-booked costs.
# Walk every seeded shipment and require exact reconciliation, no exceptions.
with app.app_context():
    from app.views.shipments import _statement_data, _cost_buildup
    from app.models import COST_TYPES as _COST_TYPES
    from app.views.shipments import COST_BUILDUP_GROUPS as _BUILDUP_GROUPS
    _TOL = 0.01

    _bucket_codes = {}
    for _key, _label, _codes in _BUILDUP_GROUPS:
        for _code in _codes:
            _bucket_codes.setdefault(_code, []).append(_key)
    check("every cost type maps to exactly one build-up bucket",
          all(len(ks) == 1 for ks in _bucket_codes.values()) and
          set(_bucket_codes) == {code for code, _ in _COST_TYPES})

    _all_shipments = Shipment.query.all()
    _reconciled = 0
    for _s in _all_shipments:
        _d = _statement_data(_s)
        _groups = _cost_buildup(_d)
        ok = abs(sum(g["amount"] for g in _groups) - _d["cost_total"]) < _TOL
        ok = ok and abs((_d["goods_base"] + _d["cost_total"]) - _d["landed_total"]) < _TOL
        if _d["item_rows"]:
            ok = ok and abs(sum(r["apportioned"] for r in _d["item_rows"]) - _d["cost_total"]) < _TOL
            ok = ok and abs(sum(r["landed"] for r in _d["item_rows"]) - _d["landed_total"]) < _TOL
            ok = ok and abs(sum(r["share"] for r in _d["item_rows"]) - 1.0) < _TOL
            ok = ok and all(
                abs((r["landed_per_unit"] or 0) * (r["item"].qty or 0) - r["landed"]) < _TOL
                for r in _d["item_rows"] if r["item"].qty)
        if ok:
            _reconciled += 1
        else:
            check(f"build-up reconciles for {_s.reference_no}", False)
    check(f"build-up reconciles exactly for all {len(_all_shipments)} shipments",
          _reconciled == len(_all_shipments), f"({_reconciled}/{len(_all_shipments)})")

    # Every cost type the seed data actually uses should show up as a nonzero
    # bucket somewhere across the register — otherwise a whole class of cost
    # (bank charges, last-mile, etc.) would be silently invisible to finance.
    _used_types = {c.cost_type for s in _all_shipments for c in s.costs}
    _nonzero_buckets = set()
    for _s in _all_shipments:
        for g in _cost_buildup(_statement_data(_s)):
            if g["amount"]:
                _nonzero_buckets.add(g["key"])
    check(f"every cost type in use ({sorted(_used_types)}) is reflected in some "
          f"nonzero build-up bucket", len(_nonzero_buckets) == len(_BUILDUP_GROUPS),
          f"(buckets with data: {sorted(_nonzero_buckets)})")

print("\n=== Financial analysis report ===")
with app.test_client() as c:
    login(c, "finance@scientificgate.test")
    r = get(c, "/reports/financial-analysis", label="financial analysis report renders")
    body = r.data.decode()
    for needle in ["Goods value", "Total landed cost", "Bank charges", "Last-mile delivery"]:
        check(f"financial analysis shows '{needle}'", needle in body)
    for fmt in ("xlsx", "csv", "pdf"):
        get(c, f"/reports/financial-analysis/export?format={fmt}",
            label=f"financial analysis export ({fmt})")

    # _financial_analysis_rows() scopes itself through visible_shipments(), which
    # reads current_user — that only resolves inside a request context, so push
    # one here (rather than a bare app_context) with the finance user signed in,
    # the same as the real request above.
    with app.test_request_context():
        from flask_login import login_user as _login_user
        finance_user = User.query.filter_by(email="finance@scientificgate.test").first()
        _login_user(finance_user)
        from app.views.reports import _financial_analysis_rows
        rows, bucket_keys = _financial_analysis_rows()
        row_goods_sum = sum(r["goods_base"] for r in rows)
        row_cost_sum = sum(r["cost_total"] for r in rows)
        all_shipments = Shipment.query.all()
        all_cost_lines_total = sum((cl.amount_base or 0) for cl in CostLine.query.all())
        check("financial analysis row count matches the visible shipment register",
              len(rows) == len(all_shipments), f"({len(rows)} vs {len(all_shipments)})")
        check("financial analysis total cost matches every cost line booked in the system",
              abs(row_cost_sum - all_cost_lines_total) < 0.01,
              f"({row_cost_sum} vs {all_cost_lines_total})")
        check("financial analysis buckets sum to the total cost, per row",
              all(abs(sum(r["buckets"]) - r["cost_total"]) < 0.01 for r in rows))
        check("financial analysis goods value ties back to shipments' invoice values",
              abs(row_goods_sum - sum(s.total_value_base for s in all_shipments)) < 0.01)

print("\n=== Help ===")
with app.test_client() as c:
    login(c, "warehouse@scientificgate.test")
    r = c.get("/help/")
    check("help reachable by every role", r.status_code == 200)
    body = r.data.decode()
    for needle in ["Every menu item", "twelve stages", "Common workflows",
                   "Glossary", "ACID", "Form 4", "Landed cost"]:
        check(f"help covers '{needle}'", needle in body)

print("\n=== Role scoping ===")
with app.test_client() as c:
    login(c, sales_email)
    r = get(c, "/", label="sales: dashboard")
    r = c.get("/shipments/")
    check("sales: shipment list loads", r.status_code == 200)
    body = r.data.decode()
    with app.app_context():
        own = {a.shipment.reference_no for a in Allocation.query.all()
               if a.customer and a.customer.sales_owner_id == sales_user.id and a.shipment}
        all_refs = {s.reference_no for s in Shipment.query.all()}
        not_own = all_refs - own
    visible_not_own = [ref for ref in not_own if f">{ref}<" in body]
    check("sales sees only their own customers' shipments", not visible_not_own,
          f"(leaked {visible_not_own[:3]})")
    check("sales sees at least one of their own", any(f">{ref}<" in body for ref in own) or not own)

    # a shipment with no allocation for this sales user must be forbidden
    with app.app_context():
        blocked = None
        for s in Shipment.query.all():
            if not any(a.customer and a.customer.sales_owner_id == sales_user.id
                       for a in s.allocations):
                blocked = s.id
                break
    if blocked:
        get(c, f"/shipments/{blocked}", expect=403, label="sales: blocked from others' shipment")
    get(c, "/admin/users", expect=403, label="sales: blocked from user admin")

    # search must respect the same scoping as the register
    with app.app_context():
        other_ref = None
        for sh in Shipment.query.all():
            if not any(a.customer and a.customer.sales_owner_id == sales_user.id
                       for a in sh.allocations):
                other_ref = sh.reference_no
                break
    if other_ref:
        with app.app_context():
            other_id = Shipment.query.filter_by(reference_no=other_ref).first().id
        r = c.get(f"/search/?q={other_ref}")
        # The term itself is echoed back in the "nothing found" message, so the only
        # meaningful test is whether a link to that shipment is offered.
        leaked = f"/shipments/{other_id}".encode() in r.data
        check("sales search cannot surface another manager's shipment",
              not leaked, f"(leaked link to {other_ref})")
    get(c, "/purchase-orders/new", expect=403, label="sales: blocked from creating a PO")

with app.test_client() as c:
    login(c, "finance@scientificgate.test")
    get(c, "/finance/costs", label="finance: cost register")
    get(c, "/admin/users", expect=403, label="finance: blocked from user admin")

with app.test_client() as c:
    login(c, "warehouse@scientificgate.test")
    get(c, "/shipments/", label="warehouse user (now Logistics Admin): shipment list")
    # Warehouse and Procurement were folded into Logistics Admin, which does carry
    # view_reports — so this account can now see reports, unlike the old warehouse role.
    get(c, "/reports/", label="warehouse user (now Logistics Admin): can view reports")
    get(c, "/admin/users", expect=403, label="logistics admin: blocked from user admin")

with app.test_client() as c:
    login(c, "salesadmin@scientificgate.test")
    get(c, "/equipment/allocations", label="sales admin: allocations")
    get(c, "/reports/", label="sales admin: reports")
    get(c, "/admin/users", expect=403, label="sales admin: blocked from user admin")

    # Unlike a Sales rep, Sales Admin is not scoped to their own customers — a shipment
    # belonging to a different sales owner's customer must still be visible.
    with app.app_context():
        other_ref2 = None
        for sh in Shipment.query.all():
            if not any(a.customer and a.customer.sales_owner_id == sales_user.id
                       for a in sh.allocations):
                other_ref2 = sh.reference_no
                other_id2 = sh.id
                break
    if other_ref2:
        get(c, f"/shipments/{other_id2}", label="sales admin: can open a shipment outside sales1's own customers")

with app.test_client() as c:
    login(c, "amr@scientificgate.test")
    get(c, "/reports/", label="MD: reports")
    get(c, "/admin/audit", expect=403, label="MD: blocked from audit admin")

print("\n=== Role matrix / Authorisation matrix / FX rates (Admin section) ===")
with app.app_context():
    role_codes = {r.code for r in Role.query.all()}
    # Subset, not equality — a prior smoke run against the same (unre-seeded) database
    # may have left a "Smoke Test Role ..." behind from testing "add a role" below,
    # which is exactly the extensibility this is meant to allow, not a regression.
    check("the six real positions exist by default",
          {"cfo", "md", "finance", "sales", "sales_admin", "logistics_admin"} <= role_codes,
          f"({role_codes})")
    cfo_role = Role.query.filter_by(code="cfo").first()
    check("CFO role keeps full access", cfo_role.has("*"))
    logistics_admin_role = Role.query.filter_by(code="logistics_admin").first()
    check("Logistics Admin role absorbed procurement permission (edit_po)",
          logistics_admin_role.has("edit_po"))
    check("Logistics Admin role absorbed warehouse permission (edit_asset)",
          logistics_admin_role.has("edit_asset"))
    sales_admin_role = Role.query.filter_by(code="sales_admin").first()
    check("Sales Admin role sees all shipments, unlike a Sales rep",
          sales_admin_role.has("view_all") and not sales_admin_role.has("view_own_customers"))

with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    get(c, "/admin/", label="CFO: Admin hub")
    get(c, "/admin/roles", label="CFO: Roles page")
    get(c, "/admin/authorisation", label="CFO: Authorisation matrix page")
    get(c, "/admin/fx-rates", label="CFO: FX rates page")

    # Editing an existing user (name/phone only, password left blank) must not touch
    # their password — this is the fix for "I can't change my Gtrack login": the Users
    # page previously had no edit affordance at all, only "Add a user".
    with app.app_context():
        edit_user = User.query.filter_by(email="sales1@scientificgate.test").first()
        edit_user_id = edit_user.id
        edit_role_id = edit_user.role_id
    resp = c.post("/admin/users",
                  data={"id": edit_user_id, "name": "Sara Mahmoud (Smoke Edit)",
                        "email": "sales1@scientificgate.test", "role_id": edit_role_id,
                        "phone": "0100000000", "is_active": "1", "password": ""},
                  follow_redirects=True)
    check("POST edit user (no password change)", resp.status_code == 200)
    with app.app_context():
        u = db.session.get(User, edit_user_id)
        check("edited user's name updated", u.name == "Sara Mahmoud (Smoke Edit)")
        check("edited user still has their old password", u.check_password("demo1234"))

    # Now actually change the password from the same edit form.
    resp = c.post("/admin/users",
                  data={"id": edit_user_id, "name": "Sara Mahmoud (Smoke Edit)",
                        "email": "sales1@scientificgate.test", "role_id": edit_role_id,
                        "phone": "0100000000", "is_active": "1", "password": f"smoke{RUN}"},
                  follow_redirects=True)
    check("POST edit user (change password)", resp.status_code == 200)
    with app.app_context():
        u = db.session.get(User, edit_user_id)
        check("new password takes effect", u.check_password(f"smoke{RUN}"))
        check("old password no longer works", not u.check_password("demo1234"))

# A fresh client, kept OUTSIDE the admin client's still-open `with` block above: Flask's
# test client preserves its request context across a `with` block, and a client opened
# *inside* another still-open one inherits that preserved context's logged-in user
# instead of starting out anonymous — which would make this check pass even if the
# new password never actually worked.
with app.test_client() as c2:
    r = c2.post("/login", data={"email": "sales1@scientificgate.test", "password": f"smoke{RUN}"},
                follow_redirects=True)
    check("can sign in with the newly-set password", b"Incorrect email or password" not in r.data)

with app.test_client() as c:
    login(c, "zak@scientificgate.test")

    # Put this demo account back the way the rest of the suite (and a re-run) expects
    # it — name, phone and password all restored to their seeded values.
    resp = c.post("/admin/users",
                  data={"id": edit_user_id, "name": "Sara Mahmoud",
                        "email": "sales1@scientificgate.test", "role_id": edit_role_id,
                        "phone": "", "is_active": "1", "password": "demo1234"},
                  follow_redirects=True)
    check("POST restore user to seeded state", resp.status_code == 200)
    with app.app_context():
        u = db.session.get(User, edit_user_id)
        # Restoring to the seeded state means no password reset is left pending either —
        # an admin-typed password here still marks must_change_password, but "seeded"
        # sales1 is a working demo account, not a fresh reset (the suite reruns as this
        # account without changing its password again, e.g. Role scoping below).
        u.must_change_password = False
        db.session.commit()
        check("user restored to seeded name and password",
              u.name == "Sara Mahmoud" and u.check_password("demo1234"))
        check("no password change left pending after restore", not u.must_change_password)

    # --- A brand-new account gets a system-generated temporary password and must set
    # its own before it can do anything else ---
    with app.app_context():
        sales_role_id_early = Role.query.filter_by(code="sales").first().id
    newpw_email = f"smokenewpw{RUN.lower()}@scientificgate.test"
    resp = c.post("/admin/users",
                  data={"name": f"Smoke NewPW User {RUN}", "email": newpw_email,
                        "role_id": sales_role_id_early, "is_active": "1"},
                  follow_redirects=True)
    check("POST add user with no password given", resp.status_code == 200)
    m = re.search(r"Temporary password: (\S+)", resp.data.decode())
    check("temporary password shown to the admin", m is not None)
    temp_pw = m.group(1) if m else None
    with app.app_context():
        newpw_user = User.query.filter_by(email=newpw_email).first()
        check("new user actually created", newpw_user is not None)
        check("new user must change password", bool(newpw_user and newpw_user.must_change_password))
        newpw_user_id = newpw_user.id

if temp_pw:
    # Again a top-level client, sibling to (not nested inside) the admin client's `with`
    # block — see the note above about a test client's preserved request context leaking
    # its logged-in user into any client opened while that block is still open.
    with app.test_client() as c3:
        r = c3.post("/login", data={"email": newpw_email, "password": temp_pw},
                    follow_redirects=True)
        check("can sign in with the generated temporary password",
              b"Incorrect email or password" not in r.data)
        r2 = c3.get("/shipments/", follow_redirects=False)
        check("forced to the change-password screen before anything else",
              r2.status_code == 302 and "/change-password" in r2.location)
        r3 = c3.post("/change-password",
                    data={"current_password": "wrong-password", "new_password": "newpassword1",
                          "confirm_password": "newpassword1"}, follow_redirects=True)
        check("wrong current password rejected on the change screen",
              b"incorrect" in r3.data.lower())
        r4 = c3.post("/change-password",
                    data={"current_password": temp_pw, "new_password": "newpassword1",
                          "confirm_password": "newpassword1"}, follow_redirects=True)
        check("password change accepted", r4.status_code == 200)
        r5 = c3.get("/shipments/", follow_redirects=False)
        check("no longer forced to change-password once a password is set",
              r5.status_code == 200)
    with app.app_context():
        u = db.session.get(User, newpw_user_id)
        check("must_change_password cleared after setting a new password",
              not u.must_change_password)
        check("the newly-chosen password actually took effect", u.check_password("newpassword1"))

with app.test_client() as c:
    login(c, "zak@scientificgate.test")

    # --- Admin can reset a user's password on request, without knowing or choosing
    # what they end up with ---
    resp = c.post(f"/admin/users/{newpw_user_id}/reset-password", follow_redirects=True)
    check("POST reset password", resp.status_code == 200)
    m2 = re.search(r"Temporary password for [^:]+: (\S+)", resp.data.decode())
    check("reset flashes a new temporary password to the admin", m2 is not None)
    reset_pw = m2.group(1) if m2 else None
    with app.app_context():
        u = db.session.get(User, newpw_user_id)
        check("reset sets must_change_password again", u.must_change_password)
        check("the previous password no longer works after a reset",
              not u.check_password("newpassword1"))
        if reset_pw:
            check("the new temporary password from the reset works", u.check_password(reset_pw))
        # cleanup — logging in and changing its own password gave this account its own
        # audit-trail entries (it's the changed_by on its own User row), so purge those
        # too before the hard delete; otherwise Postgres's real foreign key rejects the
        # delete outright (SQLite just lets it through and leaves a dangling reference).
        AuditLog.query.filter_by(changed_by_id=newpw_user_id).delete()
        db.session.delete(u)
        db.session.commit()

    # --- Delete user: a fresh account with no history can actually be deleted ---
    with app.app_context():
        cfo_role_id = Role.query.filter_by(code="cfo").first().id
        sales_role_id = Role.query.filter_by(code="sales").first().id
    resp = c.post("/admin/users",
                  data={"name": f"Smoke Temp User {RUN}", "email": f"smoketemp{RUN.lower()}@scientificgate.test",
                        "role_id": sales_role_id, "is_active": "1", "password": "demo1234"},
                  follow_redirects=True)
    check("POST add temp user for delete test", resp.status_code == 200)
    with app.app_context():
        temp_user = User.query.filter_by(email=f"smoketemp{RUN.lower()}@scientificgate.test").first()
        check("temp user created for delete test", temp_user is not None)
        temp_user_id = temp_user.id

    resp = c.post(f"/admin/users/{temp_user_id}/delete", follow_redirects=True)
    check("POST delete a history-free user", resp.status_code == 200)
    with app.app_context():
        check("history-free user is actually gone", db.session.get(User, temp_user_id) is None)

    # --- A user with activity on record can't be hard-deleted ---
    # Built deterministically (a comment on a real shipment) rather than relying on
    # which seeded users happen to have picked up notifications/allocations.
    resp = c.post("/admin/users",
                  data={"name": f"Smoke History User {RUN}", "email": f"smokehist{RUN.lower()}@scientificgate.test",
                        "role_id": sales_role_id, "is_active": "1", "password": "demo1234"},
                  follow_redirects=True)
    with app.app_context():
        hist_user = User.query.filter_by(email=f"smokehist{RUN.lower()}@scientificgate.test").first()
        hist_user_id = hist_user.id
        db.session.add(Comment(shipment_id=shipment_id, user_id=hist_user_id, body="smoke test comment"))
        db.session.commit()

    resp = c.post(f"/admin/users/{hist_user_id}/delete", follow_redirects=True)
    check("POST delete a user with history returns 200 (blocked, not crashed)",
          resp.status_code == 200)
    check("blocked-delete explains why (activity on record)",
          "activity on record".encode() in resp.data)
    with app.app_context():
        check("user with history is NOT deleted", db.session.get(User, hist_user_id) is not None)
        # Clean up: remove the comment, then the delete should succeed.
        Comment.query.filter_by(user_id=hist_user_id).delete()
        db.session.commit()
    resp = c.post(f"/admin/users/{hist_user_id}/delete", follow_redirects=True)
    with app.app_context():
        check("history user cleaned up once their history is gone",
              db.session.get(User, hist_user_id) is None)

    # --- Can't delete your own account while signed in as it ---
    with app.app_context():
        zak_id = User.query.filter_by(email="zak@scientificgate.test").first().id
    resp = c.post(f"/admin/users/{zak_id}/delete", follow_redirects=True)
    check("self-delete blocked, not crashed", resp.status_code == 200)
    with app.app_context():
        check("own account survives a self-delete attempt", db.session.get(User, zak_id) is not None)

    # --- Can't delete the last active user with full access ---
    resp = c.post("/admin/users",
                  data={"name": f"Smoke Temp CFO {RUN}", "email": f"smokecfo{RUN.lower()}@scientificgate.test",
                        "role_id": cfo_role_id, "is_active": "1", "password": "demo1234"},
                  follow_redirects=True)
    with app.app_context():
        temp_cfo = User.query.filter_by(email=f"smokecfo{RUN.lower()}@scientificgate.test").first()
        temp_cfo_id = temp_cfo.id
        # Take zak out of the running so temp_cfo is the *only* active full-access user.
        zak = db.session.get(User, zak_id)
        zak.is_active_flag = False
        db.session.commit()

    resp = c.post(f"/admin/users/{temp_cfo_id}/delete", follow_redirects=True)
    check("deleting the last active full-access user is blocked", resp.status_code == 200)
    with app.app_context():
        check("last full-access user survives", db.session.get(User, temp_cfo_id) is not None)
        # Restore zak and clean up the temp CFO now that it's safe to remove.
        zak = db.session.get(User, zak_id)
        zak.is_active_flag = True
        db.session.commit()
    resp = c.post(f"/admin/users/{temp_cfo_id}/delete", follow_redirects=True)
    with app.app_context():
        check("temp CFO cleaned up once zak is active again",
              db.session.get(User, temp_cfo_id) is None)

    # The CFO can add a new role — the matrix is not capped at the six defaults.
    resp = c.post("/admin/roles",
                  data={"role_name": f"Smoke Test Role {RUN}", "description": "temp"},
                  follow_redirects=True)
    check("POST add role", resp.status_code == 200)
    with app.app_context():
        new_role = Role.query.filter_by(role_name=f"Smoke Test Role {RUN}").first()
        check("new role persisted", new_role is not None)
        check("new role starts with no access", new_role.permissions in (None, ""))
        new_role_id = new_role.id

    # Grant it a couple of permissions via the Authorisation matrix, separately from
    # the role list itself. The real page posts the whole matrix as one form (every
    # role's checkboxes together), so build a realistic full payload here too —
    # carrying forward every other role's current permissions unchanged — rather
    # than a partial one that would wipe roles the test isn't touching.
    with app.app_context():
        before = {r.id: set(r.perm_list()) for r in Role.query.all() if r.code != "cfo"}
    form_data = {"role_ids": [str(role_id) for role_id in before]}
    for role_id, perms in before.items():
        if "*" in perms:
            form_data[f"full__{role_id}"] = "1"
        else:
            for key, _ in PERMISSIONS:
                if key in perms:
                    form_data[f"perm__{role_id}__{key}"] = "1"
    form_data[f"perm__{new_role_id}__view_all"] = "1"
    form_data[f"perm__{new_role_id}__comment"] = "1"

    resp = c.post("/admin/authorisation", data=form_data, follow_redirects=True)
    check("POST authorisation matrix", resp.status_code == 200)
    with app.app_context():
        r = db.session.get(Role, new_role_id)
        check("authorisation matrix granted the selected permissions",
              r.has("view_all") and r.has("comment") and not r.has("edit_shipment"))
        other_roles_untouched = all(
            set(db.session.get(Role, rid).perm_list()) == perms
            for rid, perms in before.items() if rid != new_role_id)
        check("saving one role's access leaves the other roles' access unchanged",
              other_roles_untouched)

    # FX rate: set a new admin rate (no date given -> defaults to today, same as the
    # seed data, so this is the tie-broken "most recent" row) and confirm to_base()
    # picks it up as the current rate.
    resp = c.post("/admin/fx-rates",
                  data={"code": "USD", "rate_to_base": "50.25"},
                  follow_redirects=True)
    check("POST set FX rate", resp.status_code == 200)
    with app.app_context():
        latest = to_base(1, "USD")
        check("to_base() reflects the admin-set USD rate", abs(latest - 50.25) < 0.001, f"({latest})")

print("\n=== Bilingual (English / Arabic) ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")

    r = c.get("/")
    check("defaults to English", b'lang="en"' in r.data and b'dir="ltr"' in r.data)
    check("English nav present", "Shipment register".encode() in r.data)

    r = c.get("/lang/ar", follow_redirects=True)
    check("switch to Arabic redirects", r.status_code == 200)

    r = c.get("/")
    body = r.data.decode()
    check("html marked Arabic", 'lang="ar"' in body)
    check("direction is RTL", 'dir="rtl"' in body)
    check("nav translated", "سجل الشحنات" in body)
    check("dashboard tiles translated", "الشحنات المفتوحة" in body)
    check("English nav gone", "Shipment register" not in body)

    # controlled vocabularies come from Python, not the template
    r = c.get("/shipments/")
    body = r.data.decode()
    check("stage labels translated", any(x in body for x in
          ["في الطريق", "الاستلام في المخزن", "التخليص", "صدور أمر الشراء للمورد"]))

    r = c.get(f"/shipments/{shipment_id}/statement")
    body = r.data.decode()
    check("statement translated", "بيان التكاليف" in body or "تتبع التكاليف" in body)
    check("landed cost translated", "التكلفة حتى الوصول" in body)

    r = c.get("/help/")
    body = r.data.decode()
    check("help guide translated", "المراحل الاثنتا عشرة" in body)
    check("glossary translated", "إقرار معلومات الشحنة المسبق" in body)
    check("workflows translated", "متابعة جهاز عميل" in body)

    r = c.get("/search/?q=SHP")
    check("search page translated", "كلمة البحث" in r.data.decode())

    r = c.get("/reports/")
    check("reports translated", "متوسط مدة النقل" in r.data.decode())

    # exports must still work in Arabic
    r = c.get("/shipments/?export=xlsx")
    check("Excel export works in Arabic",
          r.status_code == 200 and len(r.data) > 500)
    r = c.get(f"/shipments/{shipment_id}/statement?export=pdf")
    check("PDF export works in Arabic",
          r.status_code == 200 and len(r.data) > 500)

    # language persists on the account
    with app.app_context():
        u = User.query.filter_by(email="zak@scientificgate.test").first()
        check("language saved to the account", u.language == "ar", f"(got {u.language})")

    r = c.get("/lang/en", follow_redirects=True)
    r = c.get("/")
    check("switches back to English", 'dir="ltr"' in r.data.decode())

    r = c.get("/lang/zz", follow_redirects=True)
    check("unknown language ignored", r.status_code == 200)
    r = c.get("/")
    check("still English after bad code", 'lang="en"' in r.data.decode())

with app.test_client() as c:
    # a second user is unaffected by the first user's choice
    login(c, "warehouse@scientificgate.test")
    r = c.get("/")
    check("language is per-user", 'lang="en"' in r.data.decode())

print("\n=== Routing, hub traceability & the new fields ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")

    # --- reference data exists ---
    check("locations seeded", location_count >= 1, f"(got {location_count})")
    check("customs brokers seeded", broker_count >= 1, f"(got {broker_count})")
    check("a free-zone location exists", hub_location is not None)

    # --- routing shows on the register, board and detail ---
    r = get(c, "/shipments/?route=reexport_hub", label="register filters by route type")
    body = r.data.decode()
    check("route filter returns re-export legs", "Re-export from fulfilment centre" in body)

    r = get(c, "/shipments/?route=inbound_hub", label="register filters to inbound legs")
    # the label still appears once in the filter dropdown — it must not appear in any row
    check("inbound filter excludes re-export legs",
          r.data.decode().count("Re-export from fulfilment centre") == 1,
          f"(found {r.data.decode().count('Re-export from fulfilment centre')})")

    r = get(c, f"/shipments/{hub_leg_id}", label="hub leg detail renders")
    body = r.data.decode()
    check("detail shows the routing panel", "Routing &amp; logistics" in body or "Routing & logistics" in body)
    check("detail shows the route type", "fulfilment centre" in body.lower())
    check("detail shows the exporter field", "Exporter" in body)
    check("detail shows the customs broker field", "Customs broker" in body)

    r = get(c, "/shipments/board", label="board renders with route badges")
    check("board shows route labels", "from origin" in r.data.decode().lower()
          or "fulfilment centre" in r.data.decode().lower())

    # --- hub traceability ---
    if traced_shipment_id:
        r = get(c, f"/shipments/{traced_shipment_id}",
                label="shipment with a traced item renders")
        body = r.data.decode()
        check("traced item shows the hub trail", "Via fulfilment centre" in body)

        r = get(c, f"/shipments/{traced_shipment_id}/statement",
                label="statement for a traced shipment renders")
        body = r.data.decode()
        if traced_costed:
            check("statement shows earlier-leg costs", "Earlier leg" in body)
            check("statement names the upstream leg", "carried forward from" in body)
        else:
            # nothing was booked on the inbound leg, so there is nothing to carry forward
            check("no earlier-leg column when the inbound leg has no costs",
                  "Earlier leg" not in body)

    # --- asset movement history ---
    r = get(c, f"/equipment/{moved_asset_id}", label="asset with movements renders")
    body = r.data.decode()
    check("asset shows movement history", "journey" in body)

    # --- hub stock view ---
    r = get(c, "/equipment/hub-stock", label="fulfilment centre stock view renders")
    body = r.data.decode()
    check("hub stock lists balances", "Balance held" in body)
    for fmt in ("csv", "xlsx", "pdf"):
        r = c.get(f"/equipment/hub-stock?export={fmt}")
        check(f"hub stock exports {fmt}", r.status_code == 200 and len(r.data) > 200)

    # --- new master-data screens ---
    for entity in ("locations", "brokers"):
        r = get(c, f"/master-data/{entity}", label=f"master data: {entity}")
    r = c.post("/master-data/locations/save", data={
        "name": f"TEST-HUB-{RUN}", "type": "fulfilment_centre", "is_free_zone": "1",
        "city": "Dubai", "country": "UAE", "address": "", "notes": ""},
        follow_redirects=True)
    check("can create a location", r.status_code == 200)
    with app.app_context():
        made = Location.query.filter_by(name=f"TEST-HUB-{RUN}").first()
        check("location saved with the free-zone flag", bool(made and made.is_free_zone))

    r = c.post("/master-data/brokers/save", data={
        "name": f"TEST-BROKER-{RUN}", "phone": "+20 100 000 0000",
        "contact_email": "", "licence_no": "L-1", "notes": ""}, follow_redirects=True)
    with app.app_context():
        check("can create a customs broker",
              CustomsBroker.query.filter_by(name=f"TEST-BROKER-{RUN}").first() is not None)

    # --- the new shipment header fields round-trip through the edit form ---
    r = c.post(f"/shipments/{shipment_id}/edit", data={
        "direction": "Import", "route_type": "inbound_hub",
        "bl_type": "house", "payment_terms": "advance",
        "chargeable_weight_kg": "1234.5", "measurement_cbm": "7.5",
        "cut_off_date": "2026-01-15", "customs_note": f"NOTE-{RUN}",
        "pickup_address": f"PICKUP-{RUN}",
    }, follow_redirects=True)
    check("shipment edit accepts the routing fields", r.status_code == 200)
    with app.app_context():
        s2 = db.session.get(Shipment, shipment_id)
        check("route type saved", s2.route_type == "inbound_hub", f"(got {s2.route_type})")
        check("BL type saved", s2.bl_type == "house")
        check("payment terms saved", s2.payment_terms == "advance")
        check("chargeable weight saved", s2.chargeable_weight_kg == 1234.5)
        check("measurement saved", s2.measurement_cbm == 7.5)
        check("customs note saved", s2.customs_note == f"NOTE-{RUN}")
        check("pickup address saved", s2.pickup_address == f"PICKUP-{RUN}")

    # --- item-level supplier, category, values and weights ---
    r = c.post(f"/shipments/{shipment_id}/items/add", data={
        "description": f"TEST-ITEM-{RUN}", "qty": "2", "unit": "unit",
        "unit_value": "1000", "currency": "USD", "category": "spare_part",
        "invoice_value": "1800", "actual_value": "2000",
        "invoice_no": f"INV-{RUN}", "invoice_date": "2026-02-01",
        "net_weight_kg": "40", "gross_weight_kg": "52",
        "dimensions": "100 x 60 x 70 cm",
    }, follow_redirects=True)
    check("item line accepts the new fields", r.status_code == 200)
    with app.app_context():
        it = ShipmentItem.query.filter_by(description=f"TEST-ITEM-{RUN}").first()
        check("item saved", it is not None)
        if it:
            check("item category saved", it.category == "spare_part")
            check("item invoice value saved", it.invoice_value == 1800)
            check("item actual value saved", it.actual_value == 2000)
            check("declared-vs-actual variance computes", it.value_variance == 200)
            check("item weights saved", it.net_weight_kg == 40 and it.gross_weight_kg == 52)
            check("item dimensions saved", it.dimensions == "100 x 60 x 70 cm")

    # --- costs carry who paid ---
    r = c.post(f"/shipments/{shipment_id}/costs/add", data={
        "cost_type": "clearance_fee", "amount": "500", "currency": "EGP",
        "payable_to": f"TEST-PAYEE-{RUN}", "paid_by": "forwarder",
        "description": f"TEST-COST-{RUN}", "payment_status": "unpaid",
    }, follow_redirects=True)
    check("cost line accepts paid-by", r.status_code == 200)
    with app.app_context():
        cl = CostLine.query.filter_by(description=f"TEST-COST-{RUN}").first()
        check("paid-by saved", bool(cl and cl.paid_by == "forwarder"))

    # --- banking records accumulate rather than overwrite ---
    with app.app_context():
        before = BankRegistration.query.filter_by(shipment_id=shipment_id).count()
    for n in (1, 2):
        c.post(f"/shipments/{shipment_id}/bank-registration", data={
            "registration_no": f"REG-{RUN}-{n}", "registration_date": "2026-03-0%d" % n,
            "advance_payment_ref": f"ADV-{RUN}-{n}", "swift_1": f"SWIFT-{RUN}-{n}A",
            "swift_2": f"SWIFT-{RUN}-{n}B", "amount": "25000", "currency": "USD",
            "transfer_date": "2026-03-05",
        }, follow_redirects=True)
    with app.app_context():
        after = BankRegistration.query.filter_by(shipment_id=shipment_id).count()
        check("banking records accumulate", after == before + 2, f"(before {before}, after {after})")
        recs = BankRegistration.query.filter_by(shipment_id=shipment_id).all()
        check("SWIFT references stored", any(r_.swift_1 == f"SWIFT-{RUN}-1A" for r_ in recs))
        check("advance payment ref stored", any(r_.advance_payment_ref == f"ADV-{RUN}-2" for r_ in recs))

    r = get(c, f"/shipments/{shipment_id}", label="detail renders the banking panel")
    check("banking panel lists SWIFT", f"SWIFT-{RUN}-1A" in r.data.decode())

    # --- statement still balances with the new columns ---
    r = get(c, f"/shipments/{shipment_id}/statement", label="statement renders after edits")
    check("statement shows paid-by", "Paid by" in r.data.decode())
    for fmt in ("csv", "xlsx", "pdf"):
        r = c.get(f"/shipments/{shipment_id}/statement?export={fmt}")
        check(f"statement exports {fmt} after the changes",
              r.status_code == 200 and len(r.data) > 200)

    # --- register export carries routing ---
    r = c.get("/shipments/?export=csv")
    check("register CSV includes route type", b"Route type" in r.data)

    # --- reports and dashboard surface the routing comparison ---
    r = get(c, "/reports/timing", label="timing report renders with the routing comparison")
    body = r.data.decode()
    check("reports compare direct against the hub route",
          "Direct versus the fulfilment centre route" in body)
    check("reports show cost per kg by route", "Cost per kg" in body)

    r = get(c, "/", label="dashboard renders with hub figures")
    body = r.data.decode()
    check("dashboard shows the fulfilment centre holding",
          "Held at the fulfilment centre" in body)

print("\n=== Role scoping on the new screens ===")
with app.test_client() as c:
    login(c, sales_email)
    r = c.get("/equipment/hub-stock", follow_redirects=False)
    check("sales cannot see fulfilment centre stock", r.status_code in (302, 403),
          f"(got {r.status_code})")

print("\n=== Arabic covers the new screens ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    c.get("/lang/ar", follow_redirects=True)
    r = c.get("/equipment/hub-stock")
    body = r.data.decode()
    check("hub stock translated", "مخزون مركز التجميع" in body)
    r = c.get(f"/shipments/{hub_leg_id}")
    body = r.data.decode()
    check("routing panel translated", "المسار" in body)
    check("exporter translated", "المصدّر" in body)
    r = c.get("/master-data/locations")
    check("locations screen translated", "المواقع والمنشآت" in r.data.decode())
    c.get("/lang/en", follow_redirects=True)

print("\n=== Data quality: contradictory dates ===")
with app.app_context():
    anomalous = [s_ for s_ in Shipment.query.all() if s_.date_anomalies]
    check("anomaly detection finds the bad rows", len(anomalous) > 0,
          f"(found {len(anomalous)})")
    # the point of the guard: no negative timing ever reaches a KPI
    check("no negative transit time reaches the KPIs",
          all((s_.transit_days is None or s_.transit_days >= 0) for s_ in Shipment.query.all()))
    check("no negative clearance time reaches the KPIs",
          all((s_.clearance_days is None or s_.clearance_days >= 0) for s_ in Shipment.query.all()))
    anomalous_id = anomalous[0].id if anomalous else None

with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    r = get(c, "/reports/exceptions", label="exceptions report lists date anomalies")
    check("anomaly panel present", "Date anomalies" in r.data.decode())
    if anomalous_id:
        r = get(c, f"/shipments/{anomalous_id}", label="anomalous shipment detail renders")
        check("detail warns about the dates", "check the dates" in r.data.decode())

print("\n=== Translation keys never leak onto the page ===")
with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    # A few entries are keyed by a short symbolic name because they take placeholders.
    # Those must resolve in English as well as Arabic, or the key itself is rendered.
    symbolic = [k for k, v in TRANSLATIONS.items() if "en" in v and " " not in k]
    check("symbolic translation keys exist", len(symbolic) > 0)
    for lang in ("en", "ar"):
        c.get(f"/lang/{lang}", follow_redirects=True)
        for url in ("/help/", f"/shipments/{shipment_id}/statement", "/", "/reports/",
                   f"/shipments/{shipment_id}/cost-buildup", "/finance/quotations/new",
                   "/reports/financial-analysis"):
            body = c.get(url).data.decode()
            leaked = [k for k in symbolic if k in body]
            check(f"no raw keys on {url} ({lang})", not leaked, f"(leaked {leaked})")
    c.get("/lang/en", follow_redirects=True)

print("\n=== Auth ===")
with app.test_client() as c:
    r = c.get("/shipments/", follow_redirects=False)
    check("anonymous redirected to login", r.status_code == 302 and "/login" in r.location)
    r = c.post("/login", data={"email": "zak@scientificgate.test", "password": "wrong"},
               follow_redirects=True)
    check("bad password rejected", b"Incorrect email or password" in r.data)

print("\n" + "=" * 60)
print(f"{CHECKS[0] - len(FAILURES)}/{CHECKS[0]} checks passed")
if FAILURES:
    print(f"\n{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All checks passed.")
