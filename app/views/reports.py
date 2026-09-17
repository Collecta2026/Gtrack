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

bp = Blueprint("reports", __name__)


def _avg(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 1) if values else None


@bp.route("/")
@permission_required("view_reports")
def index():
    shipments = visible_shipments(Shipment.query).all()
    open_shipments = [s for s in shipments if s.is_open]

    # --- pipeline by stage ---
    pipeline = []
    for code in Stage.ORDER:
        count = sum(1 for s in open_shipments if s.current_stage == code)
        if count:
            pipeline.append(dict(label=Stage.label(code), count=count))

    # --- timing ---
    transit_times = [s.transit_days for s in shipments if s.transit_days is not None]
    clearance_times = [s.clearance_days for s in shipments if s.clearance_days is not None]

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

    # --- on-time performance ---
    arrived = [s for s in shipments if s.actual_arrival and s.eta]
    on_time = sum(1 for s in arrived if s.actual_arrival <= s.eta)
    on_time_pct = round(100 * on_time / len(arrived)) if arrived else None

    # --- cost ---
    cost_by_type = defaultdict(float)
    for c in CostLine.query.all():
        cost_by_type[c.type_label] += (c.amount_base or 0)
    cost_rows = sorted(cost_by_type.items(), key=lambda kv: -kv[1])
    total_cost = sum(cost_by_type.values())

    cost_per_shipment = round(total_cost / len(shipments)) if shipments else 0
    weights = [s.gross_weight_kg for s in shipments if s.gross_weight_kg]
    cost_per_kg = round(total_cost / sum(weights), 2) if weights else None

    # --- by brand ---
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

    # --- supplier performance ---
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

    # --- routing: direct versus the two-step route through the fulfilment centre ---
    # Worth watching, because the hub route buys flexibility but adds a second set of
    # freight, handling and clearance charges. This is the comparison that says whether
    # it is paying for itself on a given lane.
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

    # --- consolidation: how much a re-export leg is actually pooling ---
    consolidated = [s for s in shipments if s.is_consolidated]

    # --- data quality ---
    # Rows migrated from the spreadsheet sometimes carry dates that cannot both be
    # true (departure after arrival, release before arrival). Those are excluded from
    # the timing averages above, so they are listed here instead of being silently
    # dropped — the fix belongs in the record, not in the report.
    anomalies = [dict(shipment=s, problems=s.date_anomalies)
                 for s in shipments if s.date_anomalies]

    # --- ageing ---
    ageing = sorted([s for s in open_shipments if s.days_in_stage > 7],
                    key=lambda s: -s.days_in_stage)[:15]

    # --- document completeness ---
    incomplete = [s for s in open_shipments if s.missing_documents]

    # --- allocation ---
    all_assets = Asset.query.all()
    asset_status_counts = defaultdict(int)
    for a in all_assets:
        asset_status_counts[a.status_label] += 1

    # --- value in transit by currency ---
    value_by_currency = defaultdict(float)
    for s in open_shipments:
        for item in s.items:
            value_by_currency[item.currency or "USD"] += item.line_value

    stats = dict(
        total=len(shipments), open=len(open_shipments),
        avg_transit=_avg(transit_times), avg_clearance=_avg(clearance_times),
        on_time_pct=on_time_pct, arrived_count=len(arrived),
        total_cost=total_cost, cost_per_shipment=cost_per_shipment, cost_per_kg=cost_per_kg,
        delayed=sum(1 for s in open_shipments if s.is_delayed),
        incomplete_docs=len(incomplete),
        consolidated=len(consolidated),
        hub_legs=sum(1 for s in shipments if s.is_hub_leg),
        anomalies=len(anomalies),
    )

    return render_template("reports/index.html", stats=stats, pipeline=pipeline,
                           mode_stats=mode_stats, lane_stats=lane_stats,
                           cost_rows=cost_rows, brand_stats=brand_stats,
                           supplier_stats=supplier_stats, ageing=ageing,
                           route_stats=route_stats, anomalies=anomalies[:20],
                           incomplete=incomplete[:10],
                           asset_status_counts=dict(asset_status_counts),
                           value_by_currency=dict(value_by_currency))


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
