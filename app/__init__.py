from __future__ import annotations

from flask import Flask

from app.extensions import db
from config import Config


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Extensions ─────────────────────────────────────────────────────────
    db.init_app(app)

    # ── Blueprints ──────────────────────────────────────────────────────────
    from app.routes.main import main_bp
    from app.routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # ── DB Init & Default Settings ──────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _seed_default_settings()
        _configure_sqlite()

    # ── Background Scheduler ────────────────────────────────────────────────
    from app.scheduler import init_scheduler
    init_scheduler(app)

    return app


def _configure_sqlite() -> None:
    """Enable WAL journal mode for SQLite to reduce lock contention between threads."""
    from sqlalchemy import text
    uri = db.engine.url.render_as_string(hide_password=False)
    if not uri.startswith("sqlite"):
        return
    with db.engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))  # wait 30 s at SQLite level
        conn.commit()


def _seed_default_settings() -> None:
    from app.models.models import Setting

    defaults = {
        "llm_provider":            "anthropic",
        "llm_api_key":             "",
        "llm_model":               "claude-sonnet-4-6",
        "llm_temperature":         "0.2",
        "jira_url":                "",
        "jira_username":           "",
        "jira_api_token":          "",
        "snow_url":                "",
        "snow_client_name":        "",
        "snow_client_id":          "",
        "snow_client_secret":      "",
        "monitor_enabled":          "false",
        "monitor_interval_minutes": "30",
        # Notifications
        "notify_severity":  "High",
        "smtp_host":        "",
        "smtp_port":        "587",
        "smtp_tls":         "true",
        "smtp_user":        "",
        "smtp_password":    "",
        "smtp_from":        "",
        "smtp_to":          "",
        "webhook_url":      "",
        "approved_software_list": "\n".join(Config.APPROVED_SOFTWARE),
        "enabled_controls": ",".join(
            [
                key
                for key, value in Config.CONTROLS.items()
                if value.get("enabled", True)
            ]
        ),
    }

    for key, value in defaults.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))

    db.session.commit()
