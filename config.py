import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("GTRACK_SECRET_KEY", "gtrack-dev-key-change-in-production")

    # ------------------------------------------------------------------
    # Database
    #
    # Gtrack reads its OWN variable, GTRACK_DATABASE_URL — deliberately NOT the
    # generic DATABASE_URL. A machine that already runs other Flask apps usually has
    # DATABASE_URL set for one of them, and inheriting it would silently point Gtrack
    # at another application's database. Unset, Gtrack uses a local SQLite file and
    # cannot touch anything else.
    # ------------------------------------------------------------------
    _db_url = os.environ.get("GTRACK_DATABASE_URL", "").strip()
    if _db_url.startswith("postgres://"):           # Render/Heroku style URL fix
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    # Neon requires TLS; add it if the connection string does not already say so.
    if _db_url.startswith("postgresql://") and "sslmode=" not in _db_url:
        _db_url += ("&" if "?" in _db_url else "?") + "sslmode=require"
    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///" + os.path.join(BASE_DIR, "instance", "gtrack.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Neon is serverless and drops idle connections; without pre-ping the first query
    # after an idle spell fails with "server closed the connection unexpectedly".
    if _db_url:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 280,        # under Neon's ~5 minute idle timeout
            "pool_size": 5,
            "max_overflow": 5,
            "connect_args": {"connect_timeout": 10},
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}

    UPLOAD_FOLDER = os.environ.get("GTRACK_UPLOAD_FOLDER", os.path.join(BASE_DIR, "instance", "uploads"))
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB per upload
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx", "csv", "txt", "zip"}

    BASE_CURRENCY = "EGP"
    # Indicative rates used for base-currency conversion in the test system.
    DEFAULT_RATES = {"EGP": 1.0, "USD": 48.5, "EUR": 52.0, "CNY": 6.7, "GBP": 61.0, "AED": 13.2}

    APP_NAME = "Gtrack"
    APP_TAGLINE = "Import & Equipment Tracking"
    # The deploying organisation. Change this (or set GTRACK_ORG_NAME) to run Gtrack
    # for another client without touching the code.
    ORG_NAME = os.environ.get("GTRACK_ORG_NAME", "Scientific Gate Egypt")

    # In the test system notifications are written to the log rather than emailed.
    NOTIFICATIONS_LIVE = os.environ.get("GTRACK_NOTIFICATIONS_LIVE", "0") == "1"
    ETA_WARNING_DAYS = 7
    STAGE_AGEING_DAYS = 14

    @classmethod
    def database_label(cls):
        """A human-readable description of where the data actually lives."""
        uri = cls.SQLALCHEMY_DATABASE_URI
        if uri.startswith("sqlite:"):
            return f"SQLite file — {uri.replace('sqlite:///', '')}"
        # never print credentials
        tail = uri.split("@")[-1] if "@" in uri else uri
        return f"{uri.split(':')[0]} — {tail}"

    @classmethod
    def is_sqlite(cls):
        return cls.SQLALCHEMY_DATABASE_URI.startswith("sqlite:")
