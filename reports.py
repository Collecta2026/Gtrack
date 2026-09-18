from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from ..models import (db, Shipment, ShipmentItem, Asset, Allocation, CostLine,
                      Supplier, Brand, Carrier, Stage, ROUTE_TYPES)
from ..i18n import t
from ..auth import permission_required, visible_shipments
from ..exports import export_response
from .shipments import _statement_data, _cost_buildup, COST_BUILDUP_GROUPS

bp = Blueprint("reports", __name__)


def _avg(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 1) if values else None


def _shipments():
    shipments = visible_shipments(Shipment.query).all()
    open_shipments = [s for s in shipments if s.is_open]
    return shipments, open_shipments


# The various available reports, as a submenu — every reports/* page shows this
# list so moving between reports doesn't mean going back to the hub each time.
# (label is resolved through t() in the template, not here, so it stays translated.)
REPORT_PAGES = [
    ("reports.index", "Overview"),
    ("reports.pipeline", "Pipeline & ageing"),
    ("reports.timing", "Timing & routes"),
    ("reports.cost", "Cost breakdown"),
    ("reports.financial_analysis", "Financial analysis"),
    ("reports.brands", "Brands & suppliers"),
    ("reports.equipment", "Equipment & value"),
    ("reports.exceptions", "Exceptions"),
]


@bp.context_processor
def _inject_report_menu():
    return dict(report_pages=REPORT_PAGES)


@bp.route("/")
@permission_required("view_reports")
def index():
    """Reports hub — the at-a-glance KPI tiles, plus the submenu of the
    individual reports (each is its own page, reached from here or from the
    submenu shown on every report page)."""
    shipments, open_shipments = _shipments()

    transit_times = [s.transit_days for s in shipments if s.transit_days is not None]
    clearance_times = [s.clearance_days for s in shipments if s.clearance_days is not None]

    arrived = [s for s in shipments if s.actual_arrival and s.eta]
    on_time = sum(1 for s in arrived if s.actual_arrival <= s.eta)
    on_time_pct = round(100 * on_time / len(arrived)) if arrived else None

    cost_by_type = defaultdict(float)
    for c in CostLine.query.all():
        cost_by_type[c.type_label] += (c.amount_base or 0)
    total_cost = sum(cost_by_type.values())
    cost_per_shipment = round(total_cost / len(shipments)) if shipments else 0
    weights = [s.gross_weight_kg for s in shipments if s.gross_weight_kg]
    cost_per_kg = round(total_cost / sum(weights), 2) if weights else None

    consolidated = sum(1 for s in shipments if s.is_consolidated)
    incomplete_docs = sum(1 for s in open_shipments if s.missing_documents)
    anomalies = sum(1 for s in shipments if s.date_anomalies)

    stats = dict(
        total=len(shipments), open=len(open_shipments),
        avg_transit=_avg(transit_times), avg_clearance=_avg(clearance_times),
        on_time_pct=on_time_pct, arrived_count=len(arrived),
        total_cost=total_cost, cost_per_shipment=cost_per_shipment, cost_per_kg=cost_per_kg,
        delayed=sum(1 for s in open_shipments if s.is_delayed),
        incomplete_docs=incomplete_docs,
        consolidated=consolidated,
        hub_legs=sum(1 for s in shipments if s.is_hub_leg),
        anomalies=anomalies,
    )

    return render_template("reports/index.html", stats=stats)


@bp.route("/pipeline")
@permission_required("view_reports")
def pipeline():
    """Where open shipments sit right now, and which ones have been sitting
    the longest in their current stage."""
    shipments, open_shipments = _shipments()

    pipeline_rows = []
    for code in Stage.ORDER:
        count = sum(1 for s in open_shipments if s.current_stage == code)
        if count:
            pipeline_rows.append(dict(label=Stage.label(code), count=count))

    ageing = sorted([s for s in open_shipments if s.days_in_stage > 7],
                    key=lambda s: -s.days_in_stage)[:15]

    return render_template("reports/pipeline.html", pipeline=pipeline_rows, ageing=ageing,
                           open_count=len(open_shipments))


@bp.route("/timing")
@permission_required("view_reports")
def timing():
    """How long shipments actually take — by transport mode, by lane, and by
    route (direct versus the two-step route through the fulfilment centre)."""
    shipments, open_shipments = _shipments()

    by_mode = defaultdict(list)
    for s in shipments:
        if s.transit_days is not None and s.mode:
            by_mode[s.mode].append(s.transit_days)
    mode_stats = [dict(mode=(m or "").upper(), avg=_avg(v), count=len(v))
                  for m, v in sorted(by_mode.items())]

    by_lane = defaultdict(list)
    for s in shipments:
        if s.transit_days is not None and s.origin and s.destination:
            by_lane[f"{s.origin} → {s.destination}"].append(s.transit_days)
    lane_stats = sorted([dict(lane=k, avg=_avg(v), count=len(v)) for k, v in by_lane.items()],
                        key=lambda r: -r["count"])[:10]

    # Direct versus the two-step route through the fulfilment centre — the hub route
    # buys flexibility but adds a second set of freight, handling and clearance
    # charges, so this is the comparison that says whether it is paying for itself.
    route_stats = []
    for code, label in ROUTE_TYPES:
        rs = [s for s in shipments if s.route_type == code]
        if not rs:
            continue
        rs_cost = sum(s.total_cost for s in rs)
        rs_value = sum(s.total_value_base for s in rs)
        rs_weight = sum(s.gross_weight_kg or 0 for s in rs)
        route_stats.append(dict(
            label=t(label), count=len(rs),
            value=rs_value, cost=rs_cost,
            cost_pct=(100 * rs_cost / rs_value) if rs_value else None,
            cost_per_kg=(rs_cost / rs_weight) if rs_weight else None,
            avg_transit=_avg([s.transit_days for s in rs]),
            avg_clearance=_avg([s.clearance_days for s in rs]),
        ))
    hub_legs = sum(1 for s in shipments if s.is_hub_leg)
    consolidated = sum(1 for s in shipments if s.is_consolidated)

    return render_template("reports/timing.html", mode_stats=mode_stats, lane_stats=lane_stats,
                           route_stats=route_stats, hub_legs=hub_legs, consolidated=consolidated)


@bp.route("/cost")
@permission_required("view_reports")
def cost():
    """Logged cost, broken down by cost category."""
    shipments, _ = _shipments()

    cost_by_type = defaultdict(float)
    for c in CostLine.query.all():
        cost_by_type[c.type_label] += (c.amount_base or 0)
    cost_rows = sorted(cost_by_type.items(), key=lambda kv: -kv[1])
    total_cost = sum(cost_by_type.values())
    cost_per_shipment = round(total_cost / len(shipments)) if shipments else 0
    weights = [s.gross_weight_kg for s in shipments if s.gross_weight_kg]
    cost_per_kg = round(total_cost / sum(weights), 2) if weights else None

    return render_template("reports/cost.html", cost_rows=cost_rows, total_cost=total_cost,
                           cost_per_shipment=cost_per_shipment, cost_per_kg=cost_per_kg)


def _financial_analysis_rows():
    """One row per visible shipment, every cost captured — goods value from the
    invoice, then each landed-cost bucket (the same ones the per-shipment
    Landed cost build-up screen uses, so the two always agree), paid/unpaid,
    and the resulting total. This is the one place that pulls every cost
    element together across the whole register for the finance manager,
    rather than one shipment or one cost type at a time."""
    shipments, _ = _shipments()
    bucket_keys = [key for key, _, _ in COST_BUILDUP_GROUPS]
    rows = []
    for s in shipments:
        d = _statement_data(s)
        groups = {g["key"]: g["amount"] for g in _cost_buildup(d)}
        rows.append(dict(
            shipment=s,
            goods_base=d["goods_base"],
            buckets=[groups.get(k, 0.0) for k in bucket_keys],
            cost_total=d["cost_total"],
            paid_total=d["paid_total"],
            unpaid_total=d["unpaid_total"],
            landed_total=d["landed_total"],
        ))
    return rows, bucket_keys


@bp.route("/financial-analysis")
@permission_required("view_reports")
def financial_analysis():
    """Every shipment, every cost element, in one table — goods value through
    to total landed cost — for the finance manager to review the whole
    portfolio at once rather than one shipment's build-up at a time."""
    rows, bucket_keys = _financial_analysis_rows()
    bucket_labels = [t(label) for _, label, _ in COST_BUILDUP_GROUPS]

    totals = dict(
        goods_base=sum(r["goods_base"] for r in rows),
        buckets=[sum(r["buckets"][i] for r in rows) for i in range(len(bucket_keys))],
        cost_total=sum(r["cost_total"] for r in rows),
        paid_total=sum(r["paid_total"] for r in rows),
        unpaid_total=sum(r["unpaid_total"] for r in rows),
        landed_total=sum(r["landed_total"] for r in rows),
    )
    return render_template("reports/financial_analysis.html", rows=rows,
                           bucket_labels=bucket_labels, totals=totals)


@bp.route("/financial-analysis/export")
@permission_required("view_reports")
def financial_analysis_export():
    fmt = request.args.get("format", "xlsx")
    rows, bucket_keys = _financial_analysis_rows()
    bucket_labels = [t(label) for _, label, _ in COST_BUILDUP_GROUPS]

    headers = (["Shipment", "Stage", "Goods value"] + bucket_labels +
               ["Total cost", "Paid", "Unpaid", "Total landed cost"])
    out_rows = []
    for r in rows:
        out_rows.append([
            r["shipment"].reference_no, r["shipment"].stage_label,
            round(r["goods_base"], 2),
            *[round(v, 2) for v in r["buckets"]],
            round(r["cost_total"], 2), round(r["paid_total"], 2),
            round(r["unpaid_total"], 2), round(r["landed_total"], 2),
        ])
    return export_response(fmt, "financial_analysis", "Financial analysis",
                           headers, out_rows, subtitle=f"{len(out_rows)} shipments")


@bp.route("/brands")
@permission_required("view_reports")
def brands():
    """Volume, value and transit performance by brand, and by supplier."""
    shipments, _ = _shipments()

    brand_stats = []
    for brand in Brand.query.all():
        bs = [s for s in shipments if s.brand_id == brand.id]
        if not bs:
            continue
        brand_costs = sum(s.total_cost for s in bs)
        brand_stats.append(dict(brand=brand.brand_name, shipments=len(bs),
                                value=sum(s.total_value_base for s in bs), cost=brand_costs,
                                avg_transit=_avg([s.transit_days for s in bs])))
    brand_stats.sort(key=lambda r: -r["shipments"])

    supplier_stats = []
    for sup in Supplier.query.all():
        ss = [s for s in shipments if s.supplier_id == sup.id]
        if not ss:
            continue
        delayed = sum(1 for s in ss if s.is_delayed)
        supplier_stats.append(dict(
            supplier=sup.name, shipments=len(ss), delayed=delayed,
            avg_transit=_avg([s.transit_days for s in ss]),
            lead_time=sup.lead_time_days))
    supplier_stats.sort(key=lambda r: -r["shipments"])
    supplier_stats = supplier_stats[:12]

    return render_template("reports/brands.html", brand_stats=brand_stats[:12],
                           supplier_stats=supplier_stats)


@bp.route("/equipment")
@permission_required("view_reports")
def equipment():
    """Serialised equipment by status, and the value of goods currently in
    transit, by currency."""
    _, open_shipments = _shipments()

    asset_status_counts = defaultdict(int)
    for a in Asset.query.all():
        asset_status_counts[a.status_label] += 1

    value_by_currency = defaultdict(float)
    for s in open_shipments:
        for item in s.items:
            value_by_currency[item.currency or "USD"] += item.line_value

    return render_template("reports/equipment.html",
                           asset_status_counts=dict(asset_status_counts),
                           value_by_currency=dict(value_by_currency))


@bp.route("/exceptions")
@permission_required("view_reports")
def exceptions():
    """Things that need attention: shipments missing required documents, and
    rows with contradictory dates."""
    shipments, open_shipments = _shipments()

    incomplete = [s for s in open_shipments if s.missing_documents]

    # Rows migrated from the spreadsheet sometimes carry dates that cannot both be
    # true (departure after arrival, release before arrival). Those are excluded from
    # the timing averages elsewhere, so they are listed here instead of being silently
    # dropped — the fix belongs in the record, not in the report.
    anomalies = [dict(shipment=s, problems=s.date_anomalies)
                 for s in shipments if s.date_anomalies]

    return render_template("reports/exceptions.html", incomplete=incomplete[:10],
                           anomalies=anomalies[:20])


@bp.route("/export")
@permission_required("view_reports")
def export():
    """Full shipment register export with timing and cost columns."""
    fmt = request.args.get("format", "xlsx")
    shipments = visible_shipments(Shipment.query).order_by(Shipment.id).all()

    headers = ["Reference", "Direction", "Stage", "Brand", "Supplier", "Consignee",
               "Origin", "Destination", "Mode", "Service", "ACID", "BL/AWB",
               "ETD", "ETA", "Actual departure", "Actual arrival", "Cleared",
               "Transit days", "Clearance days", "Goods value", "Total cost (EGP)",
               "Unpaid (EGP)", "Docs complete %", "Customers"]
    rows = []
    for s in shipments:
        rows.append([
            s.reference_no, s.direction, s.stage_label,
            s.brand.brand_name if s.brand else "", s.supplier.name if s.supplier else "",
            s.consignee.name if s.consignee else "", s.origin, s.destination,
            (s.mode or "").upper(), (s.service_type or "").upper(),
            s.acid_number, s.bl_awb_no,
            s.etd.strftime("%d %b %Y") if s.etd else "",
            s.eta.strftime("%d %b %Y") if s.eta else "",
            s.actual_departure.strftime("%d %b %Y") if s.actual_departure else "",
            s.actual_arrival.strftime("%d %b %Y") if s.actual_arrival else "",
            s.clearance_date.strftime("%d %b %Y") if s.clearance_date else "",
            s.transit_days if s.transit_days is not None else "",
            s.clearance_days if s.clearance_days is not None else "",
            round(s.total_value, 2), round(s.total_cost, 2), round(s.unpaid_cost, 2),
            s.doc_completeness,
            ", ".join(c.customer_name for c in s.allocated_customers),
        ])
    return export_response(fmt, "shipment_register", "Full shipment register",
                           headers, rows, subtitle=f"{len(rows)} shipments")
