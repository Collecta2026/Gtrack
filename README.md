# Gtrack — Import & Equipment Tracking

A working test build of the data design, implementing the full specification: purchase
order through to installation handover, with document upload, per-shipment costing,
freight quotations, serial-number tracking and customer allocation.

Built on the same stack as Collecta — Flask, SQLAlchemy, Jinja2 — so it deploys the same
way. SQLite by default so it runs with no database server; switch to Postgres with one
environment variable.

---

## Installing and running it

You need Python 3.10 or newer. Check with `py --version` (Windows) or `python3 --version`.
If it is missing, install it from python.org — on Windows, tick **"Add Python to PATH"**
during setup.

### Windows

1. Unzip `gtrack.zip` anywhere, e.g. your Downloads folder.
2. Open the extracted folder and go in until you can see `run.py` and
   `start_windows.bat` side by side.
3. Double-click **`start_windows.bat`**.
4. Wait for it to finish installing and seeding — a minute or two the first time.
5. Open **http://127.0.0.1:5000** in your browser.
6. There are no accounts yet, so Gtrack walks you straight to a one-time setup screen —
   enter your name, email and a password of your own choosing to create the admin
   account. You're signed in immediately; add everyone else afterwards from
   **Admin -> Users**.

Leave the black window open while you use it — that is the server. Close it or press
`Ctrl+C` to stop. To start it again later, double-click the same file; it keeps the
database you already have.

### macOS / Linux

```bash
unzip gtrack.zip && cd gtrack
./start.sh
```

Then open http://127.0.0.1:5000.

### Doing it manually

From the folder containing `run.py`:

```bash
pip install -r requirements.txt
python seed.py         # builds the database from the spreadsheet
python run.py          # starts the server
```

`requirements.txt` is the local set — pure Python, no compiler needed.
`requirements-deploy.txt` adds gunicorn and the Postgres driver, and is only used when
deploying to Render or Docker.

On Windows use `py` instead of `python` if the latter isn't recognised. If you would
rather not install packages system-wide:

```bash
py -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

### If something goes wrong

**"The database has no Gtrack tables yet"** — run `python seed.py` first.

**"Cannot reach the database"** — Gtrack is pointed at an external database. Clear it for
this window with `set GTRACK_DATABASE_URL=` (Windows) or `unset GTRACK_DATABASE_URL`
(macOS/Linux) and it will fall back to the local SQLite file.

**A package fails to build / "pg_config is required"** — you are installing the server
requirements. Gtrack itself needs no compiler: install `requirements.txt`, not
`requirements-deploy.txt`. The Postgres driver is only needed when deploying.

**Port 5000 already in use** — run on another port: `set PORT=5050` then `python run.py`.

**Windows Firewall prompt** — you can decline it. `127.0.0.1` works either way; allowing
it only matters if you want to reach Gtrack from another device on your network.

### Accounts

There is no seeded login, and no directory of demo accounts on the sign-in screen — a
fresh database has zero accounts on purpose. The **first time** anyone opens Gtrack, it
shows a one-time setup screen instead of a login form: whoever gets there first creates
the admin account, choosing their own email and password (nobody else, including us, ever
knows it). That account has full access — Admin -> Users, Roles, Authorisation matrix, FX
rates — and from there you create everyone else's login, assign each one a role from the
matrix below, and hand out its one-time temporary password (**Admin -> Users** covers this
in full, including how to reset a forgotten password).

| Role | What they see |
|---|---|
| CFO | Everything, plus Admin -> Users, Roles, Authorisation matrix, FX rates |
| MD | Full read + dashboards, no admin |
| Finance | Costs, payments, bank registration, the Financial analysis report |
| Sales | **Only their own customers' shipments** |
| Sales Admin | All customers' allocations, not just their own |
| Logistics Admin | POs, supplier invoices, suppliers, shipments, stages, Form 4, warehouse receipt |

The demo shipment history (below) still seeds in, so there's real data to look at as soon
as you sign in — just no people attached to it until you add your own.

---

## What's in the seeded data

`seed.py` migrates the real **Shipments Tracking.xlsx** following Section 10 of the design
document, then adds a demo layer for the parts the spreadsheet never captured.

Migrated from the spreadsheet:

- **116 shipments**, every row preserved
- **18 suppliers, 45 brands, 32 carriers, 5 consignee entities** — extracted and
  de-duplicated (spelling and spacing variants collapsed into one record each)
- Weight, quantity, invoice value and shipping cost **split from their embedded units and
  currency symbols** into proper numeric fields
- Free-text status **mapped onto the twelve-stage pipeline**; the original text is kept in
  `legacy_status` so nothing is lost
- Shipping and customs costs **split into individual cost lines**, with payment status read
  from the old Paid/Shipper and Paid/Customs notes (including the Arabic ones)
- **Form 4** records, including the "IN < 2000$" cases recorded as threshold exemptions
- Document checklists derived from the "DOC in Office" flag
- Status history **reconstructed** from the invoice, clearance and arrival dates on each row
- **Route classified from the pathway column** — 52 direct origin→Cairo imports, 9 stock legs
  into the Jebel Ali fulfilment centre, 54 re-exports out of it, 1 outbound
- **Al Bawaba typed as an internal Scientific Gate entity**, not a third-party supplier, so
  intercompany movements are distinguishable from genuine external purchases (it is the
  exporter on 57 shipments)
- **Hub journeys linked** — re-exported item lines tied back to the inbound line they came
  from, with 179 asset movements written across the legs

Generated for the demo (the spreadsheet has none of this):

- **191 serialised units** with warranty dates
- **8 customers** with assigned sales owners, and ~118 allocations of specific machines
- **26 purchase orders** with lines, and supplier invoices against them
- **75 freight quotations** across competing forwarders, one selected per shipment
- A scatter of internal comments, plus due dates on unpaid costs

Because the spreadsheet is almost entirely historical ("Delivered"), the seed spreads the
most recent shipments across the live pipeline stages so the board and dashboard have
something to show. Older records keep their migrated state untouched.

To rebuild at any time: `python seed.py` (destructive). `python seed.py --keep` only seeds
an empty database.

---

## What's implemented

Everything in the specification, organised as it is in the document.

**Procurement** — purchase orders with lines and status workflow, part-shipment tracking
(ordered vs shipped vs outstanding per line), supplier invoices linked to both PO and
shipment, automatic overdue-PO alerting.

**Quotation & booking** — multiple competing quotations per shipment, one marked selected,
and a quoted-vs-actual variance report. Both sides are converted to EGP before comparison,
because quotes come in USD and freight invoices often arrive in EGP.

**Shipment tracking** — the twelve-stage pipeline, every stage timestamped and attributed
in Status History; list view with filters and free search; Kanban pipeline board;
planned-vs-actual dates with automatic delay flags and days-in-stage ageing.

**Routing & the fulfilment centre** — each shipment typed as direct, inbound to the
fulfilment centre, re-export from it, an internal transfer or outbound, with from/to
locations held against SGE's own facilities. The exporter is recorded separately from the
supplier, because on a re-export leg the shipper is SGE's own free-zone entity while the
original manufacturers stay on the item lines. A **Fulfilment centre stock** screen shows
what is held in the free zone, what has been called forward against orders, the balance,
its value and how long it has been sitting there.

**Customs** — ACID capture, bill type (master/house), the customs broker handling it, and
bank registration. Banking records **accumulate** rather than overwrite — a shipment
part-paid in advance and part against documents produces more than one, each with its own
advance payment reference, two SWIFT references, amount, currency and transfer date.
Threshold exemptions recorded with the reason; HS codes held at item level.

**Documents** — real file upload per shipment, a required/received checklist per document
type, version increment on replacement, download with audit trail.

**Costing** — sixteen cost categories, each line with currency, payee, **who paid it**
(us, the forwarder or the supplier), payment status and due date; multi-currency conversion
to EGP; overdue flagging; payables reporting. On a re-export leg the statement carries
forward the share of the **inbound leg's** freight, duty and handling that belongs to those
units, giving a **true landed total** across every leg — costing the re-export on its own
would understate what the machine actually cost to land in Cairo.

**Equipment & allocation** — serial-number-level asset records; allocation of a specific
unit (or a quantity of a bulk item) to a named customer at any stage; warranty register;
installation confirmation; allocation backlog and per-customer views.

**Notifications** — nine configurable rules covering stage-reached, ETA countdown, delay,
missing documents, overdue payment, overdue PO and a weekly digest. Sales alerts route
only to the account manager who owns an allocated customer on that shipment, not the whole
team. Rules are editable in the admin screen without a code change.

**Reporting** — transit and clearance timing by mode and lane, on-time performance, cost
per shipment and per kg, cost by category, brand and supplier performance, ageing,
document gaps, equipment by status, value in transit by currency, plus a **direct versus
fulfilment centre** comparison (cost as a share of goods value, cost per kilogram, transit
and clearance time by route) and a **date anomalies** list. Every table exports to CSV,
Excel and PDF.

**Data quality** — rows migrated from the spreadsheet sometimes carry dates that cannot both
be true (departure after arrival, customs release before arrival). Those transit and
clearance times read as *unknown* rather than being counted as negative, so no average is
skewed, and the affected shipments are listed in Reports and flagged on their own page for
correction at source.

**Access & audit** — six roles out of the box, matching the company's actual positions
(CFO, MD, Finance, Sales, Sales Admin, Logistics Admin), each with per-permission scoping;
the CFO can add more at any time from **Admin -> Roles**, with no code change. What a role
can actually see and do is set separately, on the **Authorisation matrix**, decoupled from
the role list itself — a new role starts with no access until it is granted some there.
Sales users are restricted at the query level to shipments carrying their own customers'
allocations; Sales Admin sees and manages every customer's allocations. A full audit log
captures every field-level change with the user who made it.

**Admin section** — a dedicated area (**Admin** in the sidebar) grouping Users, Roles, the
Authorisation matrix and FX rates, alongside Master data, Notification rules and the Audit
log. This is where role and access changes, and exchange-rate updates, actually happen.

---

## Testing

```bash
python test_smoke.py
```

Exercises every screen as every role, all export formats, the main workflows (stage
advance, serial capture, allocation, installation confirmation, costs, quotations, Form 4)
and the access-control boundaries — including the two-step route through the fulfilment
centre, hub traceability, the accumulating banking records, the new item and header fields,
role scoping on the stock view, and a guard that no translation key ever leaks onto a page.
235 checks; safe to run repeatedly, and verified against both SQLite and real PostgreSQL.

---

## Bilingual — English and Arabic

A language toggle sits at the bottom of the sidebar (**EN / ع**). Switching flips the whole
interface, including a proper right-to-left layout: the sidebar moves to the right, tables
and text align right, and numbers, references and codes stay left-to-right so they remain
readable. Dates use Arabic month names with Western digits, as Egyptian commercial documents
do.

The choice is saved on the user's account, so each person gets their own language wherever
they sign in — the Cairo team can work in Arabic while you work in English, on the same data.

Translation covers the navigation, every screen, the twelve stages, roles, document and cost
types, statuses, and the whole help guide. Data you enter — supplier names, product
descriptions, comments — is shown exactly as typed, in whichever language it was written.
Anything without an Arabic entry falls back to English rather than breaking, so adding a
translation later is a one-line change in `app/i18n.py`.

---

## What's new in this build

**No pre-loaded accounts — you create the admin yourself, on first run** — a fresh
database has zero accounts. The first person to open Gtrack is walked through a one-time
setup screen instead of a login form: name, email, and a password of your own choosing —
nobody else, including us, ever sees it. You're signed in immediately with full access,
and from **Admin -> Users** you create everyone else's login, one per person, matching
their actual position, the same way the temporary-password flow already worked. The
seeded demo shipment history still comes with the download so there's real data to look
at right away — it just has nobody attached to it until you add your own team.

**Financial analysis report** — **Reports -> Financial analysis** lists every shipment in
one table, goods value through every cost element (shipping, customs & clearance, bank
charges, last-mile delivery, other) to the total landed cost, with paid/unpaid alongside —
pulled live from the cost lines, invoices and quotations already logged, nothing entered
separately. Exports to Excel, CSV and PDF, built for a finance manager reviewing the whole
portfolio at once rather than one shipment's build-up at a time. Fixed alongside it: the
per-shipment Landed cost build-up screen used to zero out a machine's share of already-
booked costs whenever its invoice value hadn't been entered yet — apportionment now falls
back to quantity, so real costs never silently disappear from the per-item table.

**Temporary passwords, forced on first sign-in** — a new account (or one an admin resets)
gets a system-generated temporary password instead of one the admin has to invent. The
admin sees it once, in a flash message, to hand to the person; the account is locked to the
**change your password** screen the moment it signs in — nothing else in the app is reachable
until a password of its own is set. **Admin -> Users** shows a "temporary password — not yet
set their own" note on any account still in that state, and a one-click **Reset password**
button lets the admin issue a fresh temporary one whenever someone asks, without needing to
know or choose what they end up with.

**A dedicated entry screen for received freight quotes** — **Finance -> Quotations -> Log a
received quote** (also reachable from a shipment's Quotations panel) records what a forwarder
actually quoted broken down to its cost elements — air/sea freight, export customs clearance,
X-ray/scanning, origin handling, documentation, and other — rather than one lump sum. The
total is computed from the elements when they're filled in (a plain total is still accepted
for a quote that didn't come itemised), and the breakdown shows on the quote wherever it's
listed, so comparing forwarders means comparing like-for-like cost elements, not just a
bottom line.

**Landed cost build-up, from goods value to total machine cost** — a shipment's new
**Landed cost build-up** screen (button on the shipment page, next to Cost statement) walks
from the goods value (from the supplier invoice) through the actual cost groups booked
against the shipment — shipping/freight, customs & clearance, bank charges, last-mile
delivery, and other costs — to a total landed cost, then apportions that total across the
shipment's items to give a landed cost per unit. Where the earlier leg of a two-step
shipment carried its own costs, those are added in too, with the quote-vs-actual variance
noted alongside.

**Step-by-step "how to use it" guidance throughout Help** — every section of **Help** now
pairs its existing description of what a screen does with a walk-through of how to actually
use it (what to fill in, what order, what happens next), including two new workflow guides —
comparing forwarder quotes and picking one, and setting someone up with a login — and
coverage of the new Landed cost build-up screen.

**The sidebar keeps your place** — clicking a menu item used to leave the sidebar showing
its default highlight instead of where you actually navigated to; it now stays on the section
you're viewing (including a shipment's Overview/Quotations/Costs tabs, tracked as you scroll)
rather than resetting.

**Reports now open as a submenu, not one long page** — **Admin -> Reports & KPIs** is a
hub of the headline KPI tiles plus a menu of the individual reports, each its own page:
Pipeline & ageing, Timing & routes, Cost breakdown, Financial analysis, Brands & suppliers,
Equipment & value, and Exceptions (document gaps and date anomalies). A submenu strip on every report page
switches between them without going back to the hub. The full register export (Excel/CSV/PDF)
stays a click away from the hub.

**Users can now be edited and deleted, not just added** — each row on **Admin -> Users**
opens to an edit form (name, email, role, phone, active flag, and an optional password
reset), and a Delete option that only appears when it's safe: blocked for your own signed-in
account, for the last active full-access user (so the system can never be locked out), and
for any account with activity on record (a shipment, comment, notification, etc.) — that one
gets a message pointing at "set Active to No" instead of a delete that would break the
history.

**A six-role access model matching the company's actual positions, extensible by the CFO**
— the role matrix is now CFO, MD, Finance, Sales, Sales Admin and Logistics Admin
(Procurement and Warehouse folded into Logistics Admin, since one person typically runs
both in practice; Sales Admin is the department-wide view over every customer, on top of
the regular Sales rep's own-customers-only view). The CFO — the one role with full access —
can add further roles at any time from **Admin -> Roles**, with no code change. What a role
can access is set separately, on the new **Authorisation matrix** — a permission-by-permission
grid, decoupled from the role list itself, so adding a role and deciding what it can do are
two distinct steps. A new dedicated **Admin section** groups Users, Roles, the Authorisation
matrix and FX rates in one place; FX rates moved from a hard-coded default to an
admin-editable dated series, with the most recent rate for each currency used everywhere
costs are converted to EGP. The sign-in screen is now a plain email/password form, with no
directory of demo accounts on it.

**The two-step supply route** — shipments can now run origin → Jebel Ali fulfilment centre
→ Cairo as well as straight from origin, with the two legs linked so a machine's whole
journey, and its whole cost, stays in one place. A re-export leg routinely consolidates
items from several original manufacturers; each item line keeps its own supplier, brand,
category, invoice reference, declared and actual values, weights and dimensions.

**Fulfilment centre stock** — what is held in the free zone, what has been called forward,
the balance, its value, and how long it has been sitting there, with a dashboard tile and
a days-held ageing scale.

**Locations and customs brokers** as master data, suppliers typed by party (manufacturer,
trading supplier, internal entity, freight agent), and every master-data record now
editable in place.

**Global search** — one box on every page that finds a shipment by any reference: shipment
number, ACID, BL/AWB, PO number, supplier invoice, machine serial, product, model, HS code,
quotation reference, Form 4 registration, or a customer, supplier or forwarder name. Results
show which reference matched so you can see why something appeared. Respects role scoping.

**Cost & contents statement** — a per-shipment page (the Statement button) tracing every cost
booked against it, listing every item with serial numbers and allocations, and apportioning
the costs across the lines to give a landed cost per unit. Exports to PDF and Excel.

**Help & guide** — an in-app guide covering every menu item, the twelve stages, roles,
common workflows and a glossary of ACID, Form 4, FCL/LCL, incoterms and landed cost.

**Production-ready for Neon** — TLS enforced, connection pre-ping and recycle tuned for
Neon's serverless idle timeout, an environment template, and a `check_db.py` utility to
verify a connection before deploying. Tested against real PostgreSQL, not only SQLite.

---

## Deployment

**The quickest route is `python golive.py`** (or double-click `golive.bat` on Windows).
It creates the Neon database, builds and populates it, creates the GitHub repository,
pushes the code, creates the Render service and attaches `gtrack.awspro.uk` — then checks
the live site. It asks for three API tokens, never a password, and every step is
idempotent, so an interrupted run resumes rather than duplicating.

`golive.json` in this folder already holds the settings for Gtrack, so it runs without
asking anything. `golive.py` is a general tool — the same file deploys Collecta, Voya or
any other Python web app; drop it in that folder and it works the rest out itself.

**See `DEPLOY.md`** if you would rather do it by hand — the full step-by-step runbook: Neon database, GitHub repo, Render
blueprint, seeding production, and the `gtrack.awspro.uk` CNAME with SSL — including the
gotchas that caught out the Collecta deployment.

In short: push to GitHub, then New → Blueprint in Render pointed at `render.yaml`, set
`GTRACK_DATABASE_URL` to the Neon **pooled** connection string, deploy, then run
`python seed.py --force` once from the Render shell.

**Docker**

```bash
docker build -t gtrack .
docker run -p 8000:8000 gtrack
```

**Environment variables**

| Variable | Purpose |
|---|---|
| `GTRACK_DATABASE_URL` | Postgres URI. Unset → SQLite in `instance/` |
| `GTRACK_SECRET_KEY` | Session signing key — set this in production |
| `GTRACK_UPLOAD_FOLDER` | Where uploaded documents are stored |
| `GTRACK_ORG_NAME` | Organisation name shown in the interface |
| `GTRACK_NOTIFICATIONS_LIVE` | `1` to send notifications rather than log them |

Every variable is prefixed `GTRACK_` on purpose. Gtrack deliberately ignores the generic
`DATABASE_URL`: a machine already running other Flask apps usually has that set for one of
them, and inheriting it would silently point Gtrack at another application's database.
Seeding also refuses to run against anything but a local SQLite file unless you pass
`--force`, because it drops and recreates its tables.

---

## Notes and limitations

This is a test build, so a few things are deliberately stubbed:

- **Notifications are written to the log, not emailed.** The rule engine, audience routing
  and templates are all real; only the SMTP delivery step is missing. Set
  `GTRACK_NOTIFICATIONS_LIVE=1` and add a mail backend in `notifications.py` to send for real.
- **The rule sweep runs on demand**, via the button on the dashboard, rather than on a
  schedule. In production it would be a cron job or a Render scheduled task.
- **Exchange rates are admin-editable** from **Admin -> FX rates**, which writes dated rows
  to the `ExchangeRate` table; the most recent row for a currency is what conversions use.
  Until an admin sets one, each currency falls back to an indicative default in `models.py`.
- **Serial numbers, customers and allocations are demo data.** The spreadsheet has none, so
  these were generated to exercise the features — they are not real SGE records.
- Costs migrated from the spreadsheet inherit its ambiguity: where the old sheet recorded a
  payment as a free-text note, the migration takes a best-effort reading of paid/unpaid.
- **Route type is inferred from the pathway column**, not stated in the source sheet. The
  inference is deterministic and visible on every shipment, so a wrong call is a one-click
  correction on the shipment's edit page rather than a data problem.
- **Earlier-leg costs are apportioned by value**, the same basis as within a single
  shipment. Where a re-export draws on only part of an inbound line, it carries that line's
  cost per unit multiplied by the quantity called forward.

---

## Layout

```
gtrack/
├── golive.py              # one-command go-live (Neon + GitHub + Render)
├── golive.json            # Gtrack's deployment settings, no secrets
├── golive.bat             # Windows double-click wrapper for the above
├── run.py                 # dev server
├── wsgi.py                # gunicorn entry point
├── seed.py                # spreadsheet migration + demo data
├── test_smoke.py          # end-to-end tests
├── config.py
├── data/
│   └── Shipments_Tracking.xlsx
└── app/
    ├── models.py          # all 28 tables
    ├── i18n.py            # English / Arabic dictionary and RTL helpers
    ├── auth.py            # roles, permissions, scoping
    ├── audit.py           # automatic change logging
    ├── notifications.py   # rule engine
    ├── exports.py         # CSV / Excel / PDF
    ├── views/             # dashboard, shipments, POs, finance, assets, masters, reports, admin
    ├── templates/
    └── static/
```
