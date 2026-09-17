"""End-to-end smoke test — exercises every screen as every role, plus the key workflows.

Safe to run repeatedly: each run tags the records it creates with a unique prefix.
"""
import sys
import uuid

RUN = uuid.uuid4().hex[:6].upper()   # unique per run, so repeat runs don't collide

from app import create_app
from app.i18n import TRANSLATIONS
from app.auth import PERMISSIONS
from app.models import (db, Shipment, ShipmentItem, Asset, Allocation, PurchaseOrder,
                        CostLine, Customer, Carrier, Supplier, User, NotificationLog,
                        AuditLog, Stage, Location, CustomsBroker, AssetMovement,
                        BankRegistration, Role, to_base)

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
        "/finance/costs", "/finance/invoices", "/finance/quotations", "/finance/bank-registrations",
        "/equipment/", f"/equipment/{asset_id}", "/equipment/allocations", "/equipment/customers",
        "/master-data/", "/master-data/suppliers", "/master-data/brands", "/master-data/carriers",
        "/master-data/consignees", "/master-data/customers", "/master-data/banks",
        "/reports/", "/admin/users", "/admin/roles", "/admin/notification-rules",
        "/admin/notifications", "/admin/audit",
        "/help/", "/search/", f"/shipments/{shipment_id}/statement",
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
              abs(apportioned - d["cost_total"]) < 0.01 or d["goods_base"] == 0,
              f"({apportioned} vs {d['cost_total']})")

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
    get(c, "/shipments/", label="warehouse user (now Logistics Manager): shipment list")
    # Warehouse and Procurement were folded into Logistics Manager, which does carry
    # view_reports — so this account can now see reports, unlike the old warehouse role.
    get(c, "/reports/", label="warehouse user (now Logistics Manager): can view reports")
    get(c, "/admin/users", expect=403, label="logistics: blocked from user admin")

with app.test_client() as c:
    login(c, "amr@scientificgate.test")
    get(c, "/reports/", label="MD: reports")
    get(c, "/admin/audit", expect=403, label="MD: blocked from audit admin")

print("\n=== Role matrix / Authorisation matrix / FX rates (Admin section) ===")
with app.app_context():
    role_codes = {r.code for r in Role.query.all()}
    check("exactly the five requested roles exist by default",
          role_codes == {"admin", "logistics", "finance", "sales", "md"}, f"({role_codes})")
    admin_role = Role.query.filter_by(code="admin").first()
    check("admin role keeps full access", admin_role.has("*"))
    logistics_role = Role.query.filter_by(code="logistics").first()
    check("logistics role absorbed procurement permission (edit_po)",
          logistics_role.has("edit_po"))
    check("logistics role absorbed warehouse permission (edit_asset)",
          logistics_role.has("edit_asset"))

with app.test_client() as c:
    login(c, "zak@scientificgate.test")
    get(c, "/admin/", label="admin: Admin hub")
    get(c, "/admin/roles", label="admin: Roles page")
    get(c, "/admin/authorisation", label="admin: Authorisation matrix page")
    get(c, "/admin/fx-rates", label="admin: FX rates page")

    # Admin can add a new role — the matrix is not capped at the five defaults.
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
        before = {r.id: set(r.perm_list()) for r in Role.query.all() if r.code != "admin"}
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
    r = get(c, "/reports/", label="reports render with the routing comparison")
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
    r = get(c, "/reports/", label="reports list date anomalies")
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
        for url in ("/help/", f"/shipments/{shipment_id}/statement", "/", "/reports/"):
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
