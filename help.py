"""In-app help and user guide."""
from flask import Blueprint, render_template
from flask_login import login_required

from ..models import Stage, DOC_TYPES, COST_TYPES
from ..auth import ROLE_DEFINITIONS
from ..i18n import t

bp = Blueprint("help", __name__)


MENU_GUIDE = [
    ("Dashboard", "dashboard", [
        ("What it is", "Your position at a glance — what is open, what is late, what is "
                       "arriving, what is waiting on someone."),
        ("How to use it", "Open it first thing. Check Delayed and Machines unallocated, click "
                          "through to anything shown in red, and run the notification sweep if "
                          "you want the alert log refreshed before checking Notifications."),
        ("The tiles", "Open shipments counts anything still in flight. A shipment closes when "
                      "it is received into the warehouse, so the number stays meaningful. "
                      "Delayed means the ETA has passed and it has not arrived. Machines "
                      "unallocated counts serial-numbered units with no customer assigned."),
        ("Run notification sweep", "Evaluates every time-based alert rule now — ETA countdowns, "
                                   "delays, missing documents, overdue payments — and writes the "
                                   "results to the notification log. In production this runs on a "
                                   "schedule; the button lets you trigger it on demand."),
    ]),
    ("Search", "search", [
        ("What it is", "One box that finds a shipment by any reference anyone might quote at you."),
        ("How to use it", "Type whatever reference you have into the box at the top of any page "
                          "and press Search — a serial number, a customer name, an ACID, part of "
                          "a product name. Open the result you need; if several match, the list "
                          "shows which field matched each one so you can tell them apart."),
        ("What it searches", "Shipment reference, ACID number, bill of lading or air waybill, "
                             "purchase order number, supplier invoice number, machine serial "
                             "number, product description, model, HS code, quotation reference, "
                             "Form 4 registration, and customer, supplier or forwarder names."),
        ("Tips", "Partial matches work. Typing LRG finds every LargeV serial; typing part of a "
                 "product name finds every shipment that carried it. Results show which reference "
                 "matched, so you can tell why something appeared."),
    ]),
    ("Shipment register", "shipments", [
        ("What it is", "Every shipment in one filterable table."),
        ("How to use it", "Start from Open if you only care what's still moving, or switch to All "
                          "to include delivered and installed shipments too. Combine status, "
                          "stage, brand, supplier, mode and route type across the top, add the "
                          "free-text search for anything a filter doesn't cover, then click a row "
                          "to open it. Excel, CSV and PDF export exactly what your filters show."),
        ("Filters", "Combine status, stage, brand, supplier, mode and route type with a "
                    "free-text search. Status defaults to open for operational roles and to all "
                    "for sales, who still care about a machine after it lands."),
        ("Route type", "Direct means origin straight to Cairo. Inbound to fulfilment centre is a "
                       "stock leg into the Jebel Ali free zone. Re-export from fulfilment centre "
                       "is stock called forward from there against an order. Filtering on route "
                       "type separates the two halves of a two-step supply route."),
        ("Reading the columns", "In stage shows how long it has sat where it is — amber past two "
                                "weeks, red past a month. Docs shows the percentage of required "
                                "documents actually held."),
        ("Exports", "Excel, CSV and PDF buttons export exactly what your filters are showing."),
    ]),
    ("Pipeline board", "board", [
        ("What it is", "The same open shipments as cards across the twelve stages — the fastest "
                       "way to see where the bottleneck is."),
        ("How to use it", "Scan left to right — a stage with cards piling up while its neighbours "
                          "are empty is the bottleneck worth chasing. Click a card to open that "
                          "shipment and move it on."),
        ("Note", "Shipments received into the warehouse in the last 45 days stay on the board so "
                 "the warehouse and installation columns are not empty."),
    ]),
    ("Shipment detail", "detail", [
        ("How to use it", "Use the tabs along the top to jump straight to Items, Documents, Costs, "
                          "Quotations, Customs & Form 4 or Comments — whichever you're on stays "
                          "highlighted so you always know where you are. To move the shipment "
                          "along, use Move to next stage on the Overview tab: it records the date, "
                          "writes it to the timeline and fires any alert attached to that stage."),
        ("Overview", "Parties, route, references, dates and performance, plus the status timeline."),
        ("Routing & logistics", "The route type and the leg it represents, the from and to "
                                "locations, the customs broker, the document type (master or "
                                "house bill), payment terms, chargeable weight, measurement and "
                                "the cargo cut-off. A missed cut-off — the date has passed and "
                                "the shipment has not departed — is flagged in red."),
        ("Exporter versus supplier", "The supplier is who made or sold the goods; the exporter is "
                                     "who actually shipped them. On a re-export leg out of the "
                                     "fulfilment centre the exporter is our own entity, while the "
                                     "original manufacturers stay on the item lines. When more "
                                     "than one origin supplier is present the shipment is marked "
                                     "consolidated."),
        ("Moving a stage", "Move to next stage records the change with a date and note, writes it "
                           "to the timeline, updates the matching date field, and fires any "
                           "notification rule attached to that stage."),
        ("Items & allocation", "Each product line, its serial numbers, and which customer each "
                               "unit is allocated to. Add serials in bulk by separating them with "
                               "commas."),
        ("Item detail", "Each line carries its own origin supplier, brand, category, supplier "
                        "invoice number and date, net and gross weight and dimensions — so a "
                        "consolidated shipment still says which manufacturer each box came from. "
                        "Declared and actual values are held separately and the difference is "
                        "shown, which matters when the customs declaration and the commercial "
                        "reality differ."),
        ("Hub trail", "A line that came forward from the fulfilment centre is marked Via "
                      "fulfilment centre and links back to the inbound leg it first arrived on, "
                      "so you can follow a machine all the way to its origin."),
        ("Documents", "Upload and store the actual files. The checklist shows required versus "
                      "received; re-uploading the same type bumps the version."),
        ("Costs", "Every cost booked against the shipment with its own payment status, and who "
                  "paid it — us, the forwarder, or the supplier — so costs advanced on our behalf "
                  "and later recharged are not confused with what we settled directly."),
        ("Quotations", "Competing forwarder quotes. Selecting one sets the shipment's forwarder "
                       "and enables the quoted-versus-actual comparison."),
        ("Customs & Form 4", "ACID, bill type, clearance date, the customs broker handling it, "
                             "and the bank import registrations. A shipment part-paid in advance "
                             "and part against documents produces more than one banking record, "
                             "so these accumulate rather than overwrite: each carries its own "
                             "advance payment reference, two SWIFT references, amount, currency "
                             "and transfer date. Low-value shipments are recorded as exempt with "
                             "the reason."),
        ("Comments", "An internal thread so procurement, logistics, finance and sales leave notes "
                     "against the shipment rather than in email."),
    ]),
    ("Cost & contents statement", "statement", [
        ("What it is", "The full financial trace for one shipment on a single page — reachable "
                       "from the Statement button on any shipment."),
        ("How to use it", "Open it from Cost statement on any shipment — it's read-only, nothing "
                          "to fill in, only to trace and export. If you want the plainer top-down "
                          "version instead — goods value, then shipping, customs, bank charges and "
                          "last-mile, arriving at one total — use Landed cost build-up on the same "
                          "shipment page; the two always reconcile to the same landed total."),
        ("Items", "Every line in the shipment with quantity, value, serial numbers and who each "
                  "unit is allocated to."),
        ("Cost trace", "Every cost booked, grouped by category, showing original currency and the "
                       "base-currency equivalent, who it is payable to, and whether it is paid."),
        ("Landed cost by item", "Shipment costs apportioned across the lines by each line's share "
                                "of goods value, giving a landed cost per unit — the number you "
                                "need when pricing a machine."),
        ("Earlier leg costs", "When a line came forward from the fulfilment centre, the cost of "
                              "the inbound leg that first brought it into the free zone is "
                              "carried forward and added, giving a true landed total. Costing the "
                              "re-export leg on its own would understate what the machine "
                              "actually cost to land in Cairo."),
        ("Export", "The whole statement exports to PDF or Excel."),
    ]),
    ("Landed cost build-up", "buildup", [
        ("What it is", "A separate, plain-English screen for one shipment: goods value from the "
                       "invoice, plus shipping (priced from the winning quote, then reconciled "
                       "against what was actually booked), plus customs & clearance, bank charges "
                       "and last-mile delivery, arriving at the total cost of the machine — as "
                       "opposed to the detailed Statement, which apportions all of this down to a "
                       "landed cost per item and per serial."),
        ("How to use it", "Open it from Landed cost build-up on any shipment. Read it top to "
                          "bottom like a running total: each line adds to the one above it, and "
                          "the total landed cost at the bottom always matches the Statement's "
                          "figure — this screen just groups the same costs the way a finance "
                          "person actually thinks about them, in five plain buckets instead of the "
                          "finer cost-type list."),
        ("Shipping", "Shown against the selected quotation's price, with what has actually been "
                     "booked as freight alongside it and the variance between the two — logging a "
                     "quotation and selecting it is what makes this comparison possible."),
        ("Bank charges and last-mile delivery", "Only shown once a cost line is booked with that "
                                                "category — add them from the Costs tab on the "
                                                "shipment as they're incurred."),
    ]),
    ("Purchase orders", "po", [
        ("What it is", "The start of the chain — the order raised on a supplier, before any "
                       "shipment exists."),
        ("How to use it", "Raise the PO on the supplier first. Once they confirm it, record the "
                          "supplier invoice against it. When the goods actually ship, create the "
                          "shipment against this PO — that's what links the two together."),
        ("Lines", "Each line tracks ordered versus shipped versus outstanding, so a part-shipped "
                  "order is visible at a glance."),
        ("Supplier invoices", "Recorded against the PO and, once it exists, linked to the shipment "
                              "the goods travel on."),
        ("Overdue", "A confirmed PO past its expected ready date is flagged and alerts procurement."),
    ]),
    ("Freight quotations", "quotations", [
        ("What it is", "Every quotation logged across all shipments, plus the quoted-versus-actual "
                       "variance report."),
        ("How to use it", "Log a quote as it arrives — either from the Quotations tab on the "
                          "shipment itself, or from Log a received quote here, which lets you pick "
                          "the shipment from a list first. Break the forwarder's price down to its "
                          "cost elements (air/sea freight, export customs clearance, x-ray, origin "
                          "handling, documentation, other) wherever they itemised it; the elements "
                          "add up to the quoted total automatically, or type a single total if all "
                          "you were given was one lump sum. Once you've compared the quotes, click "
                          "Select on the one you're going with — that sets the shipment's forwarder "
                          "and switches on the quoted-versus-actual comparison."),
        ("Cost elements", "A quote broken into freight, export clearance, x-ray, handling, "
                          "documentation and other is worth far more than one total when comparing "
                          "two forwarders, or reconciling the quote against what actually gets "
                          "invoiced — a quote logged with only a lump sum still works, it just "
                          "can't be compared element by element."),
        ("Currency", "Quotes usually arrive in USD and freight invoices often in EGP, so both "
                     "sides are converted to the base currency before comparison."),
    ]),
    ("Serial register", "assets", [
        ("What it is", "Every individual machine, searchable by serial number."),
        ("How to use it", "Search by serial number, or open a unit straight from a shipment's "
                          "Items & allocation tab. The unit's own page then shows its whole "
                          "history — PO, shipment, route, customer, installation — in one place."),
        ("Status", "In transit, in stock, allocated, delivered, installed."),
        ("Warranty", "Warranty starts at installation (or warehouse receipt if no installation is "
                     "recorded) and the register shows whether it is still active — this is your "
                     "after-sales lookup."),
        ("Unit history", "Opening a serial shows its whole journey: PO, shipment, route, dates, "
                         "customer, sales owner and installation date."),
    ]),
    ("Allocations", "allocations", [
        ("What it is", "Which machine belongs to which customer, and what stage each is at."),
        ("How to use it", "Work down Awaiting installation first — it's the queue nothing else "
                          "surfaces. Assign unallocated stock to a customer from a shipment's "
                          "Items & allocation tab as soon as you know who it's for."),
        ("Awaiting installation", "Allocated but not yet confirmed installed — the sales and "
                                  "installation queue."),
        ("Unallocated stock", "Units with no customer assigned, so nothing sits forgotten in the "
                              "warehouse."),
    ]),
    ("Customers", "customers", [
        ("What it is", "Per customer, everything they are waiting for and everything installed."),
        ("How to use it", "Open the customer before you ring them, not the shipment register — "
                          "everything they're waiting for and everything already installed is "
                          "already gathered on their one page."),
        ("Why it matters", "This is the screen a sales account manager lives in: it answers "
                           "\"where is my customer's machine\" without them asking logistics."),
        ("Scoping", "A sales user sees only their own customers. Managers see all."),
    ]),
    ("Fulfilment centre stock", "hubstock", [
        ("What it is", "What is currently sitting in the Jebel Ali free zone, waiting to be "
                       "called forward against an order."),
        ("How to use it", "Check it before confirming a re-export leg — a part-called line shows "
                          "what's actually left to draw on. Anything sorted amber or red has been "
                          "sitting a while and is tying up cash, so it's worth chasing forward."),
        ("How a balance is worked out", "A line counts as held once its inbound leg has landed. "
                                        "When an order calls stock forward, the re-export leg "
                                        "links back to that line and the balance falls. A "
                                        "part-called line shows what is left."),
        ("Days held", "Sorted oldest first, amber past three months and red past six — anything "
                      "sitting a long time is tying up cash in the free zone."),
        ("Who can see it", "Management, procurement, logistics and finance. Sales users do not "
                           "see stock positions."),
    ]),
    ("Shipment costs", "costs", [
        ("What it is", "Every cost line across every shipment, filterable by category and payment "
                       "status."),
        ("How to use it", "Filter by category or payment status to work through what's "
                          "outstanding, and mark a line paid as soon as it's actually settled so "
                          "the unpaid total here — and the landed cost on every shipment it feeds "
                          "— stays trustworthy."),
        ("Totals", "Total, unpaid, partial and overdue, all converted to the base currency."),
    ]),
    ("Form 4 register", "form4", [
        ("What it is", "Bank-side import registrations and recorded exemptions."),
        ("How to use it", "Check the gap list first. Any open shipment on it needs a Form 4 "
                          "record raised against the financing bank — or marking exempt with a "
                          "reason, for a low-value shipment below the reporting threshold — before "
                          "it reaches customs."),
        ("Gap list", "Open shipments with no Form 4 record at all, so nothing reaches customs "
                     "unregistered."),
    ]),
    ("Reports & KPIs", "reports", [
        ("What it is", "The headline KPI tiles, plus a submenu of the individual reports — each "
                       "its own page rather than one long page combining everything."),
        ("How to use it", "Open Reports & KPIs for the KPI tiles and the menu of reports. Pick "
                          "Pipeline & ageing, Timing & routes, Cost breakdown, Brands & suppliers, "
                          "Equipment & value or Exceptions — the submenu shown along the top of "
                          "every report page moves between them without going back to the hub. "
                          "Full register (Excel/CSV/PDF) on the hub exports every shipment with "
                          "timing and cost columns, whatever report you're actually looking at."),
        ("Pipeline & ageing", "Where open shipments sit right now, and which ones have been "
                              "sitting in their current stage the longest."),
        ("Timing & routes", "Average transit time by mode and lane, average customs clearance "
                            "time from arrival to release, and direct versus the fulfilment "
                            "centre route."),
        ("Cost breakdown", "Cost per shipment, cost per kilogram, and cost by category."),
        ("Brands & suppliers", "Volume, value and transit performance by brand and by supplier, "
                               "including delay frequency and lead time."),
        ("Equipment & value", "Serialised equipment by status, and the value of goods currently "
                              "in transit by currency."),
        ("Exceptions", "The document-gap list and rows with contradictory dates."),
    ]),
    ("Notifications", "notifications", [
        ("What it is", "Every alert the rule engine has generated, with what was sent and to whom."),
        ("How to use it", "Scan it after a notification sweep to see what fired. If a sales user "
                          "says they didn't get an alert about their own customer, check here "
                          "first — Routing below explains why they might not have."),
        ("Routing", "Sales alerts go only to the account manager who owns an allocated customer on "
                    "that shipment — not the whole team."),
        ("Test build", "Alerts are written to the log rather than emailed. Setting "
                       "GTRACK_NOTIFICATIONS_LIVE=1 and adding a mail backend sends them for real."),
    ]),
    ("Master data", "masters", [
        ("What it is", "Suppliers and trading parties, locations and facilities, customs "
                       "brokers, brands, carriers, consignee entities, customers and banks. Each "
                       "record can be edited in place from its row."),
        ("How to use it", "Open the relevant list and edit a record in place from its row rather "
                          "than recreating it. Keep names consistent — a supplier entered two "
                          "different ways silently splits its totals across every report."),
        ("Party type", "Suppliers are typed as manufacturer, trading supplier, internal entity or "
                       "freight agent. Typing our own entities as internal is what lets the "
                       "system tell an intercompany movement from a third-party purchase."),
        ("Locations", "Our own facilities — the Jebel Ali fulfilment centre, the Cairo warehouse "
                      "— as distinct from a customer site. Marking one as a free zone is what "
                      "drives the fulfilment centre stock view."),
        ("Why it matters", "Clean master data is what makes grouping and totals trustworthy — the "
                           "old spreadsheet had the same supplier under several spellings, which "
                           "silently split every total."),
    ]),
    ("Admin: users, roles, authorisation, FX rates, audit", "admin", [
        ("How to use it", "Create the account under Users, assign its role, and leave the "
                          "password blank — the system generates a temporary one and shows it "
                          "once, in the confirmation message, for you to pass on. The new account "
                          "is asked to set its own password the moment it first signs in. If "
                          "someone forgets theirs later, use Reset password on their row for a "
                          "fresh temporary one, the same way — you never need to know or set what "
                          "they actually pick. Check what a role can access, or extend it, on the "
                          "Authorisation matrix."),
        ("Users", "Create accounts and assign each one a role. A row with 'Temporary password — "
                 "not yet set their own' is still on the password you (or the system) gave it; "
                 "that clears itself the moment the user sets their own."),
        ("Roles", "The role matrix — CFO, MD, Finance, Sales, Sales Admin and Logistics Admin "
                 "out of the box, matching the company's actual positions. The CFO can add more "
                 "at any time from Admin -> Roles."),
        ("Authorisation matrix", "Separate from the role list itself — a permission-by-permission "
                                 "grid of exactly what each role can see and do. New roles start "
                                 "with no access until this is set."),
        ("FX rates", "The exchange rates used to convert every cost line into EGP. Indicative "
                     "defaults until an admin sets one from Admin -> FX rates; each save is dated, "
                     "and the most recent rate for a currency is what the system uses."),
        ("Notification rules", "Triggers, audiences, channels and message templates — editable "
                               "without a code change."),
        ("Audit log", "Every field-level change with the user who made it and when. Filter by "
                      "record type and export it."),
    ]),
]


WORKFLOWS = [
    ("Following a customer's machine",
     "Search the customer's name, or open Customers and find them. Each row shows the serial "
     "number, the shipment carrying it, the stage that shipment is at, the ETA and the expected "
     "installation date. When it clears customs the account manager gets an alert, which is the "
     "cue to ring the customer about scheduling."),
    ("Recording a new import from scratch",
     "Raise the purchase order on the supplier. When they confirm, record the supplier invoice "
     "against the PO. Log the freight quotations you obtain and mark the one you accept — that "
     "sets the forwarder. Create the shipment against the PO, add its item lines, then advance "
     "the stage as it moves. Capture serial numbers on arrival, allocate each unit to a customer, "
     "and confirm installation when the engineer signs off."),
    ("Chasing what a shipment actually cost",
     "Open the shipment and click Statement. It lists every item, every cost booked against it "
     "with payment status, the landed total, and the landed cost per unit. Export it to PDF for "
     "the file or Excel to work on. For the short version instead — goods value, shipping, "
     "customs, bank charges and last-mile in one running total — click Landed cost build-up on "
     "the same shipment; the two always agree on the final figure."),
    ("Comparing forwarder quotes and picking one",
     "Log each quote as it comes in — either from the shipment's Quotations tab, or from Log a "
     "received quote under Freight quotations, which lets you pick the shipment first. Break each "
     "one down to its cost elements (freight, export clearance, x-ray, handling, documentation) "
     "wherever the forwarder itemised it, so they're actually comparable rather than one number "
     "each. Once you've decided, click Select on the winning quote — that sets the shipment's "
     "forwarder and switches on the quoted-versus-actual comparison once real freight is booked."),
    ("Setting someone up with a login",
     "Create their account under Admin -> Users with their role, and leave the password field "
     "blank. The confirmation message shows a temporary password once — copy it to them along "
     "with their email address. The first time they sign in, they're asked to set their own "
     "password before they can do anything else. If they ever forget it, open their row and click "
     "Reset password for a new temporary one — you don't need to know or choose what they land on."),
    ("Finding a machine you only have a serial number for",
     "Type the serial into Search. You get the unit, its status, the shipment that carried it, "
     "and the customer it went to — and from the unit page, its full history back to the PO."),
    ("Bringing stock in through the fulfilment centre",
     "Create the inbound leg with route type Inbound to fulfilment centre and the to location set "
     "to Jebel Ali, and record its item lines with their origin suppliers. The goods then appear "
     "on Fulfilment centre stock. When a customer orders, create a second shipment with route "
     "type Re-export from fulfilment centre, from Jebel Ali to Cairo, and record its item lines "
     "against the stock they draw on — the balance falls and the machine's journey stays in one "
     "place. If the re-export carries goods from several original manufacturers, it is marked "
     "consolidated and each line keeps its own supplier."),
    ("Working out what a re-exported machine really cost",
     "Open the re-export leg and click Statement. Alongside its own costs you will see Earlier "
     "leg costs — the share of the inbound leg's freight, duty and handling that belongs to those "
     "units — and a true landed total including every leg. The earlier legs it draws on are named "
     "and linked underneath."),
    ("Recording a payment trail against a shipment",
     "Open the shipment, go to Customs & Form 4 and add a banking record for each transfer: the "
     "advance payment reference, the SWIFT references the bank will quote back at you, the amount "
     "and the transfer date. Add a second record when the balance is paid against documents. "
     "Low-value shipments are recorded as exempt with the reason instead."),
    ("Checking nothing is stuck",
     "The dashboard's Stuck in stage panel lists anything sitting in one stage beyond two weeks. "
     "Reports & KPIs has the fuller ageing list, plus the document gaps."),
]


GLOSSARY = [
    ("ACID", "Advance Cargo Information Declaration — the Egyptian customs registration raised "
             "through Nafeza before goods ship. Without it the cargo cannot be cleared."),
    ("Form 4", "The bank-side import registration. Recorded per shipment against the financing "
               "bank, or marked exempt for low-value shipments below the reporting threshold."),
    ("BL / AWB", "Bill of Lading for sea freight, Air Waybill for air freight — the carrier's "
                 "document of title and the reference the forwarder will quote at you."),
    ("FCL / LCL", "Full Container Load, where you take a whole container, versus Less than "
                  "Container Load, where your goods share one."),
    ("Incoterm", "The trade term (FOB, CIF, EXW and so on) that fixes where the supplier's "
                 "responsibility ends and yours begins — and therefore which costs land on you."),
    ("HS code", "The customs tariff classification for a product, held per item line so a "
                "multi-product shipment classifies correctly."),
    ("Landed cost", "Goods value plus every cost of getting them here — freight, duty, clearance, "
                    "insurance. The real cost of a machine, and the basis for pricing it."),
    ("Allocation", "The record tying a specific machine, by serial number, to a specific customer. "
                   "Deliberately separate from the shipment, because one shipment routinely "
                   "carries units for several customers."),
    ("Fulfilment centre", "Our own facility in the Jebel Ali free zone. Goods can be shipped "
                          "there from the origin supplier and held, then re-exported into Egypt "
                          "when an order calls them forward — an alternative to shipping direct "
                          "from origin into Cairo."),
    ("Route type", "Which leg of the supply route a shipment represents: direct from origin, "
                   "inbound to the fulfilment centre, re-export from the fulfilment centre, an "
                   "internal transfer, or outbound."),
    ("Exporter", "Who ships the goods, as opposed to who made or sold them. On a re-export leg "
                 "the exporter is our own entity while the manufacturers stay on the item lines."),
    ("Consolidated shipment", "One shipment carrying goods from more than one original supplier — "
                              "routine on a re-export leg out of the fulfilment centre."),
    ("Master / house bill", "A master bill is issued by the carrier to the consolidator; a house "
                            "bill is issued by the consolidator to us. Which one you hold decides "
                            "who releases the cargo."),
    ("Chargeable weight", "The greater of actual weight and volumetric weight — what air freight "
                          "is actually billed on."),
    ("Cargo cut-off", "The last moment cargo can be delivered to the terminal for a given "
                      "sailing or flight. Missing it means the next departure."),
    ("Paid by", "Who settled a cost — us, the forwarder, or the supplier. Costs a forwarder "
                "advances and later recharges are tracked separately from what we paid direct."),
    ("Base currency", "Everything is converted to EGP for totals, so mixed-currency shipments add "
                      "up. Rates are set in config.py."),
]


@bp.route("/")
@login_required
def index():
    # Every string passes through t(), so the whole guide switches language.
    menu_guide = [(t(title), anchor, [(t(label), t(text)) for label, text in points])
                  for title, anchor, points in MENU_GUIDE]
    workflows = [(t(title), t(text)) for title, text in WORKFLOWS]
    glossary = [(t(term), t(meaning)) for term, meaning in GLOSSARY]

    return render_template(
        "help.html",
        menu_guide=menu_guide,
        workflows=workflows,
        glossary=glossary,
        stages=[(i + 1, Stage.label(c), Stage.owner(c)) for i, c in enumerate(Stage.ORDER)],
        roles=[(code, t(name), t(description), perms)
               for code, name, description, perms in ROLE_DEFINITIONS],
        doc_types=[(code, t(label)) for code, label in DOC_TYPES],
        cost_types=[(code, t(label)) for code, label in COST_TYPES],
    )
