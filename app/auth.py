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
#
# This is the seed set only, matching the company's actual six positions.
# The admin user matrix is not limited to these — new roles can be added at
# any time from Admin -> Roles, and each one immediately gets its own column
# in the Authorisation matrix.
#
# The CFO is the one role that always keeps full access ("*") and cannot be
# downgraded from the Authorisation matrix — it is the account that manages
# users, roles, the matrix itself and FX rates, so it can never be locked out.
# --------------------------------------------------------------------------

ROLE_DEFINITIONS = [
    ("cfo", "CFO",
     "Full access; manages users, roles, the authorisation matrix, FX rates and all master data.",
     "*"),
    ("md", "MD",
     "Full read access and dashboards across all shipments; exportable reports.",
     "view_all,view_reports,comment,export"),
    ("finance", "Finance",
     "Manages cost lines, payment status, bank registration and financial reports.",
     "view_all,edit_cost,edit_supplier_invoice,edit_bank_reg,comment,view_reports"),
    ("sales", "Sales",
     "Read-only view of shipments and allocations for their own customers; receives milestone "
     "alerts; can add customer-facing comments.",
     "view_own_customers,edit_allocation,comment,view_reports"),
    ("sales_admin", "Sales Admin",
     "Department oversight — sees and manages allocations across every customer, not just "
     "their own; receives milestone alerts; runs and exports sales reports.",
     "view_all,edit_allocation,comment,view_reports,export"),
    ("logistics_admin", "Logistics Admin",
     "Raises and manages purchase orders and supplier invoices; creates and manages shipments, "
     "quotations and bookings; updates transit and customs milestones; confirms warehouse receipt "
     "and triggers installation handover; maintains the supplier and logistics master data.",
     "view_all,edit_po,edit_supplier_invoice,edit_shipment,edit_stage,edit_quotation,edit_document,"
     "edit_bank_reg,edit_asset,edit_masters,comment,view_reports"),
]

# The role that Admin -> Authorisation matrix always shows as locked at full
# access, so the system can never be left with no one able to manage it.
SYSTEM_ROLE_CODE = "cfo"


# --------------------------------------------------------------------------
# Permission keys — the columns of the Authorisation matrix (Admin ->
# Authorisation matrix). "*" (full access) is granted separately, per role,
# and is not one of these individually-toggled keys.
# --------------------------------------------------------------------------

PERMISSIONS = [
    ("view_all", "View all shipments"),
    ("view_own_customers", "View own customers' shipments only"),
    ("view_reports", "View reports & KPIs"),
    ("export", "Export reports"),
    ("edit_masters", "Edit master data"),
    ("edit_po", "Edit purchase orders"),
    ("edit_supplier_invoice", "Edit supplier invoices"),
    ("edit_shipment", "Edit shipments"),
    ("edit_stage", "Advance shipment stage"),
    ("edit_quotation", "Edit freight quotations"),
    ("edit_document", "Edit documents"),
    ("edit_cost", "Edit cost lines"),
    ("edit_bank_reg", "Edit Form 4 / bank registration"),
    ("edit_asset", "Edit serials / assets"),
    ("edit_allocation", "Edit customer allocations"),
    ("comment", "Add comments"),
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

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
