"""Authentication, roles and permission decorators."""
from functools import wraps
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_user, logout_user, login_required, current_user

from .models import db, User
from .i18n import t

bp = Blueprint("auth", __name__)


# --------------------------------------------------------------------------
# Role definitions — code, name, description, permissions
# --------------------------------------------------------------------------

ROLE_DEFINITIONS = [
    ("admin", "Administrator",
     "Full access; manages users, roles and all master data.", "*"),
    ("procurement", "Procurement Officer",
     "Raises and manages purchase orders and supplier invoices; maintains the supplier master.",
     "view_all,edit_po,edit_supplier_invoice,edit_masters,comment,view_reports"),
    ("logistics", "Logistics & Customs Coordinator",
     "Creates and manages shipments, quotations and bookings; updates transit and customs "
     "milestones; manages ACID/Form 4 and documents.",
     "view_all,edit_shipment,edit_stage,edit_quotation,edit_document,edit_bank_reg,edit_masters,"
     "comment,view_reports"),
    ("finance", "Finance / Treasury",
     "Manages cost lines, payment status, bank registration and financial reports.",
     "view_all,edit_cost,edit_supplier_invoice,edit_bank_reg,comment,view_reports"),
    ("sales", "Sales Account Manager",
     "Read-only view of shipments and allocations for their own customers; receives milestone "
     "alerts; can add customer-facing comments.",
     "view_own_customers,edit_allocation,comment,view_reports"),
    ("warehouse", "Warehouse Officer",
     "Confirms warehouse receipt, records condition/discrepancies, and triggers installation handover.",
     "view_all,edit_stage,edit_asset,comment"),
    ("management", "Management (CEO / CFO)",
     "Full read access and dashboards across all shipments; exportable reports.",
     "view_all,view_reports,comment,export"),
]


def permission_required(perm):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.can(perm):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def any_permission(*perms):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if not any(current_user.can(p) for p in perms):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def can_view_shipment(shipment):
    """Sales users only see shipments carrying an allocation for one of their customers."""
    if current_user.can("view_all"):
        return True
    if current_user.can("view_own_customers"):
        for alloc in shipment.allocations:
            if alloc.customer and alloc.customer.sales_owner_id == current_user.id:
                return True
        return False
    return False


def visible_shipments(query):
    """Scope a shipment query to what the current user is allowed to see."""
    from .models import Shipment, ShipmentItem, Allocation, Customer
    if current_user.can("view_all"):
        return query
    if current_user.can("view_own_customers"):
        return (query.join(ShipmentItem, ShipmentItem.shipment_id == Shipment.id)
                     .join(Allocation, Allocation.shipment_item_id == ShipmentItem.id)
                     .join(Customer, Allocation.customer_id == Customer.id)
                     .filter(Customer.sales_owner_id == current_user.id)
                     .distinct())
    return query.filter(False)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash(t("Incorrect email or password."), "error")

    demo_users = User.query.order_by(User.id).all()
    return render_template("login.html", demo_users=demo_users)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
