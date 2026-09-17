import os
from datetime import date, datetime

from flask import Flask, render_template
from flask_login import LoginManager

from config import Config
from .models import db, User, Stage
from .i18n import (t, get_locale, direction, is_rtl,
                   LANGUAGES, format_date)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    os.makedirs(os.path.join(app.root_path, "..", "instance"), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .audit import register_audit_listeners
    register_audit_listeners()

    # ---- blueprints ----
    from .auth import bp as auth_bp
    from .views.dashboard import bp as dashboard_bp
    from .views.shipments import bp as shipments_bp
    from .views.purchase_orders import bp as po_bp
    from .views.finance import bp as finance_bp
    from .views.assets import bp as assets_bp
    from .views.masters import bp as masters_bp
    from .views.reports import bp as reports_bp
    from .views.admin import bp as admin_bp
    from .views.search import bp as search_bp
    from .views.help import bp as help_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(shipments_bp, url_prefix="/shipments")
    app.register_blueprint(po_bp, url_prefix="/purchase-orders")
    app.register_blueprint(finance_bp, url_prefix="/finance")
    app.register_blueprint(assets_bp, url_prefix="/equipment")
    app.register_blueprint(masters_bp, url_prefix="/master-data")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(search_bp, url_prefix="/search")
    app.register_blueprint(help_bp, url_prefix="/help")

    # ---- template helpers ----
    @app.context_processor
    def inject_globals():
        return dict(
            t=t,
            locale=get_locale(),
            direction=direction(),
            rtl=is_rtl(),
            languages=LANGUAGES,
            Stage=Stage,
            today=date.today(),
            app_name=app.config["APP_NAME"],
            app_tagline=app.config["APP_TAGLINE"],
            org_name=app.config["ORG_NAME"],
            base_currency=app.config["BASE_CURRENCY"],
        )

    @app.template_filter("money")
    def money(value, currency=None):
        if value is None:
            return "—"
        try:
            text = f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return "—"
        return f"{text} {currency}" if currency else text

    @app.template_filter("money2")
    def money2(value):
        if value is None:
            return "—"
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "—"

    @app.template_filter("shortdate")
    def shortdate(value):
        if not value:
            return "—"
        if isinstance(value, datetime):
            value = value.date()
        return format_date(value)

    @app.template_filter("datetimefmt")
    def datetimefmt(value):
        if not value:
            return "—"
        return format_date(value, with_time=True)

    # ---- language toggle ----
    @app.route("/lang/<code>")
    def set_language(code):
        from flask import session, redirect, request as rq
        from flask_login import current_user as cu
        if code in LANGUAGES:
            session["language"] = code
            # remember it on the account too, so it follows the user to any device
            try:
                if cu.is_authenticated:
                    cu.language = code
                    db.session.commit()
            except Exception:
                db.session.rollback()
        return redirect(rq.referrer or "/")

    # ---- error pages ----
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403,
                               message=t("Your role does not have access to this page.")), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404,
                               message=t("That page or record does not exist.")), 404

    return app


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
